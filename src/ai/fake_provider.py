"""Deterministic offline AI provider used in demo mode and in unit tests.

Design goals
------------
* Zero network. Zero paid API. Zero non-determinism.
* Adapts to the detected role type so QA, Python dev and AI roles all look
  realistic.
* Uses the candidate's actual data whenever it is provided (CV / LinkedIn /
  GitHub) so the GUI feels real even without an LLM.
* Produces every Pydantic model the rest of the app expects, with valid data.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from ..models.candidate import (
    CandidateProfile,
    EducationEntry,
    GitHubProject,
    WorkExperience,
)
from ..models.documents import (
    CoverLetter,
    InterviewQuestion,
    ResumeBullet,
    ResumeSection,
    SkillGap,
    TailoredResume,
)
from ..models.evidence import EvidenceItem
from ..models.job import ROLE_TYPE_LABELS, JobPosting, RoleType
from ..models.match import (
    AnswersBundle,
    CategoryScores,
    ClarifyingQuestion,
    MatchReport,
)
from .base import BaseAIProvider
from .role_detector import detect_role_type


# ---------------------------------------------------------------------------
# Shared knowledge bases used by the fake provider
# ---------------------------------------------------------------------------
# Map role -> (required_skills, nice_to_have, technologies, ats_keywords)
_ROLE_REQS: dict[RoleType, tuple[list[str], list[str], list[str], list[str]]] = {
    "software_qa_engineer": (
        ["Manual testing", "Test cases", "Bug reporting", "Regression testing",
         "Exploratory testing", "Jira", "Agile/Scrum", "Postman"],
        ["SQL", "Python", "API testing", "Selenium", "Playwright", "CI/CD"],
        ["Jira", "Postman", "Selenium", "Playwright", "Python", "SQL", "Git"],
        ["QA", "manual testing", "regression", "Jira", "Postman", "API testing",
         "test cases", "bug tracking"],
    ),
    "qa_automation_engineer": (
        ["Test automation", "Python", "Playwright OR Selenium OR Cypress",
         "API testing", "CI/CD", "Git"],
        ["Docker", "SQL", "Allure reporting", "Page Object Model"],
        ["Playwright", "Selenium", "Cypress", "pytest", "GitHub Actions",
         "Docker", "Python"],
        ["test automation", "Playwright", "Selenium", "pytest", "CI/CD",
         "Page Object Model", "API automation", "Git"],
    ),
    "manual_qa_tester": (
        ["Manual testing", "Test cases", "Bug reporting", "Jira",
         "Exploratory testing"],
        ["Postman", "SQL", "API testing", "Agile/Scrum"],
        ["Jira", "Postman", "Confluence", "Excel"],
        ["manual testing", "test cases", "bug reports", "Jira",
         "exploratory testing", "Agile"],
    ),
    "test_engineer": (
        ["Test strategy", "Performance testing", "Integration testing",
         "Automation", "CI/CD"],
        ["JMeter", "k6", "Gatling", "Python", "Docker"],
        ["JMeter", "k6", "pytest", "GitHub Actions", "Grafana"],
        ["test strategy", "performance", "load testing", "automation",
         "CI/CD"],
    ),
    "junior_python_developer": (
        ["Python", "Git", "REST APIs", "Unit testing", "OOP"],
        ["SQL", "Docker", "FastAPI OR Django OR Flask", "Linux"],
        ["Python", "FastAPI", "pytest", "Git", "PostgreSQL"],
        ["Python", "REST API", "pytest", "Git", "OOP", "SQL"],
    ),
    "junior_software_engineer": (
        ["Programming fundamentals", "Git", "Data structures",
         "One production language", "Unit testing"],
        ["SQL", "Docker", "REST APIs", "Linux"],
        ["Git", "Python OR Java OR JavaScript", "SQL"],
        ["software engineering", "Git", "data structures", "testing",
         "code review"],
    ),
    "junior_ai_engineer": (
        ["Python", "LLM APIs", "Prompt engineering", "Git", "REST APIs"],
        ["Vector databases", "RAG", "LangChain", "Pydantic", "FastAPI"],
        ["Python", "OpenAI API", "LangChain", "FAISS", "Pydantic", "Git"],
        ["LLM", "GenAI", "RAG", "prompt engineering", "Python",
         "vector database"],
    ),
    "data_analyst": (
        ["SQL", "Excel", "Data visualisation", "Statistics basics",
         "Communication"],
        ["Python (pandas)", "PowerBI OR Tableau OR Looker", "DBT"],
        ["SQL", "PowerBI", "Tableau", "Python", "pandas"],
        ["SQL", "data analysis", "dashboards", "PowerBI", "pandas",
         "statistics"],
    ),
    "frontend_developer": (
        ["JavaScript / TypeScript", "React OR Vue", "HTML", "CSS", "Git"],
        ["Testing (Vitest / Jest)", "Accessibility", "Webpack / Vite"],
        ["TypeScript", "React", "CSS", "Vite", "Jest"],
        ["JavaScript", "React", "TypeScript", "CSS", "responsive"],
    ),
    "backend_developer": (
        ["Backend language", "REST APIs", "SQL", "Git", "Unit testing"],
        ["Docker", "Kubernetes", "Caching", "Async / messaging"],
        ["Python OR Java OR Go", "PostgreSQL", "Docker", "Redis"],
        ["backend", "REST API", "SQL", "microservices", "Docker"],
    ),
    "fullstack_developer": (
        ["Frontend stack", "Backend stack", "Git", "REST APIs"],
        ["TypeScript", "Docker", "Testing", "CI/CD"],
        ["TypeScript", "React", "Node.js OR Python", "PostgreSQL"],
        ["fullstack", "React", "Node.js", "REST API", "TypeScript"],
    ),
    "devops_engineer": (
        ["Linux", "Docker", "CI/CD", "Cloud (AWS/Azure/GCP)", "Git"],
        ["Kubernetes", "Terraform", "Monitoring (Prometheus/Grafana)"],
        ["Docker", "Kubernetes", "Terraform", "GitHub Actions", "AWS"],
        ["DevOps", "Kubernetes", "Terraform", "CI/CD", "AWS"],
    ),
    "data_engineer": (
        ["SQL", "Python", "ETL", "Cloud data warehouse"],
        ["Spark", "dbt", "Airflow", "Streaming"],
        ["Python", "SQL", "Airflow", "dbt", "Snowflake"],
        ["data engineering", "ETL", "SQL", "Airflow", "dbt"],
    ),
    "machine_learning_engineer": (
        ["Python", "scikit-learn", "Statistics", "Git", "Production engineering"],
        ["PyTorch / TensorFlow", "MLflow", "Docker", "MLOps"],
        ["Python", "scikit-learn", "PyTorch", "MLflow", "Docker"],
        ["machine learning", "Python", "PyTorch", "MLOps", "model deployment"],
    ),
    "mobile_developer": (
        ["Mobile platform (iOS/Android/Flutter/RN)", "Git", "Testing"],
        ["CI for mobile", "Push notifications", "Offline support"],
        ["Swift", "Kotlin", "Flutter", "React Native"],
        ["mobile", "iOS", "Android", "Flutter", "React Native"],
    ),
    "site_reliability_engineer": (
        ["Linux", "Networking", "Observability", "Incident response"],
        ["Kubernetes", "Terraform", "Go OR Python", "Prometheus"],
        ["Kubernetes", "Prometheus", "Grafana", "Terraform"],
        ["SRE", "SLO", "incident response", "Kubernetes", "observability"],
    ),
    "security_engineer": (
        ["OWASP top 10", "Threat modelling", "Secure SDLC", "SAST/DAST"],
        ["Python", "Cloud security", "Pentesting basics"],
        ["Burp Suite", "OWASP ZAP", "Snyk", "Trivy"],
        ["security", "OWASP", "SAST", "DAST", "threat modelling"],
    ),
    "cloud_engineer": (
        ["AWS OR Azure OR GCP", "IaC (Terraform)", "Networking", "IAM"],
        ["Kubernetes", "Cost optimisation", "FinOps"],
        ["AWS", "Terraform", "Kubernetes", "CloudFormation"],
        ["cloud", "AWS", "Terraform", "IAM", "networking"],
    ),
    "other_it": (
        ["Software engineering basics", "Git", "Communication"],
        ["Cloud basics", "Testing", "Documentation"],
        ["Git", "Linux", "Python"],
        ["software", "Git", "engineering", "testing"],
    ),
    "other": (
        ["Communication", "Problem solving"],
        ["Domain knowledge", "Teamwork"],
        [],
        ["communication", "teamwork"],
    ),
}

# Role -> bank of typical clarifying questions
_QUESTION_BANK: dict[RoleType, list[tuple[str, str, str]]] = {
    "software_qa_engineer": [
        ("postman", "Have you used Postman or another tool for API testing?",
         "API testing is in the JD."),
        ("playwright", "Have you used Playwright, Selenium or Cypress for UI automation?",
         "Automation tools are listed in the JD."),
        ("jira", "Have you tracked bugs in Jira (or Azure DevOps / Trello)?",
         "Bug tracking is a common requirement."),
        ("sql", "Have you written SQL queries to validate data?",
         "SQL appears in the JD."),
        ("python", "Have you written any Python scripts (even small)?",
         "Python is a plus for QA roles."),
    ],
    "qa_automation_engineer": [
        ("playwright", "Have you built any test suite with Playwright, Selenium or Cypress?",
         "Required automation framework."),
        ("ci", "Have you integrated tests into CI (GitHub Actions, GitLab CI, Jenkins)?",
         "CI/CD pipeline experience is required."),
        ("api_auto", "Have you automated API tests (pytest+requests, RestAssured, etc.)?",
         "API automation is required."),
        ("docker", "Have you used Docker to run tests locally or in CI?",
         "Docker is a plus."),
        ("pom", "Have you applied Page Object Model or another structural pattern?",
         "Maintainable test design is critical."),
    ],
    "junior_python_developer": [
        ("rest", "Have you built or extended a REST API (Flask, FastAPI, Django)?",
         "REST APIs are a core requirement."),
        ("pytest", "Have you written automated tests with pytest?",
         "Unit testing is required."),
        ("sql", "Have you worked with relational databases and SQL?",
         "SQL appears in the JD."),
        ("git", "Are you comfortable with feature branches, PRs and code review on Git?",
         "Standard collaboration workflow."),
        ("docker", "Have you containerised any application with Docker?",
         "Docker is a plus."),
    ],
    "junior_ai_engineer": [
        ("llm_api", "Have you called an LLM API (OpenAI, Anthropic, local) directly?",
         "LLM API usage is the foundation."),
        ("prompt", "Have you iterated on prompts to improve output quality?",
         "Prompt engineering is required."),
        ("rag", "Have you built or experimented with a Retrieval-Augmented Generation (RAG) flow?",
         "RAG is widely used."),
        ("vector_db", "Have you used a vector database (Chroma, FAISS, pgvector, Pinecone)?",
         "Vector storage is part of GenAI work."),
        ("structured", "Have you used structured outputs / function calling for reliability?",
         "Structured outputs reduce hallucination."),
    ],
    "data_analyst": [
        ("sql", "Have you written multi-join SQL queries?", "SQL is core."),
        ("dashboards", "Have you built dashboards in PowerBI / Tableau / Looker?",
         "Dashboarding is required."),
        ("python_pandas", "Have you analysed data in Python (pandas)?",
         "Python is a plus."),
        ("stats", "Are you comfortable with basic statistics (mean, median, hypothesis tests)?",
         "Statistics underpins analysis."),
    ],
}


def _slug_id(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")[:40] or "q"


def _normalise_skill(skill: str) -> str:
    return re.sub(r"[^a-z0-9+#.]", "", (skill or "").lower())


def _skill_in(skill: str, pool: Iterable[str]) -> bool:
    n = _normalise_skill(skill)
    if not n:
        return False
    for p in pool:
        np = _normalise_skill(p)
        if not np:
            continue
        if n == np or n in np or np in n:
            return True
    return False


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d[\s\-]?){7,}\d")
_LINKEDIN_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/[\w\-/.%]+", re.I)
_GITHUB_RE = re.compile(r"https?://github\.com/[\w\-]+(?:/[\w\-]+)?", re.I)


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------
class FakeAIProvider(BaseAIProvider):
    """Deterministic, offline AI provider."""

    name = "fake"
    is_demo = True

    def __init__(self, reason: str = "default fake provider") -> None:
        self.reason = reason

    # ------------------------------------------------------------------ job
    def analyze_job(
        self, raw_text: str, source_url: str | None = None
    ) -> JobPosting:
        text = raw_text or ""
        title = _first_line(text) or "Software QA Engineer"
        # Try to find a "Company:" line, otherwise leave empty.
        company = ""
        for line in text.splitlines()[:10]:
            m = re.match(r"\s*(?:company|firm)\s*[:\-]\s*(.+)", line, re.I)
            if m:
                company = m.group(1).strip()
                break

        role = detect_role_type(title, text)
        required, nice, tech, ats = _ROLE_REQS.get(role, _ROLE_REQS["other_it"])

        # Try to enrich with anything literally present in the text.
        present_techs = [t for t in tech if t.lower() in text.lower()]
        all_techs = list(dict.fromkeys(present_techs + tech))

        location = ""
        for line in text.splitlines():
            m = re.search(r"(?:location|based\s+in)\s*[:\-]?\s*([A-Za-z ,/-]+)", line, re.I)
            if m:
                location = m.group(1).strip()[:80]
                break

        text_lower = text.lower()
        if "remote" in text_lower:
            arrangement = "remote"
        elif "hybrid" in text_lower:
            arrangement = "hybrid"
        elif "on-site" in text_lower or "onsite" in text_lower or "office" in text_lower:
            arrangement = "onsite"
        else:
            arrangement = "unknown"

        if "junior" in text_lower or "entry" in text_lower or "graduate" in text_lower:
            seniority = "junior"
        elif "senior" in text_lower or "lead" in text_lower:
            seniority = "senior"
        elif "intern" in text_lower:
            seniority = "intern"
        elif "mid" in text_lower:
            seniority = "mid"
        else:
            seniority = "unknown"

        return JobPosting(
            title=title,
            company=company,
            location=location,
            work_arrangement=arrangement,
            seniority=seniority,
            role_type=role,
            responsibilities=[
                f"Own and improve the {ROLE_TYPE_LABELS[role].lower()} workflow",
                "Collaborate with cross-functional teams (dev, product, design)",
                "Write clear documentation and reports",
                "Continuously improve processes and tooling",
            ],
            required_skills=required,
            nice_to_have_skills=nice,
            technologies=all_techs,
            ats_keywords=ats,
            tone="professional",
            priorities=["clear communication", "evidence of impact",
                        "ownership", "continuous learning"],
            raw_text=text,
            source_url=source_url,
        )

    # -------------------------------------------------------------- candidate
    def analyze_candidate(
        self,
        cv_text: str = "",
        linkedin_text: str = "",
        github_username: str | None = None,
        github_projects: Sequence[GitHubProject] = (),
    ) -> CandidateProfile:
        combined = "\n".join([cv_text or "", linkedin_text or ""])

        email_match = _EMAIL_RE.search(combined)
        email = email_match.group(0) if email_match else None
        phone_match = _PHONE_RE.search(combined)
        phone = phone_match.group(0).strip() if phone_match else None
        linkedin_match = _LINKEDIN_RE.search(combined)
        github_match = _GITHUB_RE.search(combined)

        first = _first_line(cv_text) or _first_line(linkedin_text) or "Anonymous Candidate"
        # Strip trailing pipe-separated contact info from the name line.
        full_name = re.split(r"[|\u2022\-]", first)[0].strip()

        skills: list[str] = []
        for project in github_projects or []:
            skills.extend(project.detected_technologies)
            if project.primary_language:
                skills.append(project.primary_language)
            skills.extend(project.languages)

        # Pull obvious tech words from the CV/LinkedIn text.
        for tech in [
            "python", "java", "javascript", "typescript", "sql", "postgres",
            "mysql", "mongodb", "docker", "kubernetes", "aws", "azure", "gcp",
            "git", "github actions", "jira", "postman", "selenium", "playwright",
            "cypress", "pytest", "rest", "fastapi", "django", "flask",
            "pandas", "numpy", "scikit-learn", "pytorch", "tensorflow",
            "langchain", "openai", "linux", "ci/cd",
        ]:
            if re.search(rf"\b{re.escape(tech)}\b", combined, re.I):
                skills.append(tech.title() if " " not in tech else tech.upper())

        skills = list(dict.fromkeys(s.strip() for s in skills if s.strip()))

        return CandidateProfile(
            full_name=full_name,
            headline="" if not skills else f"{ROLE_TYPE_LABELS.get('other_it', 'IT professional')} - {', '.join(skills[:3])}",
            contact_email=email,
            phone=phone,
            location=None,
            linkedin_url=linkedin_match.group(0) if linkedin_match else None,
            github_url=(
                github_match.group(0)
                if github_match
                else (f"https://github.com/{github_username}" if github_username else None)
            ),
            portfolio_url=None,
            summary=(
                cv_text.strip().split("\n\n", 1)[0][:600]
                if cv_text
                else "Motivated candidate with hands-on project experience."
            ),
            technical_skills=skills,
            soft_skills=["Communication", "Attention to detail", "Collaboration"],
            tools=[s for s in skills if s.lower() in {"jira", "postman", "git",
                                                      "docker", "kubernetes",
                                                      "github actions"}],
            spoken_languages=["English"],
            experience=self._fake_experience(combined),
            education=self._fake_education(combined),
            certifications=[],
            projects=list(github_projects or []),
            raw_cv_text=cv_text,
            raw_linkedin_text=linkedin_text,
            github_username=github_username,
        )

    @staticmethod
    def _fake_experience(text: str) -> list[WorkExperience]:
        # Look for "Experience" section and split lines that look like job entries.
        if "experience" not in text.lower():
            return []
        chunk = text.lower().split("experience", 1)[1]
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()][:6]
        if not lines:
            return []
        bullets = [ln for ln in lines if ln.startswith(("-", "*", "•"))]
        return [
            WorkExperience(
                title=lines[0][:80].title(),
                company="Previous employer",
                period="",
                bullets=[b.lstrip("-*• ").strip() for b in bullets][:5]
                or [lines[1] if len(lines) > 1 else "Delivered project work."],
            )
        ]

    @staticmethod
    def _fake_education(text: str) -> list[EducationEntry]:
        m = re.search(r"(?i)(bachelor|master|bsc|msc|university|college)[^\n]*", text)
        if not m:
            return []
        return [EducationEntry(institution=m.group(0)[:100], degree="", period="")]

    # --------------------------------------------------------- clarifying Q
    def generate_clarifying_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[ClarifyingQuestion]:
        bank = _QUESTION_BANK.get(job.role_type, _QUESTION_BANK["software_qa_engineer"])
        candidate_pool: list[str] = (
            list(candidate.technical_skills)
            + list(candidate.tools)
            + [p.name for p in candidate.projects]
            + [w for proj in candidate.projects for w in proj.detected_technologies]
        )
        questions: list[ClarifyingQuestion] = []
        for slug, q, why in bank:
            if _skill_in(slug, candidate_pool):
                continue
            questions.append(
                ClarifyingQuestion(
                    id=f"q_{slug}",
                    skill=slug,
                    question=q,
                    why_it_matters=why,
                    options=["Yes - practical experience",
                             "Learning in progress",
                             "No - not yet"],
                    answer_type="single_choice",
                )
            )
        # Always include a tone-of-voice question.
        questions.append(
            ClarifyingQuestion(
                id="q_tone",
                skill=None,
                question="How should the resume sound?",
                why_it_matters="Tone matters for first impressions.",
                options=["Junior and humble", "Confident", "Conservative"],
                answer_type="single_choice",
            )
        )
        return questions[:8]

    # ------------------------------------------------------------ match
    def generate_match_report(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> MatchReport:
        candidate_pool = (
            list(candidate.technical_skills)
            + list(candidate.tools)
            + [w for proj in candidate.projects for w in proj.detected_technologies]
            + [a.skill for a in (answers.answers if answers else [])
               if a.skill and a.treat_as == "practical_experience"]
        )

        matched, missing = [], []
        for req in job.required_skills + job.nice_to_have_skills:
            if _skill_in(req, candidate_pool):
                matched.append(req)
            else:
                missing.append(req)

        ats_present = [k for k in job.ats_keywords if _skill_in(k, candidate_pool)]
        ats_missing = [k for k in job.ats_keywords if k not in ats_present]

        total = max(len(job.required_skills), 1)
        required_hits = sum(1 for r in job.required_skills if r in matched)
        tech_score = int(50 + 50 * (required_hits / total))

        exp_score = 70 if candidate.experience else 45
        tools_score = int(40 + 6 * len(candidate.tools))
        tools_score = min(tools_score, 100)
        qa_score = int(50 + 50 * (len(matched) / max(total, 1)))

        overall = int((tech_score + exp_score + tools_score + qa_score) / 4)
        risky = [r for r in job.required_skills if r in missing][:3]

        evidence_items = list(evidence)
        for skill in matched:
            if not any(_skill_in(skill, [e.skill or ""]) for e in evidence_items):
                evidence_items.append(
                    EvidenceItem(
                        claim=f"Candidate matches '{skill}'",
                        skill=skill,
                        source_type="cv",
                        source_name="parsed inputs",
                        evidence_text=f"'{skill}' detected in candidate profile.",
                        confidence="medium",
                    )
                )

        return MatchReport(
            overall_score=max(0, min(overall, 100)),
            category_scores=CategoryScores(
                technical_skills=tech_score,
                experience=exp_score,
                tools=tools_score,
                qa_process=qa_score,
            ),
            matched_requirements=matched,
            missing_requirements=missing,
            risky_gaps=risky,
            ats_keywords_present=ats_present,
            ats_keywords_missing=ats_missing,
            recommended_improvements=[
                f"Add an 'ATS Skills' line that includes: {', '.join(ats_missing[:6])}"
                if ats_missing
                else "Resume already covers all key ATS keywords.",
                "Lead the summary with role-relevant experience.",
                f"Move {ROLE_TYPE_LABELS.get(job.role_type, 'role-relevant')} projects to the top of the Projects section.",
            ],
            evidence=evidence_items,
            summary=(
                f"[Demo report] Candidate matches {len(matched)} / "
                f"{len(job.required_skills + job.nice_to_have_skills)} required + "
                f"nice-to-have skills for the {ROLE_TYPE_LABELS.get(job.role_type, 'role')}."
            ),
        )

    # ------------------------------------------------------------ resume
    def generate_resume(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        evidence: Sequence[EvidenceItem] = (),
        output_language: str = "en",
    ) -> TailoredResume:
        relevant_first = sorted(
            candidate.technical_skills,
            key=lambda s: (
                0 if _skill_in(s, job.required_skills) else
                1 if _skill_in(s, job.nice_to_have_skills) else
                2,
                s.lower(),
            ),
        )

        contact_bits = [b for b in [candidate.contact_email, candidate.phone,
                                    candidate.location] if b]
        contact_line = " | ".join(contact_bits)

        projects_section = [
            ResumeSection(
                title=p.name,
                subtitle=p.url,
                bullets=[
                    ResumeBullet(
                        text=p.description or f"GitHub project ({p.primary_language or 'multi-language'}).",
                        keywords=p.detected_technologies[:6],
                    ),
                    ResumeBullet(
                        text=p.readme_excerpt[:160] + "..."
                        if p.readme_excerpt and len(p.readme_excerpt) > 160
                        else (p.readme_excerpt or "See repository for details."),
                        keywords=[],
                    ),
                ],
            )
            for p in (candidate.projects or [])[:5]
        ]

        experience_section = [
            ResumeSection(
                title=w.title,
                subtitle=" - ".join(b for b in [w.company, w.period] if b),
                bullets=[ResumeBullet(text=b, keywords=[]) for b in w.bullets[:4]]
                or [ResumeBullet(text="Delivered hands-on work in this role.", keywords=[])],
            )
            for w in candidate.experience[:5]
        ]

        education_section = [
            ResumeSection(
                title=e.degree or "Degree",
                subtitle=e.institution,
                bullets=([ResumeBullet(text=e.notes, keywords=[])] if e.notes else []),
            )
            for e in candidate.education[:3]
        ]

        role_label = ROLE_TYPE_LABELS.get(job.role_type, job.title)
        summary = (
            f"{candidate.full_name or 'Candidate'} - applying for {role_label}"
            f"{f' at {job.company}' if job.company else ''}. "
            f"Strengths: {', '.join(relevant_first[:5]) or 'broad fundamentals'}. "
            "Focused on evidence-based contributions and continuous learning."
        )

        return TailoredResume(
            name=candidate.full_name or "Anonymous Candidate",
            contact_line=contact_line,
            linkedin=candidate.linkedin_url,
            github=candidate.github_url,
            portfolio=candidate.portfolio_url,
            professional_summary=summary,
            technical_skills=relevant_first,
            projects=projects_section,
            experience=experience_section,
            education=education_section,
            certifications=[c.name for c in candidate.certifications],
            role_targeted_for=job.title,
        )

    # ----------------------------------------------------------- cover ltr
    def generate_cover_letter(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        answers: AnswersBundle,
        output_language: str = "en",
    ) -> CoverLetter:
        company = job.company or "your team"
        role_label = job.title or ROLE_TYPE_LABELS.get(job.role_type, "the role")
        signature = candidate.full_name or "[Your name]"

        relevant = [
            s for s in candidate.technical_skills
            if _skill_in(s, job.required_skills + job.nice_to_have_skills)
        ][:3] or candidate.technical_skills[:3]

        paragraphs = [
            f"I am writing to express my interest in the {role_label} position at {company}. "
            f"After reviewing the responsibilities, I see a strong overlap with what I have "
            f"been doing and the direction I want to grow.",
            (
                f"My recent work has focused on {', '.join(relevant) if relevant else 'building practical software'}. "
                f"I value clear communication, ATS-friendly documentation and reproducible "
                f"results. I am comfortable owning a task end to end and asking for help "
                f"early when I need it."
            ),
            (
                "I would welcome the opportunity to discuss how my profile fits the role and "
                "what the next steps look like. Thank you for your time and consideration."
            ),
        ]

        return CoverLetter(
            salutation="Dear Hiring Manager,",
            paragraphs=paragraphs,
            closing="Best regards,",
            signature=signature,
            company=job.company,
            role=role_label,
        )

    # --------------------------------------------------------- interview Q
    def generate_interview_questions(
        self,
        job: JobPosting,
        candidate: CandidateProfile,
        output_language: str = "en",
    ) -> list[InterviewQuestion]:
        bank = _interview_bank(job.role_type)
        return [
            InterviewQuestion(
                question=q,
                why_asked=why,
                suggested_answer=answer.format(
                    name=candidate.full_name or "I",
                    role=job.title or ROLE_TYPE_LABELS.get(job.role_type, "the role"),
                ),
                category=cat,
            )
            for q, why, answer, cat in bank
        ]

    # ------------------------------------------------------------ gaps
    def generate_skill_gap_plan(
        self,
        match_report: MatchReport,
        job: JobPosting,
        output_language: str = "en",
    ) -> list[SkillGap]:
        plan: list[SkillGap] = []
        for skill in match_report.missing_requirements[:6]:
            plan.append(_skill_gap_for(skill, job.role_type))
        return plan


# ---------------------------------------------------------------------------
# Helpers shared with the bank tables
# ---------------------------------------------------------------------------
def _interview_bank(role: RoleType) -> list[tuple[str, str, str, str]]:
    """Return a 10-question interview bank for the given role.

    Each entry is (question, why_asked, suggested_answer_template, category).
    """
    common: list[tuple[str, str, str, str]] = [
        ("Walk me through your most relevant project.",
         "Probe depth, ownership and communication.",
         "{name} would describe one project for {role}: problem, approach, "
         "tools used, impact.",
         "behavioural"),
        ("Tell me about a difficult bug or failure you investigated.",
         "Probe debugging and resilience.",
         "Use the STAR pattern: Situation, Task, Action, Result.",
         "behavioural"),
        ("How do you keep learning new tools?",
         "Probe growth mindset.",
         "Mention concrete sources - docs, projects, courses, side repos.",
         "culture"),
    ]

    role_specific: dict[RoleType, list[tuple[str, str, str, str]]] = {
        "software_qa_engineer": [
            ("How do you write a high-quality bug report?",
             "Looks for reproducibility, severity, expected vs actual.",
             "Cover steps, environment, expected/actual, severity, attachments.",
             "process"),
            ("Walk through your test design for a login form.",
             "Probe coverage thinking.",
             "Mention positive, negative, edge, security and accessibility cases.",
             "technical"),
            ("How do you decide when to automate vs test manually?",
             "Probe pragmatic test strategy.",
             "ROI, frequency of regression, stability of feature.",
             "process"),
            ("How would you test an unreliable API?",
             "Probe API testing thinking.",
             "Postman / pytest+requests, retries, contract tests, mocks.",
             "technical"),
            ("Difference between regression and smoke testing?",
             "Probe vocabulary.",
             "Smoke = critical paths, regression = guard against re-introducing bugs.",
             "technical"),
            ("How do you collaborate with developers on tickets?",
             "Probe communication.",
             "Pair on repro, document expectations, follow-up after fixes.",
             "behavioural"),
            ("What metrics do you track to measure quality?",
             "Probe ownership of process.",
             "Defect density, escape rate, MTTR, regression suite stability.",
             "process"),
        ],
        "qa_automation_engineer": [
            ("How do you structure a Playwright test suite?",
             "Probe automation maturity.",
             "Page Object Model, fixtures, parallelisation, reporting.",
             "technical"),
            ("How do you keep tests stable in CI?",
             "Probe practical CI discipline.",
             "Wait strategies, retries, test data isolation, network mocks.",
             "process"),
            ("Walk through your API automation stack.",
             "Probe API testing depth.",
             "pytest+requests, schema validation, contract tests.",
             "technical"),
            ("How do you debug a flaky test?",
             "Probe troubleshooting.",
             "Reproduce locally, isolate timing/data, add logs, fix root cause.",
             "technical"),
            ("How do you decide what NOT to automate?",
             "Probe pragmatism.",
             "Avoid low-value flaky checks, focus on high-impact regressions.",
             "process"),
            ("How do you integrate tests into CI/CD?",
             "Probe pipeline experience.",
             "GitHub Actions / Jenkins, parallel jobs, artefacts, gates.",
             "technical"),
            ("How would you onboard a junior to your test framework?",
             "Probe leadership readiness.",
             "Pairing, docs, conventions, code review.",
             "behavioural"),
        ],
        "junior_python_developer": [
            ("How do you organise a small Python project?",
             "Probe fundamentals.",
             "venv, pyproject, src layout, tests folder, type hints.",
             "technical"),
            ("Difference between list and tuple?",
             "Probe basics.",
             "Mutability, hashability, typical use cases.",
             "technical"),
            ("How would you design a small REST API?",
             "Probe API thinking.",
             "Endpoints, models, validation (Pydantic), tests.",
             "technical"),
            ("How do you debug a Python error you have not seen before?",
             "Probe troubleshooting.",
             "Read traceback bottom-up, isolate, search docs/SO, write a test.",
             "technical"),
            ("How do you collaborate via Git?",
             "Probe workflow.",
             "Branches, PR descriptions, code reviews, conventional commits.",
             "process"),
            ("What is virtualenv for?",
             "Probe environment hygiene.",
             "Isolated dependencies per project.",
             "technical"),
            ("How do you keep growing as a developer?",
             "Probe mindset.",
             "Side projects, code reviews, blogs, communities.",
             "culture"),
        ],
        "junior_ai_engineer": [
            ("How do you reduce hallucinations in an LLM application?",
             "Probe applied LLM craft.",
             "Structured outputs, RAG, evaluation harness, source citations.",
             "technical"),
            ("Walk me through a simple RAG flow.",
             "Probe RAG basics.",
             "Chunking, embedding, retrieval, prompt assembly, eval.",
             "technical"),
            ("Why use Pydantic with LLM outputs?",
             "Probe reliability thinking.",
             "Schema validation, type safety, deterministic downstream code.",
             "technical"),
            ("How do you evaluate prompt changes?",
             "Probe rigour.",
             "Hold-out set, golden examples, automated eval, manual review.",
             "process"),
            ("How would you choose between OpenAI, Anthropic and a local model?",
             "Probe pragmatism.",
             "Cost, latency, privacy, capability, vendor risk.",
             "technical"),
            ("What is function/tool calling and when do you use it?",
             "Probe LLM toolkit.",
             "Structured action selection, integrating with code APIs.",
             "technical"),
            ("Tell me about a small LLM project you built.",
             "Probe initiative.",
             "Describe goal, stack, surprising lessons.",
             "behavioural"),
        ],
    }
    extra = role_specific.get(role, role_specific.get("junior_software_engineer",
        [
            ("Tell me about a project that taught you the most.",
             "Probe self-awareness.",
             "Describe biggest lesson honestly.",
             "behavioural"),
            ("Where do you want to be in 2 years?",
             "Probe direction.",
             "Realistic plan tied to the role.",
             "culture"),
            ("How do you handle disagreement with a teammate?",
             "Probe collaboration.",
             "Listen, restate, agree on data, escalate if needed.",
             "behavioural"),
            ("What questions do you have for us?",
             "Probe engagement.",
             "Ask about team rituals, success metrics, growth path.",
             "culture"),
            ("Why this company?",
             "Probe motivation.",
             "Tie answer to company mission and your goals.",
             "culture"),
            ("What is your biggest weakness?",
             "Probe self-reflection.",
             "Pick a real one and how you address it.",
             "behavioural"),
            ("Describe a time you took initiative.",
             "Probe ownership.",
             "Use STAR.",
             "behavioural"),
        ],
    ))
    bank = common + extra
    # Always exactly 10 entries.
    return bank[:10]


def _skill_gap_for(skill: str, role: RoleType) -> SkillGap:
    importance = "critical" if role in {
        "software_qa_engineer", "qa_automation_engineer"
    } and skill.lower() in {
        "playwright", "selenium", "cypress", "test automation",
    } else "important"

    return SkillGap(
        skill=skill,
        importance=importance,
        rationale=(
            f"'{skill}' is in the job posting and is not yet evidenced in the "
            "candidate profile. Closing this gap directly improves the match score."
        ),
        learning_path=[
            f"Read the official documentation for {skill}.",
            f"Build a small end-to-end demo using {skill}.",
            f"Push the demo to GitHub with a clear README and tests.",
            f"Write a short blog post or LinkedIn note about what you learned.",
        ],
        suggested_project=(
            f"Build a tiny portfolio project that demonstrates {skill} on a "
            "realistic scenario (login flow, public API, sample dataset). "
            "Add screenshots, tests and a CI workflow."
        ),
    )


__all__ = ["FakeAIProvider"]
