"""Tests: src/nlp/skill_matcher.py

Skill matching is the foundation of Week 6 (matching engine) and Week 7
(scoring), so these tests lock in the invariants: alias resolution,
case-insensitivity, word-boundary behavior, and the explicit/inferred
evidence split by section. Tests need the seeded taxonomy, so they
skip when MySQL is unreachable.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.nlp.skill_matcher import SkillIndex, SkillHit, match  # noqa: E402


@pytest.fixture(scope="module")
def idx():
    try:
        from src.nlp.skill_matcher import load_skill_index
        return load_skill_index()
    except Exception as e:
        pytest.skip(f"Skill index unavailable (MySQL down?): {e}")


def test_index_has_skills_and_aliases(idx: SkillIndex):
    assert len(idx) == 38, f"expected 38 canon skills, got {len(idx)}"
    assert idx.patterns, "no patterns compiled"


def test_canonical_name_match_explicit(idx: SkillIndex):
    hits = match("I know SQL and Python", "skills", idx)
    ids = {h.canonical_id for h in hits}
    assert "sql" in ids and "python" in ids
    # Skills section -> explicit evidence.
    assert all(h.evidence == "explicit" for h in hits)


def test_alias_resolution_tsql(idx: SkillIndex):
    """'T-SQL' should resolve to the canonical 'sql' skill via Skill_Alias."""
    hits = match("Used T-SQL for ETL", "experience", idx)
    ids = {h.canonical_id: h for h in hits}
    assert "sql" in ids, "T-SQL alias did not resolve to sql"
    # Non-skills section -> inferred.
    assert ids["sql"].evidence == "inferred"


def test_alias_pbi(idx: SkillIndex):
    hits = match("Built PBI dashboards", "experience", idx)
    assert "power_bi" in {h.canonical_id for h in hits}


def test_word_boundaries_no_false_match_letter_r(idx: SkillIndex):
    """The single letter 'r' must not match the 'R' language skill inside
    words like 'parser'/'router'/'organizer'."""
    hits = match("parser and router are fine", "skills", idx)
    cids = {h.canonical_id for h in hits}
    assert "r_language" not in cids


def test_word_boundary_punctuation(idx: SkillIndex):
    """Skill adjacent to punctuation should still match."""
    hits = match("Skills: SQL,Python,Power BI.", "skills", idx)
    cids = {h.canonical_id for h in hits}
    assert {"sql", "python", "power_bi"} <= cids


def test_empty_text(idx: SkillIndex):
    assert match("", "skills", idx) == []
    assert match(None, "experience", idx) == []  # type: ignore[arg-type]


def test_no_duplicate_per_canonical(idx: SkillIndex):
    """Both alias AND canonical-name should yield ONE hit per skill."""
    hits = match("SQL and T-SQL together", "skills", idx)
    sql_hits = [h for h in hits if h.canonical_id == "sql"]
    assert len(sql_hits) == 1


def test_evidence_section_split(idx: SkillIndex):
    """Same skill in skills section vs experience gets correct evidence."""
    explicit = match("Python", "skills", idx)
    inferred = match("Python", "experience", idx)
    assert explicit and explicit[0].evidence == "explicit"
    assert inferred and inferred[0].evidence == "inferred"
