"""Detect a coarse :data:`RoleType` from a job title or full job description.

The detector is intentionally simple regex-based. It is deterministic and
keeps no AI dependency so it can also be used in the offline ``FakeAIProvider``
and inside the prompt builders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models.job import RoleType

# Order matters: the first matching pattern wins, so put the most specific
# patterns at the top (e.g. "QA Automation" must win over plain "QA").
@dataclass(frozen=True)
class _Pattern:
    role: RoleType
    regex: re.Pattern[str]


def _p(role: RoleType, *needles: str) -> _Pattern:
    """Build a case-insensitive word-boundary regex out of needles."""
    parts = [re.escape(n) for n in needles]
    pattern = r"(?i)\b(?:" + "|".join(parts) + r")\b"
    return _Pattern(role=role, regex=re.compile(pattern))


_PATTERNS: tuple[_Pattern, ...] = (
    # ---- QA / testing first (most specific) -------------------------------
    _p("qa_automation_engineer",
       "qa automation", "test automation", "automation qa", "automation tester",
       "sdet", "software development engineer in test"),
    _p("manual_qa_tester",
       "manual qa", "manual tester", "manual test", "manual quality"),
    _p("test_engineer",
       "test engineer", "performance tester", "performance engineer",
       "load tester"),
    _p("software_qa_engineer",
       "qa engineer", "quality assurance engineer", "qa specialist",
       "quality engineer", "software tester", "qa analyst", "tester",
       "qa", "quality assurance"),

    # ---- AI / ML (juniors first, then specific GenAI / AI SWE before
    #      generic ML to avoid accidentally bucketing "AI Software
    #      Engineer at Microsoft" into machine_learning_engineer) ---------
    _p("junior_ai_engineer",
       "junior ai engineer", "junior genai engineer", "junior llm engineer",
       "junior ml engineer", "junior machine learning"),
    # GenAI / LLM application engineering: people who BUILD WITH foundation
    # models (RAG, agents, prompt pipelines) rather than train them.
    _p("genai_engineer",
       "genai engineer", "gen ai engineer", "generative ai engineer",
       "llm engineer", "llm application engineer", "llm software engineer",
       "prompt engineer", "ai application engineer", "applied genai",
       "ai agent engineer"),
    # AI Software Engineer: shipping AI-powered features inside a product
    # codebase. Sits between pure ML research and standard SWE - we model
    # it as its own persona so the prompt can lean on both flavours.
    _p("ai_software_engineer",
       "ai software engineer", "ai/ml software engineer",
       "ai engineer software", "machine learning software engineer",
       "ml software engineer", "ai-focused software engineer",
       "ai platform engineer", "ai infrastructure engineer"),
    _p("machine_learning_engineer",
       "ml engineer", "machine learning engineer", "ai engineer",
       "applied ai", "applied scientist"),

    # ---- Python / generic dev (junior first) ------------------------------
    _p("junior_python_developer",
       "junior python developer", "junior python engineer",
       "junior backend python"),
    _p("junior_software_engineer",
       "junior software engineer", "junior software developer",
       "junior developer", "graduate developer", "graduate engineer",
       "entry level developer", "entry-level developer"),

    # ---- Data -------------------------------------------------------------
    _p("data_analyst", "data analyst", "business analyst data",
       "analytics analyst"),
    _p("data_engineer", "data engineer", "etl engineer", "analytics engineer"),

    # ---- Web / app dev ----------------------------------------------------
    _p("frontend_developer",
       "frontend developer", "front-end developer", "front end developer",
       "react developer", "vue developer", "angular developer",
       "ui developer", "ui engineer"),
    _p("backend_developer",
       "backend developer", "back-end developer", "back end developer",
       "node.js developer", "node developer", "django developer",
       "java developer", "go developer", "golang developer",
       "rust developer", "ruby developer", "php developer"),
    _p("fullstack_developer",
       "fullstack developer", "full-stack developer", "full stack developer",
       "fullstack engineer", "full-stack engineer", "full stack engineer"),
    _p("mobile_developer",
       "ios developer", "android developer", "mobile developer",
       "flutter developer", "react native developer"),

    # ---- Ops --------------------------------------------------------------
    _p("site_reliability_engineer", "site reliability engineer", "sre"),
    _p("devops_engineer",
       "devops engineer", "devops", "platform engineer",
       "platform reliability"),
    _p("cloud_engineer",
       "cloud engineer", "aws engineer", "azure engineer", "gcp engineer"),
    _p("security_engineer",
       "security engineer", "application security", "appsec",
       "security analyst"),

    # ---- Generic mid/senior software engineer (LAST so all the more
    #      specific buckets above always win first) ---------------------
    _p("software_engineer",
       "software engineer", "software developer", "senior software engineer",
       "senior software developer", "staff engineer", "staff software engineer",
       "principal engineer", "principal software engineer",
       "lead software engineer", "tech lead", "engineering manager"),
)

#: Heuristic words that, if present, make us promote a non-IT-looking title to
#: ``other_it`` (so the prompt persona at least keeps a tech tone).
_IT_HINTS: tuple[str, ...] = (
    "developer", "engineer", "programmer", "software", "python", "java",
    "javascript", "typescript", "kubernetes", "docker", "linux", "aws",
    "azure", "gcp", "rest api", "microservices", "devops", "qa", "tester",
    "machine learning", "data", "sql", "ci/cd", "git",
)


def detect_role_type(title: str, description: str = "") -> RoleType:
    """Best-effort role classification.

    The classifier inspects the job title first, then falls back to scanning
    the full description for the same patterns. If nothing matches but the
    text looks IT-related, returns ``"other_it"``.
    """
    title = (title or "").strip()
    description = description or ""

    if title:
        for p in _PATTERNS:
            if p.regex.search(title):
                return p.role

    if description:
        for p in _PATTERNS:
            if p.regex.search(description):
                return p.role

        lowered = description.lower()
        if any(hint in lowered for hint in _IT_HINTS):
            return "other_it"

    return "other"


__all__ = ["detect_role_type"]
