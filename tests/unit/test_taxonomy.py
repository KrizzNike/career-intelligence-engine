"""
Unit tests for the skill-taxonomy validator.

These pin the behaviour of validate_taxonomy.py so future taxonomy edits
can't silently break the invariants the downstream engines rely on.
Run:  pytest tests/unit/test_taxonomy.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.validate_taxonomy import validate  # noqa: E402

TAXONOMY = ROOT / "data" / "taxonomy" / "skill_taxonomy.yaml"


# --- The real taxonomy file must always validate. ---
def test_real_taxonomy_is_valid():
    errors, stats = validate(TAXONOMY)
    assert errors == [], "real taxonomy has structural errors:\n  - " + \
                         "\n  - ".join(errors)


def test_real_taxonomy_has_expected_scope():
    _, stats = validate(TAXONOMY)
    # Deep vertical is data & analytics with 5 roles, per the v0 decision.
    assert stats["industries"] >= 5
    assert stats["deep_roles"] == 5
    assert stats["skills"] >= 40, "deep vertical under-specified"
    # Each deep role meets the minimum skill floor.
    for label, count in stats["per_role"].items():
        if label.startswith("data_analytics/"):
            assert count >= 5, f"{label} under-specified ({count} skills)"


# --- Synthetic bad taxonomies must be REJECTED. ---
def _write_bad(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "bad.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_missing_schema_version_errors(tmp_path):
    p = _write_bad(tmp_path, """
industries:
  - id: x
    roles:
      - id: r
        categories:
          - id: c
            skills:
              - id: s
                name: S
                importance: high
""")
    errors, _ = validate(p)
    assert any("schema_version" in e for e in errors)


def test_duplicate_alias_across_skills_errors(tmp_path):
    p = _write_bad(tmp_path, """
schema_version: '0.1'
industries:
  - id: x
    roles:
      - id: r
        categories:
          - id: c
            skills:
              - id: skill_a
                name: A
                importance: high
                aliases: [PBI]
              - id: skill_b
                name: B
                importance: high
                aliases: [PBI]
""")
    errors, _ = validate(p)
    assert any("'PBI'" in e and "skill_a" in e and "skill_b" in e for e in errors)


def test_bad_importance_enum_errors(tmp_path):
    p = _write_bad(tmp_path, """
schema_version: '0.1'
industries:
  - id: x
    roles:
      - id: r
        categories:
          - id: c
            skills:
              - id: s
                name: S
                importance: super-important
""")
    errors, _ = validate(p)
    assert any("importance 'super-important'" in e for e in errors)


def test_under_specified_deep_role_errors(tmp_path):
    # A data_analytics role with only 2 skills trips the minimum-floor check.
    p = _write_bad(tmp_path, """
schema_version: '0.1'
industries:
  - id: data_analytics
    roles:
      - id: thin_role
        seniority: entry_to_mid
        categories:
          - id: c
            skills:
              - id: s1
                name: S1
                importance: high
              - id: s2
                name: S2
                importance: high
""")
    errors, _ = validate(p)
    assert any("under-specified" in e for e in errors)


def test_missing_file_errors(tmp_path):
    errors, _ = validate(tmp_path / "does_not_exist.yaml")
    assert errors and "not found" in errors[0]
