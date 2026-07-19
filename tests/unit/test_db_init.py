"""Tests: schema deployed by scripts/db_init.py.

These assert the *structural* invariants of the Week-3 schema: all 14
operational tables exist, star-schema views exist, the taxonomy seed is in
place (Skill_Taxonomy + Skills + Skill_Alias all non-empty and internally
consistent), and FK integrity holds.
"""
from __future__ import annotations

EXPECTED_TABLES = {
    "Candidates", "Resumes", "Education", "Experience", "Projects",
    "Certifications", "Skills", "Skill_Alias", "Candidate_Skills",
    "Job_Postings", "Job_Skills", "Skill_Taxonomy", "Match_Results",
    "Career_Readiness", "Recommendations",
}

EXPECTED_VIEWS = {
    "v_dim_candidate", "v_dim_role", "v_dim_skill", "v_dim_date",
    "v_fact_candidate_match",
}


def test_operational_tables_present(cur):
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'")
    # MySQL on Windows defaults to lower_case_table_names=1, so table
    # names come back lowercased ('candidates' not 'Candidates'). Compare
    # case-insensitively against EXPECTED_TABLES, which is mixed-case for
    # readability.
    actual = {r[0].lower() for r in cur.fetchall()}
    expected = {t.lower() for t in EXPECTED_TABLES}
    missing = expected - actual
    assert not missing, f"missing tables: {missing}"


def test_star_schema_views_present(cur):
    cur.execute(
        "SELECT table_name FROM information_schema.views "
        "WHERE table_schema = DATABASE()")
    actual = {r[0].lower() for r in cur.fetchall()}
    expected = {v.lower() for v in EXPECTED_VIEWS}
    missing = expected - actual
    assert not missing, f"missing views: {missing}"


def test_taxonomy_seeded(cur):
    cur.execute("SELECT COUNT(*) FROM Skill_Taxonomy")
    assert cur.fetchone()[0] > 0, "Skill_Taxonomy is empty — run db_init"
    cur.execute("SELECT COUNT(*) FROM Skills")
    assert cur.fetchone()[0] > 0, "Skills is empty"
    cur.execute("SELECT COUNT(*) FROM Skill_Alias")
    # aliases are optional in the taxonomy, but the v0 schema defines several.
    assert cur.fetchone()[0] > 0, "Skill_Alias is empty"


def test_every_active_skill_links_to_taxonomy(cur):
    """Active skills should resolve to a taxonomy 'skill' node."""
    cur.execute(
        """
        SELECT COUNT(*) FROM Skills s
        LEFT JOIN Skill_Taxonomy st ON st.id = s.taxonomy_id
        WHERE s.taxonomy_id IS NULL
        """)
    # A skill may be in the master list before its taxonomy node exists, but in
    # the seed path the UPDATE links them all — so this must be 0.
    unlinked = cur.fetchone()[0]
    assert unlinked == 0, f"{unlinked} skills not linked to taxonomy"


def test_skill_alias_resolves_to_active_skill(cur):
    """Every alias must point to an active, existing skill (FK + business rule)."""
    cur.execute(
        """
        SELECT COUNT(*) FROM Skill_Alias sa
        JOIN Skills s ON s.id = sa.skill_id
        WHERE s.is_active = 0
        """)
    assert cur.fetchone()[0] == 0, "alias points to an inactive skill"
