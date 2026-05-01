"""System & user prompt builders for the AI providers.

The prompts are role-aware: depending on the detected :data:`RoleType` the
``RECRUITER_PERSONAS`` table picks an appropriate "persona" for the AI to
emulate. This is what the spec calls "AI as an HR/recruiter expert
specialised for this position".
"""
from __future__ import annotations

import json
from typing import Any

from ..models.job import ROLE_TYPE_LABELS, JobPosting, RoleType
from ..models.candidate import CandidateProfile
from ..models.match import AnswersBundle, ClarifyingAnswer, MatchReport
from ..models.evidence import EvidenceItem


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------
RECRUITER_PERSONAS: dict[RoleType, str] = {
    "software_qa_engineer": (
        "a senior technical recruiter and former QA lead specialised in hiring "
        "Software QA Engineers. You judge candidates on testing process, bug "
        "reporting quality, exploratory and regression testing, API testing, "
        "SQL, Python, Selenium / Playwright / Cypress, Jira, Agile/Scrum, "
        "communication with developers, attention to detail, reproducible "
        "defects and the ability to think about edge cases."
    ),
    "qa_automation_engineer": (
        "a senior engineering manager who hires QA Automation Engineers / SDETs. "
        "You weigh test framework design, Page Object Model, parallel execution, "
        "Playwright/Selenium/Cypress, pytest, API automation with requests / RestAssured, "
        "CI/CD pipelines, Docker, reporting (Allure), code reviews and the "
        "ability to write clean, maintainable test code."
    ),
    "manual_qa_tester": (
        "a senior QA lead who hires Manual QA Testers. You focus on clear bug "
        "reports, reproducibility, exploratory and regression sessions, test "
        "case design, requirements analysis, Jira/Azure DevOps, Postman for API "
        "checks and good communication with the dev team."
    ),
    "test_engineer": (
        "a hiring manager for Test Engineers. You look at test strategy, "
        "performance testing, integration testing, automation breadth, "
        "tooling (k6, JMeter, Gatling, pytest), CI integration and the "
        "candidate's ability to identify systemic quality risks."
    ),
    "junior_python_developer": (
        "a tech lead who hires Junior Python Developers. You expect solid "
        "Python fundamentals, basic OOP, virtualenv/pip/poetry, Git, REST APIs, "
        "unit tests with pytest, SQL basics, and a willingness to learn. You "
        "value small but real Python projects on GitHub over claimed expertise."
    ),
    "junior_software_engineer": (
        "an engineering manager who hires Junior Software Engineers. You weigh "
        "data structures, algorithms basics, one production-grade language, Git, "
        "ability to read existing code, basic testing, communication, and a "
        "growth mindset."
    ),
    "junior_ai_engineer": (
        "a head of AI who hires Junior AI / GenAI Engineers. You judge Python, "
        "prompt engineering basics, LangChain or plain API usage, vector "
        "databases (pgvector, FAISS, Chroma), RAG patterns, evaluation harness "
        "thinking, structured output / function calling, and the ability to "
        "ship a small end-to-end LLM project."
    ),
    "data_analyst": (
        "a head of analytics who hires Data Analysts. You focus on SQL fluency, "
        "Excel/Sheets, Python (pandas) or R, dashboarding (PowerBI / Tableau / "
        "Looker), basic statistics, ability to translate business questions "
        "into queries, and clear written communication."
    ),
    "frontend_developer": (
        "a senior frontend lead who hires Frontend Developers. You weigh "
        "JavaScript/TypeScript, modern React or Vue, component design, CSS "
        "fundamentals, accessibility, performance, testing (Jest / Vitest / "
        "Playwright), Git workflows and design system thinking."
    ),
    "backend_developer": (
        "a backend tech lead. You judge a strong primary language, REST/gRPC "
        "API design, relational and NoSQL data modelling, caching, async "
        "patterns, security basics (OWASP top 10), observability, and tests."
    ),
    "fullstack_developer": (
        "a hiring manager for Fullstack Developers. You expect competence on "
        "both sides of the stack, with at least one strong specialisation, "
        "and pragmatic delivery skills."
    ),
    "devops_engineer": (
        "a platform engineering lead. You weigh Linux, Docker, Kubernetes, "
        "Terraform / Pulumi, CI/CD pipelines (GitHub Actions, GitLab CI), "
        "monitoring stack (Prometheus, Grafana), and a security-aware mindset."
    ),
    "data_engineer": (
        "a data platform lead. You weigh SQL, Python, Spark, dbt, Airflow, "
        "warehouse modelling (Kimball/Inmon), streaming basics and data "
        "quality discipline."
    ),
    "machine_learning_engineer": (
        "a head of ML. You weigh Python, the modelling stack (scikit-learn, "
        "PyTorch, TensorFlow), MLOps (MLflow, model registry, deployment), "
        "evaluation rigor, data pipelines and production engineering skills."
    ),
    "mobile_developer": (
        "a mobile tech lead. You weigh native iOS (Swift/Kotlin) or "
        "cross-platform (Flutter / React Native), platform UX guidelines, "
        "testing on devices and CI for mobile."
    ),
    "site_reliability_engineer": (
        "a SRE manager. You weigh SLO/SLI thinking, incident response, "
        "observability, kernel/networking fundamentals, automation and "
        "post-mortem culture."
    ),
    "security_engineer": (
        "a CISO / AppSec lead. You weigh threat modelling, OWASP top 10, "
        "SAST/DAST tooling, code review for security, secure SDLC and "
        "incident response."
    ),
    "cloud_engineer": (
        "a cloud platform manager. You weigh deep expertise in at least one "
        "of AWS / Azure / GCP, IaC (Terraform), networking, IAM, cost "
        "optimisation and reliability."
    ),
    "other_it": (
        "a senior technical recruiter for IT positions. You focus on the "
        "concrete tools and responsibilities listed in the job posting and "
        "judge fit accordingly."
    ),
    "other": (
        "a senior recruiter. You focus on the concrete responsibilities and "
        "must-have requirements listed in the job posting."
    ),
}


# ---------------------------------------------------------------------------
# Common rules embedded in every system prompt
# ---------------------------------------------------------------------------
_GLOBAL_RULES = (
    "You are powering ApplyPilot AI, a desktop assistant that helps a real "
    "candidate apply for a real job. Follow these strict rules at all times:\n"
    "1. NEVER invent experiences, jobs, certifications or skills that are not "
    "in the candidate's CV, LinkedIn, GitHub or user answers.\n"
    "2. If a required skill is not backed by evidence, treat it as a gap or "
    "a clarifying question - do not assume.\n"
    "3. Always return STRICT JSON that matches the requested schema. No "
    "markdown fences, no commentary, no extra fields.\n"
    "4. Use neutral, professional, ATS-friendly English. Prefer concrete, "
    "measurable bullets ('reduced regression cycle by 30%') over vague claims.\n"
    "5. Your tone matches the persona below."
)


def system_prompt_for(role: RoleType, extra: str = "") -> str:
    persona = RECRUITER_PERSONAS.get(role, RECRUITER_PERSONAS["other"])
    role_label = ROLE_TYPE_LABELS.get(role, "the role")
    base = (
        f"{_GLOBAL_RULES}\n\n"
        f"PERSONA: For this session you are {persona} The current opening is a "
        f"{role_label}. Reason like a recruiter who is deciding whether to "
        f"invite this candidate to interview."
    )
    if extra:
        base = f"{base}\n\n{extra}"
    return base


# ---------------------------------------------------------------------------
# User prompts (one per AI method)
# ---------------------------------------------------------------------------
def _trim(text: str, limit: int = 12000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    tail = text[-200:]
    return f"{head}\n...[truncated]...\n{tail}"


def _dump(model: Any) -> str:
    if model is None:
        return "null"
    if hasattr(model, "model_dump"):
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2)
    return json.dumps(model, ensure_ascii=False, indent=2)


def analyze_job_user_prompt(raw_text: str, source_url: str | None = None) -> str:
    return (
        "Extract a JobPosting from the raw posting below.\n"
        "- title: the job title.\n"
        "- company: best guess of the hiring company name.\n"
        "- location, work_arrangement, seniority: infer from the text.\n"
        "- role_type: pick one of the allowed RoleType values that best matches.\n"
        "- responsibilities: bullet list, max 10.\n"
        "- required_skills / nice_to_have_skills / technologies: deduplicated.\n"
        "- ats_keywords: 8-15 high-signal keywords ranked by importance.\n"
        "- tone: e.g. 'startup', 'corporate', 'casual', 'formal'.\n"
        "- priorities: 3-6 most emphasised aspects of the posting.\n"
        f"- source_url: {source_url!r}\n"
        "- raw_text: copy the input verbatim into this field.\n\n"
        "RAW POSTING:\n" + _trim(raw_text)
    )


def analyze_candidate_user_prompt(
    cv_text: str,
    linkedin_text: str,
    github_username: str | None,
    github_projects: list[Any],
) -> str:
    projects_json = json.dumps(
        [p.model_dump(mode="json") if hasattr(p, "model_dump") else p for p in github_projects],
        ensure_ascii=False,
        indent=2,
    )
    return (
        "Build a CandidateProfile by merging the inputs below. Only include "
        "facts that appear in the inputs. Skills must be deduplicated.\n\n"
        f"GITHUB USERNAME: {github_username or '(none provided)'}\n\n"
        "CV TEXT:\n" + _trim(cv_text) + "\n\n"
        "LINKEDIN TEXT:\n" + _trim(linkedin_text) + "\n\n"
        "GITHUB PROJECTS (already fetched, do NOT invent more):\n" + projects_json
    )


def clarifying_questions_user_prompt(
    job: JobPosting, candidate: CandidateProfile
) -> str:
    return (
        "Compare the JobPosting requirements against the CandidateProfile. "
        "For every required or nice_to_have skill that is NOT clearly evidenced "
        "in the candidate inputs, generate a ClarifyingQuestion the user can "
        "answer to confirm or reject the skill. Limit to 8 questions, ordered "
        "by importance for this role.\n\n"
        "JOB:\n" + _dump(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate)
    )


def match_report_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
) -> str:
    return (
        "Produce a MatchReport that scores how well the candidate matches the "
        "job. Use ONLY the evidence and confirmed user answers - do not score "
        "skills the candidate has not demonstrated.\n\n"
        "JOB:\n" + _dump(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence)
    )


def resume_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
) -> str:
    return (
        "Produce a TailoredResume in the schema. Tailor it to the job:\n"
        "- Reorder skills so the most relevant for the job are first.\n"
        "- Reorder projects so relevant ones come first.\n"
        "- Rewrite bullet points to use ATS keywords from the job - but ONLY "
        "if they reflect actual evidence (CV / LinkedIn / GitHub / user "
        "answers marked 'practical_experience'). Treat 'learning_in_progress' "
        "answers in a Summary line, not as past experience. Skip 'omit'.\n"
        "- Professional summary should be 2-3 sentences, role-targeted.\n"
        "- Set role_targeted_for to the job title.\n"
        "- Do NOT include the candidate's contact details twice.\n\n"
        "JOB:\n" + _dump(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence)
    )


def cover_letter_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
) -> str:
    return (
        "Write a CoverLetter that is concrete, specific to the company and "
        "role, 3-4 paragraphs maximum. Reference at most TWO real "
        "achievements / projects from the candidate. Match the language of the "
        "job posting (English if the JD is English).\n\n"
        "JOB:\n" + _dump(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers)
    )


def interview_questions_user_prompt(
    job: JobPosting, candidate: CandidateProfile
) -> str:
    return (
        "Generate exactly 10 likely interview questions for this candidate "
        "applying to this role. For each: explain why_asked (what the "
        "interviewer is probing) and a suggested_answer grounded in the "
        "candidate's profile. Keep a balance between technical, behavioural, "
        "process and culture categories.\n\n"
        "JOB:\n" + _dump(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate)
    )


def skill_gap_user_prompt(match_report: MatchReport, job: JobPosting) -> str:
    return (
        "Produce a SkillGap[] list. For every gap in match_report (missing or "
        "weak), output a SkillGap with importance ('critical' / 'important' / "
        "'nice_to_have'), a short rationale, a learning_path of 3-5 concrete "
        "steps, and a suggested_project the candidate could build to fill the "
        "gap. Skip skills that are already strong.\n\n"
        "MATCH REPORT:\n" + _dump(match_report) + "\n\n"
        "JOB:\n" + _dump(job)
    )


def candidate_questions_for_company_prompt(
    job: JobPosting, candidate: CandidateProfile
) -> list[ClarifyingAnswer]:  # pragma: no cover - kept for symmetry, not used
    raise NotImplementedError


__all__ = [
    "RECRUITER_PERSONAS",
    "system_prompt_for",
    "analyze_job_user_prompt",
    "analyze_candidate_user_prompt",
    "clarifying_questions_user_prompt",
    "match_report_user_prompt",
    "resume_user_prompt",
    "cover_letter_user_prompt",
    "interview_questions_user_prompt",
    "skill_gap_user_prompt",
]
