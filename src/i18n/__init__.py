"""Lightweight i18n helper for the desktop UI.

We deliberately avoid Qt's ``.ts/.qm`` machinery: the app has only ~80 user
strings and the maintenance overhead of separate translation files is not
worth it. Translations live in plain Python dictionaries below; ``t(key)``
looks up the active language with an English fallback so missing keys never
break the GUI.

Language code is one of ``en`` / ``cs``. ``set_language(code)`` flips the
runtime locale and notifies any registered listener (the main window uses
this to retranslate live).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

LanguageCode = str  # "en" or "cs" today; kept open-ended on purpose.

LANGUAGES: dict[str, str] = {
    "en": "English",
    "cs": "Čeština",
}

_FALLBACK = "en"
_current_language: str = _FALLBACK
_listeners: list[Callable[[str], None]] = []


# ---------------------------------------------------------------------------
# String tables
# ---------------------------------------------------------------------------
_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # ---- chrome ----
        "app.title": "ApplyPilot AI",
        "menu.file": "&File",
        "menu.help": "&Help",
        "menu.settings": "AI provider &settings...",
        "menu.load_sample": "Load &sample data",
        "menu.quit": "&Quit",
        "menu.about": "&About ApplyPilot AI",
        "menu.language": "&Language",
        "menu.language.english": "English",
        "menu.language.czech": "Čeština (Czech)",
        "about.html": (
            "<h3>ApplyPilot AI</h3>"
            "<p>Job URL to Tailored Resume &amp; Cover Letter</p>"
            "<p>Provider-agnostic GenAI desktop assistant. MIT licensed.</p>"
            "<p><a href='https://github.com/Fearplay/applypilot-ai'>"
            "github.com/Fearplay/applypilot-ai</a></p>"
        ),
        "about.title": "About ApplyPilot AI",
        # ---- sidebar ----
        "sidebar.workflow": "WORKFLOW",
        "sidebar.activity": "Activity",
        "sidebar.activity.ready": "Ready",
        "sidebar.setup.title": "Setup",
        "sidebar.setup.subtitle": "Job + profile inputs",
        "sidebar.match.title": "Match report",
        "sidebar.match.subtitle": "Scores & evidence",
        "sidebar.documents.title": "Documents",
        "sidebar.documents.subtitle": "Resume + cover + export",
        "sidebar.history.title": "History",
        "sidebar.history.subtitle": "Past analyses",
        # ---- chip ----
        "chip.idle": "Idle",
        "chip.active": "In progress",
        "chip.done": "Done",
        "chip.demo": "Demo",
        "chip.live": "Live AI",
        "chip.ready": "Ready",
        "chip.saved": "Saved",
        # ---- setup page ----
        "setup.heading": "Build a tailored application",
        "setup.subheading": (
            "Provide the job posting and your profile inputs. Everything below "
            "is optional except the CV - the more context you share, the more "
            "accurate the match report and tailored documents will be."
        ),
        "setup.step1": "Step 1",
        "setup.step2": "Step 2",
        "setup.step3": "Step 3",
        "setup.job.title": "Job posting",
        "setup.job.subtitle": "Fetch the description from a URL or paste the text below.",
        "setup.job.url_placeholder": "https://example.com/jobs/qa-engineer",
        "setup.job.fetch": "Fetch",
        "setup.job.text_placeholder": "Paste the job description text here, or click Fetch above.",
        "setup.profile.title": "Resume & profile",
        "setup.profile.subtitle": "Drop your CV (required) and optionally a LinkedIn export.",
        "setup.profile.cv_label": "CV (PDF / DOCX / TXT / HTML) - required",
        "setup.profile.linkedin_label": "LinkedIn export (PDF / TXT / HTML) - optional",
        "setup.github.title": "GitHub profile",
        "setup.github.subtitle": (
            "Paste your GitHub profile URL and the app will fetch your "
            "public repositories automatically (uses GITHUB_TOKEN from "
            ".env if set, anonymous otherwise)."
        ),
        "setup.github.url_placeholder": "https://github.com/your-username  (or just 'your-username')",
        "setup.github.skip": "Skip GitHub - don't fetch repositories",
        "setup.github.hint_html": (
            "Without <code>GITHUB_TOKEN</code>: ~60 anonymous requests per "
            "hour from your IP. With a token in <code>.env</code>: 5000/h. "
            "The AI provider never touches GitHub itself - the app calls the "
            "public REST API directly. Generate a fine-grained read-only "
            "token at "
            "<a href=\"https://github.com/settings/personal-access-tokens\">"
            "github.com/settings/personal-access-tokens</a>."
        ),
        "setup.try_sample": "Try sample data",
        "setup.run": "Run analysis",
        "setup.status.fetching": "Fetching {url}...",
        "setup.status.fetched": "Fetched via {method} ({chars} chars).",
        "setup.status.fetch_failed": "Fetch failed - paste the text manually.",
        "setup.status.analysing": "Analysing job posting...",
        "setup.status.job_parsed": "Job parsed: {title} ({role}). Building candidate profile...",
        "setup.status.profile_ready": "Profile ready: {name} - {skills} skills, {projects} GitHub projects",
        "setup.status.failed": "Analysis failed.",
        "setup.error.no_url.title": "Missing URL",
        "setup.error.no_url.body": "Please enter a job URL first.",
        "setup.error.no_jd.title": "Missing job description",
        "setup.error.no_jd.body": "Please paste a job description or fetch one from a URL first.",
        "setup.error.no_candidate.title": "Missing candidate input",
        "setup.error.no_candidate.body": "Add at least a CV, a LinkedIn export or a GitHub profile URL.",
        "setup.error.fetch.title": "Could not fetch URL",
        "setup.error.fetch.body": "Could not auto-fetch the page. Please paste the description text manually.\n\n{message}",
        "setup.error.pipeline.title": "Analysis failed",
        # ---- match page ----
        "match.legend": "Hover over each column heading for an explanation of how the AI bucketed these skills.",
        "match.overall": "OVERALL",
        "match.cat.tech": "Technical skills",
        "match.cat.experience": "Experience",
        "match.cat.tools": "Tools",
        "match.cat.process": "Process / QA",
        "match.col.matched": "Matched",
        "match.col.matched.tip": (
            "Skills required by the job that have evidence in your CV, "
            "LinkedIn, GitHub READMEs or in answers you marked as "
            "'practical experience'."
        ),
        "match.col.missing": "Missing / risky gaps",
        "match.col.missing.tip": (
            "Required or nice-to-have skills with no evidence at all. "
            "The [risky] tag marks REQUIRED skills - leaving these out "
            "is usually an automatic eliminator in ATS scans."
        ),
        "match.col.ats": "ATS keywords",
        "match.col.ats.tip": (
            "High-signal phrases the hiring system ranks resumes by. "
            "+ means the keyword appears in your profile, - means it is "
            "missing. ATS bots (Workday, Greenhouse, Lever) sort "
            "applicants partly by literal keyword overlap."
        ),
        "match.evidence_header": "EVIDENCE PREVIEW",
        "match.back": "Back to setup",
        "match.generate": "Generate documents",
        # ---- documents page ----
        "docs.hint": "Review and tweak each document. Exporters use the text exactly as shown.",
        "docs.tab.resume": "Tailored Resume",
        "docs.tab.modern_resume": "Modern Resume",
        "docs.tab.cover": "Cover Letter",
        "docs.tab.match": "Match Report",
        "docs.tab.interview": "Interview Prep",
        "docs.tab.gaps": "Skill Gap Plan",
        "docs.tab.evidence": "Evidence (read-only)",
        "docs.modern.info_full": (
            "Printable A4 preview. Use 'Open in browser' for a pixel-perfect "
            "render or 'Export styled HTML' to save the file."
        ),
        "docs.modern.info_simple": (
            "Simplified preview - QtWebEngine not available. Open in browser "
            "for the full styled layout."
        ),
        "docs.modern.open": "Open in browser",
        "docs.modern.export_html": "Export styled HTML",
        "docs.back": "Back to match",
        "docs.export_md": "Export MD",
        "docs.export_html": "Export HTML",
        "docs.export_docx": "Export DOCX",
        "docs.save": "Save full analysis",
        "docs.status.loaded": "Loaded {count} evidence items - score {score} / 100",
        "docs.status.opened_history": "Loaded analysis from {folder} ({count} evidence items).",
        "docs.error.export_title": "Export failed",
        "docs.error.export_missing_dep": "Missing dependency",
        "docs.modern.export_title": "Export styled resume HTML",
        "docs.modern.export_filter": "HTML (*.html);;All files (*)",
        "docs.modern.nothing_preview_title": "Nothing to preview",
        "docs.modern.nothing_preview_body": "Generate a resume first.",
        "docs.modern.nothing_export_title": "Nothing to export",
        "docs.modern.nothing_export_body": "Generate a resume first.",
        "docs.modern.open_failed": "Open failed",
        "docs.export.md_filter": "Markdown (*.md);;All files (*)",
        "docs.export.html_filter": "HTML (*.html);;All files (*)",
        "docs.export.docx_filter": "Word documents (*.docx);;All files (*)",
        "docs.export.md_title": "Export {tab} as Markdown",
        "docs.export.html_title": "Export {tab} as HTML",
        "docs.export.docx_title": "Export {tab} as DOCX",
        "docs.saved_status": "Saved to {path}",
        "docs.saved_html_status": "Saved styled HTML to {path}",
        "docs.read_only_tip": (
            "Read-only view of an existing analysis. Run a fresh analysis "
            "to enable saving."
        ),
        # ---- history page ----
        "history.loaded_from": "Loaded from <code>{path}</code>",
        "history.col.date": "Date",
        "history.col.company": "Company",
        "history.col.role": "Role",
        "history.col.score": "Score",
        "history.col.folder": "Folder",
        "history.empty.title": "No analyses yet",
        "history.empty.body": "Run your first analysis from the Setup tab and it will appear here.",
        "history.refresh": "Refresh",
        "history.open_folder": "Open selected folder",
        "history.open_in_app": "Open in app",
        "history.open_in_app.tip": (
            "Re-load the saved markdown / HTML files into the Documents tab "
            "without running the AI again."
        ),
        # ---- file drop zone ----
        "drop.hint": "Drag & drop a file ({exts}) or browse.",
        "drop.empty": "No file selected",
        "drop.unsupported": "Unsupported file type: {suffix}",
        "drop.browse": "Browse...",
        "drop.clear": "Clear",
        "drop.dialog.title": "Select file",
        # ---- questions dialog ----
        "questions.title": "Clarifying questions",
        "questions.heading": "Tell us what counts as real experience",
        "questions.intro": (
            "We could not find clear evidence for some required skills. "
            "Pick the option that matches reality so the resume can use them honestly."
        ),
        "questions.empty": "No clarifying questions needed - you can continue.",
        "questions.why_prefix": "Why we ask: {reason}",
        "questions.other": "Other - type my own answer",
        "questions.other_placeholder": "Type your answer in your own words...",
        "questions.short_text_placeholder": "Type your answer here...",
        "questions.continue": "Continue analysis",
        "questions.cancel": "Cancel",
        # ---- output language dialog ----
        "out_lang.title": "Output language",
        "out_lang.heading": "In which language should we write your documents?",
        "out_lang.intro": (
            "Resume, cover letter, interview prep and skill-gap plan will be "
            "written in this language. The AI can read your inputs in any "
            "language, so feel free to mix Czech and English freely."
        ),
        "out_lang.option.en": "English",
        "out_lang.option.cs": "Čeština",
        "out_lang.confirm": "Generate documents",
        "out_lang.cancel": "Cancel",
        # ---- settings dialog ----
        "settings.title": "AI provider settings",
        "settings.section": "AI provider",
        "settings.tip_html": (
            "<b>Tip:</b> this dialog only affects the <b>current session</b>. "
            "Restarting the app reloads everything from <code>.env</code> in "
            "the project root - copy <code>.env.example</code> to "
            "<code>.env</code> and edit <code>AI_PROVIDER</code>, "
            "<code>AI_API_KEY</code>, <code>AI_BASE_URL</code> and "
            "<code>AI_MODEL</code> to make the change permanent."
        ),
        "settings.provider": "Provider",
        "settings.provider.fake": "fake (offline demo, default)",
        "settings.provider.openai": "openai_compatible (any compatible HTTP endpoint)",
        "settings.provider.fake_tip": (
            "Free, deterministic offline mode. Even with an API key filled in "
            "below, leaving Provider on 'fake' keeps the demo - switch to "
            "'openai_compatible' to actually call the API."
        ),
        "settings.provider.openai_tip": (
            "Calls the OpenAI-compatible /v1/chat/completions endpoint at the "
            "Base URL below. Requires a valid API key."
        ),
        "settings.base_url": "Base URL",
        "settings.api_key": "API key",
        "settings.model": "Model",
        "settings.examples_html": (
            "<b>Examples</b><br>"
            "&bull; OpenAI: <code>https://api.openai.com/v1</code> "
            "<code>gpt-4o-mini</code><br>"
            "&bull; Groq: <code>https://api.groq.com/openai/v1</code> "
            "<code>llama-3.3-70b-versatile</code><br>"
            "&bull; Mistral: <code>https://api.mistral.ai/v1</code> "
            "<code>mistral-small-latest</code><br>"
            "&bull; Ollama (local): <code>http://localhost:11434/v1</code> "
            "<code>llama3.1</code>"
        ),
        # ---- workflow status / errors ----
        "status.computing_match": "Computing match score...",
        "status.recomputing_match": "Recomputing match with your answers...",
        "status.recomputing_match_short": "Recomputing match...",
        "status.generating_questions": "Generating clarifying questions...",
        "status.generating_docs": "Generating tailored documents...",
        "status.exporting": "Exporting full analysis to disk...",
        "status.no_job.title": "No job",
        "status.no_job.body": "Please add a job description first.",
        "status.no_save.title": "Nothing to save",
        "status.no_save.body": "Generate documents first.",
        "status.match_score": "Match score: {score} / 100",
        "status.docs_ready": "Documents ready - review and export",
        "status.score_summary": "Saved {n} files to {folder}",
        "status.workflow_error": "Workflow error",
        "status.sample_loaded": "Sample data loaded",
        "status.sample_loaded_msg": "Sample data loaded - click 'Run analysis' to continue.",
        "status.sample_missing.title": "Sample data missing",
        "status.sample_missing.body": "Could not find {path}.",
        "status.sample_unread.title": "Could not read sample",
        "lang_change.title": "Language changed",
        "lang_change.body": "Some labels are updated immediately; restart the app to fully apply the new language.",
        "status.parsed_job": "Parsed job: {title}",
        "status.unknown_role": "Unknown",
        "status.reopened": "Re-opened {folder}",
        "status.analysis_saved.title": "Analysis saved",
        "status.analysis_saved.body": "Saved 9 files to:\n{folder}\n\nHistory updated (entry score: {score} / 100).",
        "status.history_load_failed": "Could not load analysis",
        "status.history_empty.title": "Folder is empty",
        "status.history_empty.body": "No analysis artefacts found in:\n{folder}",
    },
    "cs": {
        "app.title": "ApplyPilot AI",
        "menu.file": "&Soubor",
        "menu.help": "&Nápověda",
        "menu.settings": "&Nastavení AI poskytovatele...",
        "menu.load_sample": "Načíst &ukázková data",
        "menu.quit": "&Ukončit",
        "menu.about": "&O aplikaci ApplyPilot AI",
        "menu.language": "&Jazyk",
        "menu.language.english": "English (angličtina)",
        "menu.language.czech": "Čeština",
        "about.html": (
            "<h3>ApplyPilot AI</h3>"
            "<p>Z URL inzerátu vygeneruje životopis a motivační dopis na míru</p>"
            "<p>Desktopový asistent nezávislý na poskytovateli AI. Licence MIT.</p>"
            "<p><a href='https://github.com/Fearplay/applypilot-ai'>"
            "github.com/Fearplay/applypilot-ai</a></p>"
        ),
        "about.title": "O aplikaci ApplyPilot AI",
        "sidebar.workflow": "POSTUP",
        "sidebar.activity": "Aktivita",
        "sidebar.activity.ready": "Připraveno",
        "sidebar.setup.title": "Nastavení",
        "sidebar.setup.subtitle": "Pozice + profil",
        "sidebar.match.title": "Shoda",
        "sidebar.match.subtitle": "Skóre a důkazy",
        "sidebar.documents.title": "Dokumenty",
        "sidebar.documents.subtitle": "Životopis + dopis + export",
        "sidebar.history.title": "Historie",
        "sidebar.history.subtitle": "Předchozí analýzy",
        "chip.idle": "Čeká",
        "chip.active": "Probíhá",
        "chip.done": "Hotovo",
        "chip.demo": "Demo",
        "chip.live": "Živá AI",
        "chip.ready": "Připraveno",
        "chip.saved": "Uloženo",
        "setup.heading": "Sestavit žádost na míru",
        "setup.subheading": (
            "Vlož inzerát a údaje o sobě. Kromě životopisu jsou všechny "
            "vstupy volitelné - čím víc kontextu dáš, tím přesnější bude "
            "report shody a vygenerované dokumenty."
        ),
        "setup.step1": "Krok 1",
        "setup.step2": "Krok 2",
        "setup.step3": "Krok 3",
        "setup.job.title": "Inzerát",
        "setup.job.subtitle": "Stáhni popis z URL nebo vlož text níže.",
        "setup.job.url_placeholder": "https://example.com/jobs/qa-engineer",
        "setup.job.fetch": "Stáhnout",
        "setup.job.text_placeholder": "Sem vlož text inzerátu, nebo nahoře klikni na Stáhnout.",
        "setup.profile.title": "Životopis a profil",
        "setup.profile.subtitle": "Přetáhni svůj životopis (povinné) a volitelně export z LinkedInu.",
        "setup.profile.cv_label": "Životopis (PDF / DOCX / TXT / HTML) - povinné",
        "setup.profile.linkedin_label": "LinkedIn export (PDF / TXT / HTML) - volitelné",
        "setup.github.title": "GitHub profil",
        "setup.github.subtitle": (
            "Vlož URL svého GitHub profilu a aplikace si automaticky stáhne "
            "tvoje veřejné repozitáře (pokud je v .env nastaven GITHUB_TOKEN, "
            "použije se; jinak anonymně)."
        ),
        "setup.github.url_placeholder": "https://github.com/tvoje-jmeno  (nebo jen 'tvoje-jmeno')",
        "setup.github.skip": "Přeskočit GitHub - nestahovat repozitáře",
        "setup.github.hint_html": (
            "Bez <code>GITHUB_TOKEN</code>: ~60 anonymních dotazů za hodinu "
            "z tvojí IP. S tokenem v <code>.env</code>: 5000/h. AI poskytovatel "
            "se GitHubu nedotýká - aplikace volá veřejné REST API přímo. "
            "Token s právy jen pro čtení vygeneruj na "
            "<a href=\"https://github.com/settings/personal-access-tokens\">"
            "github.com/settings/personal-access-tokens</a>."
        ),
        "setup.try_sample": "Vyzkoušet ukázková data",
        "setup.run": "Spustit analýzu",
        "setup.status.fetching": "Stahuji {url}...",
        "setup.status.fetched": "Staženo přes {method} ({chars} znaků).",
        "setup.status.fetch_failed": "Stažení selhalo - vlož text ručně.",
        "setup.status.analysing": "Analyzuji inzerát...",
        "setup.status.job_parsed": "Inzerát zpracován: {title} ({role}). Sestavuji profil kandidáta...",
        "setup.status.profile_ready": "Profil připraven: {name} - {skills} dovedností, {projects} GitHub projektů",
        "setup.status.failed": "Analýza selhala.",
        "setup.error.no_url.title": "Chybí URL",
        "setup.error.no_url.body": "Nejprve vlož URL inzerátu.",
        "setup.error.no_jd.title": "Chybí popis pozice",
        "setup.error.no_jd.body": "Vlož popis pozice nebo ho stáhni z URL.",
        "setup.error.no_candidate.title": "Chybí údaje o kandidátovi",
        "setup.error.no_candidate.body": "Přidej alespoň životopis, LinkedIn export nebo URL GitHub profilu.",
        "setup.error.fetch.title": "Stránku se nepovedlo načíst",
        "setup.error.fetch.body": "Stránku se nepovedlo automaticky stáhnout. Vlož text inzerátu ručně.\n\n{message}",
        "setup.error.pipeline.title": "Analýza selhala",
        "match.legend": "Najedi myší na nadpis sloupce a uvidíš, jak AI dovednosti zařadila.",
        "match.overall": "CELKEM",
        "match.cat.tech": "Technické dovednosti",
        "match.cat.experience": "Praxe",
        "match.cat.tools": "Nástroje",
        "match.cat.process": "Proces / QA",
        "match.col.matched": "Shody",
        "match.col.matched.tip": (
            "Dovednosti, které pozice požaduje a které máš podložené důkazem "
            "ze životopisu, LinkedInu, GitHub README nebo z odpovědí "
            "označených jako 'praktická zkušenost'."
        ),
        "match.col.missing": "Mezery / rizikové",
        "match.col.missing.tip": (
            "Povinné nebo nice-to-have dovednosti bez jakéhokoli důkazu. "
            "Štítek [risky] označuje POVINNÉ dovednosti - jejich vynechání "
            "obvykle automaticky vyřazuje žádost při ATS skenování."
        ),
        "match.col.ats": "ATS klíčová slova",
        "match.col.ats.tip": (
            "Slovní spojení, podle kterých nábor systém řadí životopisy. "
            "+ znamená, že slovo v profilu máš, - znamená, že chybí. "
            "ATS roboti (Workday, Greenhouse, Lever) řadí kandidáty "
            "částečně podle doslovné shody klíčových slov."
        ),
        "match.evidence_header": "NÁHLED DŮKAZŮ",
        "match.back": "Zpět na nastavení",
        "match.generate": "Vygenerovat dokumenty",
        "docs.hint": "Zkontroluj a uprav každý dokument. Export vezme text přesně tak, jak ho vidíš.",
        "docs.tab.resume": "Životopis na míru",
        "docs.tab.modern_resume": "Moderní životopis",
        "docs.tab.cover": "Motivační dopis",
        "docs.tab.match": "Report shody",
        "docs.tab.interview": "Příprava na pohovor",
        "docs.tab.gaps": "Plán doplnění mezer",
        "docs.tab.evidence": "Důkazy (jen pro čtení)",
        "docs.modern.info_full": (
            "Tisknutelný náhled A4. Pro pixelově přesné zobrazení použij "
            "'Otevřít v prohlížeči', soubor uložíš přes 'Exportovat HTML'."
        ),
        "docs.modern.info_simple": (
            "Zjednodušený náhled - QtWebEngine není k dispozici. Otevři "
            "v prohlížeči, kde uvidíš plný styl."
        ),
        "docs.modern.open": "Otevřít v prohlížeči",
        "docs.modern.export_html": "Exportovat stylované HTML",
        "docs.back": "Zpět na shodu",
        "docs.export_md": "Export MD",
        "docs.export_html": "Export HTML",
        "docs.export_docx": "Export DOCX",
        "docs.save": "Uložit kompletní analýzu",
        "docs.status.loaded": "Načteno {count} důkazů - skóre {score} / 100",
        "docs.status.opened_history": "Načtena analýza z {folder} ({count} důkazů).",
        "docs.error.export_title": "Export selhal",
        "docs.error.export_missing_dep": "Chybí závislost",
        "docs.modern.export_title": "Exportovat životopis jako stylované HTML",
        "docs.modern.export_filter": "HTML (*.html);;Všechny soubory (*)",
        "docs.modern.nothing_preview_title": "Není co zobrazit",
        "docs.modern.nothing_preview_body": "Nejdřív vygeneruj životopis.",
        "docs.modern.nothing_export_title": "Není co exportovat",
        "docs.modern.nothing_export_body": "Nejdřív vygeneruj životopis.",
        "docs.modern.open_failed": "Otevření selhalo",
        "docs.export.md_filter": "Markdown (*.md);;Všechny soubory (*)",
        "docs.export.html_filter": "HTML (*.html);;Všechny soubory (*)",
        "docs.export.docx_filter": "Word dokumenty (*.docx);;Všechny soubory (*)",
        "docs.export.md_title": "Exportovat {tab} jako Markdown",
        "docs.export.html_title": "Exportovat {tab} jako HTML",
        "docs.export.docx_title": "Exportovat {tab} jako DOCX",
        "docs.saved_status": "Uloženo do {path}",
        "docs.saved_html_status": "Stylované HTML uloženo do {path}",
        "docs.read_only_tip": (
            "Pouze náhled existující analýzy. Spusť novou analýzu, aby šlo ukládat."
        ),
        "history.loaded_from": "Načteno z <code>{path}</code>",
        "history.col.date": "Datum",
        "history.col.company": "Firma",
        "history.col.role": "Pozice",
        "history.col.score": "Skóre",
        "history.col.folder": "Složka",
        "history.empty.title": "Zatím žádné analýzy",
        "history.empty.body": "Spusť první analýzu z karty Nastavení a objeví se tady.",
        "history.refresh": "Obnovit",
        "history.open_folder": "Otevřít vybranou složku",
        "history.open_in_app": "Otevřít v aplikaci",
        "history.open_in_app.tip": (
            "Znovu načte uložené markdown / HTML soubory do karty Dokumenty "
            "bez dalšího volání AI."
        ),
        "drop.hint": "Přetáhni soubor sem ({exts}) nebo procházej disk.",
        "drop.empty": "Není vybrán žádný soubor",
        "drop.unsupported": "Nepodporovaný typ souboru: {suffix}",
        "drop.browse": "Procházet...",
        "drop.clear": "Vyčistit",
        "drop.dialog.title": "Vyber soubor",
        "questions.title": "Doplňující otázky",
        "questions.heading": "Řekni nám, co se počítá jako reálná zkušenost",
        "questions.intro": (
            "U některých povinných dovedností jsme nenašli jasný důkaz. "
            "Vyber možnost, která odpovídá realitě, ať můžeme do životopisu "
            "psát čistou pravdu."
        ),
        "questions.empty": "Žádné doplňující otázky - můžeš pokračovat.",
        "questions.why_prefix": "Proč se ptáme: {reason}",
        "questions.other": "Jiné - napsat vlastní odpověď",
        "questions.other_placeholder": "Napiš vlastní odpověď svými slovy...",
        "questions.short_text_placeholder": "Sem napiš svou odpověď...",
        "questions.continue": "Pokračovat v analýze",
        "questions.cancel": "Zrušit",
        "out_lang.title": "Jazyk výstupních dokumentů",
        "out_lang.heading": "V jakém jazyce mají být tvé dokumenty?",
        "out_lang.intro": (
            "Životopis, motivační dopis, příprava na pohovor a plán doplnění "
            "mezer budou napsané v tomto jazyce. AI rozumí vstupům v obou "
            "jazycích, takže klidně mix češtiny a angličtiny v podkladech."
        ),
        "out_lang.option.en": "English (angličtina)",
        "out_lang.option.cs": "Čeština",
        "out_lang.confirm": "Vygenerovat dokumenty",
        "out_lang.cancel": "Zrušit",
        "settings.title": "Nastavení AI poskytovatele",
        "settings.section": "AI poskytovatel",
        "settings.tip_html": (
            "<b>Tip:</b> tento dialog ovlivní pouze <b>aktuální spuštění</b>. "
            "Po restartu se vše načte znovu z <code>.env</code> v rootu "
            "projektu - zkopíruj <code>.env.example</code> na "
            "<code>.env</code> a uprav <code>AI_PROVIDER</code>, "
            "<code>AI_API_KEY</code>, <code>AI_BASE_URL</code> a "
            "<code>AI_MODEL</code>, aby změna byla trvalá."
        ),
        "settings.provider": "Poskytovatel",
        "settings.provider.fake": "fake (offline demo, výchozí)",
        "settings.provider.openai": "openai_compatible (libovolný kompatibilní HTTP endpoint)",
        "settings.provider.fake_tip": (
            "Bezplatný deterministický offline režim. I když dole vyplníš "
            "API klíč, dokud necháš poskytovatele na 'fake', zůstává demo - "
            "přepni na 'openai_compatible', aby se AI opravdu volala."
        ),
        "settings.provider.openai_tip": (
            "Volá kompatibilní endpoint /v1/chat/completions na Base URL "
            "níže. Vyžaduje platný API klíč."
        ),
        "settings.base_url": "Base URL",
        "settings.api_key": "API klíč",
        "settings.model": "Model",
        "settings.examples_html": (
            "<b>Příklady</b><br>"
            "&bull; OpenAI: <code>https://api.openai.com/v1</code> "
            "<code>gpt-4o-mini</code><br>"
            "&bull; Groq: <code>https://api.groq.com/openai/v1</code> "
            "<code>llama-3.3-70b-versatile</code><br>"
            "&bull; Mistral: <code>https://api.mistral.ai/v1</code> "
            "<code>mistral-small-latest</code><br>"
            "&bull; Ollama (lokálně): <code>http://localhost:11434/v1</code> "
            "<code>llama3.1</code>"
        ),
        "status.computing_match": "Počítám skóre shody...",
        "status.recomputing_match": "Přepočítávám shodu na základě tvých odpovědí...",
        "status.recomputing_match_short": "Přepočítávám shodu...",
        "status.generating_questions": "Generuji doplňující otázky...",
        "status.generating_docs": "Generuji dokumenty na míru...",
        "status.exporting": "Exportuji kompletní analýzu na disk...",
        "status.no_job.title": "Chybí pozice",
        "status.no_job.body": "Nejprve přidej popis pozice.",
        "status.no_save.title": "Není co uložit",
        "status.no_save.body": "Nejprve vygeneruj dokumenty.",
        "status.match_score": "Skóre shody: {score} / 100",
        "status.docs_ready": "Dokumenty hotové - zkontroluj a exportuj",
        "status.score_summary": "Uloženo {n} souborů do {folder}",
        "status.workflow_error": "Chyba workflow",
        "status.sample_loaded": "Ukázková data načtena",
        "status.sample_loaded_msg": "Ukázková data načtena - klikni 'Spustit analýzu' pro pokračování.",
        "status.sample_missing.title": "Ukázková data chybí",
        "status.sample_missing.body": "Soubor {path} nenalezen.",
        "status.sample_unread.title": "Ukázku se nepovedlo přečíst",
        "lang_change.title": "Jazyk změněn",
        "lang_change.body": "Některé popisky se změnily okamžitě; pro plné použití nového jazyka aplikaci restartuj.",
        "status.parsed_job": "Pozice zpracována: {title}",
        "status.unknown_role": "Neznámá",
        "status.reopened": "Znovu otevřeno: {folder}",
        "status.analysis_saved.title": "Analýza uložena",
        "status.analysis_saved.body": "Uloženo 9 souborů do:\n{folder}\n\nHistorie aktualizována (skóre záznamu: {score} / 100).",
        "status.history_load_failed": "Analýzu se nepovedlo načíst",
        "status.history_empty.title": "Složka je prázdná",
        "status.history_empty.body": "Ve složce nejsou žádné soubory analýzy:\n{folder}",
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_language() -> str:
    return _current_language


def set_language(code: str) -> None:
    """Switch the active language and notify all registered listeners."""
    global _current_language
    if code not in _STRINGS:
        logger.warning("Unknown language %r, falling back to %s", code, _FALLBACK)
        code = _FALLBACK
    if code == _current_language:
        return
    _current_language = code
    for listener in list(_listeners):
        try:
            listener(code)
        except Exception:  # pragma: no cover - listeners must never break i18n
            logger.exception("i18n listener failed")


def register_listener(listener: Callable[[str], None]) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def unregister_listener(listener: Callable[[str], None]) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def t(key: str, **kwargs: Any) -> str:
    """Look up ``key`` in the active language; fall back to English then key."""
    table = _STRINGS.get(_current_language) or {}
    text = table.get(key)
    if text is None:
        fallback = _STRINGS.get(_FALLBACK) or {}
        text = fallback.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError) as exc:
            logger.warning("Missing format key for %s: %s", key, exc)
            return text
    return text


def language_name(code: str) -> str:
    return LANGUAGES.get(code, code)


__all__ = [
    "LANGUAGES",
    "LanguageCode",
    "get_language",
    "set_language",
    "register_listener",
    "unregister_listener",
    "t",
    "language_name",
]
