"""
Unit tests for the synthetic resume generator (Week 2).

Pins the invariants the downstream engines rely on:
  - Determinism (same seed -> same resumes)
  - Role balance (each deep role gets equal coverage)
  - Skill validity (every sampled skill exists in the taxonomy)
  - PII safety (synthetic resumes never contain the literal scrub markers)
  - Coverage (each resume samples a believable fraction of role skills)
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import path  # noqa: E402
from src.data_ingestion.synthetic_resume import (  # noqa: E402
    ResumeGenerator, load_deep_roles,
)
from src.preprocessing.scrub_pii import scrub_text  # noqa: E402

TAXONOMY = path("data", "taxonomy", "skill_taxonomy.yaml")


# ---------- fixture: a small generated batch ----------

@pytest.fixture(scope="module")
def generator():
    return ResumeGenerator(taxonomy_path=TAXONOMY, seed=42)


@pytest.fixture(scope="module")
def batch(generator):
    return generator.generate_batch(n_per_role=5)


# ---------- generator: determinism ----------

def test_same_seed_produces_same_resumes(generator):
    other = ResumeGenerator(taxonomy_path=TAXONOMY, seed=42)
    a = generator.generate_batch(n_per_role=2)
    b = other.generate_batch(n_per_role=2)
    assert [r.name for r in a] == [r.name for r in b]
    assert [r.skills for r in a] == [r.skills for r in b]


def test_different_seed_produces_different_resumes(generator):
    other = ResumeGenerator(taxonomy_path=TAXONOMY, seed=999)
    a = generator.generate_batch(n_per_role=2)
    b = other.generate_batch(n_per_role=2)
    # IDs are the same (role-order is deterministic) but content differs.
    assert [r.resume_id for r in a] == [r.resume_id for r in b]
    assert [r.name for r in a] != [r.name for r in b]


# ---------- generator: balance ----------

def test_batch_is_balanced_across_roles(generator, batch):
    from collections import Counter
    counts = Counter(r.target_role_id for r in batch)
    expected_roles = set(generator.role_ids)
    assert set(counts) == expected_roles, \
        f"missing roles: {expected_roles - set(counts)}"
    # Exactly n_per_role per role.
    assert all(c == 5 for c in counts.values()), counts


def test_deep_roles_match_taxonomy():
    roles = load_deep_roles(TAXONOMY)
    assert set(roles) == {
        "data_analyst", "bi_analyst", "data_scientist",
        "data_engineer", "ml_engineer",
    }


# ---------- generator: skill validity ----------

def _all_taxonomy_skill_ids() -> set[str]:
    with TAXONOMY.open("r", encoding="utf-8") as fh:
        tax = yaml.safe_load(fh)
    ids = set()
    for ind in tax["industries"]:
        if ind["id"] != "data_analytics":
            continue
        for role in ind["roles"]:
            for cat in role["categories"]:
                for sk in cat["skills"]:
                    ids.add(sk["id"])
    return ids


def test_sampled_skills_are_valid_taxonomy_ids(batch):
    valid = _all_taxonomy_skill_ids()
    for r in batch:
        assert r.skills, f"{r.resume_id} has no skills"
        bad = set(r.skills) - valid
        assert not bad, f"{r.resume_id} sampled non-taxonomy skills: {bad}"


def test_sampled_skills_belong_to_their_role(batch):
    """A resume for role X should only carry skills that role declares
    (the generator samples from the role's own category skills)."""
    with TAXONOMY.open("r", encoding="utf-8") as fh:
        tax = yaml.safe_load(fh)
    role_skill_map: dict[str, set[str]] = {}
    for ind in tax["industries"]:
        if ind["id"] != "data_analytics":
            continue
        for role in ind["roles"]:
            ids = set()
            for cat in role["categories"]:
                for sk in cat["skills"]:
                    ids.add(sk["id"])
            role_skill_map[role["id"]] = ids

    for r in batch:
        allowed = role_skill_map[r.target_role_id]
        out_of_role = set(r.skills) - allowed
        assert not out_of_role, \
            f"{r.resume_id} ({r.target_role_id}) sampled foreign skills: " \
            f"{out_of_role}"


# ---------- generator: coverage ----------

def test_each_resume_samples_a_believable_skill_fraction(generator, batch):
    for r in batch:
        total = len(generator._all_skill_names_for_role(r.target_role_id))
        frac = len(r.skills) / total
        # Generator targets 60-90%; allow a small slack at the low end
        # because of the max(3, ...) floor on tiny roles.
        assert 0.4 <= frac <= 0.95, \
            f"{r.resume_id} sampled {frac:.0%} of role skills (out of band)"


# ---------- generator: PII safety on synthetic output ----------

def test_synthetic_resumes_have_no_redaction_markers(batch):
    """Synthetic resumes are generated fake from the start, so they must NOT
    contain any of the scrubber's redaction markers (those would mean real
    PII slipped through — impossible here, but we pin the invariant).

    Note: '@example.com' is excluded because Faker LEGITIMATELY uses it as
    its default email domain; only the scrubber's own static markers are
    checked here."""
    markers = ["redacted_ssn", "redacted_cc", "example_url", "fake_phone"]
    for r in batch:
        text = r.to_text()
        for m in markers:
            assert m not in text, \
                f"{r.resume_id} contains scrub marker '{m}' unexpectedly"


# ---------- scrubber: core behaviour ----------

def test_scrubber_removes_email():
    text = "Contact me at john.doe@company.com for details."
    clean, report = scrub_text(text)
    assert "john.doe@company.com" not in clean
    assert "@example.com" in clean
    assert report.counts.get("email") == 1


def test_scrubber_removes_phone():
    text = "Phone: +1-415-555-1234 or (212) 555-9999."
    clean, report = scrub_text(text)
    assert "+1-415-555-1234" not in clean
    assert "(212) 555-9999" not in clean
    assert report.counts.get("phone", 0) >= 2


def test_scrubber_removes_ssn_and_credit_card():
    text = "SSN 123-45-6789; card 4111 1111 1111 1111."
    clean, report = scrub_text(text)
    assert "123-45-6789" not in clean
    assert "4111 1111 1111 1111" not in clean
    assert report.counts.get("ssn") == 1
    assert report.counts.get("credit_card") == 1


def test_scrubber_is_deterministic():
    text = "Reach alice@acme.io or bob@acme.io."
    a, _ = scrub_text(text)
    b, _ = scrub_text(text)
    assert a == b  # same input -> same scrubbed output


def test_scrubber_preserves_non_pii_text():
    text = "Skilled in Python, SQL, and Power BI. Built dashboards."
    clean, report = scrub_text(text)
    assert "Python" in clean and "SQL" in clean and "Power BI" in clean
    assert report.total == 0


def test_scrubber_handles_empty_input():
    clean, report = scrub_text("")
    assert clean == ""
    assert report.total == 0
