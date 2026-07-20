"""
JD parsing persistence (Week 5).

Take a ParsedJD and write it into MySQL:
  - Job_Postings  : one row per JD (dedup via content_hash)
  - Job_Skills    : one row per required/preferred skill

Idempotent: re-running wipes this JD's Job_Skills rows first.
"""
from __future__ import annotations

import hashlib
import json

from src.nlp.jd_parser import ParsedJD


def _jd_hash(jd_id: str) -> str:
    return hashlib.sha256(jd_id.encode("utf-8")).hexdigest()


def _existing_job_id(cur, jd_id: str) -> int | None:
    cur.execute("SELECT id FROM Job_Postings WHERE content_hash = %s",
                (_jd_hash(jd_id),))
    row = cur.fetchone()
    return row[0] if row else None


def persist_parsed_jd(conn, parsed: ParsedJD, jd_id: str) -> dict[str, int]:
    """Upsert a ParsedJD into Job_Postings + Job_Skills. Returns counts."""
    cur = conn.cursor()
    counts: dict[str, int] = {}
    try:
        existing = _existing_job_id(cur, jd_id)
        if existing:
            job_id = existing
            # Idempotent: clear this job's skills before re-insert.
            cur.execute("DELETE FROM Job_Skills WHERE job_id = %s", (job_id,))
            cur.execute(
                """UPDATE Job_Postings
                   SET job_title=%s, company=%s, role_id=%s, industry=%s,
                       seniority_band=%s
                   WHERE id=%s""",
                (parsed.job_title, parsed.company, parsed.role_id,
                 parsed.industry, parsed.seniority_band, job_id))
            counts["job_postings"] = 0  # update, not insert
        else:
            cur.execute(
                """INSERT INTO Job_Postings
                   (job_title, company, role_id, industry, location,
                    seniority_band, description, content_hash, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'synthetic')""",
                (parsed.job_title, parsed.company, parsed.role_id,
                 parsed.industry, parsed.location, parsed.seniority_band,
                 "\n".join(parsed.responsibilities + parsed.requirements),
                 _jd_hash(jd_id)))
            job_id = cur.lastrowid
            counts["job_postings"] = 1

        # Job_Skills: required (importance derived from taxonomy), preferred.
        n_required = 0
        for h in parsed.required_skills:
            cur.execute(
                """INSERT IGNORE INTO Job_Skills
                   (job_id, skill_id, importance, is_required)
                   VALUES (%s, %s, 'high', 1)""",
                (job_id, h.skill_id))
            n_required += cur.rowcount if cur.rowcount > 0 else 0
        n_preferred = 0
        for h in parsed.preferred_skills:
            cur.execute(
                """INSERT IGNORE INTO Job_Skills
                   (job_id, skill_id, importance, is_required)
                   VALUES (%s, %s, 'low', 0)""",
                (job_id, h.skill_id))
            n_preferred += cur.rowcount if cur.rowcount > 0 else 0

        counts["job_skills_required"] = n_required
        counts["job_skills_preferred"] = n_preferred
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return counts
