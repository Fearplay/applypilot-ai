"""System & user prompt builders for the AI providers.

The prompts are role-aware: depending on the detected :data:`RoleType` the
``RECRUITER_PERSONAS`` table picks an appropriate "persona" for the AI to
emulate. This is what the spec calls "AI as an HR/recruiter expert
specialised for this position".
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

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
    "ai_software_engineer": (
        "a hiring engineering manager for a product team that ships AI-"
        "powered features. You weigh strong general software engineering "
        "(Python or TypeScript, system design, testing, code review, CI/CD) "
        "PLUS hands-on experience integrating foundation models into a "
        "real product (LLM SDKs, RAG, embeddings, evaluation harnesses, "
        "guardrails, observability for AI). You expect candidates to ship "
        "code, not just notebooks, and to reason about latency, cost, and "
        "safety trade-offs of model calls."
    ),
    "genai_engineer": (
        "a tech lead for a generative-AI / LLM application team. You weigh "
        "deep familiarity with at least one foundation-model API (OpenAI, "
        "Anthropic, Mistral, Bedrock, Vertex), prompt engineering, RAG "
        "with a vector store (pgvector, FAISS, Pinecone), tool / function "
        "calling, agent loops, eval frameworks (e.g. ragas, deepeval), and "
        "prompt / model versioning. Strong Python is table stakes; product "
        "thinking and an instinct for hallucination-resistance set great "
        "candidates apart."
    ),
    "software_engineer": (
        "a hiring engineering manager looking for a mid-to-senior software "
        "engineer. You weigh solid CS fundamentals, fluency in at least one "
        "production language (Python, Java, Go, TypeScript, C#, ...), system "
        "design (APIs, databases, queues, observability), CI/CD discipline, "
        "code-review craft, testing maturity (unit, integration, contract), "
        "and the ability to lead a feature end-to-end. Mentoring experience "
        "and clean cross-team communication are strong positives."
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
    "in the candidate's CV, LinkedIn, GitHub or user answers. If a fact is "
    "not in the inputs, it does NOT exist - do not extrapolate or assume. "
    "If the SAME fact appears twice in the inputs (e.g. one role described "
    "in Czech on LinkedIn and in English on the CV, or one degree under two "
    "translated names), MERGE it into a single entry rather than emitting "
    "duplicates. Two entries are 'the same' when their company/institution "
    "matches (after stripping legal suffixes like 's.r.o.', 'a.s.', 'Ltd', "
    "'Inc.') AND their year ranges overlap.\n"
    "2. If a required skill is not backed by evidence, treat it as a gap or "
    "a clarifying question. Be honest about what is missing rather than "
    "filling holes with plausible-sounding text.\n"
    "3. Always return STRICT JSON that matches the requested schema. No "
    "markdown fences, no commentary, no extra fields.\n"
    "4. Use neutral, professional, ATS-friendly prose. Prefer concrete, "
    "measurable bullets ('reduced regression cycle by 30%') over vague claims.\n"
    "5. Your tone matches the persona below. You are an HR / recruiter expert "
    "who tailors the resume, cover letter and interview prep to THIS specific "
    "position - not a generic application.\n"
    "6. LANGUAGE POLICY: input documents (job posting, CV, LinkedIn export, "
    "GitHub READMEs, user answers) may be written in Czech, English, or a "
    "mix of both. You read both languages natively and never lose meaning "
    "when crossing them. If the user answers a clarifying question in one "
    "language but the requested OUTPUT_LANGUAGE is different, translate the "
    "answer faithfully into the output language - do not invent extra "
    "detail. Schema field names, RoleType values and technical enums "
    "(e.g. 'practical_experience', 'critical') always stay in English. "
    "Otherwise the OUTPUT_LANGUAGE directive at the end of each user prompt "
    "is authoritative for every human-facing string.\n"
    "7. TYPOGRAPHY: write like a human, not like ChatGPT. Use ONLY the "
    "plain hyphen-minus character `-` (U+002D) for ALL dashes. NEVER use "
    "the em-dash `\u2014` (U+2014) or the en-dash `\u2013` (U+2013). Use "
    "straight ASCII quotes `\"` and `'`, never curly quotes `\u201C\u201D` "
    "or `\u2018\u2019`. Use three dots `...` instead of the unicode "
    "ellipsis `\u2026`. Do NOT decorate text with bullets like `\u2022`, "
    "`\u2023` or `\u25CF` outside the schema fields where bullets are "
    "explicitly requested as separate list items."
)


def _language_directive(output_language: str | None) -> str:
    """Return a one-liner the prompts append to lock the output language."""
    code = (output_language or "en").strip().lower()
    if code == "cs":
        return "OUTPUT_LANGUAGE: Czech. Write every human-facing string in Czech."
    return "OUTPUT_LANGUAGE: English. Write every human-facing string in English."


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


def _to_jsonable(value: Any) -> Any:
    """Recursively convert Pydantic models / containers into JSON-safe data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    return value


def _dump(model: Any, *, exclude: set[str] | None = None) -> str:
    """Serialize ``model`` to indented JSON, handling Pydantic models and lists.

    ``exclude`` only applies when ``model`` is a single Pydantic model and lets
    callers strip very large fields (e.g. ``JobPosting.raw_text``) before they
    are sent to the provider, which keeps token usage low.
    """
    if model is None:
        return "null"
    if isinstance(model, BaseModel):
        data = model.model_dump(mode="json", exclude=exclude or None)
        return json.dumps(data, ensure_ascii=False, indent=2)
    return json.dumps(_to_jsonable(model), ensure_ascii=False, indent=2)


# Fields we strip when dumping a JobPosting into a prompt: the raw text is
# already provided to the AI when we first analysed the job, and re-sending it
# in every downstream call (match report, resume, cover letter, ...) was
# burning a lot of tokens for zero added signal.
_JOB_PROMPT_EXCLUDE: set[str] = {"raw_text"}
_REFINE_CANDIDATE_PROMPT_EXCLUDE: set[str] = {
    "raw_cv_text",
    "raw_linkedin_text",
}


def _dump_job(job: JobPosting | None) -> str:
    return _dump(job, exclude=_JOB_PROMPT_EXCLUDE)


def _candidate_has_linkedin_signal(candidate: CandidateProfile) -> bool:
    if (candidate.raw_linkedin_text or "").strip():
        return True
    if (candidate.linkedin_url or "").strip():
        return True
    return any(
        getattr(entry, "source", "") in ("linkedin", "both")
        for entry in (*candidate.experience, *candidate.education)
    )


def _additional_notes_block(candidate: CandidateProfile) -> str:
    """Return the downstream-prompt block that surfaces user-typed notes.

    Returns an empty string when ``candidate.additional_notes`` is empty,
    so callers can unconditionally concatenate the block into their prompt
    without an extra ``if`` ladder. The block intentionally repeats the
    USER-AUTHORITATIVE rule because each prompt is a self-contained
    instruction to the model and we cannot rely on context from
    ``analyze_candidate``: by the time we reach match-report / resume /
    cover-letter / refine, the AI sees only ``CandidateProfile`` JSON +
    this prompt.
    """
    notes = (getattr(candidate, "additional_notes", "") or "").strip()
    if not notes:
        return ""
    trimmed = _trim(notes, limit=4000)
    return (
        "CANDIDATE ADDITIONAL NOTES (USER-AUTHORITATIVE - HARD RULE):\n"
        "- The candidate typed these clarifications in their own words. "
        "They may be in Czech, English or a mix. Read both languages "
        "natively.\n"
        "- Treat them as ground truth. When they contradict CV / "
        "LinkedIn / GitHub data (e.g. 'I finished college in 2023 "
        "without the bachelor's title', 'I want to start part-time "
        "because I plan a career change soon', 'at my last role I led "
        "the migration to Playwright'), the NOTES win - reflect them in "
        "your output.\n"
        "- Do NOT mention 'the user said' or 'according to the notes' in "
        "any user-facing text - integrate the facts naturally in "
        "OUTPUT_LANGUAGE so the resume / cover letter / report read as "
        "first-person career story, not a quoted dialogue.\n"
        "- Never invent facts that go BEYOND what the notes literally "
        "say. If the notes only mention 'no bachelor's title', do NOT "
        "extrapolate 'dropped out due to financial reasons' or similar.\n\n"
        f"NOTES TEXT:\n{trimmed}\n\n"
    )


def _position_translation_block(
    output_language: str, translate_positions: bool
) -> str:
    """Build the prompt block that controls role-title language behaviour.

    When ``translate_positions`` is ``True`` (the historical default) we
    feed the AI explicit Czech<->English examples for common job titles so
    it stops leaking source-language wording (e.g. ``"Vývojář Python"``
    inside an otherwise English resume). When ``False`` we instead pin
    the role title + company subtitle to the source language verbatim so
    the user can keep e.g. ``"Senior Software QA Engineer"`` even on a
    Czech resume - some users want the canonical English title for
    international ATS pipelines.

    The block is appended to ``resume_user_prompt`` and
    ``refine_resume_user_prompt`` right next to the OUTPUT LANGUAGE
    CONSISTENCY rules so the model picks it up as part of the same
    contract.
    """
    code = (output_language or "en").strip().lower()
    if not translate_positions:
        return (
            "POSITION TITLE EXCEPTION (HARD RULE - HIGHEST PRIORITY OVER OUTPUT LANGUAGE):\n"
            "- The user explicitly asked us NOT to translate role titles or "
            "company names. ResumeSection.title for `experience` and "
            "`projects`, plus ResumeSection.subtitle for `experience` (the "
            "company name with its employment-type decoration), MUST be "
            "kept VERBATIM from CANDIDATE.experience[].title / "
            "CANDIDATE.experience[].company / CANDIDATE.projects[].name "
            "in the SOURCE language those fields use. Do NOT translate "
            "them, paraphrase them, or replace them with their "
            "OUTPUT_LANGUAGE equivalents. Example: if the CV says "
            "'Senior Software QA Engineer' and OUTPUT_LANGUAGE is Czech, "
            "the title on the resume is still 'Senior Software QA "
            "Engineer' - NOT 'Senior softwarový QA inženýr'.\n"
            "- The employment-type decoration on the subtitle (Internship "
            "/ Stáž / Contract / Kontrakt / ...) ALSO follows this rule: "
            "use the wording the candidate's CV / LinkedIn used.\n"
            "- Bullets, professional_summary, periods (e.g. 'present' vs "
            "'současnost'), education degrees, education institution "
            "names, certification names and spoken_languages entries "
            "STILL follow OUTPUT_LANGUAGE - this exception covers ONLY "
            "experience / project TITLES and experience SUBTITLES.\n"
        )
    if code == "cs":
        return (
            "POSITION TITLE TRANSLATION EXAMPLES (the OUTPUT LANGUAGE "
            "CONSISTENCY rule applies, here are concrete reminders):\n"
            "- 'Software Engineer' -> 'Softwarový inženýr'\n"
            "- 'Senior Software QA Engineer' -> 'Senior softwarový QA inženýr'\n"
            "- 'Junior Developer' -> 'Junior vývojář'\n"
            "- 'Frontend Developer' -> 'Frontendový vývojář'\n"
            "- 'Backend Developer' -> 'Backendový vývojář'\n"
            "- 'Data Analyst' -> 'Datový analytik'\n"
            "- 'Project Manager' -> 'Projektový manažer'\n"
            "- 'Product Manager' -> 'Produktový manažer'\n"
            "- 'DevOps Engineer' -> 'DevOps inženýr'\n"
            "- 'Internship' -> 'Stáž', 'Intern' -> 'Stážista'\n"
            "Apply the same logic to every other role title. The Czech "
            "form is the canonical resume entry; do NOT leave the "
            "English original alongside it.\n"
        )
    return (
        "POSITION TITLE TRANSLATION EXAMPLES (the OUTPUT LANGUAGE "
        "CONSISTENCY rule applies, here are concrete reminders):\n"
        "- 'Vývojář' -> 'Developer'\n"
        "- 'Softwarový inženýr' -> 'Software Engineer'\n"
        "- 'Senior softwarový QA inženýr' -> 'Senior Software QA Engineer'\n"
        "- 'Junior vývojář' -> 'Junior Developer'\n"
        "- 'Frontendový vývojář' -> 'Frontend Developer'\n"
        "- 'Backendový vývojář' -> 'Backend Developer'\n"
        "- 'Datový analytik' -> 'Data Analyst'\n"
        "- 'Projektový manažer' -> 'Project Manager'\n"
        "- 'Produktový manažer' -> 'Product Manager'\n"
        "- 'DevOps inženýr' -> 'DevOps Engineer'\n"
        "- 'Stáž' -> 'Internship', 'Stážista' -> 'Intern'\n"
        "Apply the same logic to every other role title. The English "
        "form is the canonical resume entry; do NOT leave the Czech "
        "original alongside it.\n"
    )


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
    additional_notes: str = "",
) -> str:
    projects_json = json.dumps(
        [p.model_dump(mode="json") if hasattr(p, "model_dump") else p for p in github_projects],
        ensure_ascii=False,
        indent=2,
    )
    notes_clean = (additional_notes or "").strip()
    notes_block = ""
    if notes_clean:
        notes_block = (
            "ADDITIONAL CANDIDATE NOTES (USER-AUTHORITATIVE - HARD RULE):\n"
            "* The candidate typed these clarifications themselves on the "
            "Setup page. They may be written in Czech, English or both.\n"
            "* Treat them as ground truth. When they contradict CV / "
            "LinkedIn (e.g. CV says 'Bachelor in Informatics 2019-2023' "
            "but the notes say 'school ended in 2023, no bachelor's "
            "title'), the NOTES win - update the EducationEntry: keep "
            "institution + period, set degree to '' if no degree was "
            "earned, and put the user's clarification verbatim into "
            "`notes`.\n"
            "* Promote concrete facts: dates, employment_type "
            "('part-time' / 'stáž' / 'OSVČ'), promotion timing, "
            "responsibilities at past roles, motivation for the "
            "application, availability constraints (full-time vs "
            "part-time).\n"
            "* DO NOT invent anything that is not literally in the notes "
            "or the other inputs.\n"
            "* MANDATORY: copy the notes text VERBATIM into the returned "
            "`CandidateProfile.additional_notes` field, regardless of "
            "any other edits you derive from them. Downstream prompts "
            "(match report, resume, cover letter, refine) re-read this "
            "field directly so it MUST contain the user's original "
            "wording, not a paraphrase.\n\n"
            f"NOTES TEXT:\n{_trim(notes_clean, limit=4000)}\n\n"
        )
    return (
        "Build a CandidateProfile by merging the inputs below. Only include "
        "facts that appear in the inputs. Skills must be deduplicated.\n\n"
        "INFORMAL CV NORMALISATION:\n"
        "* The CV text may be a fully formatted resume OR just a few short "
        "sentences (e.g. 'Juraj Axay, 20 let, dělal jsem 4 roky v Gen Digital "
        "od 2021, dostal jsem povýšení na seniora 03/2024, studoval jsem "
        "Ječnou'). Treat both formats equally: extract every concrete fact "
        "you can see and PROMOTE it into the proper structured field:\n"
        "  - Names, ages, locations, contact details -> `personal_info`.\n"
        "  - Verbs of work ('dělal jsem', 'pracoval jsem', 'I worked at') "
        "    plus a company name -> a WorkExperience row.\n"
        "  - Promotions ('dostal jsem povýšení na seniora 03/2024') -> a "
        "    SECOND WorkExperience row at the same company with the new "
        "    title and `period` starting from the promotion date, OR add a "
        "    bullet to the existing role - whichever fits the wording best.\n"
        "  - Verbs of study ('studoval jsem', 'I studied at') plus an "
        "    institution name -> an EducationEntry row.\n"
        "  - Mentions of certificates ('mám ISTQB', 'I'm AWS certified') -> "
        "    a CertificationEntry row.\n"
        "* Infer reasonable `period` strings from the context. 'od 2021' "
        "with no explicit end date and no later contradicting role becomes "
        "'2021-Present' (Czech: '2021 - současnost'). 'od 03/2024' becomes "
        "'03/2024-Present'. Fixed pairs ('2021-2024') stay literal.\n"
        "* Preserve the language of the source text in the structured "
        "fields - do NOT translate role titles, company names or bullets "
        "into English here. The downstream prompts handle language switching "
        "via OUTPUT_LANGUAGE; this step is meant for round-tripping the "
        "candidate profile.\n"
        "* If a fact is mentioned but ambiguous (a half-typed company name, "
        "a missing location), set the corresponding field to its default "
        "(empty string / unknown) instead of guessing - never invent.\n"
        "PER-ENTRY METADATA (REQUIRED):\n"
        "* For every WorkExperience and EducationEntry, set a stable id "
        "(experience: 'exp-0', 'exp-1', ...; education: 'edu-0', 'edu-1', ...).\n"
        "* Set `source` to 'cv' if the entry only appears in the CV, "
        "'linkedin' if it only appears in the LinkedIn export, or 'both' if "
        "the same role/study appears in both inputs (different language "
        "counts as the SAME entry - merge it).\n"
        "* For WorkExperience, set `employment_type` from these keywords:\n"
        "  - 'Stáž' / 'Stážista' / 'Internship' / 'Trainee' -> 'internship'\n"
        "  - 'Na smlouvu' / 'Kontrakt' / 'Contract' / 'Contractor' -> 'contract'\n"
        "  - 'Brigáda' / 'Part-time' / 'Half-time' / 'Částečný úvazek' -> 'part_time'\n"
        "  - 'OSVČ' / 'Self-employed' / 'Freelance' / 'Na živnost' -> 'freelance'\n"
        "  - 'Dočasný' / 'Temporary' / 'Fixed-term' -> 'temporary'\n"
        "  - Otherwise default to 'full_time' for a real role, 'unknown' if "
        "  truly ambiguous.\n"
        "DEDUPLICATION (REQUIRED):\n"
        "* If the same role/study appears in both CV and LinkedIn (even in "
        "different languages, e.g. CV says 'Computer Science studies, Czech "
        "University of Life Sciences Prague, 2021-2024' and LinkedIn says "
        "'Provozně ekonomická fakulta ČZU v Praze, 2021-2023'), emit ONE "
        "entry with `source='both'`. Use the longer / richer description, "
        "union the bullets, and prefer the explicit degree name.\n"
        "* Same applies for roles whose wording differs but the COMPANY and "
        "TITLE refer to the same job, e.g. CV says 'Senior Software QA "
        "Engineer promoted 07/2025 - present, Gen Digital · Trust Based "
        "Solutions (Norton · Avast · AVG · CCleaner · LifeLock)' and "
        "LinkedIn says 'Senior Software QA Engineer · července 2025 - "
        "Present, Gen' - emit ONE entry with `source='both'`.\n"
        "* SCHOOL ABBREVIATIONS: a Czech abbreviation in one source vs "
        "its full English name in the other is the SAME entry "
        "('SPŠE Ječná' = 'Secondary Technical School of Electrical "
        "Engineering'; 'ČZU' = 'Czech University of Life Sciences'; "
        "'Provozně ekonomická fakulta' = 'Faculty of Economics and "
        "Management'). Emit ONE EducationEntry with `source='both'` and "
        "the longer description. If the two sources disagree on the END "
        "year (CV says 2024, LinkedIn says 2023), put BOTH periods on "
        "`notes` so the GUI can ask the user later.\n"
        "* CERTIFICATIONS: same course in two languages OR with vs. without "
        "the issuer prefix is the SAME entry. Examples: 'Java Programming' "
        "+ 'Oracle Academy - Java Programming' -> ONE entry; 'Python "
        "Akademie' + 'Engeto - Python Academy (12-week)' -> ONE entry; "
        "'Database Foundations' + 'Oracle Academy - Database Foundations' "
        "-> ONE entry. Always keep the longest, most specific name (with "
        "the issuer + year if available) and drop the bare duplicate.\n"
        "* SPOKEN LANGUAGES: same language in two languages is the SAME "
        "entry. Always emit each language only ONCE in the canonical "
        "English name. Examples: 'Czech' + 'čeština' -> just 'Czech'; "
        "'English' + 'angličtina' -> just 'English'; 'German' + 'němčina' "
        "-> just 'German'; 'Slovak' + 'slovenština' -> just 'Slovak'. The "
        "downstream renderer will translate to the target language if "
        "needed; here you must NEVER duplicate.\n"
        "* SPOKEN LANGUAGES - PROFICIENCY (REQUIRED): if the source text "
        "lists a proficiency next to the language (LinkedIn typically does: "
        "'angličtina (Full Professional)', 'čeština (Native or Bilingual)', "
        "'němčina (Elementary)'), you MUST KEEP that proficiency on the "
        "emitted entry. Format: 'English (Full Professional)' / 'Czech "
        "(Native or Bilingual)' / 'German (Elementary)'. The downstream "
        "dedup pass converts descriptive labels to CEFR codes (Native -> "
        "C2, Full Professional -> C1, Professional Working -> B2, Limited "
        "Working -> B1, Elementary -> A2). NEVER drop the proficiency "
        "annotation - that turns the resume sidebar into a useless 'just a "
        "list of languages' block. If you only have a CEFR code already "
        "('English (C1)'), keep it verbatim.\n"
        "* Strip legal suffixes ('s.r.o.', 'a.s.', 'Ltd', 'Inc.', "
        "'University', 'Univerzita', 'Fakulta') AND brand parentheticals "
        "('· Trust Based Solutions ...', ' (XYZ)') when comparing names. "
        "If after stripping, one name is a substring of the other (e.g. "
        "'Gen' ⊂ 'Gen Digital'), they are the same employer.\n"
        "* When the dates DIFFER between CV and LinkedIn for the same "
        "merged role/study (e.g. 2021-2024 vs 2021-2023), still emit ONE "
        "entry with `source='both'`, and put BOTH periods on the entry's "
        "`notes` field as 'CV: 2021-2024 | LinkedIn: 2021-2023' so the GUI "
        "can ask the user which one is correct. Do NOT silently pick one.\n"
        "* If the two periods only DIFFER IN FORMATTING but cover the same "
        "year range (e.g. CV '06/2023 - 07/2025' vs LinkedIn 'června 2023 "
        "- července 2025'), they are NOT a real conflict - leave `notes` "
        "empty for that entry so the GUI doesn't ask a useless question.\n"
        "* When unsure whether two entries are the same, KEEP both with "
        "their distinct `source` and let the app ask the user later.\n"
        "* CAREER PROGRESSION (HARD RULE): rows with DIFFERENT seniority "
        "prefixes (Junior / Senior / Lead / Staff / Principal / Head) are "
        "ALWAYS separate entries even when the company name matches and "
        "the date ranges look adjacent. Never collapse 'Junior X at Acme' "
        "into 'Senior X at Acme'. Each promotion is a row of its own.\n"
        "* REBRANDS vs PROGRESSION: when the company rebranded between "
        "two roles ('Avast Software' -> 'Gen Digital'), the rows still "
        "stay SEPARATE if the titles differ in seniority (Junior, mid, "
        "Senior, Lead). Same employer + new title = new row. Never "
        "merge a Junior into a Senior just because the company name "
        "now appears inside the new role's subtitle.\n\n"
        f"GITHUB USERNAME: {github_username or '(none provided)'}\n\n"
        + notes_block
        + "CV TEXT:\n" + _trim(cv_text) + "\n\n"
        "LINKEDIN TEXT:\n" + _trim(linkedin_text) + "\n\n"
        "GITHUB PROJECTS (already fetched, do NOT invent more):\n" + projects_json
    )


def clarifying_questions_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    output_language: str = "en",
) -> str:
    return (
        "Compare the JobPosting requirements against the CandidateProfile. "
        "For every required or nice_to_have skill that is NOT clearly evidenced "
        "in the candidate inputs, generate a ClarifyingQuestion the user can "
        "answer to confirm or reject the skill. Limit to 8 questions, ordered "
        "by importance for this role.\n\n"
        "ANSWER-TYPE PICKER (HARD RULES - the user complained that 'do you "
        "have experience with X' kept arriving as a free-text field instead "
        "of a Yes/No):\n"
        "- If the question is 'do you have experience with X', 'have you "
        "worked with Y', 'have you used Z', 'do you know W', 'have you "
        "led / shipped / written ...': ALWAYS answer_type='yes_no' with "
        "options=['Yes', 'No'] (translated to OUTPUT_LANGUAGE). NEVER "
        "short_text for these.\n"
        "- If the question lists explicit alternatives the user picks "
        "from (e.g. 'Which testing framework: xUnit / NUnit / MSTest?'), "
        "answer_type='single_choice' with options=[the literal "
        "alternatives].\n"
        "- If the question allows multiple alternatives at the same time "
        "(e.g. 'Which of the following AWS services have you used?'), "
        "answer_type='multi_choice' with the explicit options list.\n"
        "- ONLY use answer_type='short_text' for open numeric / open "
        "narrative questions: 'How many years of X?', 'Which project "
        "used X?', 'Briefly describe Y.' If you can phrase the same "
        "question as Yes/No, do that instead.\n"
        "- options must NEVER be empty when answer_type is yes_no, "
        "single_choice or multi_choice.\n"
        "- If `candidate.additional_notes` already answers a skill (e.g. "
        "the user wrote 'I have part-time experience with Playwright'), "
        "DO NOT generate a clarifying question for that skill. Use the "
        "notes as evidence and skip ahead to the next gap.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + _language_directive(output_language)
    )


def match_report_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
    output_language: str = "en",
) -> str:
    return (
        "Produce a MatchReport that scores how well the candidate matches the "
        "job. Use ONLY the evidence and confirmed user answers - do not score "
        "skills the candidate has not demonstrated. If a user answer arrived "
        "in a different language than OUTPUT_LANGUAGE, translate it - do not "
        "drop or fabricate detail.\n\n"
        "ADDITIONAL NOTES IMPACT (HARD RULE):\n"
        "- When the candidate's `additional_notes` declares an "
        "availability constraint ('part-time only', 'looking for a "
        "career change'), do NOT count it as a missing requirement and "
        "do NOT lower the technical score because of it. Mention it in "
        "`summary` and `recommended_improvements` so the user can decide "
        "whether to pursue this opening, but never silently penalise "
        "for a stated preference.\n"
        "- When the notes correct a fact (no degree earned, role "
        "rebrand, different period), use the corrected version when "
        "scoring matched / missing requirements - the notes override "
        "the CV / LinkedIn content for evidence purposes.\n\n"
        "SUGGESTED REMOVALS (irrelevant rows):\n"
        "- Populate `suggested_removals` with WorkExperience or EducationEntry "
        "rows from CANDIDATE that you judge UNRELATED to this specific job - "
        "for example a fast-food crew job (McDonald's, KFC), retail cashier, "
        "or unrelated manual labour when the role is an IT / engineering / "
        "office position. Use the row's existing `id` field verbatim - never "
        "invent ids.\n"
        "- Set `section` to `'experience'` for WorkExperience rows and "
        "`'education'` for EducationEntry rows.\n"
        "- For each entry write a short, plain-language `reason` (max ~120 "
        "characters) explaining why it doesn't fit. Be respectful: the user "
        "did real work and just needs help focusing the resume.\n"
        "- BE CONSERVATIVE: only flag rows that have NO transferable skills "
        "for this role. When in doubt, leave the row off the list - the user "
        "can always remove it manually. Education rows are almost never "
        "irrelevant; only flag them when the field of study is wildly "
        "different (e.g. a music conservatory degree for a backend SWE "
        "role) AND the candidate already has more relevant education.\n"
        "- The list is shown to the user with checkboxes DEFAULT-UNTICKED. "
        "Nothing is deleted automatically - this is a SUGGESTION the user "
        "explicitly confirms or rejects.\n"
        "- Cap at 4 suggested removals per report. Empty list is fine and is "
        "the right answer when every row plausibly belongs.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence) + "\n\n"
        + _language_directive(output_language)
    )


def resume_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
    output_language: str = "en",
    *,
    translate_positions: bool = True,
) -> str:
    has_linkedin = bool((candidate.raw_linkedin_text or "").strip())
    position_block = _position_translation_block(
        output_language, translate_positions
    )
    linkedin_block = (
        ""
        if has_linkedin
        else (
            "LINKEDIN ABSENCE (HARD RULE):\n"
            "- The candidate did NOT supply a LinkedIn export. "
            "``CANDIDATE.raw_linkedin_text`` is empty AND no entry has "
            "``source='linkedin'`` or ``'both'``. You MUST NOT mention "
            "LinkedIn anywhere in the resume - not in the contact line "
            "(unless `linkedin` field below is non-null), not in any "
            "bullet, not in the summary. Do NOT invent claims like "
            "'verified on LinkedIn'. The only biographical sources "
            "available are the CV text, GitHub data, and clarifying "
            "answers - reason from those alone.\n\n"
        )
    )
    return (
        "Produce a TailoredResume in the schema. Tailor it to the job:\n"
        + linkedin_block
        + "ADDITIONAL NOTES IMPACT (HARD RULE):\n"
        "- Treat `candidate.additional_notes` as USER-AUTHORITATIVE - it "
        "OVERRIDES CV / LinkedIn data when they conflict (degree status, "
        "dates, employment_type, responsibilities at past roles).\n"
        "- Examples: notes 'school ended 2023, no bachelor's title' "
        "-> education entry keeps institution + period but degree is "
        "empty and bullets reflect the field of study without claiming "
        "a degree. Notes 'led Playwright migration at Avast' -> add "
        "that bullet to the matching WorkExperience entry only if the "
        "company name matches; otherwise treat it as additional context "
        "for the summary / cover letter rather than fabricating a new "
        "row.\n"
        "- Never quote the notes literally in the resume. Integrate the "
        "facts naturally in OUTPUT_LANGUAGE so the resume reads as a "
        "first-person career story, not a transcript.\n"
        + "- Reorder skills so the most relevant for the job are first.\n"
        "- Rewrite bullet points to use ATS keywords from the job - but ONLY "
        "if they reflect actual evidence (CV / LinkedIn / GitHub / user "
        "answers marked 'practical_experience'). Treat 'learning_in_progress' "
        "answers in a Summary line, not as past experience. Skip 'omit'.\n"
        "- Professional summary should be 2-3 sentences, role-targeted.\n"
        "- Set role_targeted_for to the job title.\n"
        "- Do NOT include the candidate's contact details twice.\n"
        "- Skill / technology names stay in their canonical form "
        "(e.g. 'Playwright', 'CI/CD') regardless of OUTPUT_LANGUAGE.\n"
        "REORDER, NEVER DELETE (HARD RULE):\n"
        "- KEEP every WorkExperience, EducationEntry, CertificationEntry and "
        "course from the candidate input. Do NOT drop any of them, even if "
        "you judge them irrelevant to this job.\n"
        "- If a row really has nothing to do with the job, DEMOTE it: write "
        "a shorter bullet (but at least one bullet), drop trailing detail "
        "and place it lower in the section. Demotion is allowed - deletion "
        "is never allowed at this stage. Deletion is the user's decision "
        "and a confirmation dialog will ask them explicitly before anything "
        "is removed from the exported resume.\n"
        "- This rule covers experience (paid, internship, freelance), "
        "education (every degree the candidate listed), certifications, and "
        "courses. Treat each row as evidence the user wants to show.\n"
        "BULLETS - PRESERVE EXISTING DETAIL (HARD RULE):\n"
        "- For every WorkExperience that has bullets in candidate.experience, "
        "the tailored output MUST keep at LEAST 2 of those bullets (or all "
        "of them if the source had fewer than 2). You may rephrase, "
        "translate or shorten the bullet text, but you may NOT silently "
        "drop bullets just because they aren't keyword-aligned with the "
        "job. Sparse resumes look bad - if the source CV listed five "
        "responsibilities for a role, the output should still cover most of "
        "them.\n"
        "- For roles where the candidate input has NO bullets at all "
        "(e.g. just a title and a company because that is all the CV had), "
        "leave the bullet list empty too. Do NOT invent generic responsibilities "
        "just to make the section look fuller.\n"
        "- ONE LANGUAGE PER BULLET LIST (HARD RULE): every bullet in a "
        "single ResumeSection.bullets list MUST be written in "
        "OUTPUT_LANGUAGE. Never emit a Czech bullet next to its English "
        "twin in the same section ('\u0160koln\u00ed st\u00e1\u017ee zam\u011b\u0159en\u00e9 "
        "na Python game development...' followed by 'School internships' / "
        "'Python game development' / 'IBM Watson chatbot in a 2-person "
        "team') - that is a duplicate, not extra detail. Pick the "
        "OUTPUT_LANGUAGE wording, drop the other-language twin entirely.\n"
        "EDUCATION (HARD RULE - INSTITUTION REQUIRED):\n"
        "- Every emitted ResumeSection in `education` MUST have a "
        "non-empty `subtitle` (the institution name, e.g. 'Czech "
        "University of Life Sciences Prague' / 'Provozn\u011b ekonomick\u00e1 "
        "fakulta \u010cZU v Praze'). NEVER emit an education row with only "
        "a field of study and no school - 'Informatika studies', "
        "'Computer Science studies', 'Bachelor of X' on its own with no "
        "subtitle is a broken row that hurts the resume more than it "
        "helps. If the candidate input lists a degree but the "
        "institution is unknown / empty, OMIT that education row "
        "entirely. The user can add it later via Refine with AI.\n"
        "- Do NOT pad the title with the word 'studies' / 'studium' "
        "when the field of study is already a noun phrase. 'Informatika' "
        "alone is a perfect title; 'Informatika studies' is broken "
        "Czech-English code-mix.\n"
        "DEDUPLICATION:\n"
        "- Treat two experience entries with the same company and overlapping "
        "dates as the SAME role - emit ONE TailoredResume.experience item. "
        "If candidate.experience already contains both languages of the same "
        "role, prefer the entry with `source='both'`, otherwise the longer "
        "one; never emit twins.\n"
        "- Same rule for education: one row per institution + period, even "
        "when the inputs spelled the institution differently in CZ and EN.\n"
        "- Same rule for certifications and spoken_languages: one row per "
        "course / language even if the inputs included it twice (e.g. "
        "'Java Programming' and 'Oracle Academy - Java Programming' are "
        "ONE certification; 'Czech' and 'čeština' are ONE language).\n"
        "OUTPUT LANGUAGE CONSISTENCY:\n"
        "- Every human-facing string in the resume must be in OUTPUT_LANGUAGE: "
        "professional_summary, ResumeSection.title, ResumeSection.subtitle, "
        "ResumeBullet.text, education degree names, institution names, "
        "certification names, and spoken_languages entries.\n"
        "- If the candidate input has a section in the OTHER language "
        "(e.g. CV is in English but a LinkedIn-original education entry "
        "still reads 'Provozně ekonomická fakulta ČZU v Praze, ledna 2021 "
        "- července 2023'), TRANSLATE it into OUTPUT_LANGUAGE in the "
        "tailored resume. Czech month names ('ledna', 'července') become "
        "their numeric or English equivalents and vice versa.\n"
        "- NEVER mix English words into the middle of a Czech sentence "
        "(or Czech words into an English one). When OUTPUT_LANGUAGE is "
        "Czech, every adjective inside a `professional_summary` or a "
        "`ResumeBullet.text` must also be Czech. Translate the noise "
        "words: 'acting' -> 'pověřený', 'interim' -> 'dočasně pověřený', "
        "'lead' (used as adjective) -> 'vedoucí', 'team' -> 'tým', "
        "'mentoring' -> 'mentoring' (international, fine), 'review' -> "
        "'review' (international, fine). Conversely, when OUTPUT_LANGUAGE "
        "is English, never leave 'Stáž', 'Vývojář' or other Czech words "
        "embedded in an English bullet - translate them to 'Internship' "
        "/ 'Developer'.\n"
        "- ONLY product / technology / brand names stay canonical: "
        "'Playwright', 'C#', 'Gen Digital', 'CI/CD'. Job titles, company "
        "subtitles, period strings and bullet prose all follow OUTPUT_LANGUAGE.\n"
        + position_block
        + "EMPLOYMENT TYPE:\n"
        "- Use each WorkExperience.employment_type to decorate the role's "
        "subtitle: 'Internship', 'Contract', 'Part-time', 'Freelance', "
        "'Self-employed', 'Temporary'. Skip the decoration for 'full_time' "
        "and 'unknown'. Translate the decoration into OUTPUT_LANGUAGE "
        "(e.g. Czech 'Stáž', 'Kontrakt', 'Částečný úvazek', 'OSVČ').\n"
        "PROJECTS (Github - safe to filter, NOT user-claimed history):\n"
        "- Keep AT MOST 5 projects. Rank them by overlap of "
        "`detected_technologies` (and topics / description) with "
        "`job.required_skills`, `job.ats_keywords`, and "
        "`job.nice_to_have_skills`. Drop unrelated personal projects unless "
        "their `stars` > 5 or topics overlap with the job. For each kept "
        "project, write ONE bullet that ties it to the job using ONLY facts "
        "in `description`, `readme_excerpt` or `detected_technologies` - "
        "never invent metrics, dates or features. The 5-project cap is "
        "intentional and overrides the REORDER-NEVER-DELETE rule above "
        "*only* for `projects` (which are user-public Github data, not "
        "explicit profile claims).\n"
        "- HARD RULE: every project you emit MUST have a `title` that "
        "matches an entry in CANDIDATE.projects[].name (case-insensitive, "
        "ignoring punctuation / whitespace) OR a project name explicitly "
        "mentioned in CANDIDATE.raw_cv_text / raw_linkedin_text / a user "
        "answer marked 'practical_experience'. NEVER invent a project just "
        "because it would 'fit the role'. If the candidate has no GitHub "
        "projects and no CV-mentioned ones, leave the Projects section "
        "EMPTY rather than fabricating one.\n"
        "- ALWAYS include AT LEAST ONE project when the candidate has any "
        "GitHub projects available. An empty Projects section makes the "
        "resume look weak even for very specific roles - if no project is a "
        "strong technical match, pick the highest-quality one (most stars, "
        "richest README) and write a one-bullet overview that frames the "
        "transferable skills (problem solving, language proficiency, "
        "shipped product) without overclaiming role relevance.\n"
        "NO HALLUCINATION:\n"
        "- If a date or responsibility is unclear from the inputs, write it "
        "generically rather than guessing - or skip it. Do not invent "
        "metrics, team sizes or business impact.\n"
        "DATES / PERIOD (HARD RULE):\n"
        "- Every experience and education entry MUST have a `period` field "
        "with dates taken from the candidate data. Use the format from the "
        "source (e.g. '04/2022 - 06/2023', '2017 - 2021', '07/2025 - present'). "
        "If the output language is Czech, translate 'present' to 'současnost'. "
        "Never omit dates - they are critical for recruiters.\n"
        "LANGUAGES - CEFR ONLY (HARD RULE):\n"
        "- Languages MUST use CEFR levels only: C2, C1, B2, B1, A2, A1. "
        "Never use descriptive labels like 'Native or Bilingual', 'Full "
        "Professional', 'Elementary' or 'passive'. Convert them: "
        "Native/Bilingual -> C2, Full Professional -> C1, Professional "
        "Working -> B2, Limited Working -> B1, Elementary -> A2.\n"
        "CAREER PROGRESSION (HARD RULE):\n"
        "- Career progression entries (Junior -> Mid -> Senior at the same "
        "company) are SEPARATE experience rows, each with their own period "
        "and distinct title. Never merge them into one entry.\n"
        "TAILORING RULES (compact):\n"
        "- Classify every position by relevance: DIRECTLY RELATED -> 3-5 "
        "rich bullets and place first; PARTIALLY RELATED -> 2-3 bullets; "
        "UNRELATED -> 1 minimal bullet. Never DELETE a real candidate "
        "entry just because it isn't relevant - just shorten it.\n"
        "- professional_summary: 2-4 sentences mentioning the target role "
        "title; never generic.\n"
        "- technical_skills: ordered by relevance to the target job, "
        "grouped by category when the list is long.\n"
        "- For IT roles, the candidate's main IT employer gets the "
        "richest bullet block; surface internal toolkits/frameworks as "
        "bullets there. Senior roles call out mentoring, leadership and "
        "cross-team collaboration explicitly.\n"
        "- Each experience entry leads with its highest-impact bullet "
        "(the one most aligned with the job requirements).\n"
        "- Quantify achievements when the inputs support it (X% bugs "
        "reduced, N tests automated). NEVER invent numbers, dates or "
        "team sizes.\n"
        "- Education entries: institution + degree/field + period; "
        "highlight IT-adjacent fields when the role is technical.\n"
        "- Certifications: include the issuing body when known.\n"
        "- Resume must be ATS-friendly: standard section headings, no "
        "tables/columns/graphics, naturally weave job keywords into "
        "bullets. Length: 1-2 pages for junior/mid, up to 3 pages for "
        "seniors with extensive relevant experience.\n"
        "- Contact line: 'email | phone | location'; LinkedIn / GitHub "
        "go in their dedicated fields, never on the contact line.\n"
        "- Every claim must be traceable to the candidate inputs - no "
        "fabrication, no exaggeration.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence) + "\n\n"
        + _language_directive(output_language)
    )


def cover_letter_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    output_language: str = "en",
) -> str:
    return (
        "Write a CoverLetter that is concrete, specific to the company and "
        "role, 3-4 paragraphs maximum. Reference at most TWO real "
        "achievements / projects from the candidate. Salutation, body and "
        "closing must all sit inside the same OUTPUT_LANGUAGE.\n\n"
        "ADDITIONAL NOTES IMPACT (HARD RULE):\n"
        "- When `candidate.additional_notes` declares motivation ('I'm "
        "very interested in this position'), an availability constraint "
        "('want to start part-time, planning a career change'), a "
        "missing-degree clarification, or any first-person context the "
        "CV / LinkedIn does NOT carry, you MUST surface it in ONE "
        "dedicated paragraph - typically the second or third. Phrase it "
        "in OUTPUT_LANGUAGE as the candidate's own voice (first person), "
        "never paste the notes verbatim.\n"
        "- Be honest: don't gloss over a part-time preference or a "
        "missing degree. State it briefly and reframe it as confidence "
        "('I'd like to start part-time and grow into the role', not "
        "'unfortunately I can only do part-time').\n"
        "- Never invent extra context that goes BEYOND what the notes "
        "literally say.\n\n"
        "STRUCTURE RULES (HARD - violations will be stripped before save):\n"
        "- Do NOT include a heading line such as 'Cover letter for X at Y' "
        "or any role-and-company title at the top. The first content the "
        "user reads must be the salutation. The export already names the "
        "file '{firstname_lastname}_cover_letter' so the recruiter knows "
        "what they're opening.\n"
        "- The body must read as a direct message to the hiring team. "
        "Address them as humans, not as a job listing.\n"
        "- Put the sign-off ONLY in the structured `closing` (e.g. 'Best "
        "regards,' / 'S pozdravem,') and `signature` (the candidate's full "
        "name) fields. Do NOT also paste 'Best regards, <Name>' or "
        "'S pozdravem, <Jméno>' at the end of the last body paragraph - the "
        "exporter prints `closing` and `signature` once at the end and a "
        "duplicate inside the body would show up twice.\n"
        "- The last body paragraph must be a forward-looking line "
        "(availability, willingness to discuss next steps, etc.) and must "
        "NOT end with a sign-off phrase.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        + _language_directive(output_language)
    )


def interview_questions_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    output_language: str = "en",
) -> str:
    return (
        "Generate exactly 10 likely interview questions for this candidate "
        "applying to this role. For each: explain why_asked (what the "
        "interviewer is probing) and a suggested_answer grounded in the "
        "candidate's profile. Keep a balance between technical, behavioural, "
        "process and culture categories. The category enum stays in English "
        "('technical' etc.); question, why_asked and suggested_answer follow "
        "OUTPUT_LANGUAGE.\n"
        "- If `candidate.additional_notes` mentions an availability "
        "preference (part-time, career change), motivation or a "
        "missing-degree clarification, weave them into the relevant "
        "suggested_answer so the candidate has rehearsed phrasing ready "
        "for tough questions like 'why this role?' / 'why part-time?' / "
        "'why didn't you finish your degree?'.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + _language_directive(output_language)
    )


def skill_gap_user_prompt(
    match_report: MatchReport,
    job: JobPosting,
    output_language: str = "en",
) -> str:
    return (
        "Produce a SkillGap[] list. For every gap in match_report (missing or "
        "weak), output a SkillGap with importance ('critical' / 'important' / "
        "'nice_to_have'), a short rationale, a learning_path of 3-5 concrete "
        "steps, and a suggested_project the candidate could build to fill the "
        "gap. Skip skills that are already strong. Importance stays in "
        "English; rationale, learning_path entries and suggested_project "
        "follow OUTPUT_LANGUAGE.\n\n"
        "MATCH REPORT:\n" + _dump(match_report) + "\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        + _language_directive(output_language)
    )


def refine_resume_user_prompt(
    current_resume: Any,
    feedback: str,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
    output_language: str = "en",
    previous_explanation: str = "",
    *,
    translate_positions: bool = True,
) -> str:
    has_linkedin = _candidate_has_linkedin_signal(candidate)
    position_block = _position_translation_block(
        output_language, translate_positions
    )
    linkedin_block = (
        ""
        if has_linkedin
        else (
            "LINKEDIN ABSENCE (HARD RULE):\n"
            "- The candidate did NOT supply a LinkedIn export for this "
            "session. ``CANDIDATE.raw_linkedin_text`` is empty AND no "
            "experience / education entry has ``source='linkedin'`` or "
            "``'both'``. Therefore you MUST NOT reference LinkedIn anywhere "
            "in your output - not in `explanation`, not in any bullet, not "
            "in `professional_summary`. Do NOT say 'LinkedIn does not "
            "list X', 'add this to your LinkedIn', 'check your LinkedIn', "
            "'na LinkedInu nemáš X', 'dopl\u0148 to na LinkedIn'. The only "
            "biographical sources available are the CV text, GitHub data, "
            "and the user's clarifying answers - reason from those alone.\n\n"
        )
    )
    prev_explanation_block = ""
    if previous_explanation.strip():
        prev_explanation_block = (
            "PREVIOUS_AI_EXPLANATION (the note YOU wrote in the last refine "
            "round, shown for context):\n"
            f"{previous_explanation.strip()}\n\n"
            "AFFIRMATION INTERPRETATION (HARD RULE):\n"
            "- If the user's current FEEDBACK is a short affirmation ('yes', "
            "'ano', 'jo', 'ok', 'okay', 'sure', 'go ahead', 'do it', "
            "'klidn\u011b', 'jasn\u011b', 'proved\u2019', 'sma\u017e to', "
            "'odstra\u0148 to', 'jdi do toho') WITHOUT any other concrete "
            "instructions, treat it as the user AGREEING with the SUGGESTION "
            "you made in PREVIOUS_AI_EXPLANATION above. If your previous "
            "explanation included a question like 'Mohu sma\u017eat X?' / "
            "'Should I delete X?' / 'Chce\u0161 to odstranit?' / 'Doplnit Y?', "
            "perform that exact action now (delete X, add Y, etc.). Be "
            "decisive: the user already answered. Do NOT just acknowledge - "
            "actually mutate the resume to reflect the action you proposed.\n"
            "- If the affirmation is paired with a more specific instruction "
            "(e.g. 'Ano, sma\u017e tu pozici Junior Developer'), the specific "
            "instruction wins and you do not need to re-derive the action "
            "from PREVIOUS_AI_EXPLANATION.\n\n"
        )
    return (
        "The user has reviewed the current tailored resume and provided "
        "feedback describing what is wrong or missing. Your task is to "
        "produce an UPDATED resume that addresses every point in the "
        "user's feedback while preserving everything that was already "
        "correct, and to explain (briefly) what you changed.\n\n"
        "OUTPUT SCHEMA: return a `RefinedResume` JSON with two fields:\n"
        "- `resume`: the complete updated `TailoredResume` JSON. NOT a "
        "diff and NOT a partial update - this object replaces the current "
        "resume entirely.\n"
        "- `explanation`: 1-3 sentences (in OUTPUT_LANGUAGE) telling the "
        "user WHAT you changed and, when relevant, WHY the previous "
        "version had the issue. Be concrete and reference the specific "
        "row by title and company. Example: 'Pozici Junior Software QA "
        "Engineer @ Avast Software (04/2022 - 06/2023) jsem v původním "
        "návrhu vynechal, protože jsem ji omylem sloučil s pozdější rolí "
        "v Gen Digital. Nyní ji doplňuji jako samostatný řádek.'\n\n"
        "USER IS AUTHORITATIVE (HARD RULE - HIGHEST PRIORITY):\n"
        "- The user is the FINAL AUTHORITY over their own resume. When "
        "their feedback contradicts the original CV / LinkedIn / candidate "
        "data, the user wins. They know their own life better than the "
        "input documents do. If they say 'change German A2 to B2', do "
        "exactly that - do not preserve A2 because the original input "
        "said A2. If they say 'rename position X to Y', use Y. If they "
        "say 'school is XYZ University', set it to XYZ University.\n"
        "- DIRECT TEXT REPLACEMENT: when the user explicitly asks to "
        "change one specific phrase to another (English: 'change \"A\" "
        "to \"B\"', 'replace \"A\" with \"B\"', 'rename \"A\" to \"B\"'; "
        "Czech: 'zm\u011b\u0148 \"A\" na \"B\"', 'p\u0159epi\u0161 \"A\" "
        "na \"B\"', 'dej tam \"B\" m\u00edsto \"A\"', 'p\u0159elo\u017e "
        "\"A\" na \"B\"'), perform that EXACT substitution wherever 'A' "
        "appears in the resume (bullets, summary, subtitle, title - "
        "everywhere). Do NOT preserve the original wording for "
        "'canonicalization', 'technical terminology' or 'consistency' "
        "reasons - the user explicitly asked for the change. Example: "
        "user says 'p\u0159elo\u017e Java backend development na Java "
        "backend v\u00fdvoj' -> every occurrence of 'Java backend "
        "development' in the resume becomes 'Java backend v\u00fdvoj'. "
        "The general 'product / brand names stay canonical' policy from "
        "the resume prompt is OVERRIDDEN by an explicit user instruction.\n"
        "- LANGUAGE LEVEL CHANGES: when the user says 'n\u011bm\u010dina "
        "A2 m\u00e1 b\u00fdt B2', 'angli\u010dtina C1 ne C2', 'change "
        "French to B1', update the relevant entry in `spoken_languages` "
        "to the requested CEFR level. The CEFR-only rule still applies "
        "to the format ('B2', not 'Professional Working'), but the "
        "level itself is whatever the user said.\n"
        "- FACT CORRECTIONS: when the user corrects a date, school name, "
        "company, location, or any other piece of data, accept it. The "
        "candidate profile is just our best parse of imperfect inputs - "
        "the user's correction overrides it.\n"
        "- DELETION CONFIRMATIONS: when the user agrees to a deletion "
        "you previously suggested (see AFFIRMATION INTERPRETATION below), "
        "actually drop the row. Don't just say 'I would drop X' and leave "
        "X in the resume.\n\n"
        + prev_explanation_block
        + linkedin_block
        + "FEEDBACK INTERPRETATION (HARD RULE):\n"
        "- The feedback may be ONE sentence OR a numbered list ('1) ...\\n"
        "2) ...\\n3) ...'). When you see a numbered list, treat each item "
        "as a SEPARATE actionable request and address them ALL in the "
        "single updated resume you return. Do NOT skip any numbered item "
        "even if you think it overlaps with another - the user typed them "
        "as distinct concerns.\n"
        "- If the user's feedback contains words like 'missing', 'chybí', "
        "'chybi', 'vynechal', 'vynechala', 'vynechals', 'vynechalas', "
        "'zapomněl', 'zapomněls', 'forgot', 'add', 'přidej', 'doplň', "
        "'doplnit', 'kde je', 'where is' near a position / education / "
        "certificate name, the correct action is to ADD that row to the "
        "resume - NEVER interpret it as a request to delete a different "
        "row.\n"
        "- If the user names a specific row (company name, role title, "
        "school name, course name) and says it's missing or wrong, your "
        "first move is to look that row up in CANDIDATE below and inject "
        "it back into the resume with the data the user already provided. "
        "Do NOT invent a new row from scratch when the candidate data "
        "already has it.\n"
        "- 'remove', 'smaž', 'odstraň', 'delete', 'odeber' are the only "
        "deletion intents. Always ask yourself which intent matches the "
        "feedback before changing anything.\n\n"
        "PROJECTS - SOURCE OF TRUTH (HARD RULE):\n"
        "- 'add a project', 'more projects', 'přidej projekt', 'více "
        "projektů', 'doplň projekt' MUST be answered using ONLY the "
        "projects already present in CANDIDATE.projects (these are the "
        "candidate's real GitHub repositories) or projects the candidate "
        "explicitly described in their CV / LinkedIn / clarifying answers. "
        "NEVER invent a project name, technology stack or outcome that is "
        "not in the inputs - even if it would 'fit the role' on paper.\n"
        "- If the user names a specific project that DOES NOT exist in "
        "CANDIDATE.projects and is not mentioned in CV / LinkedIn / "
        "answers either, do NOT add it. Instead leave the resume "
        "unchanged for that point and tell the user honestly in "
        "`explanation` that the project wasn't found in their data, e.g. "
        "'Projekt \"Foo\" jsem nenašel ve tvých GitHub repozitářích ani "
        "v CV, takže ho neuvádím - dej mi prosím odkaz nebo popis a "
        "doplním ho v dalším kole.'\n"
        "- When asked for 'more projects' without naming any, pick the "
        "next unused entry from CANDIDATE.projects ranked by overlap "
        "with the job (highest `relevance_score` / matching topics / "
        "biggest stars). Use ONLY that project's `name`, `description`, "
        "`readme_excerpt`, `detected_technologies`, `primary_language`, "
        "`stars` and `url` to write the resume bullet - never extrapolate.\n\n"
        + position_block
        + "INSTRUCTIONS:\n"
        "- Read the CURRENT RESUME below. It is a valid TailoredResume JSON.\n"
        "- Read the USER FEEDBACK carefully. Fix, add or rework exactly "
        "what the user asks for - and only that. Do not silently revert "
        "other parts of the resume.\n"
        "- All rules from the original resume generation still apply: no "
        "hallucination, CEFR-only language levels, mandatory dates/periods, "
        "career progression as separate entries (Junior vs Senior at the "
        "same company are separate rows), ATS-friendly prose, "
        "OUTPUT_LANGUAGE consistency for both `resume` and `explanation`.\n"
        "- If the user asks to add something that is not in the candidate "
        "data, say so honestly in `explanation` rather than inventing "
        "content. The `resume` should still be valid even when the user's "
        "request can't be fulfilled - leave the existing rows intact.\n\n"
        "CURRENT RESUME:\n" + _dump(current_resume) + "\n\n"
        "USER FEEDBACK:\n" + feedback.strip() + "\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n"
        + _dump(candidate, exclude=_REFINE_CANDIDATE_PROMPT_EXCLUDE)
        + "\n\n"
        + _additional_notes_block(candidate)
        + "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence) + "\n\n"
        + _language_directive(output_language)
    )


def refine_cover_letter_user_prompt(
    current_cover_letter: Any,
    feedback: str,
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    output_language: str = "en",
    previous_explanation: str = "",
) -> str:
    """Build the user prompt for a cover-letter refine pass.

    Mirrors :func:`refine_resume_user_prompt` so the cover-letter loop
    inherits the same affirmation interpretation, LinkedIn safety net
    and direct-text-replacement rules. The model returns a
    :class:`RefinedCoverLetter` with the FULL updated cover letter plus
    a 1-3 sentence explanation. The deterministic safety nets in
    :mod:`src.services.cover_letter_generator` (role-heading stripper,
    duplicate sign-off cleanup) run on the result regardless of which
    provider produced it.
    """
    has_linkedin = _candidate_has_linkedin_signal(candidate)
    linkedin_block = (
        ""
        if has_linkedin
        else (
            "LINKEDIN ABSENCE (HARD RULE):\n"
            "- The candidate did NOT supply a LinkedIn export for this "
            "session. Do NOT reference LinkedIn anywhere in the cover "
            "letter or `explanation`. Reason from the CV / GitHub data / "
            "user answers alone.\n\n"
        )
    )
    prev_explanation_block = ""
    if previous_explanation.strip():
        prev_explanation_block = (
            "PREVIOUS_AI_EXPLANATION (the note YOU wrote in the last refine "
            "round, shown for context):\n"
            f"{previous_explanation.strip()}\n\n"
            "AFFIRMATION INTERPRETATION (HARD RULE):\n"
            "- If the user's current FEEDBACK is a short affirmation ('yes', "
            "'ano', 'jo', 'ok', 'okay', 'sure', 'go ahead', 'do it', "
            "'klidn\u011b', 'jasn\u011b', 'proved\u2019', 'sma\u017e to', "
            "'odstra\u0148 to', 'jdi do toho') WITHOUT any other concrete "
            "instructions, treat it as the user AGREEING with the SUGGESTION "
            "you made in PREVIOUS_AI_EXPLANATION above. Perform the action "
            "you proposed (rewrite the opening paragraph, mention X, drop Y, "
            "etc.). Be decisive: the user already answered. Do NOT just "
            "acknowledge - actually mutate the cover letter to reflect the "
            "action you proposed.\n\n"
        )
    return (
        "The user has reviewed the current tailored cover letter and "
        "provided feedback describing what is wrong or missing. Your task "
        "is to produce an UPDATED cover letter that addresses every point "
        "in the user's feedback while keeping everything that was already "
        "fine, and to explain (briefly) what you changed.\n\n"
        "OUTPUT SCHEMA: return a `RefinedCoverLetter` JSON with two "
        "fields:\n"
        "- `cover_letter`: the complete updated `CoverLetter` JSON. NOT a "
        "diff and NOT a partial update - this object replaces the current "
        "cover letter entirely. Keep the structured `salutation`, "
        "`paragraphs`, `closing`, `signature` shape.\n"
        "- `explanation`: 1-3 sentences (in OUTPUT_LANGUAGE) telling the "
        "user WHAT you changed and, when relevant, WHY the previous "
        "version had the issue. Be concrete and reference the specific "
        "paragraph or sentence you rewrote.\n\n"
        "USER IS AUTHORITATIVE (HARD RULE - HIGHEST PRIORITY):\n"
        "- The user is the FINAL AUTHORITY over their own cover letter. "
        "When their feedback contradicts the original CV / candidate data, "
        "the user wins. If they say 'tone too humble', soften the apologies "
        "and add concrete impact. If they say 'change Avast to Gen Digital', "
        "use Gen Digital. If they say 'mention RAG project', mention it.\n"
        "- DIRECT TEXT REPLACEMENT: when the user explicitly asks to "
        "change one specific phrase to another, perform that EXACT "
        "substitution wherever the original phrase appears in the cover "
        "letter (salutation, paragraphs, closing).\n\n"
        + prev_explanation_block
        + linkedin_block
        + "FEEDBACK INTERPRETATION (HARD RULE):\n"
        "- The feedback may be ONE sentence OR a numbered list ('1) ...\\n"
        "2) ...\\n3) ...'). When you see a numbered list, treat each item "
        "as a SEPARATE actionable request and address them ALL in the "
        "single updated cover letter you return. Do NOT skip any numbered "
        "item even if you think it overlaps with another - the user typed "
        "them as distinct concerns.\n"
        "- 'remove', 'sma\u017e', 'odstra\u0148', 'delete', 'odeber' are "
        "deletion intents. 'add', 'p\u0159idej', 'dopl\u0148', 'mention', "
        "'zm\u00ednit' are addition intents. 'change X to Y', 'p\u0159epi\u0161 "
        "X na Y' are replacement intents. Always ask yourself which intent "
        "matches the feedback before changing anything.\n\n"
        "STRUCTURE RULES (HARD - violations will be stripped before save):\n"
        "- Do NOT include a heading line such as 'Cover letter for X at Y' "
        "at the top. The first content the user reads must be the "
        "salutation.\n"
        "- The body must read as a direct message to the hiring team.\n"
        "- Put the sign-off ONLY in the structured `closing` and "
        "`signature` fields. Do NOT also paste 'Best regards, <Name>' at "
        "the end of the last body paragraph.\n"
        "- Keep the cover letter to 3-4 paragraphs unless the user "
        "explicitly asks for a longer / shorter version.\n\n"
        "INSTRUCTIONS:\n"
        "- Read the CURRENT COVER LETTER below.\n"
        "- Read the USER FEEDBACK carefully. Fix, add or rework exactly "
        "what the user asks for - and only that. Do not silently revert "
        "other parts of the cover letter.\n"
        "- All rules from the original cover-letter generation still "
        "apply: no hallucinated achievements, ATS-friendly prose, "
        "OUTPUT_LANGUAGE consistency for both `cover_letter` and "
        "`explanation`.\n"
        "- If the user asks to add something that is not in the candidate "
        "data, say so honestly in `explanation` rather than inventing "
        "content.\n\n"
        "CURRENT COVER LETTER:\n" + _dump(current_cover_letter) + "\n\n"
        "USER FEEDBACK:\n" + feedback.strip() + "\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        + _additional_notes_block(candidate)
        + "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        + _language_directive(output_language)
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
    "refine_resume_user_prompt",
    "refine_cover_letter_user_prompt",
    "cover_letter_user_prompt",
    "interview_questions_user_prompt",
    "skill_gap_user_prompt",
]
