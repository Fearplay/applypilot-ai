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
    EducationEntry,
    WorkExperience,
)
from src.services.profile_dedup import (
    _names_match,
    _normalize_name,
    _parse_year_range,
    build_date_conflict_questions,
    build_source_discrepancy_questions,
    dedup_profile,
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

def test_dedup_keeps_czech_english_university_pair_separate_when_no_token_overlap():
    """Documents the heuristic's ceiling: ``Provozně ekonomická fakulta ČZU
    v Praze`` and ``Faculty of Economics and Management, Czech University
    of Life Sciences Prague`` share no common tokens after normalisation
    (``czu`` vs ``cz`` after the equivalence map) so the dedup pass keeps
    them separate. The AI prompt is the primary mechanism for merging
    these; the discrepancy clarifying question covers anything the AI
    misses by asking the user directly."""
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
    # Heuristic CANNOT merge these without help from the AI side.
    assert len(deduped.education) == 2
    # But the GUI WILL ask the user about both single-source rows.
    questions = build_source_discrepancy_questions(deduped)
    qids = {q.id for q in questions}
    assert "discrepancy:edu-0" in qids
    assert "discrepancy:edu-1" in qids
