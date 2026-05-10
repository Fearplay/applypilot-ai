"""HTTP provider that talks to any OpenAI-compatible chat/completions endpoint.

This single class works against:
* OpenAI (https://api.openai.com/v1)
* Groq (https://api.groq.com/openai/v1)
* Mistral (https://api.mistral.ai/v1)
* OpenRouter (https://openrouter.ai/api/v1)
* DeepSeek (https://api.deepseek.com/v1)
* Together AI (https://api.together.xyz/v1)
* Anthropic via the official OpenAI-compatible endpoint
* Google Gemini OpenAI-compatible mode
* Local Ollama (http://localhost:11434/v1)
* Local LM Studio (http://localhost:1234/v1)

It is implemented with the ``requests`` library only - we do not depend on any
vendor SDK. The user switches providers by changing ``AI_BASE_URL``,
``AI_API_KEY`` and ``AI_MODEL`` in ``.env``.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..models.candidate import CandidateProfile, GitHubProject
from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    RefinedCoverLetter,
    RefinedResume,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion, MatchReport
from ..utils.logging_config import get_ai_request_logger
from ..utils.preferences import get_preference, set_preference
from . import prompts, session_cost
from .base import BaseAIProvider
from .pricing import estimate_cost_usd, lookup_pricing

logger = logging.getLogger(__name__)


def _json_schema_support_key(base_url: str, model: str) -> str:
    """Stable preferences key per (base_url, model) pair.

    Persisting the flag means we don't burn one failed call per session
    on providers that don't speak strict ``json_schema`` (Groq, some
    Mistral models, Ollama, ...). Once we learn ``False`` we remember it
    across restarts; once we learn ``True`` we keep using it.
    """
    cleaned_url = (base_url or "").rstrip("/").lower()
    cleaned_model = (model or "").strip().lower()
    return f"json_schema_support::{cleaned_url}::{cleaned_model}"

T = TypeVar("T", bound=BaseModel)


class _QuestionsWrapper(BaseModel):
    items: list[ClarifyingQuestion] = Field(default_factory=list)


class _InterviewWrapper(BaseModel):
    items: list[InterviewQuestion] = Field(default_factory=list)


class _GapsWrapper(BaseModel):
    items: list[SkillGap] = Field(default_factory=list)


class OpenAIProviderError(RuntimeError):
    """Raised when the upstream HTTP provider fails fatally.

    Carries the optional HTTP ``status_code`` + truncated ``body`` so the
    caller can decide whether the failure is recoverable (e.g. "json_schema
    is unsupported, retry as json_object") or terminal (anything else).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body or ""

    def looks_like_unsupported_schema(self) -> bool:
        """``True`` when the body says the provider rejects ``json_schema``.

        We use this to safely fall back to ``json_object`` exactly once
        (and to PERSIST the discovery so we don't pay for the failure
        again next session). Network timeouts and other transport issues
        are NOT treated as schema rejections - those raise
        :class:`NetworkAIError` and short-circuit the retry loop.
        """
        if self.status_code is None or self.status_code >= 500:
            return False
        body = self.body.lower()
        markers = (
            "response_format",
            "json_schema",
            "unsupported",
            "not supported",
            "invalid_request_error",
            "schema",
        )
        return any(m in body for m in markers)


class NetworkAIError(OpenAIProviderError):
    """Raised when the HTTP transport itself failed (timeout, DNS, TLS).

    Subclasses :class:`OpenAIProviderError` so existing ``except``
    handlers keep working, but :meth:`looks_like_unsupported_schema`
    always returns ``False`` so we never retry on this path.
    """

    def looks_like_unsupported_schema(self) -> bool:  # noqa: D401 - override
        return False


class OpenAICompatibleProvider(BaseAIProvider):
    """Provider that calls any OpenAI-compatible chat/completions endpoint."""

    name = "openai_compatible"
    is_demo = False

    def __init__(self, settings: Settings) -> None:
        if not settings.ai_api_key:
            raise OpenAIProviderError(
                "AI_API_KEY is empty - cannot use a real AI provider."
            )
        self._settings = settings
        self._endpoint = f"{settings.ai_base_url.rstrip('/')}/chat/completions"
        self._headers = {
            "Authorization": f"Bearer {settings.ai_api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = settings.ai_timeout
        self._temperature = settings.ai_temperature
        self._model = settings.ai_model
        self._debug_prompts = settings.ai_debug_prompts
        # Persisted across runs: avoids paying for one failed json_schema
        # call on every restart against providers that don't support it.
        self._json_schema_pref_key = _json_schema_support_key(
            settings.ai_base_url, settings.ai_model
        )
        stored = get_preference(self._json_schema_pref_key)
        self._supports_json_schema: bool | None = (
            stored if isinstance(stored, bool) else None
        )
        self.reason = (
            f"OpenAI-compatible: base_url={settings.ai_base_url}, model={self._model}"
        )
        self._audit_log = (
            get_ai_request_logger() if settings.ai_request_log else None
        )
        self._current_call: str = "unknown"
        # Origin of the current AI call, set by the GUI right before each
        # _run() invocation. Surfaces in logs so the user can answer
        # "who triggered this AI call?" when a refine fires unexpectedly.
        self._current_trigger: str = ""

    # ------------------------------------------------------------------ http
    @staticmethod
    def _payload_size(payload: dict[str, Any]) -> int:
        total = 0
        for msg in payload.get("messages", []):
            content = msg.get("content")
            if isinstance(content, str):
                total += len(content)
        return total

    def _log_payload(self, payload: dict[str, Any]) -> None:
        size = self._payload_size(payload)
        # Rough heuristic: ~4 chars per token is the OpenAI rule of thumb.
        approx_tokens = size // 4
        logger.info(
            "AI call=%s model=%s messages=%d input_chars=%d ~tokens=%d",
            self._current_call,
            payload.get("model"),
            len(payload.get("messages", [])),
            size,
            approx_tokens,
        )
        if self._audit_log is not None:
            self._audit_log.info(
                "POST %s call=%s model=%s messages=%d input_chars=%d ~tokens=%d",
                self._endpoint,
                self._current_call,
                payload.get("model"),
                len(payload.get("messages", [])),
                size,
                approx_tokens,
            )
        if self._debug_prompts:
            for idx, msg in enumerate(payload.get("messages", [])):
                content = msg.get("content") or ""
                preview = content if len(content) <= 1500 else content[:1500] + "...[truncated]"
                logger.debug(
                    "AI call=%s message[%d] role=%s content=%s",
                    self._current_call,
                    idx,
                    msg.get("role"),
                    preview,
                )

    def _log_response(self, response: dict[str, Any]) -> None:
        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = usage.get("total_tokens")
        finish_reason = None
        choices = response.get("choices") or []
        if choices:
            finish_reason = choices[0].get("finish_reason")
        # Track per-session spend so the status bar can surface running totals.
        # Even when pricing is unknown for the model, recording the call still
        # bumps the call/token counters so the user sees activity.
        snapshot = session_cost.record_call(
            self._model, prompt_tokens, completion_tokens
        )
        cost_call = estimate_cost_usd(self._model, prompt_tokens, completion_tokens)
        pricing = lookup_pricing(self._model)
        cost_str = (
            f"~${cost_call:.4f}"
            if pricing.input_per_million or pricing.output_per_million
            else "~$? (unknown model price)"
        )
        logger.info(
            "AI reply call=%s prompt_tokens=%s completion_tokens=%s "
            "total_tokens=%s finish=%s cost=%s session=%d calls/%d tokens/~$%.4f",
            self._current_call,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            finish_reason,
            cost_str,
            snapshot.calls,
            snapshot.total_tokens,
            snapshot.estimated_usd,
        )
        if self._audit_log is not None:
            self._audit_log.info(
                "REPLY call=%s trigger=%s prompt_tokens=%s completion_tokens=%s "
                "total_tokens=%s finish=%s cost=%s session_calls=%d "
                "session_tokens=%d session_cost=~$%.4f",
                self._current_call,
                self._current_trigger or "?",
                prompt_tokens,
                completion_tokens,
                total_tokens,
                finish_reason,
                cost_str,
                snapshot.calls,
                snapshot.total_tokens,
                snapshot.estimated_usd,
            )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._log_payload(payload)
        try:
            resp = requests.post(
                self._endpoint,
                headers=self._headers,
                data=json.dumps(payload),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            # Network failure (timeout, DNS, TLS, connection reset). The
            # upstream may still have GENERATED tokens we'd be billed for,
            # so retrying the same request immediately on this code path
            # is what made the recent run cost ~30c instead of 21c
            # (terminals/1.txt:557-558 in the original report). Wrap as a
            # NetworkError so callers can decide NOT to retry on this case.
            raise NetworkAIError(
                f"HTTP error talking to AI: {exc}"
            ) from exc

        if resp.status_code >= 400:
            raise OpenAIProviderError(
                f"AI provider returned HTTP {resp.status_code}: {resp.text[:300]}",
                status_code=resp.status_code,
                body=resp.text,
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise OpenAIProviderError(
                f"AI provider returned non-JSON body: {resp.text[:200]}"
            ) from exc
        self._log_response(data)
        return data

    def _completion_text(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise OpenAIProviderError("AI provider response had no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OpenAIProviderError("AI provider returned empty content.")
        return content

    def _structured_call(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[T],
    ) -> T:
        """Call the provider asking for JSON validating ``schema_model``.

        Cost-aware retry policy:

        * Try ``json_schema`` only when the persisted preference doesn't
          already say it's unsupported.
        * Fall back to ``json_object`` ONLY when the failure was a 4xx
          rejection of ``response_format`` (we use
          :meth:`OpenAIProviderError.looks_like_unsupported_schema`).
          Persist the discovery to ``~/.applypilot/state.json`` so we
          don't pay for the same failed call next session.
        * NEVER retry on :class:`NetworkAIError` (timeout / DNS / TLS) -
          re-issuing a 60-second timeout immediately doubled the user's
          per-run cost (terminals/1.txt:557-558 in the bug report).
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        schema = schema_model.model_json_schema()

        if self._supports_json_schema is not False:
            payload = {
                "model": self._model,
                "messages": messages,
                "temperature": self._temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_model.__name__,
                        "schema": schema,
                        "strict": False,
                    },
                },
            }
            try:
                response = self._post(payload)
                if self._supports_json_schema is not True:
                    self._remember_json_schema_support(True)
                content = self._completion_text(response)
                return self._parse_into(content, schema_model)
            except NetworkAIError:
                # Transport failure - the provider may have already
                # generated billable tokens. Don't pile on a retry.
                raise
            except OpenAIProviderError as exc:
                if not exc.looks_like_unsupported_schema():
                    raise
                logger.warning(
                    "json_schema rejected by provider (HTTP %s), "
                    "falling back to json_object once and remembering "
                    "the choice: %s",
                    exc.status_code,
                    exc,
                )
                self._remember_json_schema_support(False)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        user_prompt
                        + "\n\nReturn STRICT JSON matching this schema (no markdown, no commentary):\n"
                        + json.dumps(schema, ensure_ascii=False, indent=2)
                    ),
                },
            ],
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._post(payload)
            content = self._completion_text(response)
            return self._parse_into(content, schema_model)
        except NetworkAIError:
            raise
        except OpenAIProviderError as exc:
            if not exc.looks_like_unsupported_schema():
                raise
            logger.warning(
                "json_object also rejected by provider (HTTP %s), "
                "retrying once without response_format: %s",
                exc.status_code,
                exc,
            )
            payload.pop("response_format", None)
            response = self._post(payload)
            content = self._completion_text(response)
            return self._parse_into(content, schema_model)

    def _remember_json_schema_support(self, supported: bool) -> None:
        """Persist the support flag so the next session skips the probe."""
        self._supports_json_schema = supported
        try:
            set_preference(self._json_schema_pref_key, supported)
        except Exception:
            # Preference store is best-effort; log and continue.
            logger.debug(
                "Could not persist json_schema flag for %s",
                self._json_schema_pref_key,
                exc_info=True,
            )

    @staticmethod
    def _parse_into(content: str, schema_model: type[T]) -> T:
        text = content.strip()
        # Strip accidental markdown fences.
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OpenAIProviderError(
                f"AI returned invalid JSON: {exc}\nRaw: {text[:300]}"
            ) from exc
        try:
            return schema_model.model_validate(data)
        except ValidationError as exc:
            raise OpenAIProviderError(
                f"AI JSON failed schema validation: {exc}\nRaw: {text[:300]}"
            ) from exc

    # ------------------------------------------------------------------ API
    def set_trigger(self, trigger: str) -> None:
        """Tag the next ``_run()`` with the GUI action that initiated it.

        The orchestrator calls this right before each background AI job
        (``"DocumentsPage._on_refine_clicked(user_text='1) ...')"`` etc.)
        so the audit log can answer "who started this AI call?" the next
        time the user thinks the app spent money on its own.
        """
        self._current_trigger = (trigger or "").strip()[:200]

    def _run(self, call_name: str, system: str, user: str, schema: type[T]) -> T:
        """Execute a structured call while tagging logs with ``call_name``."""
        previous = self._current_call
        self._current_call = call_name
        try:
            return self._structured_call(system, user, schema)
        finally:
            self._current_call = previous

    def analyze_job(
        self, raw_text: str, source_url: str | None = None
    ) -> JobPosting:
        # Use a generic IT recruiter persona for the initial analysis - the
        # role isn't known yet.
        system = prompts.system_prompt_for("other_it")
        user = prompts.analyze_job_user_prompt(raw_text, source_url)
        result = self._run("analyze_job", system, user, JobPosting)
        if not result.raw_text:
            object.__setattr__(result, "raw_text", raw_text)
        if not result.source_url:
            object.__setattr__(result, "source_url", source_url)
        return result

    def analyze_candidate(
        self,
        cv_text: str = "",
        linkedin_text: str = "",
        github_username: str | None = None,
        github_projects: Sequence[GitHubProject] = (),
        additional_notes: str = "",
    ) -> CandidateProfile:
        system = prompts.system_prompt_for("other_it")
        user = prompts.analyze_candidate_user_prompt(
            cv_text,
            linkedin_text,
            github_username,
            list(github_projects),
            additional_notes=additional_notes,
        )
        result = self._run("analyze_candidate", system, user, CandidateProfile)
        # Defensive copy: even though the prompt explicitly tells the model
        # to copy the notes verbatim into the profile, providers occasionally
        # drop the field (especially on json_object fallback paths). Always
        # restore the verbatim user text so downstream prompts re-read it
        # consistently.
        cleaned = (additional_notes or "").strip()
        if cleaned and not (result.additional_notes or "").strip():
            object.__setattr__(result, "additional_notes", cleaned)
        return result

    def generate_clarifying_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[ClarifyingQuestion]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.clarifying_questions_user_prompt(job, candidate, output_language)
        wrapped = self._run("clarifying_questions", system, user, _QuestionsWrapper)
        return list(wrapped.items)

    def generate_match_report(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> MatchReport:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.match_report_user_prompt(
            job, candidate, answers, list(evidence), output_language
        )
        return self._run("match_report", system, user, MatchReport)

    def generate_resume(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
        translate_positions: bool = True,
    ) -> TailoredResume:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.resume_user_prompt(
            job, candidate, answers, list(evidence), output_language,
            translate_positions=translate_positions,
        )
        return self._run("resume", system, user, TailoredResume)

    def generate_cover_letter(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        output_language: str = "en",
    ) -> CoverLetter:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.cover_letter_user_prompt(job, candidate, answers, output_language)
        return self._run("cover_letter", system, user, CoverLetter)

    def generate_interview_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[InterviewQuestion]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.interview_questions_user_prompt(job, candidate, output_language)
        wrapped = self._run("interview_questions", system, user, _InterviewWrapper)
        return list(wrapped.items)

    def generate_skill_gap_plan(
        self,
        match_report: MatchReport,
        job: JobPosting,
        output_language: str = "en",
    ) -> list[SkillGap]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.skill_gap_user_prompt(match_report, job, output_language)
        wrapped = self._run("skill_gap_plan", system, user, _GapsWrapper)
        return list(wrapped.items)

    def refine_resume(
        self,
        current_resume: TailoredResume,
        feedback: str,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
        previous_explanation: str = "",
        translate_positions: bool = True,
    ) -> RefinedResume:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.refine_resume_user_prompt(
            current_resume, feedback, job, candidate, answers,
            list(evidence), output_language,
            previous_explanation=previous_explanation,
            translate_positions=translate_positions,
        )
        return self._run("refine_resume", system, user, RefinedResume)

    def refine_cover_letter(
        self,
        current_cover_letter: CoverLetter,
        feedback: str,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        output_language: str = "en",
        previous_explanation: str = "",
    ) -> RefinedCoverLetter:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.refine_cover_letter_user_prompt(
            current_cover_letter, feedback, job, candidate, answers,
            output_language=output_language,
            previous_explanation=previous_explanation,
        )
        return self._run("refine_cover_letter", system, user, RefinedCoverLetter)


__all__ = [
    "OpenAICompatibleProvider",
    "OpenAIProviderError",
    "NetworkAIError",
]
