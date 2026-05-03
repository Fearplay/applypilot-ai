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
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.job import JobPosting
from ..models.match import AnswersBundle, ClarifyingQuestion, MatchReport
from ..utils.logging_config import get_ai_request_logger
from . import prompts
from .base import BaseAIProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class _QuestionsWrapper(BaseModel):
    items: list[ClarifyingQuestion] = Field(default_factory=list)


class _InterviewWrapper(BaseModel):
    items: list[InterviewQuestion] = Field(default_factory=list)


class _GapsWrapper(BaseModel):
    items: list[SkillGap] = Field(default_factory=list)


class OpenAIProviderError(RuntimeError):
    """Raised when the upstream HTTP provider fails fatally."""


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
        self._supports_json_schema: bool | None = None
        self.reason = (
            f"OpenAI-compatible: base_url={settings.ai_base_url}, model={self._model}"
        )
        self._audit_log = (
            get_ai_request_logger() if settings.ai_request_log else None
        )
        self._current_call: str = "unknown"

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
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        finish_reason = None
        choices = response.get("choices") or []
        if choices:
            finish_reason = choices[0].get("finish_reason")
        logger.info(
            "AI reply call=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s finish=%s",
            self._current_call,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            finish_reason,
        )
        if self._audit_log is not None:
            self._audit_log.info(
                "REPLY call=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s finish=%s",
                self._current_call,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                finish_reason,
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
            raise OpenAIProviderError(f"HTTP error talking to AI: {exc}") from exc

        if resp.status_code >= 400:
            raise OpenAIProviderError(
                f"AI provider returned HTTP {resp.status_code}: {resp.text[:300]}"
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
        """Call the provider asking for JSON validating ``schema_model``."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        schema = schema_model.model_json_schema()

        # First try strict json_schema (OpenAI, OpenRouter, vLLM, ...).
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
                self._supports_json_schema = True
                content = self._completion_text(response)
                return self._parse_into(content, schema_model)
            except OpenAIProviderError as exc:
                # Try json_object fallback once.
                logger.warning("json_schema failed, falling back to json_object: %s", exc)
                self._supports_json_schema = False

        # json_object fallback - inject the schema into the user prompt.
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
        except OpenAIProviderError:
            # Last-resort: no response_format at all.
            payload.pop("response_format", None)
            response = self._post(payload)
            content = self._completion_text(response)
            return self._parse_into(content, schema_model)

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
    ) -> CandidateProfile:
        system = prompts.system_prompt_for("other_it")
        user = prompts.analyze_candidate_user_prompt(
            cv_text, linkedin_text, github_username, list(github_projects)
        )
        return self._run("analyze_candidate", system, user, CandidateProfile)

    def generate_clarifying_questions(
        self, job: JobPosting, candidate: CandidateProfile
    ) -> list[ClarifyingQuestion]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.clarifying_questions_user_prompt(job, candidate)
        wrapped = self._run("clarifying_questions", system, user, _QuestionsWrapper)
        return list(wrapped.items)

    def generate_match_report(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
    ) -> MatchReport:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.match_report_user_prompt(job, candidate, answers, list(evidence))
        return self._run("match_report", system, user, MatchReport)

    def generate_resume(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
    ) -> TailoredResume:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.resume_user_prompt(job, candidate, answers, list(evidence))
        return self._run("resume", system, user, TailoredResume)

    def generate_cover_letter(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
    ) -> CoverLetter:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.cover_letter_user_prompt(job, candidate, answers)
        return self._run("cover_letter", system, user, CoverLetter)

    def generate_interview_questions(
        self, job: JobPosting, candidate: CandidateProfile
    ) -> list[InterviewQuestion]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.interview_questions_user_prompt(job, candidate)
        wrapped = self._run("interview_questions", system, user, _InterviewWrapper)
        return list(wrapped.items)

    def generate_skill_gap_plan(
        self, match_report: MatchReport, job: JobPosting
    ) -> list[SkillGap]:
        system = prompts.system_prompt_for(job.role_type)
        user = prompts.skill_gap_user_prompt(match_report, job)
        wrapped = self._run("skill_gap_plan", system, user, _GapsWrapper)
        return list(wrapped.items)


__all__ = ["OpenAICompatibleProvider", "OpenAIProviderError"]
