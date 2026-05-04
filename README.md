# ApplyPilot AI

> **Job URL to Tailored Resume & Cover Letter**

ApplyPilot AI is a Python desktop GenAI application that turns a job posting URL, resume, GitHub profile and LinkedIn export into a tailored ATS-friendly resume and cover letter. It uses **evidence-based generation**, **clarifying questions** and **structured AI outputs** to avoid hallucinated experience. The app supports a **provider-agnostic AI API architecture** and includes a **fake/demo provider** for local testing without API costs.

| Status | Functional MVP | Default mode | Offline (FakeAIProvider) |
| --- | --- | --- | --- |
| Tested on | Python 3.11 / 3.12 / 3.13, Windows / macOS / Linux | Cost when running demos | $0 |
| Cost per real application | ~$0.035 (gpt-4o-mini) | Cost per 30 apps / month | ~$1.05 |

## Screenshots

![Setup screen - Build a tailored application: paste a job URL or job text, drop your CV (PDF / DOCX / TXT / HTML), optionally add a LinkedIn export and a GitHub profile, then click Run analysis.](docs/screenshots/welcome.png)

*Setup - single scrollable page with three cards (job posting, resume + LinkedIn, GitHub profile). The `Try sample data` button pre-fills demo inputs so you can click straight through to a finished application package without an API key.*

![Match report - overall score gauge plus four category bars (Technical skills, Experience, Tools, Process / QA) and three columns: Matched, Missing / risky gaps, ATS keywords.](docs/screenshots/match_report.png)

*Match report - overall and per-category scores, matched / missing / ATS keyword columns and an evidence preview underneath. Hover any column heading for an in-app explanation of what it means in ATS terminology.*

![Documents - tabs for Tailored Resume, Modern Resume, Cover Letter, Match Report, Interview Prep, Skill Gap Plan and Evidence (read-only); each tab exports to MD / HTML / DOCX, or you can click Save full analysis to write all 10 artefacts at once.](docs/screenshots/documents.png)

*Documents - tabbed editor with per-tab `Export MD / HTML / DOCX` buttons and a single `Save full analysis` action that writes all 10 artefacts to `outputs/<company>-<role>-<timestamp>/`.*

---

## Table of contents

1. [What it does](#what-it-does)
2. [Why it exists](#why-it-exists)
3. [Tech stack](#tech-stack)
4. [Architecture](#architecture)
5. [GenAI features](#genai-features)
6. [No hallucinated experience policy](#no-hallucinated-experience-policy)
7. [AI provider architecture](#ai-provider-architecture)
8. [Fake / demo mode (no API key needed)](#fake--demo-mode-no-api-key-needed)
9. [Installation](#installation)
10. [Running the app](#running-the-app)
11. [Configuring `.env`](#configuring-env)
12. [Cost per analysis](#cost-per-analysis-measured)
13. [Languages](#languages)
14. [Workflow walkthrough](#workflow-walkthrough)
15. [Project structure](#project-structure)
16. [Outputs](#outputs)
17. [Tests](#tests)
18. [Limitations](#limitations)
19. [Roadmap](#roadmap)
20. [GitHub push instructions](#github-push-instructions)
21. [License](#license)

---

## What it does

You paste a job URL (or the description text), drop your CV (PDF / DOCX / TXT / HTML), optionally add your LinkedIn export and GitHub username, and the app produces:

- A **tailored ATS-friendly resume** that reorders your skills and projects for this specific role.
- A **printable styled HTML resume** in a modern two-column A4 layout (sidebar with grouped tech stack pills + main column with experience, projects, education) that you can preview in-app on the *Modern Resume* tab and print to PDF straight from the browser.
- A **cover letter** that mentions the company and role concretely (no generic templates).
- A **match report** with overall and category scores, matched / missing requirements, ATS keyword coverage and recommended improvements.
- **Interview preparation** - 10 likely questions with rationale and suggested answers grounded in your profile.
- A **skill gap plan** with importance, learning path and a suggested side project for each gap.
- An **evidence report** (JSON) listing every claim and where it came from.
- A single-page **HTML application summary** that bundles everything for review.

All outputs are editable in-app before export and are written to `outputs/<company>-<role>-<timestamp>/`. Past analyses can be re-opened from the **History** tab without re-running the AI.

## Why it exists

Most AI resume tools either invent experience you do not have or produce generic outputs that do not match the posting. ApplyPilot AI is built around two opinionated choices:

1. **No hallucinated experience.** Every claim in the resume must trace back to evidence the candidate actually provided (CV / LinkedIn / GitHub / answered clarifying questions).
2. **No vendor lock-in.** Use any LLM provider that speaks the OpenAI HTTP protocol - or no provider at all in offline demo mode.

It is also a portfolio project for QA / Junior Python / Junior AI roles, so the architecture is intentionally readable and tested.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11+ | type hints, async-friendly, Pydantic v2 |
| GUI | **PySide6** (LGPL-3.0) | first-class Qt bindings, no GPL contagion |
| Theme | Centralised QSS in `src/gui/theme.py` | one place to tweak the dark UI tokens |
| Data validation | Pydantic v2 | structured AI outputs + strict typing |
| AI HTTP | `requests` only | works with every OpenAI-compatible endpoint |
| Job URL fetch | `trafilatura`, `requests` + `beautifulsoup4` | best signal-to-noise on job pages |
| CV/DOCX/HTML | `pymupdf`, `python-docx`, `beautifulsoup4` + `lxml` | robust PDF + DOCX parsing, HTML CV import |
| Markdown | `markdown` | renders the application summary HTML |
| Tests | `pytest` | hermetic, never touches the network |
| Config | `python-dotenv` | one `.env` file for everything |

## Architecture

```mermaid
flowchart TB
    subgraph GUI [PySide6 GUI - 4 sections]
        Setup[Setup<br/>job + CV + GitHub URLs]
        Match[Match Report]
        Docs[Generated Documents]
        Hist[History]
        QDlg["Clarifying Questions<br/>(modal dialog)"]
        Setup --> Match
        Match -. "if evidence < 85%" .-> QDlg
        QDlg --> Match
        Match --> Docs
    end

    subgraph Services [src/services]
        Fetcher[job_url_fetcher]
        JobParser[job_parser]
        ResParser[resume_parser]
        LiParser[linkedin_parser]
        GhAnalyzer[github_analyzer]
        ProfBuilder[profile_builder]
        EvCheck[evidence_checker]
        MatchSvc[match_engine]
        QGen[question_generator]
        DocGen[resume / cover / interview / gap generators]
        Export[export_service]
        HistSvc[history_service]
    end

    subgraph AI [src/ai - provider-agnostic]
        Base[BaseAIProvider ABC]
        Fake[FakeAIProvider - default]
        OAI[OpenAICompatibleProvider - HTTP]
        Factory[provider_factory]
        Base --> Fake
        Base --> OAI
        Factory --> Fake
        Factory --> OAI
    end

    GUI -->|background QThread| Services
    Services -->|structured Pydantic outputs| AI
    Services -->|files| FS["outputs/company-role/ + outputs/history.json"]
```

**Key principle:** the GUI never calls AI directly. Every AI call goes through `services/*` which work with Pydantic models, so business logic is testable without a window manager.

## GenAI features

- **Role-aware persona prompts.** The AI is told to behave like the right kind of recruiter for the detected role (e.g. "former QA lead" for QA Engineer, "head of AI" for GenAI Engineer, "head of analytics" for Data Analyst).
- **Title-based role detection.** A regex classifier in `src/ai/role_detector.py` recognises 20 distinct IT roles from job titles - QA, automation, manual QA, test, junior python, junior swe, junior AI/GenAI, data analyst, data engineer, ML, frontend, backend, fullstack, mobile, devops, SRE, security, cloud - with `other_it` and `other` fallbacks. The selected role steers the persona, the question bank and the gap plan.
- **Structured outputs.** Every AI method returns a validated Pydantic model. The HTTP provider asks the LLM for `response_format=json_schema` first, falls back to `json_object`, and finally to plain JSON-in-prompt - so it works with strict providers and looser ones alike.
- **Evidence-first resume.** Before generating the resume we run the `evidence_checker`, which buckets every required / nice-to-have / ATS keyword into evidenced / weak / missing buckets. Only evidenced (or user-confirmed) skills make it into bullets.
- **Human-in-the-loop clarifying questions.** When required-skill evidence coverage drops below 85% (or any required skill is missing), the GUI shows a `Clarifying Questions` page that lets the candidate answer with `practical_experience` / `learning_in_progress` / `omit`. Only `practical_experience` answers count as evidence; `learning_in_progress` ends up in the summary line; `omit` triggers a gap plan entry.

## No hallucinated experience policy

This project explicitly forbids:

- Inventing roles, employers, projects, certifications or skills the candidate does not have.
- Phrasing learning intentions as past experience.
- Rewriting bullet points to claim outcomes that are not in the source documents.

Allowed instead:

- Reordering and rephrasing **real** bullets so they highlight job-relevant terms.
- Adding a Summary line that mentions skills the candidate is **currently learning** (when they confirmed `learning_in_progress` in the clarifying questions).
- Surfacing skills the candidate does not have as **gap plan entries** with concrete learning paths and suggested side projects.

The `EvidenceItem` Pydantic model carries a `claim`, `source_type`, `source_name`, `evidence_text` and `confidence` for every important claim, so you can audit each line of the resume back to its source.

## AI provider architecture

ApplyPilot AI talks to AI providers through a single HTTP class, `OpenAICompatibleProvider`. Every modern LLM provider exposes the same `POST /v1/chat/completions` endpoint with `messages`, `model`, `temperature` and `response_format`. By building against this de-facto standard we get full provider freedom with zero SDK dependencies.

Switching providers is purely a `.env` change:

| Provider | `AI_BASE_URL` | Example `AI_MODEL` | Notes |
| --- | --- | --- | --- |
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini` | full json_schema support |
| **Groq** (free tier) | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | very fast |
| **Mistral** | `https://api.mistral.ai/v1` | `mistral-small-latest` | EU-hosted |
| **OpenRouter** | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` | one key, many models |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | low cost |
| **Together AI** | `https://api.together.xyz/v1` | `meta-llama/Llama-3-70b-chat-hf` | open-weights catalogue |
| **Anthropic** | OpenAI-compat endpoint | `claude-3-5-sonnet-20241022` | requires the OAI-compat enabled token |
| **Gemini** | OpenAI-compat endpoint | `gemini-1.5-flash` | preview API |
| **Ollama** (local) | `http://localhost:11434/v1` | `llama3.1` | offline, free |
| **LM Studio** (local) | `http://localhost:1234/v1` | the model you loaded | offline, free |

Adding a brand-new provider is *zero code* - it is a `.env` change.

## Fake / demo mode (no API key needed)

If `AI_PROVIDER=fake` (the default) or `AI_API_KEY` is empty, the app uses `FakeAIProvider` instead. The fake provider:

- runs entirely **offline** (no network),
- is **deterministic** - the same input produces the same output, which makes the test suite stable,
- adapts to the **detected role** (a QA job gets QA-flavoured demo data, a Junior Python job gets dev-flavoured data, etc.),
- uses the **real candidate inputs** when present (it really pulls Python/Selenium/Jira mentions out of your CV text), so the GUI looks like it actually understands you - even without an LLM.

The Welcome screen has a **Try with sample data** button that pre-fills the demo CV, LinkedIn and GitHub fields so you can click straight through to a finished application package.

## Installation

```bash
# Clone (after the repository exists)
git clone https://github.com/Fearplay/applypilot-ai.git
cd applypilot-ai

# Create + activate a virtual env
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
# source .venv/bin/activate     # Linux / macOS

# Install runtime + dev dependencies
pip install -r requirements.txt
```

Tested on Python **3.11**, **3.12** and **3.13**.

### Optional: SPA renderer for Microsoft / Workday / Greenhouse

`pip install -r requirements.txt` already pulls in the [Playwright Python](https://playwright.dev/python/) bindings, but it does **not** download any browser binaries. The renderer first tries to drive your existing Chrome (`channel="chrome"`) and Edge (`channel="msedge"`) installs - those exist on virtually every Windows 10/11 box, so the *Wrong content* button works out of the box. If neither is present (e.g. minimal Linux container), grab a Playwright-managed browser once with:

```bash
playwright install chromium       # ~140 MB, recommended
# playwright install firefox      # alternative if Chromium is unavailable
```

## Running the app

```bash
python app.py
```

The first thing you see is the Welcome screen with a coloured banner at the top:

- **Amber banner** = you are in `FakeAIProvider` demo mode (no API calls, free).
- **Green banner** = a real provider is active (`OpenAICompatibleProvider` will hit your endpoint).

You can switch providers at runtime via **File > AI provider settings...** (Ctrl+,).

## Configuring `.env`

Copy the template and edit it:

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # Linux / macOS
```

Minimum keys to switch on a real provider:

```env
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=sk-...
AI_MODEL=gpt-4o-mini
```

`.env` is git-ignored, so your key never leaks. Every real AI call is also logged to `logs/ai_requests.log` (toggle via `AI_REQUEST_LOG=true|false`).

> **GitHub:** paste your **profile URL** (`https://github.com/your-username`) into the Setup page and the app fetches your public repositories from the GitHub REST API. Optionally set `GITHUB_TOKEN` in `.env` to lift the rate limit from 60 req/h (anonymous) to 5000 req/h. Tick *Skip GitHub* in the Setup card if you don't want any network call to github.com.

## Cost per analysis (measured)

Demo / FakeAIProvider mode is always **$0** - no network calls. With a real provider, one full *Run analysis + Generate documents* pipeline triggers seven AI calls (analyze_job, analyze_candidate, generate_match_report, generate_resume, generate_cover_letter, generate_interview_questions, generate_skill_gap_plan), with two more calls if clarifying questions are needed (generate_clarifying_questions + a recomputed match_report). The numbers below were captured from a single end-to-end run against **`gpt-5.4-mini`** (the default OpenAI mini model in 2026, priced at **$0.75 / $4.50 per 1M input/output tokens** - cached inputs drop to $0.075 / 1M).

### Per-call breakdown (one full pipeline, 9 calls including clarifying questions)

| Step | Prompt tokens | Completion tokens |
| --- | ---: | ---: |
| `analyze_job` | 1,474 | 931 |
| `analyze_candidate` | 15,223 | 14,591 |
| `match_report` (1st) | 21,441 | 1,194 |
| `clarifying_questions` | 17,310 | 560 |
| `match_report` (recompute after answers) | 22,315 | 1,406 |
| `resume` | 22,308 | 1,754 |
| `cover_letter` | 17,574 | 340 |
| `interview_questions` | 17,242 | 1,487 |
| `skill_gap_plan` | 3,064 | 827 |
| **Total** | **137,951** | **23,090** |

### Cost per application

```
137,951 input  x  $0.75 / 1M  =  $0.1035
 23,090 output x  $4.50 / 1M  =  $0.1039
                              ---------------
                       Total ≈  $0.21
```

Effective blended price is ~**$1.30 per 1M mixed tokens** at this 85% input / 15% output ratio. One million tokens is therefore roughly six full applications.

### Monthly extrapolation (gpt-5.4-mini)

| Apps / month | Input tokens | Output tokens | Cost |
| --- | ---: | ---: | ---: |
| 10 | ~1.38 M | ~0.23 M | **~$2.07** |
| 30 | ~4.14 M | ~0.69 M | **~$6.21** |
| 100 | ~13.8 M | ~2.31 M | **~$20.70** |
| 300 | ~41.4 M | ~6.93 M | **~$62.10** |

### Other providers / fallbacks

| Provider / model | One full application | Worst-case prompt cap (~30k in / ~8k out) |
| --- | --- | --- |
| **fake provider** (default) | **$0** | **$0** |
| **gpt-5.4-mini** ($0.75 / $4.50) | ~$0.21 | ~$0.06 |
| gpt-4o-mini ($0.15 / $0.60) | ~$0.035 | ~$0.009 |
| gpt-4o ($2.50 / $10.00) | ~$0.58 | ~$0.16 |
| Mistral small ($0.20 / $0.60) | ~$0.041 | ~$0.011 |
| Groq llama-3.3-70b free tier | **$0** | **$0** |

> **Why is the worst case lower than the measured run?** The `_trim()` cap in [`src/ai/prompts.py`](src/ai/prompts.py) limits each *single* prompt to ~12 KB, but the full pipeline issues nine prompts and the candidate summary produced by `analyze_candidate` is fed into every downstream call - so totals above the per-prompt cap are normal in practice.

### Optimisation note (roadmap)

`analyze_candidate` produced **14,591 output tokens** in this run, and that summary becomes the input of `match_report`, `resume`, `cover_letter` and `interview_questions` (which is why their prompts come out at 17-22k tokens each). Trimming this summary - especially **omitting `readme_excerpt` from GitHub projects** - is expected to shave **~10-15%** off the total token bill without losing signal. Tracked under [Roadmap](#roadmap).

Set `AI_REQUEST_LOG=true` in `.env` and the app logs every real API call (with prompt/completion token counts) to `logs/ai_requests.log` so you can audit your own per-application cost after the fact.

## Languages

ApplyPilot AI is bilingual. The AI provider is instructed (rule 6 of the global system prompt in `src/ai/prompts.py`) to detect the language of the job posting and write **all** human-facing outputs - professional summary, resume bullets, cover letter, interview questions, skill-gap rationales - in the same language. Czech and English are first-class; other Latin-script languages will usually work too as long as the LLM you pick supports them. Schema field names, role-type enums and importance levels stay in English regardless.

The HTML CV import (`src/services/resume_parser.py:_parse_html`) handles Czech diacritics correctly, and the styled HTML resume template renders a localised set of section headings (`Profil` / `Pracovní zkušenosti` / `Vzdělání` etc.) when Czech diacritics are detected in the resume text. The fake / demo provider keeps its templates in English (it is a deterministic placeholder, not an LLM), but the candidate's raw CV text propagates through unchanged so you still see your real Czech bullets in the evidence preview.

## Workflow walkthrough

The UI is now a single-window dashboard with four sections in the left sidebar. The active provider is shown as a small chip in the header (orange "Demo" or green "Live AI").

1. **Setup** - one scrollable page with three cards:
   - *Job posting* - URL fetch (uses `trafilatura` then `requests + BeautifulSoup`) or paste the text directly. Czech and English postings are both supported.
   - *Resume & profile* - drop your CV (PDF / DOCX / TXT / HTML) and optionally a LinkedIn export. HTML is parsed with `beautifulsoup4` + `lxml` so styled CV templates work out of the box.
   - *GitHub profile* - paste a profile URL like `https://github.com/your-username` (or just the bare username); the app extracts the login and fetches your public repos via the GitHub REST API. Tick *Skip GitHub* to disable the network call entirely.

   Click **Run analysis** at the bottom to fire the whole pipeline (job parse + GitHub fetch + profile build + match) in one go.

2. **Clarifying questions** - if required-skill evidence coverage drops below 85%, a modal dialog appears. For each question pick *practical experience*, *learning in progress* or *no - not yet*. Click **Continue analysis** and the match report refreshes.

3. **Match report** - score badge, four category bars, three columns (matched / missing / ATS) and an evidence preview. Hover over each column heading for an explanation of what `Matched` / `Missing / risky gaps` / `ATS keywords` mean in ATS terminology. Click **Generate documents**.

4. **Documents** - tabs for resume (markdown), **Modern Resume** (printable two-column A4 preview), cover letter, match report, interview prep, skill gap plan and evidence report. Edit the text inline. Use the per-tab **Export MD / HTML / DOCX** buttons, the *Modern Resume* tab's **Open in browser** / **Export styled HTML** buttons, or click **Save full analysis** to write all 10 artefacts to `outputs/<company>-<role>-<timestamp>/`.

5. **History** - the History tab loads `outputs/history.json` and lets you **Open the selected folder** in your file explorer or **Open in app** to reload the markdown / HTML files into the Documents tab without spending another AI call. Empty state shows a hint when there are no analyses yet.

## Project structure

```
applypilot-ai/
  README.md, LICENSE, requirements.txt, pyproject.toml
  .env.example, .gitignore
  app.py                    # entry point: python app.py
  src/
    config.py               # dotenv loader, Settings dataclass
    gui/                    # PySide6 main window + 4 sections + widgets + workers + theme
      theme.py              # centralised dark QSS + colour tokens
      main_window.py        # sidebar + header + section stack
      setup_page.py         # job + CV + GitHub URLs (one screen)
      match_report_page.py
      documents_page.py
      history_page.py
      questions_dialog.py   # modal clarifying-questions dialog
      widgets/              # Sidebar, StatusChip, SectionCard, FileDropZone, ScoreBadge, EvidenceCard
    ai/
      base.py               # BaseAIProvider ABC
      fake_provider.py      # offline demo provider, default
      openai_compatible_provider.py
      provider_factory.py   # graceful fallback
      prompts.py            # role-aware system + user prompts
      role_detector.py      # title -> RoleType classifier
    services/               # business logic: fetchers, parsers, generators, exporters, history
                            # github_analyzer.py - REST API for the candidate's public repos
    models/                 # Pydantic schemas (job, candidate, evidence, match, documents, package)
    storage/file_history.py # outputs/history.json reader + writer
    utils/                  # text_cleaning, file_utils, slugify, privacy, logging_config
  tests/                    # 64 pytest tests; never call real AI
  sample_data/              # anonymised CV, LinkedIn, JD and GitHub username
  outputs/                  # user-generated outputs, .gitignored except .gitkeep
```

## Outputs

For one application the export service writes ten files into one folder:

```
outputs/democorp-qa-automation-engineer-20260501-191500/
  tailored_resume.md
  tailored_resume.docx
  tailored_resume.html      # printable two-column A4, self-contained CSS
  cover_letter.md
  cover_letter.docx
  match_report.md
  interview_questions.md
  skill_gap_plan.md
  evidence_report.json
  application_summary.html  # everything bundled for review
```

Plus a single shared file:

```
outputs/history.json
```

Each history entry stores `date`, `company`, `role`, `job_url`, `match_score`, `output_folder` and `role_type`.

## Tests

```bash
pytest -q
```

The test suite is hermetic. An autouse pytest fixture replaces `requests.post` with a function that fails the test loudly if anything tries to call a real AI provider. The 64 tests cover:

- All 8 `FakeAIProvider` methods returning valid Pydantic models.
- 21 `RoleType` detector cases for IT roles + a non-IT fallback.
- Resume / DOCX / TXT parser happy and error paths.
- Evidence checker bucketing logic.
- `match_engine.compute_match` and `needs_clarifying_questions`.
- Export service writing all 9 files.
- Provider factory falling back to fake when the API key is missing.
- A guard test that asserts the safety net actually blocks an attempted real-AI call.

## Limitations

- **JavaScript-heavy job sites** (LinkedIn job posts, some ATS pages, Microsoft Careers, Workday) ship the description via JavaScript, so the static `trafilatura` / `requests` strategies see only the SPA bootstrap JSON. The fetcher detects this and the *Wrong content* button (next to *Fetch* on the setup screen) escalates to a headless system-browser render via Playwright (Chrome / Edge / Firefox - whichever is installed). If even that fails the manual paste box is offered as the final fallback.
- **PDF resumes that are scanned images** cannot be parsed (no OCR yet).
- **Demo mode is deterministic, not magical.** It produces realistic placeholder content but cannot reason about your CV the way an LLM can. Czech CV / job text propagates through unchanged in evidence previews, but generated bullets, summaries and cover letters stay in English. Switch to a real provider for full bilingual generation.
- **Modern Resume preview quality** depends on your PySide6 install. With `PySide6-Addons` (the default `PySide6` metapackage) the tab renders in Chromium-based `QtWebEngine` for pixel-perfect layout. Without it the tab degrades to `QTextBrowser` which only supports a CSS subset - use *Open in browser* for the full styled output.
- **No telemetry.** No data leaves your machine in demo mode. With a real provider, your prompts go to whichever endpoint you configured in `.env`.

## Roadmap

- [x] **Playwright system-browser fallback** for SPA career sites (Microsoft, Workday, Greenhouse). Implemented in [`src/services/playwright_renderer.py`](src/services/playwright_renderer.py); `fetch_job_text(..., use_renderer=True)` (wired to the *Wrong content* button) drives the user's existing Chrome / Edge / Firefox via Playwright channels, so `playwright install` is only needed if none of those browsers is present.
- [ ] **Trim `analyze_candidate` output** (~10-15% cost reduction): cap the structured summary, drop `readme_excerpt` from GitHub project rows, and let the downstream calls re-fetch the relevant slice on demand. See [Cost per analysis](#cost-per-analysis-measured).
- [ ] OCR fallback for scanned PDF resumes (Tesseract).
- [ ] Local vector store for cross-application evidence search.
- [ ] Browser extension that sends the current LinkedIn job URL to the desktop app.
- [ ] German (DE) localisation of the cover letter (CZ / EN already supported via prompt language matching).
- [ ] PyInstaller / Nuitka standalone builds.
- [ ] CI: GitHub Actions matrix (Windows / macOS / Linux x Python 3.11 / 3.12 / 3.13).

## GitHub push instructions

If you want to publish your fork:

```bash
git init                        # only if the repo is not already git-initialised
git add .
git commit -m "Initial commit - ApplyPilot AI MVP"
git remote add origin https://github.com/<your-user>/applypilot-ai.git
git branch -M main
git push -u origin main
```

If the remote already exists:

```bash
git remote set-url origin https://github.com/<your-user>/applypilot-ai.git
git branch -M main
git push -u origin main
```

The MVP scaffold was developed on `feat/initial-mvp-scaffold` (PR #1, merged into `main`). The current modern UI redesign and GitHub-without-REST rework live on `feat/modern-ui` and target `main` directly. See `git log --graph --oneline` for the per-commit history.

## License

This project is licensed under the **MIT License** - see [`LICENSE`](LICENSE) for details.

### Third-party licences

- **PySide6** is licensed under the **GNU LGPL-3.0**. ApplyPilot AI links against PySide6 dynamically and does not modify it, which is permitted by the LGPL. If you redistribute the application, you must keep PySide6 dynamically linked or comply with the LGPL terms (which usually means shipping it as a separate library that the user can replace).
- All other dependencies are MIT, BSD or Apache 2.0 licensed - see `requirements.txt`.

---

Made with [Cursor](https://cursor.com).
