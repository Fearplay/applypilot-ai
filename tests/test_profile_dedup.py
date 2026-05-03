"""Tests for the deterministic profile dedup safety net.

These tests cover the scenarios described in the implementation plan:

* the AI emitted the same education entry once in English and once in Czech;
* the AI emitted the same role twice with the company spelled differently
  (with and without the legal suffix);
* normalization correctly maps "ČZU" / "Czech University of Life Sciences";
* entries with no parsable date but matching names still merge;
* sources combine into ``both`` whenever the original entries came from
  different inputs;
* a ``Gen Digital · Trust Based Solutions ...`` entry merges with a bare
  ``Gen`` entry once brand parentheticals are stripped (loosened heuristic);
* date conflicts between the CV and LinkedIn for the same merged entry
  produce a ``discrepancy:date:<id>`` clarifying question listing both
  periods plus an "Other" fallthrough.
"""
from __future__ import annotations

from src.models.candidate import (
    CandidateProfile,
    CertificationEntry,
    EducationEntry,
    WorkExperience,
)
from src.services.profile_dedup import (
    _canonicalise_language_name,
    _dedup_certifications,
    _dedup_languages,
    _is_combined_company,
    _names_match,
    _normalize_cert_name,
    _normalize_name,
    _parse_year_range,
    _periods_are_equivalent,
    _split_combined_company,
    _structural_choice_kind,
    apply_structural_choice,
    build_date_conflict_questions,
    build_source_discrepancy_questions,
    build_structural_mismatch_questions,
    dedup_profile,
    detect_structural_mismatches,
    excluded_ids_from_answers,
    filter_profile_entries,
)
from src.models.match import ClarifyingAnswer


# ---------------------------------------------------------------------------
# Normalization unit tests
# ---------------------------------------------------------------------------

def test_normalize_name_strips_diacritics_and_legal_suffixes():
    assert _normalize_name("Acme s.r.o.") == "acme"
    assert _normalize_name("Acme A.S.") == "acme"
    assert _normalize_name("Demo Ltd.") == "demo"


def test_normalize_name_handles_university_synonyms():
    cz = _normalize_name("Provozně ekonomická fakulta ČZU v Praze")
    en = _normalize_name(
        "Faculty of Economics and Management, Czech University of Life "
        "Sciences Prague"
    )
    # The CZ version normalises to "provozne ekonomicka czu v praze". The EN
    # version normalises to "economics and management czech life sciences
    # prague". They still share the strong signal "czech ... prague" and the
    # AI is expected to mark both as the same row anyway. We only assert
    # that the helper drops the diacritics + stop tokens.
    assert "fakulta" not in cz
    assert "univerzita" not in cz
    assert "university" not in en
    assert "of" not in en.split()


def test_parse_year_range_extracts_first_and_last_year():
    assert _parse_year_range("Jan 2021 - Jul 2023") == (2021, 2023)
    assert _parse_year_range("2017 - 2021") == (2017, 2021)
    assert _parse_year_range("2024") == (2024, 2024)


def test_parse_year_range_handles_present():
    rng = _parse_year_range("2022 - Present")
    assert rng is not None
    assert rng[0] == 2022
    assert rng[1] >= 2022  # current year, anything >= start is fine.


def test_parse_year_range_returns_none_for_missing_dates():
    assert _parse_year_range("") is None
    assert _parse_year_range("ongoing") is None


def test_names_match_is_case_and_diacritics_insensitive():
    assert _names_match("Acme s.r.o.", "ACME S.R.O.")
    assert _names_match("ČZU v Praze", "czu praze")


# ---------------------------------------------------------------------------
# Experience dedup
# ---------------------------------------------------------------------------

def test_dedup_collapses_same_role_in_two_languages():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Senior Python Developer",
                company="Acme s.r.o.",
                period="2021 - 2024",
                bullets=["Built billing service in Django."],
                technologies=["Python", "Django"],
                source="cv",
            ),
            WorkExperience(
                id="exp-1",
                title="Senior Python Developer",
                company="ACME",
                period="2021 - 2024",
                bullets=["Postavil fakturační službu v Djangu."],
                technologies=["Python", "PostgreSQL"],
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)

    assert len(deduped.experience) == 1
    merged = deduped.experience[0]
    assert merged.source == "both"
    assert "Python" in merged.technologies
    assert "PostgreSQL" in merged.technologies
    assert len(merged.bullets) == 2  # both languages preserved verbatim


def test_dedup_keeps_distinct_roles():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="QA Engineer",
                company="Acme",
                period="2020 - 2021",
                source="cv",
            ),
            WorkExperience(
                id="exp-1",
                title="QA Engineer",
                company="OtherCorp",
                period="2021 - 2023",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.experience) == 2


def test_dedup_keeps_distinct_periods():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="QA Engineer",
                company="Acme",
                period="2018 - 2019",
                source="cv",
            ),
            WorkExperience(
                id="exp-1",
                title="QA Engineer",
                company="Acme",
                period="2022 - 2023",
                source="cv",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.experience) == 2  # no year overlap, so no merge


def test_dedup_propagates_employment_type_when_one_is_unknown():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Intern",
                company="Acme",
                period="2020",
                employment_type="internship",
                source="linkedin",
            ),
            WorkExperience(
                id="exp-1",
                title="Intern",
                company="Acme",
                period="2020",
                employment_type="unknown",
                source="cv",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.experience) == 1
    assert deduped.experience[0].employment_type == "internship"


# ---------------------------------------------------------------------------
# Education dedup
# ---------------------------------------------------------------------------

def test_dedup_collapses_same_university_with_shared_identifier():
    """When the institution name shares a strong token (the abbreviation
    'ČZU' / 'czu') the Python safety net merges the rows even if the rest
    of the text differs across languages.

    The harder cross-language case where names share NO common tokens
    (e.g. "Czech University of Life Sciences Prague" vs "ČZU v Praze") is
    handled by the AI prompt rules in `analyze_candidate_user_prompt` and
    by the discrepancy clarifying question, NOT by this Python pass.
    """
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="ČZU Prague",
                degree="Computer Science studies",
                period="2021 - 2024",
                source="cv",
            ),
            EducationEntry(
                id="edu-1",
                institution="Provozně ekonomická fakulta ČZU v Praze",
                degree="Bakalář (Bc.), Informatika",
                period="January 2021 - July 2023",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)

    assert len(deduped.education) == 1
    merged = deduped.education[0]
    assert merged.source == "both"
    assert merged.degree


def test_dedup_does_not_force_merge_for_unrelated_token_sets():
    """Two institution names with no token overlap should remain separate -
    the AI prompt and the discrepancy question handle that branch."""
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="MIT",
                period="2018 - 2020",
                source="cv",
            ),
            EducationEntry(
                id="edu-1",
                institution="Stanford University",
                period="2018 - 2020",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)

    assert len(deduped.education) == 2


def test_dedup_assigns_ids_when_missing():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(title="Dev", company="Acme", period="2020 - 2021"),
            WorkExperience(title="QA", company="Other", period="2021 - 2022"),
        ],
        education=[
            EducationEntry(institution="MIT", period="2018 - 2020"),
        ],
    )

    deduped = dedup_profile(profile)

    assert all(e.id for e in deduped.experience)
    assert all(e.id for e in deduped.education)
    assert deduped.experience[0].id != deduped.experience[1].id


# ---------------------------------------------------------------------------
# Excluded-id helpers used by main_window
# ---------------------------------------------------------------------------

def test_excluded_ids_from_answers_extracts_no_skip_answers():
    answers = [
        ClarifyingAnswer(question_id="discrepancy:exp-3", answer="No - skip it"),
        ClarifyingAnswer(question_id="discrepancy:edu-0", answer="Yes - include it"),
        ClarifyingAnswer(question_id="q1", answer="No"),  # not a discrepancy q
    ]

    excluded = excluded_ids_from_answers(answers)
    assert excluded == {"exp-3"}


def test_filter_profile_entries_drops_excluded_rows():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(id="exp-0", title="A", company="Acme", period="2020"),
            WorkExperience(id="exp-1", title="B", company="Other", period="2021"),
        ],
        education=[
            EducationEntry(id="edu-0", institution="MIT"),
            EducationEntry(id="edu-1", institution="Stanford"),
        ],
    )

    filtered = filter_profile_entries(profile, {"exp-1", "edu-0"})

    assert [e.id for e in filtered.experience] == ["exp-0"]
    assert [e.id for e in filtered.education] == ["edu-1"]
    # Source profile is untouched (model_copy is shallow but lists are new).
    assert len(profile.experience) == 2
    assert len(profile.education) == 2


def test_filter_profile_entries_returns_same_object_when_nothing_excluded():
    profile = CandidateProfile(
        full_name="Test",
        experience=[WorkExperience(id="exp-0", title="A", company="Acme")],
    )

    filtered = filter_profile_entries(profile, set())

    # Tiny perf optimisation: when the exclusion set is empty we don't
    # bother allocating a new model.
    assert filtered is profile


# ---------------------------------------------------------------------------
# Loosened heuristic: brand parentheticals & cross-language place names
# ---------------------------------------------------------------------------

def test_names_match_collapses_gen_digital_brand_parenthetical_with_short_name():
    """The full LinkedIn name `Gen Digital · Trust Based Solutions (Norton ·
    Avast · AVG · CCleaner · LifeLock)` must merge with a CV entry that
    just says `Gen`. The bullet/parenthetical noise is stripped, and the
    short name is then a substring of the long name."""
    long_name = (
        "Gen Digital · Trust Based Solutions "
        "(Norton · Avast · AVG · CCleaner · LifeLock)"
    )
    short_name = "Gen"
    assert _names_match(long_name, short_name)


def test_dedup_collapses_same_role_with_brand_parentheticals_in_one_input():
    """Variant of the QA-engineer example from the user message: the CV uses
    the full Gen Digital brand listing, LinkedIn just says ``Gen``. After
    dedup we should see ONE merged role with ``source='both'``."""
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Senior Software QA Engineer",
                company=(
                    "Gen Digital · Trust Based Solutions "
                    "(Norton · Avast · AVG · CCleaner · LifeLock)"
                ),
                period="07/2025 - present",
                source="cv",
            ),
            WorkExperience(
                id="exp-1",
                title="Senior Software QA Engineer",
                company="Gen",
                period="July 2025 - Present",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)

    assert len(deduped.experience) == 1
    merged = deduped.experience[0]
    assert merged.source == "both"


def test_normalize_name_maps_prague_to_praha_across_languages():
    cz = _normalize_name("ČZU v Praze")
    en = _normalize_name("Czech University Prague")
    # Both forms land on the canonical 'praha' token thanks to the
    # cross-language equivalence map.
    assert "praha" in cz.split()
    assert "praha" in en.split()


def test_dedup_does_not_merge_unrelated_prague_universities():
    """Two real Prague universities must NOT collapse just because they
    share the city token. The threshold and substring rules keep them
    apart so the user still gets two entries."""
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="Univerzita Karlova v Praze",
                degree="Mgr.",
                period="2018 - 2020",
                source="cv",
            ),
            EducationEntry(
                id="edu-1",
                institution="Fakulta strojní ČVUT v Praze",
                degree="Ing.",
                period="2018 - 2020",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.education) == 2


# ---------------------------------------------------------------------------
# Date-conflict questions
# ---------------------------------------------------------------------------

def test_dedup_records_date_conflict_in_notes():
    """When CV and LinkedIn agree on the role but disagree on the dates,
    the merged row records both periods in ``notes`` so the GUI can ask
    the user which one is correct."""
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Senior Python Developer",
                company="Acme",
                period="2021 - 2024",
                source="cv",
            ),
            WorkExperience(
                id="exp-1",
                title="Senior Python Developer",
                company="Acme",
                period="2021 - 2023",
                source="linkedin",
            ),
        ],
    )

    deduped = dedup_profile(profile)

    assert len(deduped.experience) == 1
    merged = deduped.experience[0]
    assert merged.source == "both"
    assert merged.notes is not None
    assert "CV: 2021 - 2024" in merged.notes
    assert "LinkedIn: 2021 - 2023" in merged.notes


def test_build_date_conflict_questions_for_experience():
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Senior Python Developer",
                company="Acme",
                period="2021 - 2024",
                source="both",
                notes="CV: 2021 - 2024 | LinkedIn: 2021 - 2023",
            ),
        ],
    )

    questions = build_date_conflict_questions(profile)

    assert len(questions) == 1
    q = questions[0]
    assert q.id == "discrepancy:date:exp-0"
    assert q.answer_type == "single_choice"
    # Both periods are offered as explicit options + an "Other" fall-through.
    assert "2021 - 2024" in q.options
    assert "2021 - 2023" in q.options
    assert any("ther" in opt.lower() or "iné" in opt.lower() for opt in q.options)


def test_build_date_conflict_questions_for_education_uses_dedup_notes():
    """The education flow mirrors experience but the source comes from
    the AI's own ``notes`` field (the prompt already instructs the model
    to write the conflict there)."""
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="Czech University of Life Sciences Prague",
                degree="Bc.",
                period="2021 - 2024",
                source="both",
                notes="CV: 2021 - 2024 | LinkedIn: 2021 - 2023",
            ),
        ],
    )

    questions = build_date_conflict_questions(profile)
    assert len(questions) == 1
    assert questions[0].id == "discrepancy:date:edu-0"


def test_build_date_conflict_questions_skips_matching_periods():
    """When the CV and LinkedIn periods written into notes happen to be
    identical we don't bother the user with a question."""
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Engineer",
                company="Acme",
                period="2021 - 2024",
                source="both",
                notes="CV: 2021 - 2024 | LinkedIn: 2021 - 2024",
            ),
        ],
    )

    assert build_date_conflict_questions(profile) == []


def test_excluded_ids_does_not_pull_in_date_discrepancy_answers():
    """Date-conflict answers select a period; they must NEVER be treated
    as an instruction to drop the row, regardless of which option the
    user picked."""
    answers = [
        ClarifyingAnswer(
            question_id="discrepancy:date:exp-0", answer="2021 - 2024"
        ),
        ClarifyingAnswer(
            question_id="discrepancy:date:edu-0", answer="No - skip it"
        ),
    ]

    excluded = excluded_ids_from_answers(answers)
    assert excluded == set()


# ---------------------------------------------------------------------------
# CV-vs-LinkedIn cross-language ČZU example (documents the limit)
# ---------------------------------------------------------------------------

def test_dedup_merges_czech_english_university_pair_with_overlapping_years():
    """The user's bug: CV (English) and LinkedIn (Czech) describe the
    SAME university with overlapping year ranges. After expanding the
    cross-language token equivalence map (``ekonomicka`` <-> ``economics``,
    ``informatika`` <-> ``informatics``) the strict heuristic catches this
    pair and the profile shows ONE entry, with the date discrepancy
    captured in ``notes`` for the GUI to surface to the user.
    """
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="Provozně ekonomická fakulta ČZU v Praze",
                degree="Bakalář (Bc.), Informatika",
                period="ledna 2021 - července 2023",
                source="linkedin",
            ),
            EducationEntry(
                id="edu-1",
                institution=(
                    "Faculty of Economics and Management, "
                    "Czech University of Life Sciences Prague"
                ),
                degree="Computer Science studies",
                period="2021 - 2024",
                source="cv",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.education) == 1
    merged = deduped.education[0]
    assert merged.source == "both"
    assert merged.notes and "CV" in merged.notes and "LinkedIn" in merged.notes


# ---------------------------------------------------------------------------
# Cross-language education merge via expanded token equivalence map
# ---------------------------------------------------------------------------

def test_dedup_education_merges_user_bug_pair_via_token_equivalences():
    """The user's actual case from the duplicate-resume bug: CV (English)
    and LinkedIn (Czech) describe the same Prague university with NO
    direct token overlap. After adding ``ekonomicka`` <-> ``economics``
    and ``informatika`` <-> ``informatics`` to the cross-language token
    equivalence map, both names normalise to share enough tokens
    (``economics`` + ``praha``) that the strict heuristic merges them.
    """
    profile = CandidateProfile(
        full_name="Test",
        education=[
            EducationEntry(
                id="edu-0",
                institution="Provozně ekonomická fakulta ČZU v Praze",
                degree="Bakalář (Bc.), Informatika",
                period="2021 - 2023",
                source="linkedin",
            ),
            EducationEntry(
                id="edu-1",
                institution=(
                    "Faculty of Economics and Management, "
                    "Czech University of Life Sciences Prague"
                ),
                degree="Computer Science studies",
                period="2021 - 2024",
                source="cv",
            ),
        ],
    )

    deduped = dedup_profile(profile)
    assert len(deduped.education) == 1
    assert deduped.education[0].source == "both"
    # Date conflict (2023 vs 2024) is preserved in notes for the GUI.
    assert "CV" in (deduped.education[0].notes or "")
    assert "LinkedIn" in (deduped.education[0].notes or "")


# ---------------------------------------------------------------------------
# build_date_conflict_questions: skip when year ranges already match
# ---------------------------------------------------------------------------

def test_periods_are_equivalent_recognises_year_range_match():
    assert _periods_are_equivalent(
        "06/2023 - 07/2025",
        "\u010Dervna 2023 - \u010Dervence 2025",
    )
    assert _periods_are_equivalent("2021 - 2023", "ledna 2021 - prosince 2023")
    assert not _periods_are_equivalent("2021 - 2024", "2021 - 2023")


def test_build_date_conflict_questions_skips_when_year_ranges_match():
    """The screenshot showed the user being asked about the SAME period
    written two ways ('06/2023 - 07/2025' vs 'června 2023 - července
    2025'). Year-range comparison must short-circuit that question.
    """
    profile = CandidateProfile(
        full_name="Test",
        experience=[
            WorkExperience(
                id="exp-0",
                title="Senior QA Engineer",
                company="Gen Digital",
                period="06/2023 - 07/2025",
                source="both",
                notes=(
                    "CV: 06/2023 - 07/2025 | "
                    "LinkedIn: \u010Dervna 2023 - \u010Dervence 2025"
                ),
            ),
        ],
    )

    assert build_date_conflict_questions(profile) == []


# ---------------------------------------------------------------------------
# Certifications dedup
# ---------------------------------------------------------------------------

def test_normalize_cert_name_strips_issuer_prefix_and_year():
    assert _normalize_cert_name("Oracle Academy - Java Programming · 2021") == \
        "java programming"
    assert _normalize_cert_name("Engeto - Python Academy (12-week) · 2020") == \
        "python academy 12 week"
    assert _normalize_cert_name("Java Programming") == "java programming"


def test_dedup_certifications_collapses_oracle_academy_prefix_pair():
    """The bug from the user's resume: ``Java Programming`` and
    ``Oracle Academy - Java Programming`` showed up as two cert rows.
    """
    entries = [
        CertificationEntry(
            name="Oracle Academy - Java Programming",
            issuer="Oracle Academy",
            year="2021",
        ),
        CertificationEntry(name="Java Programming"),
    ]
    deduped = _dedup_certifications(entries)
    assert len(deduped) == 1
    # Keeps the longer, more specific name.
    assert "Oracle Academy" in deduped[0].name
    assert deduped[0].issuer == "Oracle Academy"
    assert deduped[0].year == "2021"


def test_dedup_certifications_collapses_python_akademie_pair():
    entries = [
        CertificationEntry(
            name="Engeto - Python Academy (12-week)",
            issuer="Engeto",
            year="2020",
        ),
        CertificationEntry(name="Python Akademie"),
    ]
    deduped = _dedup_certifications(entries)
    assert len(deduped) == 1
    assert deduped[0].issuer == "Engeto"


def test_dedup_certifications_keeps_distinct_courses():
    entries = [
        CertificationEntry(name="Oracle Academy - Java Programming", year="2021"),
        CertificationEntry(name="Oracle Academy - Database Foundations", year="2020"),
    ]
    deduped = _dedup_certifications(entries)
    assert len(deduped) == 2


def test_dedup_certifications_drops_blank_names():
    entries = [
        CertificationEntry(name=""),
        CertificationEntry(name="Real Course"),
    ]
    deduped = _dedup_certifications(entries)
    assert [c.name for c in deduped] == ["Real Course"]


# ---------------------------------------------------------------------------
# Spoken languages dedup
# ---------------------------------------------------------------------------

def test_canonicalise_language_name_maps_czech_synonyms_to_english_label():
    assert _canonicalise_language_name("\u010De\u0161tina") == "Czech"
    assert _canonicalise_language_name("Czech") == "Czech"
    assert _canonicalise_language_name("angli\u010Dtina") == "English"
    assert _canonicalise_language_name("n\u011Bm\u010Dina") == "German"
    assert _canonicalise_language_name("slovak") == "Slovak"
    # Unknown languages are returned verbatim so we don't silently drop them.
    assert _canonicalise_language_name("Klingon") == "Klingon"


def test_dedup_languages_collapses_czech_cestina_and_english_anglictina():
    """The bug from the user's resume: the sidebar listed Czech twice
    ('Czech' + 'čeština') and English twice ('English' + 'angličtina').
    """
    raw = [
        "Czech",
        "English",
        "Slovak",
        "German",
        "\u010De\u0161tina",
        "angli\u010Dtina",
        "n\u011Bm\u010Dina",
    ]
    deduped = _dedup_languages(raw)
    assert deduped == ["Czech", "English", "Slovak", "German"]


def test_dedup_languages_preserves_level_annotation():
    raw = ["Czech (mate\u0159sk\u00FD)", "\u010De\u0161tina"]
    deduped = _dedup_languages(raw)
    assert len(deduped) == 1
    assert "Czech" in deduped[0]
    assert "mate\u0159sk\u00FD" in deduped[0]


def test_dedup_languages_picks_richest_level_when_multiple_provided():
    raw = ["English (B2)", "angli\u010Dtina (C1 - native)"]
    deduped = _dedup_languages(raw)
    assert len(deduped) == 1
    # The "C1 - native" annotation is longer and therefore more informative.
    assert "C1 - native" in deduped[0]


def test_dedup_languages_drops_blanks_and_pure_whitespace():
    deduped = _dedup_languages(["", "  ", "Czech"])
    assert deduped == ["Czech"]


# ---------------------------------------------------------------------------
# dedup_profile: end-to-end with cert + language fields
# ---------------------------------------------------------------------------

def test_dedup_profile_collapses_certifications_and_languages():
    profile = CandidateProfile(
        full_name="Test",
        certifications=[
            CertificationEntry(name="Oracle Academy - Java Programming", year="2021"),
            CertificationEntry(name="Java Programming"),
            CertificationEntry(name="Engeto - Python Academy", year="2020"),
            CertificationEntry(name="Python Akademie"),
        ],
        spoken_languages=[
            "Czech", "English", "\u010De\u0161tina", "angli\u010Dtina",
        ],
    )
    deduped = dedup_profile(profile)
    assert len(deduped.certifications) == 2
    assert deduped.spoken_languages == ["Czech", "English"]


# ---------------------------------------------------------------------------
# Structural mismatch (CV combines N companies vs LinkedIn splits them)
# ---------------------------------------------------------------------------

def test_split_combined_company_handles_interpunct_separator():
    assert _split_combined_company("CreatiWeb · AppYours · IBM") == [
        "CreatiWeb", "AppYours", "IBM",
    ]


def test_split_combined_company_handles_comma_and_pipe():
    assert _split_combined_company("Acme, Globex | Initech") == [
        "Acme", "Globex", "Initech",
    ]


def test_split_combined_company_returns_single_for_normal_name():
    assert _split_combined_company("Gen Digital s.r.o.") == ["Gen Digital s.r.o."]


def test_is_combined_company_detects_multi_brand_string():
    assert _is_combined_company("CreatiWeb · AppYours · IBM")
    assert not _is_combined_company("Microsoft")
    # Trademarks like "C++" must not split on the bare "+".
    assert not _is_combined_company("C++ Studio")


def _make_combined_cv_and_linkedin_profile() -> CandidateProfile:
    """Reproduce the user's CreatiWeb / IBM scenario.

    CV row (source='cv'): 'CreatiWeb · AppYours · IBM (school internships) 2019-2020'
    LinkedIn rows (source='linkedin'): 'CreatiWeb' 2020 + 'IBM' 2019
    """
    cv = WorkExperience(
        id="exp-cv-combined",
        title="Developer (Python · Chatbot · Game dev)",
        company="CreatiWeb · AppYours · IBM",
        period="2019 - 2020",
        bullets=["Python game dev", "IBM Watson chatbot"],
        source="cv",
    )
    li_creatiweb = WorkExperience(
        id="exp-li-creatiweb",
        title="Vývojář Python",
        company="CreatiWeb s.r.o.",
        period="06/2020 - 08/2020",
        bullets=["Přepis .PO souborů"],
        source="linkedin",
    )
    li_ibm = WorkExperience(
        id="exp-li-ibm",
        title="Stážista vývojář",
        company="IBM",
        period="05/2019 - 06/2019",
        bullets=["Vývoj chatbota v IBM Watson"],
        source="linkedin",
    )
    return CandidateProfile(
        full_name="Test",
        experience=[cv, li_creatiweb, li_ibm],
    )


def test_detect_structural_mismatches_finds_creatiweb_ibm_pair():
    profile = _make_combined_cv_and_linkedin_profile()
    findings = detect_structural_mismatches(profile)
    assert len(findings) == 1
    cv, linkedin_rows = findings[0]
    assert cv.id == "exp-cv-combined"
    matched_ids = sorted(li.id for li in linkedin_rows)
    assert matched_ids == ["exp-li-creatiweb", "exp-li-ibm"]


def test_detect_structural_mismatches_skips_when_only_one_match():
    """A single-company CV row with one matching LinkedIn row is the regular
    duplicate scenario - the existing date-conflict question covers it."""
    cv = WorkExperience(
        id="exp-cv",
        title="Dev",
        company="Acme · Beta",
        period="2020 - 2021",
        source="cv",
    )
    li = WorkExperience(
        id="exp-li",
        title="Dev",
        company="Acme",
        period="2020 - 2021",
        source="linkedin",
    )
    profile = CandidateProfile(full_name="X", experience=[cv, li])
    assert detect_structural_mismatches(profile) == []


def test_build_structural_mismatch_questions_emits_struct_id():
    profile = _make_combined_cv_and_linkedin_profile()
    questions = build_structural_mismatch_questions(profile)
    assert len(questions) == 1
    q = questions[0]
    assert q.id == "discrepancy:struct:exp-cv-combined"
    assert q.answer_type == "single_choice"
    # Three options: split / merge / manual (text varies by UI language but
    # we always have exactly three).
    assert len(q.options) == 3


def test_structural_choice_kind_classifies_split_merge_manual():
    assert _structural_choice_kind("Split into separate entries") == "split"
    assert _structural_choice_kind("Rozdělit na samostatné záznamy") == "split"
    assert _structural_choice_kind("Keep as one combined entry") == "merge"
    assert _structural_choice_kind("Nechat jako jeden společný záznam") == "merge"
    assert _structural_choice_kind("Other - I'll edit") == "manual"
    assert _structural_choice_kind("Jiné") == "manual"
    assert _structural_choice_kind("") == "manual"


def test_apply_structural_choice_split_drops_combined_cv_row():
    profile = _make_combined_cv_and_linkedin_profile()
    apply_structural_choice(profile, "exp-cv-combined", "Split into separate entries")
    ids = [e.id for e in profile.experience]
    assert "exp-cv-combined" not in ids
    assert sorted(ids) == ["exp-li-creatiweb", "exp-li-ibm"]


def test_apply_structural_choice_merge_drops_linkedin_rows():
    profile = _make_combined_cv_and_linkedin_profile()
    apply_structural_choice(profile, "exp-cv-combined", "Keep as one combined entry")
    ids = [e.id for e in profile.experience]
    assert ids == ["exp-cv-combined"]


def test_apply_structural_choice_manual_is_noop():
    profile = _make_combined_cv_and_linkedin_profile()
    apply_structural_choice(profile, "exp-cv-combined", "Other - I'll edit later")
    ids = sorted(e.id for e in profile.experience)
    assert ids == ["exp-cv-combined", "exp-li-creatiweb", "exp-li-ibm"]


def test_apply_structural_choice_unknown_id_is_safe_noop():
    profile = _make_combined_cv_and_linkedin_profile()
    apply_structural_choice(profile, "no-such-id", "split")
    ids = sorted(e.id for e in profile.experience)
    assert ids == ["exp-cv-combined", "exp-li-creatiweb", "exp-li-ibm"]
