"""Tests: src/data_ingestion/synthetic_jd.py + src/nlp/jd_parser.py.

Pins the Week-5 JD pipeline invariants: generator determinism + balance,
parser role classification, years extraction, and that the parser recovers
required skills from rendered JD text.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.config import path  # noqa: E402
from src.data_ingestion.synthetic_jd import JDGenerator, load_deep_roles  # noqa: E402
from src.data_ingestion.jd_loader import load_jd_text  # noqa: E402
from src.nlp.jd_parser import (  # noqa: E402
    parse_jd, _extract_years, _infer_seniority, _classify_role,
    _segment_jd,
)
from src.nlp.skill_matcher import SkillIndex  # noqa: E402

TAXONOMY = path("data", "taxonomy", "skill_taxonomy.yaml")


# ---------- generator ----------

@pytest.fixture(scope="module")
def generator():
    return JDGenerator(taxonomy_path=TAXONOMY, seed=42)


@pytest.fixture(scope="module")
def batch(generator):
    return generator.generate_batch(n_per_role=5)


def test_same_seed_produces_same_jds(generator):
    other = JDGenerator(taxonomy_path=TAXONOMY, seed=42)
    a = generator.generate_batch(n_per_role=2)
    b = other.generate_batch(n_per_role=2)
    assert [j.job_title for j in a] == [j.job_title for j in b]
    assert [j.required_skills for j in a] == [j.required_skills for j in b]


def test_different_seed_changes_jds(generator):
    other = JDGenerator(taxonomy_path=TAXONOMY, seed=999)
    a = generator.generate_batch(n_per_role=2)
    b = other.generate_batch(n_per_role=2)
    assert [j.jd_id for j in a] == [j.jd_id for j in b]  # ids stable
    assert [j.company for j in a] != [j.company for j in b]  # content differs


def test_batch_is_balanced(batch):
    from collections import Counter
    counts = Counter(j.target_role_id for j in batch)
    assert set(counts) == set(load_deep_roles(TAXONOMY))
    assert all(c == 5 for c in counts.values())


def test_required_skills_subset_of_role_skills(generator, batch):
    """Required skills must all belong to the JD's role (per the taxonomy)."""
    import yaml
    with TAXONOMY.open() as fh:
        tax = yaml.safe_load(fh)
    role_skills: dict[str, set[str]] = {}
    for ind in tax["industries"]:
        if ind["id"] != "data_analytics":
            continue
        for role in ind["roles"]:
            ids = set()
            for cat in role["categories"]:
                for sk in cat["skills"]:
                    ids.add(sk["id"])
            role_skills[role["id"]] = ids
    for j in batch:
        assert j.required_skills, f"{j.jd_id} has no required skills"
        bad = set(j.required_skills) - role_skills[j.target_role_id]
        assert not bad, f"{j.jd_id} required skills out of role: {bad}"


def test_preferred_subset_of_required_complement(generator, batch):
    """Preferred skills must NOT appear in required (mutually exclusive)."""
    for j in batch:
        overlap = set(j.required_skills) & set(j.preferred_skills)
        assert not overlap, f"{j.jd_id} overlap: {overlap}"


# ---------- parser: pure-function extractors ----------

def test_extract_years_picks_minimum():
    assert _extract_years(["5+ years of experience"]) == 5
    assert _extract_years(["3-5 years building pipelines"]) == 3
    assert _extract_years(["no years mentioned"]) is None


def test_infer_seniority_by_title():
    assert _infer_seniority("Junior Data Analyst", None) == "fresher"
    assert _infer_seniority("Senior Data Scientist", None) == "senior"
    assert _infer_seniority("Data Engineer", 3) == "mid"


def test_classify_role_by_title():
    idx = SkillIndex(skills={}, patterns=[])
    assert _classify_role("Senior Data Analyst", idx) == "data_analyst"
    assert _classify_role("Machine Learning Engineer", idx) == "ml_engineer"
    assert _classify_role("BI Analyst", idx) == "bi_analyst"


def test_segment_jd_finds_canonical_sections():
    text = """Senior Data Analyst
Acme | NYC

ABOUT THE ROLE
We are hiring.

RESPONSIBILITIES
- Build dashboards
- Write SQL

REQUIREMENTS
- 3+ years experience
- Python
"""
    sections = _segment_jd([ln for ln in text.splitlines() if ln.strip()])
    assert "header" in sections
    assert "about" in sections
    assert "responsibilities" in sections
    assert "requirements" in sections


# ---------- parser: end-to-end on synthetic JD ----------

@pytest.fixture(scope="module")
def idx():
    try:
        from src.nlp.skill_matcher import load_skill_index
        return load_skill_index()
    except Exception as e:
        pytest.skip(f"skill index unavailable: {e}")


def test_parse_jd_extracts_title_company_location(idx):
    jd = JDGenerator(TAXONOMY, seed=1).generate_one("data_analyst_test", "data_analyst")
    parsed = parse_jd(load_jd_text(jd.to_text(), source_path="<test>"), idx)
    assert parsed.job_title == jd.job_title
    assert parsed.company == jd.company
    assert parsed.location == jd.location


def test_parse_jd_extracts_years_and_seniority(idx):
    jd = JDGenerator(TAXONOMY, seed=2).generate_one("data_engineer_test", "data_engineer")
    parsed = parse_jd(load_jd_text(jd.to_text()), idx)
    assert parsed.min_years_experience is not None
    assert parsed.seniority_band in ("fresher", "mid", "senior")


def test_parse_jd_recovers_required_skills(idx):
    """Parser must recover >=80% of the generator's required skills from text."""
    gen = JDGenerator(TAXONOMY, seed=3)
    jd = gen.generate_one("data_scientist_test", "data_scientist")
    parsed = parse_jd(load_jd_text(jd.to_text()), idx)
    pred_ids = {h.canonical_id for h in parsed.required_skills}
    truth_ids = set(jd.required_skills)
    recall = len(pred_ids & truth_ids) / len(truth_ids)
    assert recall >= 0.80, (
        f"JD skill recall too low: {recall:.0%} "
        f"(pred={sorted(pred_ids)}, truth={sorted(truth_ids)})")


def test_parse_jd_classifies_role_from_title(idx):
    jd = JDGenerator(TAXONOMY, seed=4).generate_one("ml_engineer_test", "ml_engineer")
    parsed = parse_jd(load_jd_text(jd.to_text()), idx)
    assert parsed.role_id == "ml_engineer"
