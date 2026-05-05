"""Visual themes (palette + layout) for the styled HTML resume + cover letter.

The user explicitly asked for the *visual* style of the exported resume +
cover letter to vary between generations - "different colors, different
structure / architecture", not different AI writing voice. This module is
the registry of those visual variants.

Each theme is a :class:`ResumeTheme` with:

* a deterministic ``slug`` used as a preferences key,
* localised display labels,
* a colour palette (accent, accent_dark, accent_light, body / text / bg),
* font choices (body + heading),
* a ``layout`` literal that picks one of the renderer functions below.

Layouts shipped today:

* ``two_column_sidebar`` - the classic teal CV: dark sidebar with contact /
  online / skills / languages on the left, white main column with profile /
  experience / projects / education on the right.
* ``single_column_serif`` - newspaper-style serif headings, single column,
  the candidate name framed by a thin accent rule on top.
* ``single_column_minimal`` - sans-serif, single column, generous whitespace,
  plain accent underlines on the section headings - no chips or pills.
* ``centered_header_band`` - bold accent banner across the top with the
  candidate name, then a single-column body in two sub-columns for skills /
  languages and the rest below.

Public entry points:

* :func:`tailored_resume_to_styled_html` - the function the modern-resume
  preview tab and the PDF renderer call.
* :func:`cover_letter_to_styled_html` - HTML wrapper for the cover letter
  PDF that picks up the same theme so the two documents look like a set.
* :func:`resolve_theme` - turn a user-picked slug (including ``random``)
  into a concrete :class:`ResumeTheme`.

The helpers `_group_skills`, `_localise_location` and friends used to live
in :mod:`src.services.export_service`; they migrated here unchanged
because every layout consumes them.
"""
from __future__ import annotations

import html
import logging
import random
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from ..models.candidate import CandidateProfile
from ..models.documents import CoverLetter, TailoredResume
from ..utils.text_cleaning import strip_ai_tells

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Localised section labels (resume + cover letter)
# ---------------------------------------------------------------------------
_RESUME_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "profile": "Profile",
        "experience": "Work Experience",
        "projects": "Projects",
        "education": "Education",
        "certifications": "Certifications",
        "contact": "Contact",
        "online": "Online",
        "tech_stack": "Tech Stack",
        "languages": "Languages",
    },
    "cs": {
        "profile": "Profil",
        "experience": "Pracovní zkušenosti",
        "projects": "Vlastní projekty",
        "education": "Vzdělání",
        "certifications": "Certifikáty & kurzy",
        "contact": "Kontakt",
        "online": "Online",
        "tech_stack": "Technologie",
        "languages": "Jazyky",
    },
}


def resume_labels(output_language: str) -> dict[str, str]:
    """Return the resume section labels for ``output_language``.

    Falls back to English when the code isn't in the registry; never
    raises, so unknown locales just inherit the English wording.
    """
    code = (output_language or "en").strip().lower()
    return _RESUME_LABELS.get(code, _RESUME_LABELS["en"])


# ---------------------------------------------------------------------------
# Skill / language / location helpers (theme-agnostic data extraction)
# ---------------------------------------------------------------------------
_SKILL_GROUP_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Test Automation", (
        "playwright", "selenium", "cypress", "pytest", "appium", "puppeteer",
        "webdriver", "page object", "robot framework", "testng", "junit",
    )),
    ("Languages", (
        "python", "java", "javascript", "typescript", "c#", "c++", "go ",
        "rust", "kotlin", "swift", "ruby", "php", "sql", "bash", "powershell",
        "scala",
    )),
    ("CI/CD & Tooling", (
        "jenkins", "teamcity", "docker", "kubernetes", "git", "github actions",
        "gitlab ci", "circleci", "jira", "linux", "azure devops", "ansible",
        "terraform", "vmware", "virtualization", "virtualisation",
    )),
    ("Frameworks", (
        "fastapi", "django", "flask", "react", "vue", "angular", "next.js",
        "nextjs", "express", "spring", "node.js", "nodejs", ".net",
    )),
    ("AI / Data", (
        "openai", "anthropic", "claude", "llm", "langchain", "rag",
        "pgvector", "faiss", "chroma", "pinecone", "pandas", "numpy",
        "scikit-learn", "pytorch", "tensorflow", "ai-asistovan",
        "prompt engineering",
    )),
    ("Databases", (
        "postgres", "postgresql", "mysql", "mongodb", "sqlite", "redis",
        "oracle db", "mssql",
    )),
    ("Methodology", (
        "agile", "scrum", "kanban", "tdd", "bdd", "test strategy",
        "framework design", "mentoring",
    )),
)

_SKILL_GROUP_LOCALISED_LABELS: dict[str, dict[str, str]] = {
    "cs": {
        "Test Automation": "Automatizace testů",
        "Languages": "Programovací jazyky",
        "CI/CD & Tooling": "CI/CD a nástroje",
        "Frameworks": "Frameworky",
        "AI / Data": "AI / Data",
        "Databases": "Databáze",
        "Methodology": "Metodiky",
        "Other": "Ostatní",
    },
    "en": {},
}

_LANGUAGE_DISPLAY_BY_LANG: dict[str, dict[str, str]] = {
    "cs": {
        "Czech": "čeština",
        "English": "angličtina",
        "Slovak": "slovenština",
        "German": "němčina",
        "French": "francouzština",
        "Spanish": "španělština",
        "Italian": "italština",
        "Polish": "polština",
        "Russian": "ruština",
        "Ukrainian": "ukrajinština",
        "Chinese": "čínština",
        "Japanese": "japonština",
        "Korean": "korejština",
        "Portuguese": "portugalština",
        "Dutch": "nizozemština",
        "Swedish": "švédština",
        "Norwegian": "norština",
        "Danish": "dánština",
    },
}

_LOCATION_TRANSLATIONS_CS: dict[str, str] = {
    "prague": "Praha",
    "brno": "Brno",
    "ostrava": "Ostrava",
    "pilsen": "Plzeň",
    "plzen": "Plzeň",
    "bratislava": "Bratislava",
    "vienna": "Vídeň",
    "berlin": "Berlín",
    "warsaw": "Varšava",
    "budapest": "Budapešť",
    "remote": "Vzdáleně",
    "hybrid": "Hybridně",
    "onsite": "Na pracovišti",
}

_LOCATION_TRANSLATIONS_CS_MULTI: dict[str, str] = {
    "czech republic": "Česká republika",
    "czechia": "Česká republika",
    "slovak republic": "Slovenská republika",
    "slovakia": "Slovensko",
    "united kingdom": "Spojené království",
    "united states": "Spojené státy",
    "germany": "Německo",
    "austria": "Rakousko",
    "poland": "Polsko",
    "hungary": "Maďarsko",
}

_LOCATION_TRANSLATIONS_EN: dict[str, str] = {
    "praha": "Prague",
    "brno": "Brno",
    "ostrava": "Ostrava",
    "plzen": "Pilsen",
    "bratislava": "Bratislava",
    "viden": "Vienna",
    "berlin": "Berlin",
    "varsava": "Warsaw",
    "budapest": "Budapest",
    "vzdalene": "Remote",
    "hybridne": "Hybrid",
    "pracoviste": "On-site",
    "metropolitni": "Metropolitan",
    "oblast": "Area",
    "okoli": "Area",
}

_LOCATION_TRANSLATIONS_EN_MULTI: dict[str, str] = {
    "praha a okoli": "Prague Metropolitan Area",
    "praha metropolitni oblast": "Prague Metropolitan Area",
    "metropolitni oblast prahy": "Prague Metropolitan Area",
    "hlavni mesto praha": "Prague",
    "ceska republika": "Czech Republic",
    "ceskoslovensko": "Czechoslovakia",
    "slovenska republika": "Slovak Republic",
    "slovensko": "Slovakia",
    "spojene kralovstvi": "United Kingdom",
    "spojene staty": "United States",
    "nemecko": "Germany",
    "rakousko": "Austria",
    "polsko": "Poland",
    "madarsko": "Hungary",
}

_CZECH_DIACRITICS = set("ěščřžýáíéúůťďňĚŠČŘŽÝÁÍÉÚŮŤĎŇ")


def _esc(text: str | None) -> str:
    """HTML-escape ``text`` after scrubbing AI-tell punctuation."""
    return html.escape(strip_ai_tells(text or ""), quote=True)


def _strip_diacritics_for_match(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _localised_group_label(group: str, lang: str) -> str:
    overrides = _SKILL_GROUP_LOCALISED_LABELS.get(lang, {})
    return overrides.get(group, group)


def _localise_spoken_language(name: str, lang: str) -> str:
    overrides = _LANGUAGE_DISPLAY_BY_LANG.get(lang, {})
    return overrides.get(name, name)


def _localise_location(location: str, lang: str) -> str:
    """Translate common place names to ``lang`` while preserving structure.

    Bidirectional helper: ``cs`` maps EN->CZ and vice versa for ``en``.
    Tokenises on commas first so a multi-part location like
    ``"Praha, Česká republika"`` becomes ``"Prague, Czech Republic"``.
    Unknown chunks pass through verbatim.
    """
    if not location or lang not in ("cs", "en"):
        return location
    parts = [p.strip() for p in location.split(",")]
    out: list[str] = []
    if lang == "cs":
        for part in parts:
            if not part:
                continue
            translated = _LOCATION_TRANSLATIONS_CS_MULTI.get(part.lower())
            if translated is not None:
                out.append(translated)
                continue
            tokens = part.split()
            rebuilt = [
                _LOCATION_TRANSLATIONS_CS.get(tok.lower(), tok) for tok in tokens
            ]
            out.append(" ".join(rebuilt))
        return ", ".join(out)
    for part in parts:
        if not part:
            continue
        norm = _strip_diacritics_for_match(part).lower().strip()
        translated = _LOCATION_TRANSLATIONS_EN_MULTI.get(norm)
        if translated is not None:
            out.append(translated)
            continue
        tokens = part.split()
        rebuilt: list[str] = []
        for tok in tokens:
            tok_norm = _strip_diacritics_for_match(tok).lower()
            rebuilt.append(_LOCATION_TRANSLATIONS_EN.get(tok_norm, tok))
        out.append(" ".join(rebuilt))
    return ", ".join(out)


def _group_skills(skills: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Bucket a flat skill list into ``(group_label, skills)`` tuples."""
    buckets: dict[str, list[str]] = {g: [] for g, _ in _SKILL_GROUP_KEYWORDS}
    other: list[str] = []
    for skill in skills:
        s_low = (skill or "").lower()
        if not s_low:
            continue
        placed = False
        for group, keywords in _SKILL_GROUP_KEYWORDS:
            if any(kw in s_low for kw in keywords):
                if skill not in buckets[group]:
                    buckets[group].append(skill)
                placed = True
                break
        if not placed and skill not in other:
            other.append(skill)
    result: list[tuple[str, list[str]]] = [
        (group, items) for group, items in buckets.items() if items
    ]
    if other:
        result.append(("Other", other))
    return result


_EN_EDU_MARKERS_RE = re.compile(
    r"\b(?:High School|Diploma|Bachelor|Master|Faculty|University|School|"
    r"College|Institute|Academy|Engineering|Technology|Science)\b",
    re.IGNORECASE,
)


def detect_resume_language(resume: TailoredResume) -> str:
    """Return ``'cs'`` if Czech diacritics are common, ``'en'`` otherwise."""
    blobs: list[str] = [resume.professional_summary or ""]
    for section in (resume.experience, resume.projects, resume.education):
        for s in section:
            blobs.append(s.title or "")
            blobs.append(s.subtitle or "")
            for b in s.bullets:
                blobs.append(b.text or "")
    text = " ".join(blobs)
    if not text:
        return "en"
    cz = sum(1 for c in text if c in _CZECH_DIACRITICS)
    letters = sum(1 for c in text if c.isalpha())
    if letters and (cz / letters) > 0.005:
        return "cs"
    return "en"


# ---------------------------------------------------------------------------
# Theme registry
# ---------------------------------------------------------------------------
# Two-axis split: a "theme" is the cross product of one LAYOUT (which CSS
# builder runs) and one PALETTE (which colours + fonts that builder uses).
# The user can ask the GUI to "change layout" without touching the
# palette and vice-versa, which fixes the long-standing complaint that
# the old "change style" button only ever swapped the colour.
ThemeLayout = Literal[
    "two_column_sidebar",
    "single_column_serif",
    "single_column_minimal",
    "centered_header_band",
]

#: All shipped layout slugs in their preferred display order. Used by
#: :func:`pick_different_layout` to walk the universe of layouts when
#: the user clicks "Change layout".
LAYOUTS: tuple[ThemeLayout, ...] = (
    "two_column_sidebar",
    "single_column_serif",
    "single_column_minimal",
    "centered_header_band",
)


@dataclass(frozen=True)
class Palette:
    """The colour + typography half of a :class:`ResumeTheme`.

    Decoupled from the layout so the user can flip palettes without
    touching the structure of the document. Every palette ships with
    a stable ``slug`` (used to round-trip through preferences),
    localised display labels, the nine colour tokens the layouts read,
    and the body / heading font stacks.
    """

    slug: str
    display_name_en: str
    display_name_cs: str
    accent: str          # primary accent (sidebar / banner / heading colour)
    accent_dark: str     # darker shade used for gradients / hover
    accent_soft: str     # tint used for chip backgrounds / pills
    on_accent: str       # text colour rendered on top of the accent
    text_primary: str    # main body text colour
    text_muted: str      # secondary text (period dates, captions)
    rule: str            # border / underline colour for section headings
    body_font: str       # CSS font-family stack for body text
    heading_font: str    # CSS font-family stack for headings


#: Eight palettes - the original six plus two fillers (graphite, plum) so
#: every layout has at least two colour choices the picker can rotate
#: between when the user clicks "Change colour".
PALETTES: dict[str, Palette] = {
    "teal": Palette(
        slug="teal",
        display_name_en="Teal",
        display_name_cs="Teal",
        accent="#0E7490",
        accent_dark="#0F766E",
        accent_soft="#7DD3FC",
        on_accent="#FFFFFF",
        text_primary="#0F172A",
        text_muted="#64748B",
        rule="#14B8A6",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    "burgundy": Palette(
        slug="burgundy",
        display_name_en="Burgundy",
        display_name_cs="Bordó",
        accent="#7F1D1D",
        accent_dark="#5B0F0F",
        accent_soft="#FECACA",
        on_accent="#FFFFFF",
        text_primary="#1F1A18",
        text_muted="#7B6F6A",
        rule="#B91C1C",
        body_font="'Source Sans 3','Segoe UI',Arial,sans-serif",
        heading_font="'Playfair Display','Georgia','Times New Roman',serif",
    ),
    "slate": Palette(
        slug="slate",
        display_name_en="Slate",
        display_name_cs="Slate",
        accent="#1E293B",
        accent_dark="#0F172A",
        accent_soft="#CBD5E1",
        on_accent="#FFFFFF",
        text_primary="#0F172A",
        text_muted="#64748B",
        rule="#475569",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    "forest": Palette(
        slug="forest",
        display_name_en="Forest",
        display_name_cs="Lesní",
        accent="#065F46",
        accent_dark="#064E3B",
        accent_soft="#A7F3D0",
        on_accent="#FFFFFF",
        text_primary="#111827",
        text_muted="#4B5563",
        rule="#10B981",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    "indigo": Palette(
        slug="indigo",
        display_name_en="Indigo",
        display_name_cs="Indigo",
        accent="#3730A3",
        accent_dark="#1E1B4B",
        accent_soft="#C7D2FE",
        on_accent="#FFFFFF",
        text_primary="#1F2937",
        text_muted="#6B7280",
        rule="#6366F1",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    "sunset": Palette(
        slug="sunset",
        display_name_en="Sunset",
        display_name_cs="Západ slunce",
        accent="#C2410C",
        accent_dark="#9A3412",
        accent_soft="#FED7AA",
        on_accent="#FFFFFF",
        text_primary="#1F2937",
        text_muted="#57534E",
        rule="#F97316",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    # --- new fillers so every layout has at least 2 palette choices ---
    "graphite": Palette(
        slug="graphite",
        display_name_en="Graphite",
        display_name_cs="Grafit",
        accent="#374151",
        accent_dark="#1F2937",
        accent_soft="#D1D5DB",
        on_accent="#FFFFFF",
        text_primary="#111827",
        text_muted="#6B7280",
        rule="#4B5563",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
    "plum": Palette(
        slug="plum",
        display_name_en="Plum",
        display_name_cs="Švestka",
        accent="#6B21A8",
        accent_dark="#4C1D95",
        accent_soft="#E9D5FF",
        on_accent="#FFFFFF",
        text_primary="#1F1A24",
        text_muted="#6B5876",
        rule="#9333EA",
        body_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
        heading_font="'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif",
    ),
}


@dataclass(frozen=True)
class ResumeTheme:
    """A single visual variant for the resume + cover letter HTML.

    The slug is the stable ID stored on disk + in user preferences;
    everything else is the palette + typography + layout knob.

    ``layout_slug`` and ``palette_slug`` decompose the theme along its
    two axes so :func:`pick_different_layout` /
    :func:`pick_different_palette` can rotate one axis at a time. The
    legacy ``layout`` field is preserved for the existing CSS builders
    (which dispatch on it).
    """

    slug: str
    display_name_en: str
    display_name_cs: str
    layout: ThemeLayout
    accent: str          # primary accent (sidebar background / banner / heading colour)
    accent_dark: str     # darker shade used for gradients / hover
    accent_soft: str     # very light tint used for chip backgrounds / sidebars
    on_accent: str       # text colour rendered on top of the accent (white on dark)
    text_primary: str    # main body text colour
    text_muted: str      # secondary text (period dates, captions)
    rule: str            # border / underline colour for section headings
    body_font: str       # CSS font-family stack for body text
    heading_font: str    # CSS font-family stack for headings
    layout_slug: str = ""    # axis-1 identity, used by pick_different_layout
    palette_slug: str = ""   # axis-2 identity, used by pick_different_palette

    def display_name(self, lang: str) -> str:
        code = (lang or "en").strip().lower()
        if code == "cs":
            return self.display_name_cs
        return self.display_name_en


def _theme_from_axes(
    slug: str,
    *,
    display_name_en: str,
    display_name_cs: str,
    layout_slug: ThemeLayout,
    palette_slug: str,
) -> ResumeTheme:
    """Build a :class:`ResumeTheme` from a (layout, palette) pair.

    Used by :data:`RESUME_THEMES` to assemble the shipped presets and by
    :func:`pick_different_layout` / :func:`pick_different_palette` so a
    layout / palette swap stays fully consistent (typography stack and
    colour tokens both come from the same palette object).
    """
    palette = PALETTES[palette_slug]
    return ResumeTheme(
        slug=slug,
        display_name_en=display_name_en,
        display_name_cs=display_name_cs,
        layout=layout_slug,
        accent=palette.accent,
        accent_dark=palette.accent_dark,
        accent_soft=palette.accent_soft,
        on_accent=palette.on_accent,
        text_primary=palette.text_primary,
        text_muted=palette.text_muted,
        rule=palette.rule,
        body_font=palette.body_font,
        heading_font=palette.heading_font,
        layout_slug=layout_slug,
        palette_slug=palette_slug,
    )


# Six visually distinct presets. ``teal_sidebar`` is the original look so the
# old "I want my CV to look like before" path always works. The slug names
# are preserved verbatim so saved analyses on disk still load.
RESUME_THEMES: dict[str, ResumeTheme] = {
    "teal_sidebar": _theme_from_axes(
        "teal_sidebar",
        display_name_en="Teal Two-Column",
        display_name_cs="Teal dvousloupcový",
        layout_slug="two_column_sidebar",
        palette_slug="teal",
    ),
    "burgundy_serif": _theme_from_axes(
        "burgundy_serif",
        display_name_en="Burgundy Serif",
        display_name_cs="Bordó serif",
        layout_slug="single_column_serif",
        palette_slug="burgundy",
    ),
    "slate_minimal": _theme_from_axes(
        "slate_minimal",
        display_name_en="Slate Minimal",
        display_name_cs="Slate minimal",
        layout_slug="single_column_minimal",
        palette_slug="slate",
    ),
    "forest_sidebar": _theme_from_axes(
        "forest_sidebar",
        display_name_en="Forest Two-Column",
        display_name_cs="Lesní dvousloupcový",
        layout_slug="two_column_sidebar",
        palette_slug="forest",
    ),
    "indigo_header": _theme_from_axes(
        "indigo_header",
        display_name_en="Indigo Header",
        display_name_cs="Indigo hlavička",
        layout_slug="centered_header_band",
        palette_slug="indigo",
    ),
    "sunset_modern": _theme_from_axes(
        "sunset_modern",
        display_name_en="Sunset Two-Column",
        display_name_cs="Západ slunce",
        layout_slug="two_column_sidebar",
        palette_slug="sunset",
    ),
}

#: Sentinel slug the picker uses to ask the engine for a random theme each
#: generation. Resolved by :func:`resolve_theme` so downstream code only
#: ever sees a real :class:`ResumeTheme`.
RANDOM_THEME_SLUG = "random"

#: Default theme (used when callers don't override).
DEFAULT_THEME_SLUG = "teal_sidebar"


def theme_choices() -> list[ResumeTheme]:
    """Return the ordered list of themes the picker shows in the GUI."""
    return list(RESUME_THEMES.values())


# Memoise on-the-fly themes built by ``pick_different_*`` so the same
# (layout, palette) pair always resolves to the same :class:`ResumeTheme`
# slug. Without this, two clicks of "Change palette" on a layout that
# already has a preset palette would generate two distinct synthetic
# slugs, which downstream code (preferences, exports) would then have
# to deduplicate.
_DERIVED_THEMES: dict[tuple[str, str], ResumeTheme] = {}


def _theme_for_axes(layout_slug: str, palette_slug: str) -> ResumeTheme:
    """Return the (possibly synthetic) theme for ``(layout, palette)``.

    Walks :data:`RESUME_THEMES` first to honour any preset name (e.g.
    ``("two_column_sidebar", "teal")`` resolves to the existing
    ``teal_sidebar`` slug). Otherwise builds a derived theme on the fly
    and stamps it with a deterministic ``{layout}_{palette}`` slug.
    """
    for theme in RESUME_THEMES.values():
        if theme.layout_slug == layout_slug and theme.palette_slug == palette_slug:
            return theme
    cache_key = (layout_slug, palette_slug)
    cached = _DERIVED_THEMES.get(cache_key)
    if cached is not None:
        return cached
    palette = PALETTES[palette_slug]
    derived_slug = f"{layout_slug}__{palette_slug}"
    layout_label_en = layout_slug.replace("_", " ").title()
    layout_label_cs = layout_label_en  # English fallback for derived slugs
    derived = _theme_from_axes(
        derived_slug,
        display_name_en=f"{palette.display_name_en} {layout_label_en}",
        display_name_cs=f"{palette.display_name_cs} {layout_label_cs}",
        layout_slug=layout_slug,  # type: ignore[arg-type]
        palette_slug=palette_slug,
    )
    _DERIVED_THEMES[cache_key] = derived
    return derived


def pick_different_layout(
    current: ResumeTheme, *, rng: random.Random | None = None
) -> ResumeTheme:
    """Return a theme with a DIFFERENT layout than ``current``.

    Keeps the same palette when possible so the swap reads as a layout
    change rather than a colour change. Falls back to a random palette
    only when the target layout has no preset using the current
    palette - which never happens today because every palette / layout
    combo can be synthesised on the fly via :func:`_theme_for_axes`.

    ``rng`` lets tests inject a seeded :class:`random.Random` for
    deterministic assertions; production calls let it default to the
    module-level random.
    """
    chooser = rng or random
    other_layouts = [layout for layout in LAYOUTS if layout != current.layout_slug]
    if not other_layouts:
        return current
    target_layout = chooser.choice(other_layouts)
    palette_slug = current.palette_slug or _guess_palette_slug(current)
    return _theme_for_axes(target_layout, palette_slug)


def pick_different_palette(
    current: ResumeTheme, *, rng: random.Random | None = None
) -> ResumeTheme:
    """Return a theme with the SAME layout but a different palette.

    Mirrors :func:`pick_different_layout`: keep the structure, change
    the colour. The user's "Change colour" button hits this; the result
    re-renders the modern-resume preview without changing the
    document's overall shape.
    """
    chooser = rng or random
    current_palette = current.palette_slug or _guess_palette_slug(current)
    other_palettes = [
        slug for slug in PALETTES.keys() if slug != current_palette
    ]
    if not other_palettes:
        return current
    target_palette = chooser.choice(other_palettes)
    layout_slug = current.layout_slug or current.layout
    return _theme_for_axes(layout_slug, target_palette)


def _guess_palette_slug(theme: ResumeTheme) -> str:
    """Best-effort palette identity for legacy themes.

    Old saved analyses can carry a hand-built :class:`ResumeTheme`
    without a ``palette_slug``; in that case we walk :data:`PALETTES`
    looking for the matching ``accent`` colour. Falls back to the
    first palette so the picker can still rotate.
    """
    if theme.palette_slug:
        return theme.palette_slug
    for slug, palette in PALETTES.items():
        if palette.accent.lower() == (theme.accent or "").lower():
            return slug
    # Last resort: just pick any palette so callers can keep going.
    return next(iter(PALETTES))


def resolve_theme(slug: str | None) -> ResumeTheme:
    """Turn a stored slug (possibly ``random`` or empty) into a real theme.

    ``random`` rotates the architecture: it picks one of the four
    :data:`LAYOUTS` AND one of the eight :data:`PALETTES` independently
    and combines them via :func:`_theme_for_axes`. The user's complaint
    was that the old random branch only sampled the six preset
    :data:`RESUME_THEMES`, three of which share the ``two_column_sidebar``
    layout, so half the random picks landed on the same architecture and
    the result felt "always the first PDF". With 4 layouts x 8 palettes
    the random pool is 32 distinct combos, and every layout has the same
    1/4 chance regardless of how many palettes ship for it.

    Synthetic ``{layout}__{palette}`` slugs (produced by random picks
    and the ``Change layout`` / ``Change colour`` buttons) round-trip
    through this resolver so a saved analysis re-opens with the same
    architecture it was generated with - otherwise random would silently
    collapse back to the default theme on the next load.

    Unknown slugs collapse to the default theme so loading an old /
    hand-edited preference never crashes the renderer.
    """
    code = (slug or "").strip().lower() or DEFAULT_THEME_SLUG
    if code == RANDOM_THEME_SLUG:
        layout_slug = random.choice(list(LAYOUTS))
        palette_slug = random.choice(list(PALETTES.keys()))
        return _theme_for_axes(layout_slug, palette_slug)
    preset = RESUME_THEMES.get(code)
    if preset is not None:
        return preset
    # Synthetic slug: ``{layout}__{palette}``. Both halves must be known
    # for the resolve to succeed; otherwise we fall back to the default
    # theme so a typo / retired layout never crashes the renderer.
    if "__" in code:
        layout_part, _, palette_part = code.partition("__")
        if layout_part in LAYOUTS and palette_part in PALETTES:
            return _theme_for_axes(layout_part, palette_part)  # type: ignore[arg-type]
    return RESUME_THEMES[DEFAULT_THEME_SLUG]


# ---------------------------------------------------------------------------
# Shared HTML fragment builders (theme-agnostic data -> HTML)
# ---------------------------------------------------------------------------
_ICON_LOCATION = "&#x1F4CD;"
_ICON_EMAIL = "&#x2709;&#xFE0F;"
_ICON_PHONE = "&#x1F4DE;"
_ICON_PORTFOLIO = "&#x1F517;"


def _contact_lines(
    resume: TailoredResume, candidate: CandidateProfile, lang: str
) -> list[tuple[str, str]]:
    """Return ``[(icon_html, text_html), ...]`` for the sidebar contact block.

    Theme-agnostic: each layout decides how to wrap the rows. Returning a
    pair of escaped strings means the caller can drop them straight into
    its own template without having to re-escape.
    """
    rows: list[tuple[str, str]] = []
    if candidate.location:
        rows.append((_ICON_LOCATION, _esc(_localise_location(candidate.location, lang))))
    if candidate.contact_email:
        rows.append((_ICON_EMAIL, _esc(candidate.contact_email)))
    if candidate.phone:
        rows.append((_ICON_PHONE, _esc(candidate.phone)))
    if not rows and resume.contact_line:
        for piece in [p.strip() for p in resume.contact_line.split("|") if p.strip()]:
            rows.append(("&middot;", _esc(piece)))
    return rows


def _online_lines(
    resume: TailoredResume, candidate: CandidateProfile
) -> list[tuple[str, str, str]]:
    """Return ``[(icon, href, label), ...]`` for the online-links block."""
    rows: list[tuple[str, str, str]] = []
    li = resume.linkedin or candidate.linkedin_url
    gh = resume.github or candidate.github_url
    pf = resume.portfolio or candidate.portfolio_url
    if li:
        rows.append(("in", _esc(li), _esc(li)))
    if gh:
        rows.append(("gh", _esc(gh), _esc(gh)))
    if pf:
        rows.append((_ICON_PORTFOLIO, _esc(pf), _esc(pf)))
    return rows


def _languages_rows(
    resume: TailoredResume, candidate: CandidateProfile, lang: str
) -> list[tuple[str, str]]:
    """Return ``[(language_name, level), ...]`` ready for HTML wrapping."""
    source = (
        list(resume.spoken_languages)
        if resume.spoken_languages
        else list(candidate.spoken_languages)
    )
    rows: list[tuple[str, str]] = []
    for entry in source:
        name, level = entry, ""
        for sep in ("(", " - ", " \u2013 ", ":"):
            if sep in entry:
                name, _, raw_level = entry.partition(sep)
                level = raw_level.rstrip(") ").strip()
                name = name.strip()
                break
        rows.append((_localise_spoken_language(name, lang), level))
    return rows


def _experience_html(resume: TailoredResume, theme: ResumeTheme) -> str:
    """Build the experience section HTML used by every layout.

    The wrapping ``<h2>`` is inserted by the caller because each layout
    wraps section headings differently (band underline vs sidebar vs
    plain rule).
    """
    if not resume.experience:
        return ""
    parts: list[str] = []
    for s in resume.experience:
        bullets = "".join(f"<li>{_esc(b.text)}</li>" for b in s.bullets)
        period_html = (
            f'<span class="job-period">{_esc(s.period)}</span>'
            if s.period else ""
        )
        parts.append(
            '<div class="job">'
            '<div class="job-header">'
            f'<div class="job-title">{_esc(s.title)}</div>'
            + period_html
            + "</div>"
            + (f'<div class="job-company">{_esc(s.subtitle)}</div>' if s.subtitle else "")
            + (f"<ul>{bullets}</ul>" if bullets else "")
            + "</div>"
        )
    return "".join(parts)


def _projects_html(resume: TailoredResume, theme: ResumeTheme) -> str:
    if not resume.projects:
        return ""
    parts: list[str] = []
    for s in resume.projects:
        description = " ".join(b.text for b in s.bullets) or s.subtitle
        parts.append(
            '<div class="project-card">'
            f'<div class="pname">{_esc(s.title)}</div>'
            f'<div class="pdesc">{_esc(description)}</div>'
            "</div>"
        )
    return "".join(parts)


def _education_html(resume: TailoredResume, theme: ResumeTheme) -> str:
    if not resume.education:
        return ""
    parts: list[str] = []
    for s in resume.education:
        period_html = (
            f'<span class="job-period">{_esc(s.period)}</span>'
            if s.period else ""
        )
        parts.append(
            '<div class="edu-row">'
            f'<div class="top"><span>{_esc(s.title)}</span>{period_html}</div>'
            + (f'<div class="sub">{_esc(s.subtitle)}</div>' if s.subtitle else "")
            + "</div>"
        )
    return "".join(parts)


def _certifications_html(resume: TailoredResume, theme: ResumeTheme) -> str:
    if not resume.certifications:
        return ""
    items = "".join(
        f'<div class="cert-item">{_esc(cert)}</div>'
        for cert in resume.certifications
    )
    return f'<div class="cert-list">{items}</div>'


# ---------------------------------------------------------------------------
# Layout-specific CSS
# ---------------------------------------------------------------------------
# Shared base CSS used by every layout. Two responsibilities:
#
# 1. Page sizing.  Both screen preview and print keep ``.page`` at a
#    297mm minimum so the rendered HTML looks like an A4 sheet AND - in
#    print - the .page element is at least one full A4 page tall, which
#    means the layout-level page background (e.g. the teal stripe in
#    ``two_column_sidebar``) actually covers the whole printed page.
#    The earlier ``min-height:auto !important`` print override let
#    short CVs collapse the .page to content-height, which dragged the
#    sidebar stripe up with it and left a wide white slab below the
#    content.  Multi-page CVs are unaffected because ``min-height`` only
#    sets a floor: when content is taller than 297mm the .page element
#    grows naturally and pages get split by the browser as usual.
#
# 2. Page breaks.  Every layout-level CSS (``_two_column_css``, ``_single
#    _column_serif_css``, etc.) inherits these defaults so jobs / projects
#    / education rows never split mid-section across pages, and section
#    headings never end up alone at the bottom of a page above an empty
#    block.  ``orphans`` / ``widows`` keeps prose paragraphs readable.
_CSS_BASE_PAGE = """
*{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:0}
@media print{
  html,body{background:#fff !important}
  .page{box-shadow:none !important;margin:0}
  .sidebar,.banner,.header{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
.job,.project-card,.edu-row,.cert-item,.lang-row,.skill-group,.skills-row .group,.skills-grid .group,.lang-list .lang,section.block{break-inside:avoid;page-break-inside:avoid}
.job-header,.edu-row .top{break-inside:avoid;page-break-inside:avoid}
h1,h2,h3{break-after:avoid-page;page-break-after:avoid}
p,li{orphans:2;widows:2}
""".strip()


def _two_column_css(theme: ResumeTheme) -> str:
    # The teal stripe is painted as TWO complementary layers so the
    # left-hand column reads as a continuous brand colour on every
    # printed page, including the last one where the .page element
    # may end mid-page:
    #
    # 1. ``.page`` carries the gradient as a tiled background sized
    #    73mm x 297mm with ``repeat-y``.  In screen preview (where
    #    ``min-height:297mm`` keeps .page exactly one A4 page tall)
    #    this paints the visible teal stripe.  In print, the same
    #    tile keeps painting on every A4 page worth of element content
    #    so multi-page CVs get teal on page 1 and page 2 down to where
    #    the .page element ends.
    #
    # 2. ``.bg-stripe`` is an empty positioned div in the HTML.  In
    #    screen mode it is hidden.  In print, it becomes
    #    ``position:fixed`` with ``height:100vh`` and Chromium's print
    #    layout repeats it on every paginated A4 page (per the CSS
    #    Paged Media spec, fixed-positioned elements appear in every
    #    page box).  This guarantees the teal column extends all the
    #    way to the bottom of the LAST page even when the .page
    #    element ended early - the case the user complained about
    #    (huge white slab below the sidebar on page 2).
    #
    # ``.sidebar`` stays transparent so it never repaints on top of
    # either layer; its content (name, contact, skills) sits over the
    # tiled / fixed teal background and reads identically.
    return f"""
{_CSS_BASE_PAGE}
html,body{{font-family:{theme.body_font};color:{theme.text_primary};background:#F8FAFC;line-height:1.45;font-size:10.5pt}}
.bg-stripe{{display:none}}
@media print{{.bg-stripe{{display:block;position:fixed;top:0;left:50%;transform:translateX(-105mm);width:73mm;height:100vh;background:linear-gradient(180deg,{theme.accent} 0%,{theme.accent_dark} 100%);-webkit-print-color-adjust:exact;print-color-adjust:exact;z-index:-1}}}}
.page{{max-width:210mm;min-height:297mm;margin:0 auto;box-shadow:0 8px 30px rgba(15,23,42,0.08);display:grid;grid-template-columns:73mm 1fr;align-items:stretch;background-color:#FFFFFF;background-image:linear-gradient(180deg,{theme.accent} 0%,{theme.accent_dark} 100%);background-size:73mm 297mm;background-repeat:repeat-y;background-position:top left;position:relative}}
.sidebar{{color:{theme.on_accent};padding:14mm 9mm 12mm 9mm;position:relative;z-index:1}}
.sidebar h1{{font-family:{theme.heading_font};font-size:20pt;line-height:1.1;font-weight:800;letter-spacing:-0.02em;margin-bottom:3mm}}
.sb-section{{margin-top:7mm}}
.sb-section h3{{font-size:9pt;text-transform:uppercase;letter-spacing:0.18em;font-weight:700;color:{theme.accent_soft};border-bottom:1px solid rgba(255,255,255,0.35);padding-bottom:1.5mm;margin-bottom:3mm}}
.sb-section p,.sb-section li{{font-size:9.5pt;color:rgba(255,255,255,0.92);margin-bottom:1.5mm;word-wrap:break-word}}
.sb-section a{{color:{theme.on_accent};text-decoration:none;border-bottom:1px dotted rgba(255,255,255,0.4)}}
.sb-section ul{{list-style:none}}
.sb-section .contact-line{{display:flex;align-items:center;gap:2.2mm;font-size:9pt;margin-bottom:1.8mm}}
.sb-section .contact-line .ic{{flex:0 0 5mm;color:{theme.accent_soft};font-weight:700;font-size:10.5pt;line-height:1;font-family:"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji","Twemoji Mozilla",system-ui,sans-serif}}
.skill-group{{margin-bottom:3.5mm}}
.skill-group .group-label{{font-size:8.5pt;color:{theme.accent_soft};font-weight:600;margin-bottom:1mm;text-transform:uppercase;letter-spacing:0.06em}}
.skill-tags{{display:flex;flex-wrap:wrap;gap:1.5mm}}
.skill-tag{{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.2);padding:0.8mm 2mm;border-radius:2mm;font-size:8.5pt;color:{theme.on_accent}}}
.lang-row{{display:flex;justify-content:space-between;align-items:center;font-size:9.5pt;margin-bottom:1.5mm}}
.lang-row .lvl{{font-size:8.5pt;color:{theme.accent_soft};font-weight:600}}
.main{{padding:14mm 12mm 12mm 12mm}}
.main h2{{font-family:{theme.heading_font};font-size:11pt;text-transform:uppercase;letter-spacing:0.16em;color:{theme.accent};font-weight:800;border-bottom:2px solid {theme.rule};padding-bottom:1.2mm;margin:0 0 4mm 0}}
.main h2:not(:first-child){{margin-top:7mm}}
.summary{{font-size:10pt;color:{theme.text_primary};line-height:1.55}}
.job{{margin-bottom:5mm}}
.job-header{{display:flex;justify-content:space-between;align-items:baseline;gap:3mm;margin-bottom:0.5mm}}
.job-title{{font-size:10.5pt;font-weight:700;color:{theme.text_primary}}}
.job-period{{font-size:9pt;color:{theme.text_muted};font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:500}}
.job-company{{font-size:9.5pt;color:{theme.accent_dark};font-weight:600;margin-bottom:1.5mm}}
.job ul{{list-style:none;padding-left:0}}
.job ul li{{position:relative;padding-left:4mm;margin-bottom:1.4mm;font-size:9.5pt;color:{theme.text_primary};line-height:1.45}}
.job ul li::before{{content:'\\25B8';position:absolute;left:0;top:0;color:{theme.rule};font-weight:700;font-size:9pt}}
.project-card{{border-left:3px solid {theme.rule};padding-left:3mm;margin-bottom:3mm}}
.project-card .pname{{font-size:10pt;font-weight:700;color:{theme.text_primary};margin-bottom:0.5mm}}
.project-card .pdesc{{font-size:9.5pt;color:{theme.text_primary};line-height:1.45}}
.edu-row{{margin-bottom:3mm}}
.edu-row .top{{display:flex;justify-content:space-between;font-size:10pt;font-weight:600;color:{theme.text_primary}}}
.edu-row .sub{{font-size:9.5pt;color:{theme.text_muted};font-style:italic}}
.cert-list{{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 4mm}}
.cert-item{{font-size:9.5pt;color:{theme.text_primary}}}
""".strip()


def _single_column_serif_css(theme: ResumeTheme) -> str:
    return f"""
{_CSS_BASE_PAGE}
html,body{{font-family:{theme.body_font};color:{theme.text_primary};background:#FAF7F2;line-height:1.55;font-size:10.5pt}}
.page{{max-width:210mm;min-height:297mm;margin:0 auto;background:#FFFFFF;box-shadow:0 8px 30px rgba(31,26,24,0.06);padding:18mm 18mm 16mm 18mm}}
.title-block{{border-top:4px solid {theme.accent};padding-top:6mm;margin-bottom:8mm;text-align:center}}
.title-block h1{{font-family:{theme.heading_font};font-size:30pt;font-weight:700;color:{theme.accent_dark};letter-spacing:0.02em;margin-bottom:2mm}}
.title-block .meta{{font-size:9.5pt;color:{theme.text_muted};letter-spacing:0.06em;text-transform:uppercase}}
.contact-bar{{display:flex;justify-content:center;flex-wrap:wrap;gap:6mm;margin-bottom:9mm;font-size:9.5pt;color:{theme.text_primary}}}
.contact-bar .ic{{color:{theme.accent};margin-right:1.5mm}}
.contact-bar a{{color:{theme.text_primary};text-decoration:none;border-bottom:1px dotted {theme.accent_soft}}}
section.block{{margin-bottom:7mm}}
section.block h2{{font-family:{theme.heading_font};font-size:14pt;color:{theme.accent_dark};font-weight:700;letter-spacing:0.04em;border-bottom:1px solid {theme.rule};padding-bottom:1.5mm;margin-bottom:4mm;text-transform:uppercase}}
.summary{{font-size:10.5pt;color:{theme.text_primary};line-height:1.6}}
.job{{margin-bottom:5mm}}
.job-header{{display:flex;justify-content:space-between;align-items:baseline;gap:3mm;margin-bottom:0.5mm}}
.job-title{{font-family:{theme.heading_font};font-size:11.5pt;font-weight:700;color:{theme.text_primary}}}
.job-period{{font-size:9.5pt;color:{theme.text_muted};font-style:italic;white-space:nowrap}}
.job-company{{font-size:10pt;color:{theme.accent_dark};font-style:italic;margin-bottom:1.5mm}}
.job ul{{list-style:none;padding-left:0}}
.job ul li{{position:relative;padding-left:5mm;margin-bottom:1.5mm;font-size:10pt;color:{theme.text_primary};line-height:1.5}}
.job ul li::before{{content:'\\2014';position:absolute;left:0;top:0;color:{theme.accent}}}
.skills-row{{display:flex;flex-wrap:wrap;gap:2mm 4mm;font-size:10pt}}
.skills-row .group{{margin-right:6mm}}
.skills-row .group strong{{font-family:{theme.heading_font};color:{theme.accent_dark};font-weight:700;margin-right:1.5mm}}
.languages-row{{display:flex;gap:6mm;flex-wrap:wrap;font-size:10pt}}
.languages-row .lang{{padding:1mm 0}}
.languages-row .lang strong{{color:{theme.accent_dark}}}
.project-card{{border-left:2px solid {theme.accent};padding:0 0 0 4mm;margin-bottom:3.5mm}}
.project-card .pname{{font-family:{theme.heading_font};font-size:11pt;font-weight:700;color:{theme.text_primary};margin-bottom:0.5mm}}
.project-card .pdesc{{font-size:10pt;color:{theme.text_primary};line-height:1.5}}
.edu-row{{margin-bottom:3mm}}
.edu-row .top{{display:flex;justify-content:space-between;font-family:{theme.heading_font};font-size:10.5pt;font-weight:700;color:{theme.text_primary}}}
.edu-row .sub{{font-size:10pt;color:{theme.text_muted};font-style:italic}}
.cert-list{{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 6mm}}
.cert-item{{font-size:10pt;color:{theme.text_primary}}}
""".strip()


def _single_column_minimal_css(theme: ResumeTheme) -> str:
    return f"""
{_CSS_BASE_PAGE}
html,body{{font-family:{theme.body_font};color:{theme.text_primary};background:#FFFFFF;line-height:1.55;font-size:10.5pt}}
.page{{max-width:210mm;min-height:297mm;margin:0 auto;background:#FFFFFF;padding:18mm 22mm 18mm 22mm}}
.title-block{{margin-bottom:9mm}}
.title-block h1{{font-family:{theme.heading_font};font-size:24pt;font-weight:700;color:{theme.text_primary};letter-spacing:-0.01em;margin-bottom:2.5mm}}
.title-block .meta{{font-size:10pt;color:{theme.text_muted}}}
.contact-bar{{display:flex;flex-wrap:wrap;gap:5mm;font-size:10pt;color:{theme.text_primary};margin-bottom:8mm}}
.contact-bar .ic{{color:{theme.accent};margin-right:1.2mm}}
.contact-bar a{{color:{theme.text_primary};text-decoration:none;border-bottom:1px solid {theme.accent_soft}}}
section.block{{margin-bottom:7mm}}
section.block h2{{font-family:{theme.heading_font};font-size:11pt;color:{theme.accent};font-weight:700;letter-spacing:0.18em;text-transform:uppercase;margin-bottom:3mm}}
section.block h2::after{{content:"";display:block;width:14mm;height:1.4pt;background:{theme.rule};margin-top:1.5mm}}
.summary{{font-size:10.5pt;color:{theme.text_primary};line-height:1.65}}
.job{{margin-bottom:5mm}}
.job-header{{display:flex;justify-content:space-between;align-items:baseline;gap:3mm;margin-bottom:0.5mm}}
.job-title{{font-size:11pt;font-weight:600;color:{theme.text_primary}}}
.job-period{{font-size:9.5pt;color:{theme.text_muted};white-space:nowrap}}
.job-company{{font-size:10pt;color:{theme.accent};font-weight:500;margin-bottom:1.5mm}}
.job ul{{list-style:none;padding-left:0}}
.job ul li{{position:relative;padding-left:4mm;margin-bottom:1.4mm;font-size:10pt;color:{theme.text_primary};line-height:1.55}}
.job ul li::before{{content:'\\2022';position:absolute;left:0;top:0;color:{theme.accent}}}
.skills-row{{display:flex;flex-wrap:wrap;gap:2mm 5mm;font-size:10pt}}
.skills-row .group{{margin-right:6mm}}
.skills-row .group strong{{color:{theme.accent};font-weight:600;margin-right:1.5mm;letter-spacing:0.06em;text-transform:uppercase;font-size:9pt}}
.languages-row{{display:flex;flex-wrap:wrap;gap:5mm;font-size:10pt}}
.languages-row .lang strong{{color:{theme.accent};font-weight:600}}
.project-card{{margin-bottom:3.5mm}}
.project-card .pname{{font-size:10.5pt;font-weight:600;color:{theme.text_primary}}}
.project-card .pdesc{{font-size:10pt;color:{theme.text_primary};line-height:1.55}}
.edu-row{{margin-bottom:3mm}}
.edu-row .top{{display:flex;justify-content:space-between;font-size:10.5pt;font-weight:600;color:{theme.text_primary}}}
.edu-row .sub{{font-size:10pt;color:{theme.text_muted}}}
.cert-list{{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 6mm}}
.cert-item{{font-size:10pt;color:{theme.text_primary}}}
""".strip()


def _centered_header_css(theme: ResumeTheme) -> str:
    return f"""
{_CSS_BASE_PAGE}
html,body{{font-family:{theme.body_font};color:{theme.text_primary};background:#F8FAFC;line-height:1.5;font-size:10.5pt}}
.page{{max-width:210mm;min-height:297mm;margin:0 auto;background:#FFFFFF;box-shadow:0 8px 30px rgba(15,23,42,0.08)}}
.banner{{background:linear-gradient(135deg,{theme.accent} 0%,{theme.accent_dark} 100%);color:{theme.on_accent};padding:16mm 18mm 12mm 18mm;text-align:center}}
.banner h1{{font-family:{theme.heading_font};font-size:26pt;font-weight:800;letter-spacing:0.01em;margin-bottom:3mm}}
.banner .role{{font-size:11pt;color:{theme.accent_soft};letter-spacing:0.08em;text-transform:uppercase;margin-bottom:5mm}}
.banner .contact-bar{{display:flex;justify-content:center;flex-wrap:wrap;gap:6mm;font-size:9.5pt;color:rgba(255,255,255,0.92)}}
.banner .contact-bar a{{color:{theme.on_accent};text-decoration:none;border-bottom:1px dotted rgba(255,255,255,0.5)}}
.banner .contact-bar .ic{{color:{theme.accent_soft};margin-right:1.2mm}}
.body{{padding:12mm 18mm 16mm 18mm}}
section.block{{margin-bottom:7mm}}
section.block h2{{font-family:{theme.heading_font};font-size:12pt;color:{theme.accent_dark};font-weight:800;letter-spacing:0.14em;text-transform:uppercase;border-bottom:2px solid {theme.rule};padding-bottom:1.5mm;margin-bottom:4mm}}
.summary{{font-size:10.5pt;color:{theme.text_primary};line-height:1.6;text-align:justify}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:9mm}}
.job{{margin-bottom:5mm}}
.job-header{{display:flex;justify-content:space-between;align-items:baseline;gap:3mm;margin-bottom:0.5mm}}
.job-title{{font-size:11pt;font-weight:700;color:{theme.text_primary}}}
.job-period{{font-size:9.5pt;color:{theme.text_muted};white-space:nowrap}}
.job-company{{font-size:10pt;color:{theme.accent};font-weight:600;margin-bottom:1.5mm}}
.job ul{{list-style:none;padding-left:0}}
.job ul li{{position:relative;padding-left:4mm;margin-bottom:1.5mm;font-size:10pt;color:{theme.text_primary};line-height:1.5}}
.job ul li::before{{content:'\\25C6';position:absolute;left:0;top:0;color:{theme.rule};font-size:8pt}}
.skills-grid{{display:grid;grid-template-columns:1fr 1fr;gap:3mm 6mm;font-size:10pt}}
.skills-grid .group strong{{color:{theme.accent};font-weight:700;font-size:9pt;text-transform:uppercase;letter-spacing:0.08em;display:block;margin-bottom:1mm}}
.lang-list{{display:flex;flex-direction:column;gap:1.5mm;font-size:10pt}}
.lang-list .lang{{display:flex;justify-content:space-between;border-bottom:1px dashed {theme.accent_soft};padding-bottom:1mm}}
.lang-list .lang strong{{color:{theme.text_primary};font-weight:600}}
.lang-list .lang .lvl{{color:{theme.accent};font-weight:700}}
.project-card{{background:#F1F5F9;border-radius:2mm;padding:3mm 4mm;margin-bottom:3mm}}
.project-card .pname{{font-size:10.5pt;font-weight:700;color:{theme.accent_dark};margin-bottom:0.5mm}}
.project-card .pdesc{{font-size:10pt;color:{theme.text_primary};line-height:1.5}}
.edu-row{{margin-bottom:3mm}}
.edu-row .top{{display:flex;justify-content:space-between;font-size:10.5pt;font-weight:700;color:{theme.text_primary}}}
.edu-row .sub{{font-size:10pt;color:{theme.text_muted}}}
.cert-list{{display:grid;grid-template-columns:1fr 1fr;gap:1.5mm 6mm}}
.cert-item{{font-size:10pt;color:{theme.text_primary}}}
""".strip()


def _theme_css(theme: ResumeTheme) -> str:
    if theme.layout == "two_column_sidebar":
        return _two_column_css(theme)
    if theme.layout == "single_column_serif":
        return _single_column_serif_css(theme)
    if theme.layout == "single_column_minimal":
        return _single_column_minimal_css(theme)
    if theme.layout == "centered_header_band":
        return _centered_header_css(theme)
    # Defensive default - keeps unknown layouts rendering as the classic theme.
    return _two_column_css(theme)


# ---------------------------------------------------------------------------
# Layout-specific renderers
# ---------------------------------------------------------------------------
def _render_two_column(
    resume: TailoredResume,
    candidate: CandidateProfile,
    theme: ResumeTheme,
    labels: dict[str, str],
    lang: str,
) -> str:
    sidebar_sections: list[str] = [f'<h1>{_esc(resume.name or "Candidate")}</h1>']

    contact_rows = _contact_lines(resume, candidate, lang)
    if contact_rows:
        body = "".join(
            f'<div class="contact-line"><span class="ic">{ic}</span>'
            f"<span>{txt}</span></div>"
            for ic, txt in contact_rows
        )
        sidebar_sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["contact"])}</h3>{body}</div>'
        )

    online_rows = _online_lines(resume, candidate)
    if online_rows:
        body = "".join(
            f'<div class="contact-line"><span class="ic">{ic}</span>'
            f'<a href="{href}">{label}</a></div>'
            for ic, href, label in online_rows
        )
        sidebar_sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["online"])}</h3>{body}</div>'
        )

    skill_groups_html: list[str] = []
    for group_label, items in _group_skills(resume.technical_skills):
        tags = "".join(
            f'<span class="skill-tag">{_esc(s)}</span>' for s in items
        )
        skill_groups_html.append(
            '<div class="skill-group">'
            f'<div class="group-label">{_esc(_localised_group_label(group_label, lang))}</div>'
            f'<div class="skill-tags">{tags}</div>'
            "</div>"
        )
    if skill_groups_html:
        sidebar_sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["tech_stack"])}</h3>'
            + "".join(skill_groups_html)
            + "</div>"
        )

    languages = _languages_rows(resume, candidate, lang)
    if languages:
        rows = "".join(
            f'<div class="lang-row"><span>{_esc(name)}</span>'
            f'<span class="lvl">{_esc(level)}</span></div>'
            for name, level in languages
        )
        sidebar_sections.append(
            f'<div class="sb-section"><h3>{_esc(labels["languages"])}</h3>{rows}</div>'
        )

    sidebar = f'<aside class="sidebar">{"".join(sidebar_sections)}</aside>'

    main_parts: list[str] = []
    if resume.professional_summary:
        main_parts.append(
            f'<h2>{_esc(labels["profile"])}</h2>'
            f'<p class="summary">{_esc(resume.professional_summary)}</p>'
        )
    if resume.experience:
        main_parts.append(f'<h2>{_esc(labels["experience"])}</h2>')
        main_parts.append(_experience_html(resume, theme))
    if resume.projects:
        main_parts.append(f'<h2>{_esc(labels["projects"])}</h2>')
        main_parts.append(_projects_html(resume, theme))
    if resume.education:
        main_parts.append(f'<h2>{_esc(labels["education"])}</h2>')
        main_parts.append(_education_html(resume, theme))
    if resume.certifications:
        main_parts.append(f'<h2>{_esc(labels["certifications"])}</h2>')
        main_parts.append(_certifications_html(resume, theme))
    main = f'<main class="main">{"".join(main_parts)}</main>'

    # ``.bg-stripe`` is a print-only fixed-position teal column that
    # Chromium repeats on every paginated A4 page.  See ``_two_column_css``
    # for the rationale - this guarantees the sidebar stripe extends to
    # the bottom of the last page even when the .page element ended
    # early because the right column had less content than 297mm.
    return f'<div class="bg-stripe"></div><div class="page">{sidebar}{main}</div>'


def _flat_contact_bar(
    resume: TailoredResume, candidate: CandidateProfile, lang: str
) -> str:
    """Single-line contact bar used by the non-sidebar layouts."""
    bits: list[str] = []
    contact_rows = _contact_lines(resume, candidate, lang)
    for ic, txt in contact_rows:
        bits.append(f'<span><span class="ic">{ic}</span>{txt}</span>')
    online_rows = _online_lines(resume, candidate)
    for ic, href, label in online_rows:
        bits.append(
            f'<span><span class="ic">{ic}</span>'
            f'<a href="{href}">{label}</a></span>'
        )
    if not bits:
        return ""
    return f'<div class="contact-bar">{"".join(bits)}</div>'


def _flat_skills_html(resume: TailoredResume, lang: str) -> str:
    groups = _group_skills(resume.technical_skills)
    if not groups:
        return ""
    rows: list[str] = []
    for group_label, items in groups:
        rows.append(
            '<div class="group">'
            f'<strong>{_esc(_localised_group_label(group_label, lang))}:</strong>'
            f' {_esc(", ".join(items))}'
            "</div>"
        )
    return f'<div class="skills-row">{"".join(rows)}</div>'


def _flat_languages_html(
    resume: TailoredResume, candidate: CandidateProfile, lang: str
) -> str:
    rows = _languages_rows(resume, candidate, lang)
    if not rows:
        return ""
    parts = "".join(
        f'<div class="lang"><strong>{_esc(name)}</strong>'
        f"{' (' + _esc(level) + ')' if level else ''}</div>"
        for name, level in rows
    )
    return f'<div class="languages-row">{parts}</div>'


def _grid_skills_html(resume: TailoredResume, lang: str) -> str:
    groups = _group_skills(resume.technical_skills)
    if not groups:
        return ""
    rows: list[str] = []
    for group_label, items in groups:
        rows.append(
            '<div class="group">'
            f'<strong>{_esc(_localised_group_label(group_label, lang))}</strong>'
            f"<span>{_esc(', '.join(items))}</span>"
            "</div>"
        )
    return f'<div class="skills-grid">{"".join(rows)}</div>'


def _grid_languages_html(
    resume: TailoredResume, candidate: CandidateProfile, lang: str
) -> str:
    rows = _languages_rows(resume, candidate, lang)
    if not rows:
        return ""
    parts = "".join(
        f'<div class="lang"><strong>{_esc(name)}</strong>'
        f'<span class="lvl">{_esc(level)}</span></div>'
        for name, level in rows
    )
    return f'<div class="lang-list">{parts}</div>'


def _render_single_column_serif(
    resume: TailoredResume,
    candidate: CandidateProfile,
    theme: ResumeTheme,
    labels: dict[str, str],
    lang: str,
) -> str:
    parts: list[str] = []
    parts.append('<div class="page">')
    parts.append(
        '<div class="title-block">'
        f'<h1>{_esc(resume.name or "Candidate")}</h1>'
        + (
            f'<div class="meta">{_esc(resume.role_targeted_for)}</div>'
            if resume.role_targeted_for else ""
        )
        + "</div>"
    )
    parts.append(_flat_contact_bar(resume, candidate, lang))

    if resume.professional_summary:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["profile"])}</h2>'
            f'<p class="summary">{_esc(resume.professional_summary)}</p></section>'
        )

    skills = _flat_skills_html(resume, lang)
    if skills:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["tech_stack"])}</h2>{skills}</section>'
        )

    if resume.experience:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["experience"])}</h2>'
            f"{_experience_html(resume, theme)}</section>"
        )
    if resume.projects:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["projects"])}</h2>'
            f"{_projects_html(resume, theme)}</section>"
        )
    if resume.education:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["education"])}</h2>'
            f"{_education_html(resume, theme)}</section>"
        )
    if resume.certifications:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["certifications"])}</h2>'
            f"{_certifications_html(resume, theme)}</section>"
        )
    languages = _flat_languages_html(resume, candidate, lang)
    if languages:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["languages"])}</h2>{languages}</section>'
        )

    parts.append("</div>")
    return "".join(parts)


def _render_single_column_minimal(
    resume: TailoredResume,
    candidate: CandidateProfile,
    theme: ResumeTheme,
    labels: dict[str, str],
    lang: str,
) -> str:
    parts: list[str] = []
    parts.append('<div class="page">')
    parts.append(
        '<div class="title-block">'
        f'<h1>{_esc(resume.name or "Candidate")}</h1>'
        + (
            f'<div class="meta">{_esc(resume.role_targeted_for)}</div>'
            if resume.role_targeted_for else ""
        )
        + "</div>"
    )
    parts.append(_flat_contact_bar(resume, candidate, lang))

    if resume.professional_summary:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["profile"])}</h2>'
            f'<p class="summary">{_esc(resume.professional_summary)}</p></section>'
        )
    skills = _flat_skills_html(resume, lang)
    if skills:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["tech_stack"])}</h2>{skills}</section>'
        )
    if resume.experience:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["experience"])}</h2>'
            f"{_experience_html(resume, theme)}</section>"
        )
    if resume.projects:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["projects"])}</h2>'
            f"{_projects_html(resume, theme)}</section>"
        )
    if resume.education:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["education"])}</h2>'
            f"{_education_html(resume, theme)}</section>"
        )
    if resume.certifications:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["certifications"])}</h2>'
            f"{_certifications_html(resume, theme)}</section>"
        )
    languages = _flat_languages_html(resume, candidate, lang)
    if languages:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["languages"])}</h2>{languages}</section>'
        )
    parts.append("</div>")
    return "".join(parts)


def _render_centered_header(
    resume: TailoredResume,
    candidate: CandidateProfile,
    theme: ResumeTheme,
    labels: dict[str, str],
    lang: str,
) -> str:
    parts: list[str] = []
    parts.append('<div class="page">')
    banner_bits: list[str] = [f'<h1>{_esc(resume.name or "Candidate")}</h1>']
    if resume.role_targeted_for:
        banner_bits.append(
            f'<div class="role">{_esc(resume.role_targeted_for)}</div>'
        )
    contact_inline_parts: list[str] = []
    for ic, txt in _contact_lines(resume, candidate, lang):
        contact_inline_parts.append(
            f'<span><span class="ic">{ic}</span>{txt}</span>'
        )
    for ic, href, label in _online_lines(resume, candidate):
        contact_inline_parts.append(
            f'<span><span class="ic">{ic}</span>'
            f'<a href="{href}">{label}</a></span>'
        )
    if contact_inline_parts:
        banner_bits.append(
            f'<div class="contact-bar">{"".join(contact_inline_parts)}</div>'
        )
    parts.append(f'<div class="banner">{"".join(banner_bits)}</div>')

    parts.append('<div class="body">')
    if resume.professional_summary:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["profile"])}</h2>'
            f'<p class="summary">{_esc(resume.professional_summary)}</p></section>'
        )

    # Skills + languages share a two-column row to break up the heavy banner.
    skills_grid = _grid_skills_html(resume, lang)
    languages_grid = _grid_languages_html(resume, candidate, lang)
    if skills_grid or languages_grid:
        sub_blocks: list[str] = []
        if skills_grid:
            sub_blocks.append(
                f'<section class="block"><h2>{_esc(labels["tech_stack"])}</h2>{skills_grid}</section>'
            )
        if languages_grid:
            sub_blocks.append(
                f'<section class="block"><h2>{_esc(labels["languages"])}</h2>{languages_grid}</section>'
            )
        parts.append(f'<div class="two-col">{"".join(sub_blocks)}</div>')

    if resume.experience:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["experience"])}</h2>'
            f"{_experience_html(resume, theme)}</section>"
        )
    if resume.projects:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["projects"])}</h2>'
            f"{_projects_html(resume, theme)}</section>"
        )
    if resume.education:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["education"])}</h2>'
            f"{_education_html(resume, theme)}</section>"
        )
    if resume.certifications:
        parts.append(
            f'<section class="block"><h2>{_esc(labels["certifications"])}</h2>'
            f"{_certifications_html(resume, theme)}</section>"
        )
    parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _render_resume_body(
    resume: TailoredResume,
    candidate: CandidateProfile,
    theme: ResumeTheme,
    labels: dict[str, str],
    lang: str,
) -> str:
    if theme.layout == "two_column_sidebar":
        return _render_two_column(resume, candidate, theme, labels, lang)
    if theme.layout == "single_column_serif":
        return _render_single_column_serif(resume, candidate, theme, labels, lang)
    if theme.layout == "single_column_minimal":
        return _render_single_column_minimal(resume, candidate, theme, labels, lang)
    if theme.layout == "centered_header_band":
        return _render_centered_header(resume, candidate, theme, labels, lang)
    # Fallback - keep rendering even for an unknown layout literal.
    return _render_two_column(resume, candidate, theme, labels, lang)


# ---------------------------------------------------------------------------
# Public resume entry points
# ---------------------------------------------------------------------------
def tailored_resume_to_styled_html(
    resume: TailoredResume,
    candidate: CandidateProfile | None = None,
    output_language: str = "",
    theme: str | ResumeTheme | None = None,
) -> str:
    """Render a printable A4 HTML resume in the picked visual theme.

    ``output_language`` overrides the diacritic-sniff fallback so the
    section headers stay consistent with what the user picked in the
    output-language dialog. Pass ``""`` to keep the legacy auto-detection
    used by tests that don't have a ``GeneratedApplicationPackage``.

    ``theme`` is one of:

    * ``None`` / unset: the default theme (``teal_sidebar``) ships, which
      is the look every existing test asserts on - keeps backward
      compatibility for snapshot-style tests.
    * a slug string: looked up in :data:`RESUME_THEMES`. ``random``
      picks one uniformly so each call can produce a different look.
    * an explicit :class:`ResumeTheme` instance: bypasses the registry
      lookup, useful for tests + bypassing the random sentinel.
    """
    candidate = candidate or CandidateProfile()
    lang = (output_language or "").strip().lower()
    if lang not in _RESUME_LABELS:
        lang = detect_resume_language(resume)
    labels = _RESUME_LABELS[lang]

    if isinstance(theme, ResumeTheme):
        chosen = theme
    else:
        chosen = resolve_theme(theme or DEFAULT_THEME_SLUG)

    title = resume.name or "Resume"
    body = _render_resume_body(resume, candidate, chosen, labels, lang)
    css = _theme_css(chosen)
    return (
        '<!doctype html>\n'
        f'<html lang="{lang}"><head><meta charset="utf-8"/>'
        f"<title>{_esc(title)}</title>"
        f"<style>{css}</style></head>"
        f"<body>{body}</body></html>"
    )


# ---------------------------------------------------------------------------
# Cover letter (uses the same theme so the two documents look like a set)
# ---------------------------------------------------------------------------
def _cover_letter_css(theme: ResumeTheme) -> str:
    """Theme-aware CSS for the cover letter print-ready HTML.

    Single-column letter format (A4) regardless of ``theme.layout`` so
    the cover letter always reads naturally; the theme's accent colour
    drives the header band, the candidate name, and the closing line so
    the document still visually matches the resume.
    """
    return f"""
{_CSS_BASE_PAGE}
html,body{{font-family:{theme.body_font};color:{theme.text_primary};background:#FFFFFF;line-height:1.6;font-size:11pt}}
.page{{max-width:210mm;min-height:297mm;margin:0 auto;background:#FFFFFF;padding:0}}
.header{{background:linear-gradient(135deg,{theme.accent} 0%,{theme.accent_dark} 100%);color:{theme.on_accent};padding:18mm 22mm 14mm 22mm}}
.header h1{{font-family:{theme.heading_font};font-size:24pt;font-weight:800;letter-spacing:-0.01em;margin-bottom:3mm}}
.header .contact-bar{{display:flex;flex-wrap:wrap;gap:5mm;font-size:10pt;color:rgba(255,255,255,0.92)}}
.header .contact-bar a{{color:{theme.on_accent};text-decoration:none;border-bottom:1px dotted rgba(255,255,255,0.5)}}
.header .contact-bar .ic{{color:{theme.accent_soft};margin-right:1mm}}
.body{{padding:14mm 22mm 18mm 22mm}}
.salutation{{font-size:11pt;font-weight:600;color:{theme.text_primary};margin-bottom:6mm}}
.body p{{font-size:11pt;color:{theme.text_primary};line-height:1.65;margin-bottom:5mm;text-align:justify}}
.signoff{{margin-top:7mm;font-size:11pt;color:{theme.text_primary}}}
.signoff .closing{{margin-bottom:8mm}}
.signoff .signature{{font-family:{theme.heading_font};font-weight:700;color:{theme.accent_dark};font-size:12pt}}
""".strip()


def cover_letter_to_styled_html(
    cover: CoverLetter,
    candidate: CandidateProfile | None = None,
    *,
    theme: str | ResumeTheme | None = None,
    output_language: str = "",
) -> str:
    """Render the cover letter as a print-ready HTML document.

    The header band carries the candidate's name + contact bar in the
    theme's accent colour so the cover letter feels like a sibling of
    the resume PDF. The body is always single-column for readability,
    no matter which resume layout the theme uses.

    ``output_language`` is currently informational (the cover letter
    text itself comes pre-translated from the AI provider); it sets the
    ``<html lang>`` attribute so screen readers / PDF tools pick up the
    right hyphenation rules.
    """
    candidate = candidate or CandidateProfile()
    if isinstance(theme, ResumeTheme):
        chosen = theme
    else:
        chosen = resolve_theme(theme or DEFAULT_THEME_SLUG)
    css = _cover_letter_css(chosen)
    lang = (output_language or "en").strip().lower()
    name = candidate.full_name or cover.signature or "Candidate"

    contact_bits: list[str] = []
    if candidate.location:
        contact_bits.append(
            f'<span><span class="ic">{_ICON_LOCATION}</span>'
            f'{_esc(candidate.location)}</span>'
        )
    if candidate.contact_email:
        contact_bits.append(
            f'<span><span class="ic">{_ICON_EMAIL}</span>'
            f'{_esc(candidate.contact_email)}</span>'
        )
    if candidate.phone:
        contact_bits.append(
            f'<span><span class="ic">{_ICON_PHONE}</span>'
            f'{_esc(candidate.phone)}</span>'
        )
    if candidate.linkedin_url:
        contact_bits.append(
            f'<span><span class="ic">in</span>'
            f'<a href="{_esc(candidate.linkedin_url)}">{_esc(candidate.linkedin_url)}</a></span>'
        )

    contact_bar = (
        f'<div class="contact-bar">{"".join(contact_bits)}</div>'
        if contact_bits else ""
    )

    paragraphs_html = "".join(
        f"<p>{_esc(para)}</p>" for para in cover.paragraphs if para
    )

    closing_html = ""
    if cover.closing or cover.signature:
        closing_html = (
            '<div class="signoff">'
            + (f'<div class="closing">{_esc(cover.closing)}</div>' if cover.closing else "")
            + (f'<div class="signature">{_esc(cover.signature)}</div>' if cover.signature else "")
            + "</div>"
        )

    body_inner = (
        (f'<div class="salutation">{_esc(cover.salutation)}</div>' if cover.salutation else "")
        + paragraphs_html
        + closing_html
    )

    return (
        '<!doctype html>\n'
        f'<html lang="{lang}"><head><meta charset="utf-8"/>'
        f'<title>{_esc(name)} - Cover letter</title>'
        f"<style>{css}</style></head>"
        '<body><div class="page">'
        f'<div class="header"><h1>{_esc(name)}</h1>{contact_bar}</div>'
        f'<div class="body">{body_inner}</div>'
        "</div></body></html>"
    )


__all__ = [
    "ResumeTheme",
    "ThemeLayout",
    "Palette",
    "PALETTES",
    "LAYOUTS",
    "RESUME_THEMES",
    "RANDOM_THEME_SLUG",
    "DEFAULT_THEME_SLUG",
    "theme_choices",
    "resolve_theme",
    "pick_different_layout",
    "pick_different_palette",
    "resume_labels",
    "detect_resume_language",
    "tailored_resume_to_styled_html",
    "cover_letter_to_styled_html",
]
