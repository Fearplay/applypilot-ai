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


def _dump_job(job: JobPosting | None) -> str:
    return _dump(job, exclude=_JOB_PROMPT_EXCLUDE)


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
        "* WORKED EXAMPLE (high schools): CV says 'Secondary Technical "
        "School of Electrical Engineering, Ječná, Prague, 2017-2021' and "
        "LinkedIn says 'SPŠE Ječná, 2017-2021'. These are the SAME school "
        "('SPŠE' is the Czech abbreviation of 'Střední Průmyslová Škola "
        "Elektrotechnická' which is exactly 'Secondary Technical School of "
        "Electrical Engineering'). Emit ONE EducationEntry with "
        "`source='both'` and the longer description.\n"
        "* WORKED EXAMPLE (universities): CV says 'Faculty of Economics "
        "and Management, Czech University of Life Sciences Prague, "
        "2021-2024' and LinkedIn says 'Provozně ekonomická fakulta ČZU v "
        "Praze, ledna 2021 - července 2023' (i.e. January 2021 - July "
        "2023). 'ČZU' is exactly 'Czech University of Life Sciences', "
        "'Provozně ekonomická fakulta' is exactly 'Faculty of Economics "
        "and Management', 'Praze' is the locative form of 'Praha' = "
        "'Prague'. Emit ONE EducationEntry with `source='both'`. The years "
        "differ (2024 vs 2023) so put both periods on the entry's `notes` "
        "field as 'CV: 2021-2024 | LinkedIn: ledna 2021 - července 2023'.\n"
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
        "their distinct `source` and let the app ask the user later.\n\n"
        f"GITHUB USERNAME: {github_username or '(none provided)'}\n\n"
        "CV TEXT:\n" + _trim(cv_text) + "\n\n"
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
        "by importance for this role. The user will read these questions, so "
        "phrase them naturally and provide concrete option strings when "
        "answer_type is single_choice / yes_no / multi_choice.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
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
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers) + "\n\n"
        "EVIDENCE:\n" + _dump(evidence) + "\n\n"
        + _language_directive(output_language)
    )


def resume_user_prompt(
    job: JobPosting,
    candidate: CandidateProfile,
    answers: AnswersBundle,
    evidence: list[EvidenceItem],
    output_language: str = "en",
) -> str:
    return (
        "Produce a TailoredResume in the schema. Tailor it to the job:\n"
        "- Reorder skills so the most relevant for the job are first.\n"
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
        "- ONLY product / technology / brand names stay canonical: "
        "'Playwright', 'C#', 'Gen Digital', 'CI/CD'. Job titles, company "
        "subtitles, period strings and bullet prose all follow OUTPUT_LANGUAGE.\n"
        "EMPLOYMENT TYPE:\n"
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
        "NO HALLUCINATION:\n"
        "- If a date or responsibility is unclear from the inputs, write it "
        "generically rather than guessing - or skip it. Do not invent "
        "metrics, team sizes or business impact.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers) + "\n\n"
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
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
        "USER ANSWERS:\n" + _dump(answers) + "\n\n"
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
        "OUTPUT_LANGUAGE.\n\n"
        "JOB:\n" + _dump_job(job) + "\n\n"
        "CANDIDATE:\n" + _dump(candidate) + "\n\n"
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
