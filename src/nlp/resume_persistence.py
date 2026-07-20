"""
Resume parsing persistence (Week 4).

Purpose
-------
Take a ParsedResume (pure-logic output of src.nlp.resume_parser) and
write its structured fields into the MySQL operational schema created
in Week 3, then flip the Resumes row parsed_status 'pending' -> 'parsed'.

This is the ONLY place parsing touches the database, kept separate from
the (pure) parser so the parser stays unit-testable without MySQL.

Tables written:
  - Education        : one row per parsed EducationEntry
  - Experience       : one row per parsed ExperienceEntry
  - Projects         : one row per parsed ProjectEntry, tech_stack as JSON
  - Certifications   : one row per parsed CertEntry
  - Candidate_Skills : upgrade evidence inferred->explicit + insert new
                        (INSERT IGNORE preserves the Week-3 'inferred' rows
                        added by the loader; explicit wins on the UPDATE)
  - Resumes          : parsed_status = 'parsed', parsed_at = now()

Idempotency:
  - Education/Experience/Projects/Certifications are DELETED for this
    candidate_id before re-insert so re-parsing never doubles rows.
  - Resumes update is keyed on the resume's content_hash (Week-3 loader
    stored it), so we can find the row from the file path.

Inputs
------
conn : mysql.connector connection (caller owns commit/rollback)
parsed : ParsedResume
candidate_id : int
resume_id : str (the synthetic resume_id, e.g. 'bi_analyst_0000') used to
            locate the Resumes row via content_hash.

Outputs
-------
counts dict: {education, experience, projects, certifications,
              candidate_skills_inserted, candidate_skills_upgraded,
              resume_status_flipped}

Dependencies
------------
mysql-connector-python, json.

Testing example
---------------
    from src.nlp.resume_persistence import persist_parsed_resume
    counts = persist_parsed_resume(conn, parsed, candidate_id=42,
                                   resume_id='bi_analyst_0000')
    assert counts['resume_status_flipped'] == 1
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.nlp.resume_parser import ParsedResume


def _resume_hash(resume_id: str) -> str:
    """Matches the hash the Week-3 loader wrote to Resumes.content_hash."""
    return hashlib.sha256(resume_id.encode("utf-8")).hexdigest()


def _year_to_int(y) -> int | None:
    try:
        return int(y) if y else None
    except (TypeError, ValueError):
        return None


def _parse_date(s: str) -> str | None:
    """'Jul 2017' or '2017' -> 'YYYY-MM-01' (MySQL DATE), or None."""
    if not s:
        return None
    s = s.strip()
    m = re.match(
        r"([A-Za-z]{3,9})\.?\s+(\d{4})", s, re.IGNORECASE)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].title(), 1)
        return f"{m.group(2)}-{mon:02d}-01"
    m = re.match(r"(\d{4})", s)
    if m:
        return f"{m.group(1)}-01-01"
    return None


_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _clear_existing(cur, candidate_id: int) -> None:
    """Wipe previously-parsed structured rows for this candidate so
    re-parsing is idempotent (no duplicate Education/Experience/etc.)."""
    for t in ("Education", "Experience", "Projects", "Certifications"):
        cur.execute(f"DELETE FROM {t} WHERE candidate_id = %s", (candidate_id,))


def _insert_education(cur, candidate_id: int, parsed: ParsedResume) -> int:
    n = 0
    for e in parsed.education:
        end_year = _year_to_int(e.year)
        cur.execute(
            """INSERT INTO Education
               (candidate_id, degree, institution, field_of_study, end_year)
               VALUES (%s, %s, %s, %s, %s)""",
            (candidate_id, e.degree or "Unknown",
             e.institution or None, e.field_of_study or None, end_year),
        )
        n += cur.rowcount if cur.rowcount > 0 else 0
    return n


def _insert_experience(cur, candidate_id: int, parsed: ParsedResume) -> int:
    n = 0
    for e in parsed.experience:
        descr = "\n".join(e.bullets) if e.bullets else None
        cur.execute(
            """INSERT INTO Experience
               (candidate_id, title, company, start_date, end_date,
                is_current, description)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (candidate_id, e.title or "Unknown", e.company or None,
             _parse_date(e.start), _parse_date(e.end),
             1 if e.is_current else 0, descr),
        )
        n += 1
    return n


def _insert_projects(cur, candidate_id: int, parsed: ParsedResume) -> int:
    n = 0
    for pr in parsed.projects:
        # tech_stack is JSON array of canonical skill ids the parser matched.
        tech = json.dumps(pr.skills) if pr.skills else None
        cur.execute(
            """INSERT INTO Projects
               (candidate_id, name, description, tech_stack)
               VALUES (%s, %s, %s, %s)""",
            (candidate_id, pr.name or "Untitled", pr.description or None, tech),
        )
        n += 1
    return n


def _insert_certs(cur, candidate_id: int, parsed: ParsedResume) -> int:
    n = 0
    for c in parsed.certifications:
        cur.execute(
            """INSERT INTO Certifications
               (candidate_id, name, issuer) VALUES (%s, %s, %s)""",
            (candidate_id, c.name or "Unknown", c.issuer or None),
        )
        n += 1
    return n


def _update_candidate_skills(cur, candidate_id: int, parsed: ParsedResume
                             ) -> tuple[int, int]:
    """Insert/upgrade Candidate_Skills. Returns (inserted, upgraded).

    For each SkillHit: if a Candidate_Skills row exists for this
    (candidate, skill), upgrade its evidence to 'explicit' and record the
    section it was found in (only if the new evidence is stronger).
    Otherwise INSERT IGNORE a new row with the parsed evidence.
    """
    inserted = 0
    upgraded = 0
    for h in parsed.skills:
        cur.execute(
            "SELECT id, evidence FROM Candidate_Skills "
            "WHERE candidate_id = %s AND skill_id = %s",
            (candidate_id, h.skill_id))
        row = cur.fetchone()
        if row:
            cs_id, existing_ev = row
            # Only upgrade inferred -> explicit; never downgrade.
            if h.evidence == "explicit" and existing_ev != "explicit":
                cur.execute(
                    "UPDATE Candidate_Skills SET evidence = 'explicit', "
                    "source_section = %s WHERE id = %s",
                    (h.section, cs_id))
                upgraded += 1
        else:
            cur.execute(
                """INSERT IGNORE INTO Candidate_Skills
                   (candidate_id, skill_id, proficiency, evidence,
                    source_section) VALUES (%s, %s, 'intermediate', %s, %s)""",
                (candidate_id, h.skill_id, h.evidence, h.section))
            if cur.rowcount > 0:
                inserted += 1
    return inserted, upgraded


def _flip_resume_status(cur, resume_id: str) -> int:
    cur.execute(
        "SELECT id FROM Resumes WHERE content_hash = %s",
        (_resume_hash(resume_id),))
    row = cur.fetchone()
    if not row:
        return 0
    rid = row[0]
    cur.execute(
        "UPDATE Resumes SET parsed_status = 'parsed', parsed_at = NOW(3) "
        "WHERE id = %s AND parsed_status = 'pending'", (rid,))
    return cur.rowcount


def persist_parsed_resume(conn, parsed: ParsedResume, candidate_id: int,
                          resume_id: str) -> dict[str, int]:
    """Write ParsedResume to the DB for an already-known candidate_id + resume_id."""
    cur = conn.cursor()
    counts: dict[str, int] = {}
    try:
        _clear_existing(cur, candidate_id)
        counts["education"] = _insert_education(cur, candidate_id, parsed)
        counts["experience"] = _insert_experience(cur, candidate_id, parsed)
        counts["projects"] = _insert_projects(cur, candidate_id, parsed)
        counts["certifications"] = _insert_certs(cur, candidate_id, parsed)
        ins, upg = _update_candidate_skills(cur, candidate_id, parsed)
        counts["candidate_skills_inserted"] = ins
        counts["candidate_skills_upgraded"] = upg
        counts["resume_status_flipped"] = _flip_resume_status(cur, resume_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return counts
