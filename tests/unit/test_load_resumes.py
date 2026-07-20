"""Tests: src/data_ingestion/load_resumes_to_db.py

These assume the synthetic resumes were generated in Week 2 (600 files) and
that db_init has seeded the taxonomy. They verify the loader is idempotent
(re-running doesn't double-insert) and that the loaded data is referentially
consistent.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_DIR = ROOT / "data" / "raw" / "resumes" / "synthetic"


def _resume_json_count() -> int:
    return len(list(SYNTHETIC_DIR.glob("*.json")))


def test_candidate_count_matches_resume_files(cur):
    """One candidate per JSON label — the defining invariant of the loader."""
    cur.execute("SELECT COUNT(*) FROM Candidates")
    candidates = cur.fetchone()[0]
    expected = _resume_json_count()
    assert candidates == expected, (
        f"{candidates} candidates vs {expected} resume JSON files")


def test_every_candidate_has_a_resume(cur):
    cur.execute(
        """
        SELECT COUNT(*) FROM Candidates c
        LEFT JOIN Resumes r ON r.candidate_id = c.id
        WHERE r.id IS NULL
        """)
    assert cur.fetchone()[0] == 0, "a candidate has no resume row"


def test_all_resumes_pending_parse(cur):
    """No resumes should be 'failed'; some may be 'parsed' after Week 4."""
    cur.execute(
        "SELECT COUNT(*) FROM Resumes WHERE parsed_status = 'failed'")
    assert cur.fetchone()[0] == 0, "some resumes are marked failed"


def test_candidate_skills_linked(cur):
    """Each synthetic resume samples 3+ skills, so the bridge must be populated."""
    cur.execute("SELECT COUNT(*) FROM Candidate_Skills")
    assert cur.fetchone()[0] > 0, "no candidate-skill links loaded"


def test_loader_is_idempotent(cur):
    """Re-running load_all must NOT increase row counts."""
    import importlib
    from dotenv import load_dotenv
    from src.config import get_env
    import mysql.connector
    from src.data_ingestion import load_resumes_to_db

    load_dotenv(ROOT / ".env")
    conn = mysql.connector.connect(
        host=get_env("DB_HOST", "localhost"),
        port=int(get_env("DB_PORT", "3306")),
        user=get_env("DB_USER", "root"),
        password=get_env("DB_PASSWORD", ""),
        database=get_env("DB_NAME", "career_intelligence"),
        charset="utf8mb4", use_pure=True)
    try:
        before = {}
        for t in ("Candidates", "Resumes", "Candidate_Skills"):
            c = conn.cursor()
            c.execute(f"SELECT COUNT(*) FROM {t}")
            before[t] = c.fetchone()[0]
            c.close()

        totals = load_resumes_to_db.load_all(conn, SYNTHETIC_DIR.resolve())

        after = {}
        for t in ("Candidates", "Resumes", "Candidate_Skills"):
            c = conn.cursor()
            c.execute(f"SELECT COUNT(*) FROM {t}")
            after[t] = c.fetchone()[0]
            c.close()
    finally:
        conn.close()

    assert after == before, (
        f"re-run changed counts: {before} -> {after}")

    # load_all reports skills already linked as 0 new (INSERT IGNORE),
    # but candidates touched should equal the file count.
    assert totals["candidates"] == _resume_json_count()
