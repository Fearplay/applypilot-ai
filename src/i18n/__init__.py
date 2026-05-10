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
        "sidebar.cost": "SESSION COST",
        "sidebar.cost.usage": "{calls} calls - {tokens} tokens",
        "sidebar.cost.total": "~${cost:.2f} this session",
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
        "setup.job.wrong": "Wrong content",
        "setup.job.wrong.tip": (
            "Retry the fetch with a desktop-browser User-Agent and, if "
            "needed, render the page in a headless system browser (Chrome / "
            "Edge / Firefox). Use this if the description above looks like "
            "JSON or like a navigation page."
        ),
        "setup.job.js_needed_hint": (
            "This page seems to need JavaScript. Click \u201cWrong content\u201d "
            "to render it in a real browser, or paste the description below."
        ),
        "setup.job.text_placeholder": "Paste the job description text here, or click Fetch above.",
        "setup.job.fallback.title": "Could not load this job page",
        "setup.job.fallback.body": (
            "Even with a desktop User-Agent the page didn't return a "
            "human-readable description (it likely needs JavaScript to "
            "render). Pick what to do next:"
        ),
        "setup.job.fallback.open_browser": "Open URL in browser",
        "setup.job.fallback.copy": "Copy URL",
        "setup.job.fallback.cancel": "Cancel",
        "setup.job.fallback.copied": "Job URL copied to clipboard - paste the description manually.",
        "setup.job.fallback.opened": "Opened the URL in your default browser - paste the description below.",
        "setup.profile.title": "Resume & profile",
        "setup.profile.subtitle": "Drop your CV (required) and optionally a LinkedIn export.",
        "setup.profile.cv_label": "CV (PDF / DOCX / TXT / HTML) - required",
        "setup.profile.linkedin_label": "LinkedIn export (PDF / TXT / HTML) - optional",
        "setup.profile.additional.label": "Additional info (optional)",
        "setup.profile.additional.subtitle": (
            "Anything the AI cannot read from your CV - in your own words. "
            "Drop a .txt / .md / .pdf / .docx / .html file to fill the box "
            "below, or just type. Both Czech and English are understood."
        ),
        "setup.profile.additional.drop_label": (
            "Drop a notes file (.txt / .md / .pdf / .docx / .html) - optional"
        ),
        "setup.profile.additional.notes_placeholder": (
            "Examples:\n"
            "- I finished university in 2023, but did not earn the bachelor's title.\n"
            "- I'm very interested in this position, but I'd like to start "
            "part-time because I plan a career change soon.\n"
            "- At my previous role I led the migration to Playwright and "
            "mentored two juniors (the CV doesn't mention this)."
        ),
        "setup.profile.additional.parsing": "Reading {name}...",
        "setup.profile.additional.parsed": (
            "Loaded {chars} characters from {name} - edit below if needed."
        ),
        "setup.profile.additional.parse_failed": (
            "Could not read {name}: {error}"
        ),
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
        "setup.github.warning.title": "GitHub repositories were skipped",
        "setup.github.warning.body": (
            "{message}\n\n"
            "Your CV analysis can continue, but GitHub projects were not "
            "included. Add GITHUB_TOKEN to .env or wait for the anonymous "
            "rate limit to reset, then run the analysis again."
        ),
        "setup.try_sample": "Try sample data",
        "setup.run": "Run analysis",
        "setup.status.fetching": "Fetching {url}...",
        "setup.status.fetched": "Fetched via {method} ({chars} chars).",
        "setup.status.fetch_failed": "Fetch failed - paste the text manually.",
        "setup.status.fetch_retrying": (
            "Retrying with desktop User-Agent and headless system browser "
            "(may take a few seconds)..."
        ),
        "setup.status.blocked.generating_questions": "AI is generating clarifying questions - please wait.",
        "setup.status.blocked.questions_pending": "Please answer all clarifying questions first.",
        "setup.status.blocked.recomputing": "Resolving discrepancies - please wait.",
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
        "setup.error.fetch.retry_title": "Page didn't load",
        "setup.error.fetch.retry_body": (
            "Couldn't fetch this page automatically. Try with browser "
            "rendering (Playwright)? It uses your installed Chrome / Edge "
            "and usually works on JavaScript-heavy career sites."
        ),
        "setup.error.fetch.try_playwright": "Try Playwright",
        "setup.error.fetch.cancel": "Cancel",
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
        "match.generate.busy": "Generating documents...",
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
        "docs.modern.change_layout": "Change layout",
        "docs.modern.change_layout.tip": (
            "Rotate the structural CSS (two-column, banner, minimal). "
            "The colour palette stays the same so you see the layout "
            "swap without the colour distracting from it."
        ),
        "docs.modern.change_colour": "Change colour",
        "docs.modern.change_colour.tip": (
            "Rotate only the colour palette. The layout stays the "
            "same so the resume's overall shape is preserved."
        ),
        "docs.modern.nothing_to_restyle.title": "Generate the resume first",
        "docs.modern.nothing_to_restyle.body": (
            "There is no resume on screen yet. Run an analysis or load "
            "a saved one before changing layout or colour."
        ),
        "docs.modern.changed_layout": "Layout swapped to {name}.",
        "docs.modern.changed_colour": "Colour swapped to {name}.",
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
        "docs.pdf.skipped": (
            "Saved to {path} - PDF export skipped (install Chrome / Edge or "
            "run `playwright install chromium` to enable A4 PDFs)."
        ),
        "docs.read_only_tip": (
            "Read-only view of an existing analysis. Run a fresh analysis "
            "to enable saving."
        ),
        # ---- refine panel ----
        "docs.refine.placeholder": "Tell the AI what's missing or wrong...",
        "docs.refine.button": "Refine with AI",
        "docs.refine.status": "Refining the active document with your feedback...",
        "docs.refine.status.resume": "Refining resume with your feedback...",
        "docs.refine.status.cover_letter": (
            "Refining cover letter with your feedback..."
        ),
        "docs.refine.done": "Document refined successfully",
        "docs.refine.error": "Refinement failed: {error}",
        "docs.refine.unsupported_tab.title": "Switch to Resume or Cover Letter",
        "docs.refine.unsupported_tab.body": (
            "The Refine with AI panel only rewrites the resume or the "
            "cover letter. Switch to one of those tabs (Resume / Modern "
            "Resume / Cover Letter) and try again."
        ),
        "docs.refine.safety_added.explicit": (
            "Safety net re-added these positions you mentioned were "
            "missing: {labels}."
        ),
        "docs.refine.safety_added.auto": (
            "Safety net also re-added these positions the AI dropped: "
            "{labels}."
        ),
        "docs.refine.problem_label": "Problem {n}",
        "docs.refine.problem_placeholder": "Problem {n}: what's wrong or missing?",
        "docs.refine.add_problem": "+ Add another problem",
        "docs.refine.add_problem_tip": (
            "Add another numbered problem so the AI can address them as "
            "separate, ordered tasks."
        ),
        "docs.refine.remove_problem_tip": "Remove this problem",
        "docs.refine.empty_warning_title": "Nothing to refine",
        "docs.refine.empty_warning_body": (
            "Type at least one problem before clicking Refine with AI."
        ),
        "docs.refine.invented_project_dropped": (
            "Removed project '{title}' because it isn't backed by your "
            "CV, LinkedIn or GitHub data - the AI shouldn't add unverified "
            "projects."
        ),
        "docs.refine.confirm.title": "Refine resume with AI?",
        "docs.refine.confirm.body": (
            "This calls the AI again on the current resume.\n\n"
            "Estimated cost: <b>{cost}</b> (based on the last similar refine "
            "on model <code>{model}</code>; actual price may vary).\n\n"
            "Continue?"
        ),
        "docs.refine.confirm.body_unknown_cost": (
            "This calls the AI again on the current resume.\n\n"
            "Estimated cost is unknown for model <code>{model}</code>.\n\n"
            "Continue?"
        ),
        "docs.refine.confirm.dont_ask": "Don't ask again this session",
        "docs.refine.confirm.cost_about": "~${cost:.2f}",
        # ---- session AI counter (status bar) ----
        "ai.session.label": "AI",
        "ai.session.summary": (
            "{calls} calls - {tokens} tokens - ~${cost:.2f} this session"
        ),
        "ai.session.tokens.short": "{value:.1f}k",
        "ai.session.tooltip": (
            "AI usage since the app started. Resets when you restart "
            "ApplyPilot. Numbers are estimated from the model price table; "
            "your provider invoice is the source of truth."
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
        "questions.continue.disabled_tip": "Answer every question above to continue.",
        "questions.cancel": "Cancel",
        # ---- discrepancy / date-conflict questions (profile_dedup) ----
        "dedup.q.cv_only": (
            "{label} appears on your CV but not on LinkedIn. "
            "Should we include it in the tailored resume?"
        ),
        "dedup.q.linkedin_only": (
            "{label} appears on LinkedIn but not on your CV. "
            "Should we include it in the tailored resume?"
        ),
        "dedup.q.date_conflict": (
            "Different dates found for {label}: CV says {cv_period}, "
            "LinkedIn says {linkedin_period}. Which is correct?"
        ),
        "dedup.q.struct_mismatch": (
            "Your CV groups multiple companies into one entry ({cv_label}), but "
            "LinkedIn lists them separately ({linkedin_labels}). How should the "
            "resume present this period?"
        ),
        "dedup.opt.include": "Yes - include in resume",
        "dedup.opt.skip": "No - skip",
        "dedup.opt.other_dates": "Other - type the correct dates",
        "dedup.opt.struct_split": "Split into separate entries (one per company, like LinkedIn)",
        "dedup.opt.struct_merge": "Keep as one combined entry (like the CV)",
        "dedup.opt.struct_manual": "Other - I'll edit it manually later",
        "dedup.why.cv_only": (
            "We only saw this entry in your CV. Confirm it's still relevant before we use it."
        ),
        "dedup.why.linkedin_only": (
            "We only saw this entry on LinkedIn. Confirm it's still relevant before we use it."
        ),
        "dedup.why.date_conflict": (
            "Your CV and LinkedIn give different periods for the same entry. "
            "We need the correct dates to avoid an inconsistency in the resume."
        ),
        "dedup.why.struct_mismatch": (
            "Your two sources describe the same period at different levels of detail. "
            "Pick the layout you prefer so the resume stays consistent."
        ),
        # ---- pre-deletion confirmation modal ----
        "dedup.confirm.title": "Confirm removals before generating",
        "dedup.confirm.body": (
            "The AI suggested removing the entries below because it judged them irrelevant "
            "for this job. Tick the box next to a row only if you actually want it gone - "
            "anything left unticked stays in the resume."
        ),
        "dedup.confirm.keep": "Keep this entry",
        "dedup.confirm.remove": "Remove",
        "dedup.confirm.remove_action": "Remove this entry",
        "dedup.confirm.reason": "Reason: {reason}",
        "dedup.confirm.continue": "Continue",
        "dedup.confirm.cancel": "Cancel",
        "dedup.confirm.section.experience": "Work experience",
        "dedup.confirm.section.education": "Education",
        "dedup.confirm.section.certifications": "Certifications",
        "dedup.confirm.section.courses": "Courses",
        "dedup.confirm.section.projects": "Projects",
        "dedup.confirm.reason.unrelated": "AI flagged it as unrelated to the target role: {reason}",
        "dedup.confirm.reason.single_source": "Only one source mentioned this entry.",
        "dedup.confirm.reason.short_or_old": "Entry is short or older than the rest of your timeline.",
        "dedup.confirm.preselected_hint": (
            "Rows you previously asked to skip are pre-checked below. "
            "Untick a box to keep that row in the resume after all."
        ),
        "dedup.confirm.preselected_badge": "Pre-selected from your earlier answer",
        # ---- 'fresh run' UX on the setup page ----
        "setup.fresh_run.label": "Re-ask clarifying questions on next run",
        "setup.fresh_run.tip": (
            "Discard the answers and skip-decisions from the previous run "
            "so the clarifying-questions dialog appears again. Useful when "
            "the new analysis should treat your inputs as a fresh start."
        ),
        # ---- restart prompt ----
        "restart.title": "Restart required",
        "restart.body": (
            "ApplyPilot AI works best when restarted to pick up the new language. "
            "Restart now? Your work in progress is preserved."
        ),
        "restart.now": "Restart now",
        "restart.later": "Restart later",
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
        "out_lang.style_label": "Visual style",
        "out_lang.style.intro": (
            "Choose how the resume + cover letter PDF should look. Pick "
            "Random to get a different layout / colour scheme each save."
        ),
        "out_lang.style.random": "Random (different each time)",
        "out_lang.style.teal_sidebar": "Teal sidebar (two-column)",
        "out_lang.style.burgundy_serif": "Burgundy serif (single column)",
        "out_lang.style.slate_minimal": "Slate minimal (clean, single column)",
        "out_lang.style.forest_sidebar": "Forest sidebar (two-column)",
        "out_lang.style.indigo_header": "Indigo header band (single column)",
        "out_lang.style.sunset_modern": "Sunset coral (two-column)",
        "out_lang.translate_positions.label": "Translate position titles",
        "out_lang.translate_positions.tooltip": (
            "Translate role titles and company decorations into the chosen "
            "output language. Uncheck to keep titles like \"Senior Software "
            "QA Engineer\" verbatim from your CV / LinkedIn even on a Czech "
            "resume (bullets, summary and education still follow the picked "
            "language)."
        ),
        # ---- settings dialog ----
        "settings.title": "AI provider settings",
        "settings.section": "AI provider",
        "settings.tip_html": (
            "<b>Tip:</b> API keys saved here are stored in your operating "
            "system keyring (Windows Credential Manager / macOS Keychain / "
            "Linux Secret Service). They survive restarts and never touch "
            "<code>.env</code>. The <code>.env</code> file stays as a "
            "convenience for CI / power users."
        ),
        "settings.tip_html.json_fallback": (
            "<b>Note:</b> the OS keyring is unavailable, so secrets fall "
            "back to <code>~/.applypilot/secrets.json</code> with "
            "<code>0o600</code> permissions. Still safer than "
            "<code>.env</code>; never check that file into git."
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
        "settings.preset": "Preset",
        "settings.preset.tip": (
            "Pick a vendor to auto-fill Base URL + a recommended Model. "
            "Custom keeps whatever you typed manually."
        ),
        "settings.base_url": "Base URL",
        "settings.api_key": "API key",
        "settings.api_key.show": "Show",
        "settings.api_key.hide": "Hide",
        "settings.api_key.test": "Test connection",
        "settings.api_key.delete": "Delete from keyring",
        "settings.api_key.testing": "Testing connection...",
        "settings.api_key.test_ok": "OK - {n} models available.",
        "settings.api_key.test_fail": "Failed: {error}",
        "settings.api_key.test_no_url": "Fill Base URL + API key first.",
        "settings.api_key.deleted": "Removed from keyring + cleared field.",
        "settings.api_key.delete_failed": "Could not remove from keyring: {error}",
        "settings.model": "Model",
        "settings.github.title": "GitHub",
        "settings.github.token": "GitHub token (optional)",
        "settings.github.tip_html": (
            "Without a token GitHub allows ~60 unauthenticated requests/hour "
            "per IP, with a token ~5000/hour. Generate a fine-grained "
            "<b>read-only</b> personal access token at "
            "<a href='https://github.com/settings/personal-access-tokens'>"
            "github.com/settings/personal-access-tokens</a>. Grant it "
            "<i>public_repo</i> read scope only."
        ),
        "settings.github.delete": "Delete from keyring",
        "settings.github.deleted": "GitHub token removed from keyring.",
        "settings.github.delete_failed": "Could not remove GitHub token: {error}",
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
        "settings.save": "Save",
        "settings.cancel": "Cancel",
        "settings.confirm_refine": "Confirm before each AI refine call (recommended)",
        "settings.confirm_refine.tip": (
            "Shows a small modal with the estimated $ cost before every "
            "'Refine with AI' click. Untick only if you trust your fingers."
        ),
        "settings.preset.openai": "OpenAI",
        "settings.preset.groq": "Groq",
        "settings.preset.mistral": "Mistral",
        "settings.preset.openrouter": "OpenRouter",
        "settings.preset.deepseek": "DeepSeek",
        "settings.preset.anthropic": "Anthropic (OpenAI-compat)",
        "settings.preset.gemini": "Google Gemini (OpenAI-compat)",
        "settings.preset.ollama": "Ollama (local)",
        "settings.preset.lmstudio": "LM Studio (local)",
        "settings.preset.custom": "Custom (manual)",
        "settings.preset.fake": "fake (offline demo)",
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
        "sidebar.cost": "NÁKLADY RELACE",
        "sidebar.cost.usage": "{calls} volání - {tokens} tokenů",
        "sidebar.cost.total": "~${cost:.2f} v této relaci",
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
        "setup.job.wrong": "Špatný obsah",
        "setup.job.wrong.tip": (
            "Zkus stáhnout znovu - nejprve s User-Agentem desktopového "
            "prohlížeče a, když to nestačí, vyrenderuj stránku v "
            "headless systémovém prohlížeči (Chrome / Edge / Firefox). "
            "Použij, pokud popis výše vypadá jako JSON nebo jen jako "
            "navigační stránka."
        ),
        "setup.job.js_needed_hint": (
            "Tato stránka zřejmě potřebuje JavaScript. Klikni na "
            "\u201eŠpatný obsah\u201c pro render v reálném prohlížeči, "
            "nebo popis pozice vlož níže ručně."
        ),
        "setup.job.text_placeholder": "Sem vlož text inzerátu, nebo nahoře klikni na Stáhnout.",
        "setup.job.fallback.title": "Tuto stránku se nepovedlo načíst",
        "setup.job.fallback.body": (
            "Ani s desktopovým User-Agentem nevrátila stránka čitelný text "
            "(pravděpodobně potřebuje JavaScript). Vyber, co dál:"
        ),
        "setup.job.fallback.open_browser": "Otevřít URL v prohlížeči",
        "setup.job.fallback.copy": "Zkopírovat URL",
        "setup.job.fallback.cancel": "Zrušit",
        "setup.job.fallback.copied": "URL pozice zkopírována do schránky - vlož popis ručně níže.",
        "setup.job.fallback.opened": "Otevřel jsem URL ve výchozím prohlížeči - vlož popis ručně níže.",
        "setup.profile.title": "Životopis a profil",
        "setup.profile.subtitle": "Přetáhni svůj životopis (povinné) a volitelně export z LinkedInu.",
        "setup.profile.cv_label": "Životopis (PDF / DOCX / TXT / HTML) - povinné",
        "setup.profile.linkedin_label": "LinkedIn export (PDF / TXT / HTML) - volitelné",
        "setup.profile.additional.label": "Doplňující informace (volitelné)",
        "setup.profile.additional.subtitle": (
            "Co AI nemůže vyčíst ze životopisu - vlastními slovy. Přetáhni "
            "soubor .txt / .md / .pdf / .docx / .html pro vyplnění pole "
            "níže, nebo rovnou piš. Funguje v češtině i angličtině."
        ),
        "setup.profile.additional.drop_label": (
            "Přetáhni soubor s poznámkami (.txt / .md / .pdf / .docx / .html) - volitelné"
        ),
        "setup.profile.additional.notes_placeholder": (
            "Příklady:\n"
            "- Vysokou školu jsem ukončil v roce 2023 bez titulu bakaláře.\n"
            "- O tuto pozici mám velký zájem, ale chci nastoupit na "
            "part-time, protože brzy plánuji změnu kariérní cesty.\n"
            "- Na minulé pozici jsem vedl migraci na Playwright a mentoroval "
            "dva juniory (v CV to není)."
        ),
        "setup.profile.additional.parsing": "Čtu {name}...",
        "setup.profile.additional.parsed": (
            "Načteno {chars} znaků z {name} - níže můžeš text upravit."
        ),
        "setup.profile.additional.parse_failed": (
            "Soubor {name} se nepovedlo načíst: {error}"
        ),
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
        "setup.github.warning.title": "GitHub repozitáře se přeskočily",
        "setup.github.warning.body": (
            "{message}\n\n"
            "Analýza CV může pokračovat, ale GitHub projekty v ní nebudou. "
            "Přidej GITHUB_TOKEN do .env nebo počkej na obnovení anonymního "
            "limitu a spusť analýzu znovu."
        ),
        "setup.try_sample": "Vyzkoušet ukázková data",
        "setup.run": "Spustit analýzu",
        "setup.status.fetching": "Stahuji {url}...",
        "setup.status.fetched": "Staženo přes {method} ({chars} znaků).",
        "setup.status.fetch_failed": "Stažení selhalo - vlož text ručně.",
        "setup.status.fetch_retrying": (
            "Zkouším znovu s desktopovým User-Agentem a headless "
            "systémovým prohlížečem (může to trvat pár sekund)..."
        ),
        "setup.status.blocked.generating_questions": "AI generuje doplňující otázky - počkej prosím.",
        "setup.status.blocked.questions_pending": "Nejprve odpověz na všechny doplňující otázky.",
        "setup.status.blocked.recomputing": "Řeším nesrovnalosti - počkej prosím.",
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
        "setup.error.fetch.retry_title": "Stránku se nepovedlo načíst",
        "setup.error.fetch.retry_body": (
            "Tuto stránku se nepovedlo automaticky stáhnout. Zkusit to "
            "přes prohlížeč (Playwright)? Použije nainstalovaný Chrome / "
            "Edge a obvykle to funguje i na kariérních stránkách "
            "závislých na JavaScriptu."
        ),
        "setup.error.fetch.try_playwright": "Zkusit Playwright",
        "setup.error.fetch.cancel": "Zrušit",
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
        "match.generate.busy": "Generuji dokumenty...",
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
        "docs.modern.change_layout": "Změnit vzhled",
        "docs.modern.change_layout.tip": (
            "Změní strukturu CSS (dvousloupcové, banner, minimalistické). "
            "Barva zůstane stejná, takže uvidíš změnu rozvržení bez "
            "rušivého přebarvení."
        ),
        "docs.modern.change_colour": "Změnit barvu",
        "docs.modern.change_colour.tip": (
            "Změní jen barevnou paletu. Rozvržení zůstane stejné, "
            "takže životopis si zachová svůj tvar."
        ),
        "docs.modern.nothing_to_restyle.title": "Nejprve vygeneruj životopis",
        "docs.modern.nothing_to_restyle.body": (
            "Životopis ještě není na obrazovce. Spusť analýzu nebo "
            "načti existující, než změníš rozvržení nebo barvu."
        ),
        "docs.modern.changed_layout": "Rozvržení změněno na {name}.",
        "docs.modern.changed_colour": "Barva změněna na {name}.",
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
        "docs.pdf.skipped": (
            "Uloženo do {path} - PDF nebylo vytvořeno (nainstaluj Chrome / Edge "
            "nebo spusť `playwright install chromium`, aby šlo generovat A4 PDF)."
        ),
        "docs.read_only_tip": (
            "Pouze náhled existující analýzy. Spusť novou analýzu, aby šlo ukládat."
        ),
        "docs.refine.placeholder": "Napiš AI, co chybí nebo je špatně...",
        "docs.refine.button": "Upřesnit pomocí AI",
        "docs.refine.status": "Upřesňuji aktivní dokument na základě tvé zpětné vazby...",
        "docs.refine.status.resume": (
            "Upřesňuji životopis na základě tvé zpětné vazby..."
        ),
        "docs.refine.status.cover_letter": (
            "Upřesňuji motivační dopis na základě tvé zpětné vazby..."
        ),
        "docs.refine.done": "Dokument úspěšně upřesněn",
        "docs.refine.error": "Upřesnění selhalo: {error}",
        "docs.refine.unsupported_tab.title": "Přepni na Životopis nebo Motivační dopis",
        "docs.refine.unsupported_tab.body": (
            "Panel Upřesnit pomocí AI přepisuje pouze životopis nebo "
            "motivační dopis. Přepni se na některou z těchto záložek "
            "(Životopis na míru / Moderní životopis / Motivační dopis) "
            "a zkus to znovu."
        ),
        "docs.refine.safety_added.explicit": (
            "Bezpečnostní vrstva doplnila tyto pozice, o kterých jsi "
            "psal/a, že chybí: {labels}."
        ),
        "docs.refine.safety_added.auto": (
            "Bezpečnostní vrstva navíc doplnila tyto pozice, které AI "
            "vynechala: {labels}."
        ),
        "docs.refine.problem_label": "Problém {n}",
        "docs.refine.problem_placeholder": "Problém {n}: co je špatně nebo chybí?",
        "docs.refine.add_problem": "+ Přidat další problém",
        "docs.refine.add_problem_tip": (
            "Přidej další očíslovaný problém, ať je AI může řešit jako "
            "samostatné očíslované úkoly."
        ),
        "docs.refine.remove_problem_tip": "Odebrat tento problém",
        "docs.refine.empty_warning_title": "Není co upřesnit",
        "docs.refine.empty_warning_body": (
            "Před kliknutím na Upřesnit pomocí AI napiš alespoň jeden problém."
        ),
        "docs.refine.invented_project_dropped": (
            "Odstraněn projekt '{title}' - nemá oporu v tvém CV, LinkedInu "
            "ani GitHubu, AI nesmí přidávat neověřené projekty."
        ),
        "docs.refine.confirm.title": "Upřesnit životopis pomocí AI?",
        "docs.refine.confirm.body": (
            "Tohle znovu zavolá AI na aktuální životopis.\n\n"
            "Odhadovaná cena: <b>{cost}</b> (podle posledního podobného "
            "upřesnění na modelu <code>{model}</code>; skutečná cena se "
            "může lišit).\n\nPokračovat?"
        ),
        "docs.refine.confirm.body_unknown_cost": (
            "Tohle znovu zavolá AI na aktuální životopis.\n\n"
            "Odhad ceny pro model <code>{model}</code> není známý.\n\n"
            "Pokračovat?"
        ),
        "docs.refine.confirm.dont_ask": "Tuhle relaci se už neptat",
        "docs.refine.confirm.cost_about": "~${cost:.2f}",
        "ai.session.label": "AI",
        "ai.session.summary": (
            "{calls} volání - {tokens} tokenů - ~${cost:.2f} v této relaci"
        ),
        "ai.session.tokens.short": "{value:.1f}k",
        "ai.session.tooltip": (
            "Využití AI od spuštění aplikace. Resetuje se při restartu. "
            "Čísla vychází z tabulky cen modelů, faktura od poskytovatele "
            "je závazná."
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
        "questions.continue.disabled_tip": "Než budeš pokračovat, odpověz na všechny otázky výše.",
        "questions.cancel": "Zrušit",
        "dedup.q.cv_only": (
            "{label} máš v životopisu, ale ne na LinkedInu. "
            "Mám to použít v životopisu na míru?"
        ),
        "dedup.q.linkedin_only": (
            "{label} máš na LinkedInu, ale ne v životopisu. "
            "Mám to použít v životopisu na míru?"
        ),
        "dedup.q.date_conflict": (
            "Pro {label} máš v životopisu jiné datum než na LinkedInu: "
            "životopis říká {cv_period}, LinkedIn {linkedin_period}. Co je správně?"
        ),
        "dedup.q.struct_mismatch": (
            "V životopisu máš víc firem v jednom záznamu ({cv_label}), ale na "
            "LinkedInu jsou rozdělené ({linkedin_labels}). Jak to mám prezentovat "
            "v životopisu na míru?"
        ),
        "dedup.opt.include": "Ano - zařadit do životopisu",
        "dedup.opt.skip": "Ne - vynechat",
        "dedup.opt.other_dates": "Jiné - zadám správná data ručně",
        "dedup.opt.struct_split": "Rozdělit na samostatné záznamy (po jedné firmě, jako na LinkedInu)",
        "dedup.opt.struct_merge": "Nechat jako jeden společný záznam (jako v životopisu)",
        "dedup.opt.struct_manual": "Jiné - dodatečně si to upravím ručně",
        "dedup.why.cv_only": (
            "Tento záznam jsme našli jen v životopisu. Potvrď, že je relevantní, "
            "než ho použijeme."
        ),
        "dedup.why.linkedin_only": (
            "Tento záznam jsme našli jen na LinkedInu. Potvrď, že je relevantní, "
            "než ho použijeme."
        ),
        "dedup.why.date_conflict": (
            "Životopis a LinkedIn uvádějí pro stejný záznam jiné období. "
            "Potřebujeme správné datum, aby v životopise nebyl nesoulad."
        ),
        "dedup.why.struct_mismatch": (
            "Tvoje dva zdroje popisují stejné období v jiné úrovni detailu. "
            "Vyber preferované rozložení, ať životopis zůstane konzistentní."
        ),
        "dedup.confirm.title": "Potvrď odstranění před generováním",
        "dedup.confirm.body": (
            "AI navrhuje odstranit níže uvedené záznamy, protože je vyhodnotila "
            "jako nerelevantní pro tuto pozici. Zaškrtni jen ty, které opravdu "
            "chceš smazat - cokoliv neoznačeného v životopise zůstane."
        ),
        "dedup.confirm.keep": "Zachovat tento záznam",
        "dedup.confirm.remove": "Odstranit",
        "dedup.confirm.remove_action": "Odstranit tento záznam",
        "dedup.confirm.reason": "Důvod: {reason}",
        "dedup.confirm.continue": "Pokračovat",
        "dedup.confirm.cancel": "Zrušit",
        "dedup.confirm.section.experience": "Pracovní zkušenosti",
        "dedup.confirm.section.education": "Vzdělání",
        "dedup.confirm.section.certifications": "Certifikáty",
        "dedup.confirm.section.courses": "Kurzy",
        "dedup.confirm.section.projects": "Projekty",
        "dedup.confirm.reason.unrelated": "AI vyhodnotila, že nesouvisí s cílovou pozicí: {reason}",
        "dedup.confirm.reason.single_source": "Tento záznam zmiňuje jen jeden zdroj.",
        "dedup.confirm.reason.short_or_old": "Záznam je krátký nebo starší než zbytek tvojí historie.",
        "dedup.confirm.preselected_hint": (
            "Řádky, které jsi v předchozí otázce označil/a jako vynechat, "
            "jsou níže přednastavené k odstranění. Pokud je chceš nakonec "
            "v životopisu nechat, odznač zaškrtnutí."
        ),
        "dedup.confirm.preselected_badge": "Předvybráno z předchozí odpovědi",
        "setup.fresh_run.label": "Zeptat se znovu na doplňující otázky při dalším spuštění",
        "setup.fresh_run.tip": (
            "Zahodí odpovědi a rozhodnutí o vynechání z předchozího běhu, "
            "takže se znovu objeví dialog s doplňujícími otázkami. Hodí se "
            "když nová analýza má začít s čistým stolem."
        ),
        "restart.title": "Vyžadován restart",
        "restart.body": (
            "ApplyPilot AI bude se změnou jazyka pracovat nejlépe po restartu. "
            "Restartovat hned? Rozpracovaná data se zachovají."
        ),
        "restart.now": "Restartovat hned",
        "restart.later": "Restartovat později",
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
        "out_lang.style_label": "Vizuální styl",
        "out_lang.style.intro": (
            "Vyber, jak má vypadat životopis a motivační dopis ve formátu PDF. "
            "Možnost \u201eNáhodný\u201c při každém uložení vytvoří jiné rozložení a barvy."
        ),
        "out_lang.style.random": "Náhodný (jiný styl pokaždé)",
        "out_lang.style.teal_sidebar": "Tyrkysový postranní panel (dva sloupce)",
        "out_lang.style.burgundy_serif": "Bordó serif (jeden sloupec)",
        "out_lang.style.slate_minimal": "Slate minimal (čistý, jeden sloupec)",
        "out_lang.style.forest_sidebar": "Lesní postranní panel (dva sloupce)",
        "out_lang.style.indigo_header": "Indigová hlavička (jeden sloupec)",
        "out_lang.style.sunset_modern": "Korálová (dva sloupce)",
        "out_lang.translate_positions.label": "Přeložit názvy pozic",
        "out_lang.translate_positions.tooltip": (
            "Přeloží názvy pozic a doplňky u zaměstnavatelů do zvoleného "
            "jazyka výstupu. Odškrtni, pokud chceš nechat názvy jako "
            "\u201eSenior Software QA Engineer\u201c v původním znění z CV "
            "/ LinkedInu i v českém životopise (odrážky, shrnutí a "
            "vzdělání se pořád přeloží podle vybraného jazyka)."
        ),
        "settings.title": "Nastavení AI poskytovatele",
        "settings.section": "AI poskytovatel",
        "settings.tip_html": (
            "<b>Tip:</b> API klíče zadané tady se ukládají do OS keyringu "
            "(Windows Credential Manager / macOS Keychain / Linux Secret "
            "Service). Zůstanou napříč restarty a do <code>.env</code> se "
            "nikdy nezapisují. Soubor <code>.env</code> zůstává jen jako "
            "pohodlí pro CI / pokročilé uživatele."
        ),
        "settings.tip_html.json_fallback": (
            "<b>Pozor:</b> OS keyring není dostupný, secrety padnou do "
            "<code>~/.applypilot/secrets.json</code> s právy "
            "<code>0o600</code>. Pořád bezpečnější než <code>.env</code>, "
            "ale ten soubor nikdy nepushuj do gitu."
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
        "settings.preset": "Přednastavení",
        "settings.preset.tip": (
            "Vyber dodavatele a Base URL + doporučený Model se vyplní samy. "
            "Custom ponechá to, co máš ručně napsané."
        ),
        "settings.base_url": "Base URL",
        "settings.api_key": "API klíč",
        "settings.api_key.show": "Zobrazit",
        "settings.api_key.hide": "Skrýt",
        "settings.api_key.test": "Otestovat spojení",
        "settings.api_key.delete": "Smazat z keyringu",
        "settings.api_key.testing": "Testuji spojení...",
        "settings.api_key.test_ok": "OK - {n} modelů dostupných.",
        "settings.api_key.test_fail": "Selhalo: {error}",
        "settings.api_key.test_no_url": "Vyplň nejdřív Base URL a API klíč.",
        "settings.api_key.deleted": "Smazáno z keyringu a z pole.",
        "settings.api_key.delete_failed": "Z keyringu se nepodařilo smazat: {error}",
        "settings.model": "Model",
        "settings.github.title": "GitHub",
        "settings.github.token": "GitHub token (volitelné)",
        "settings.github.tip_html": (
            "Bez tokenu má GitHub limit ~60 anonymních requestů/hod na IP, "
            "s tokenem ~5000/hod. Vygeneruj fine-grained <b>read-only</b> "
            "personal access token na "
            "<a href='https://github.com/settings/personal-access-tokens'>"
            "github.com/settings/personal-access-tokens</a>. Stačí scope "
            "<i>public_repo</i> read."
        ),
        "settings.github.delete": "Smazat z keyringu",
        "settings.github.deleted": "GitHub token smazán z keyringu.",
        "settings.github.delete_failed": "GitHub token se nepodařilo smazat: {error}",
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
        "settings.save": "Uložit",
        "settings.cancel": "Zrušit",
        "settings.confirm_refine": "Potvrdit před každým AI refine voláním (doporučeno)",
        "settings.confirm_refine.tip": (
            "Před každým kliknutím na 'Refine with AI' ukáže krátký dialog "
            "s odhadem ceny. Vypni jen pokud věříš svým prstům."
        ),
        "settings.preset.openai": "OpenAI",
        "settings.preset.groq": "Groq",
        "settings.preset.mistral": "Mistral",
        "settings.preset.openrouter": "OpenRouter",
        "settings.preset.deepseek": "DeepSeek",
        "settings.preset.anthropic": "Anthropic (OpenAI-compat)",
        "settings.preset.gemini": "Google Gemini (OpenAI-compat)",
        "settings.preset.ollama": "Ollama (lokální)",
        "settings.preset.lmstudio": "LM Studio (lokální)",
        "settings.preset.custom": "Custom (ručně)",
        "settings.preset.fake": "fake (offline demo)",
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
    return t_in(_current_language, key, **kwargs)


def t_in(language: str, key: str, **kwargs: Any) -> str:
    """Translate ``key`` into ``language`` regardless of the global UI
    locale. Falls back to English if the requested language is missing
    the key, then to the key itself.

    Useful for content that's part of a generated document (e.g. the
    refine safety-net message) where the document's language does not
    necessarily match the chrome's language - the user might be reading
    the GUI in English while exporting a Czech resume.
    """
    table = _STRINGS.get(language or _FALLBACK) or {}
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
    "t_in",
    "register_listener",
    "unregister_listener",
    "t",
    "language_name",
]
