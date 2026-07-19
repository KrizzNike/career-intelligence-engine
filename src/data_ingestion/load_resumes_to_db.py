"""
Load synthetic resume LABELS into the database (Week 3 ETL).

Purpose
-------
Persist the Week-2 synthetic resume metadata into the operational schema so
that the Week-4 parser, Week-5 JD analyzer, and Week-6/7 matching/scoring
engines have a place to write their results against.

What we load (and what we deliberately DON'T):
  - LOAD: the resume *label* file (data/raw/resumes/synthetic/*.json), which
    is the ground-truth record of {resume_id, target_role, name, canonical
    skill ids}. This populates Candidates, Resumes, Candidate_Skills.
  - DO NOT LOAD: the rendered free text / PII. The .pdf/.docx companions hold
    the real resume *content* (with faker email/phone) that the Week-4 parser
    will read and extract. Loading the text now would duplicate Week-4's job
    and would also pull in PII we don't need at the metadata layer. The
    Resumes row is created with parsed_status='pending' precisely so Week 4
    knows which rows still need parsing.

Deterministic synthetic email:
  The label JSON omits email (PII stays in the rendered file). Candidates.email
  is UNIQUE NOT NULL, so we synthesize a deterministic, obviously-fake address
  from resume_id: `{resume_id}@synthetic.local`. This keeps the loader
  idempotent (same candidate resolves to the same row on re-runs) and makes it
  visually obvious these are not real addresses.

Idempotency:
  - Candidates: matched/updated by email (ON DUPLICATE KEY UPDATE).
  - Resumes: content_hash UNIQUE (sha256 of the resume_id); INSERT IGNORE.
  - Candidate_Skills: UNIQUE(candidate_id, skill_id); INSERT IGNORE.

Proficiency defaults to 'intermediate' — the label file has no proficiency
signal; the parser (Week 4) will refine this from evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT

try:
    import mysql.connector
except ImportError as exc:  # pragma: no cover
    raise SystemExit("mysql-connector-python not installed") from exc

DEFAULT_RESUME_DIR = PROJECT_ROOT / "data" / "raw" / "resumes" / "synthetic"

# Skills known in the taxonomy live in the Skills table; we resolve a
# canonical_id -> Skills.id once at load time and cache it.
EVIDENCE_INFERRED = "inferred"
SOURCE_SECTION_SKILLS = "skills"


def _synthetic_email(resume_id: str) -> str:
    """Deterministic, obviously-fake email keyed on resume_id."""
    return f"{resume_id}@synthetic.local"


def _content_hash(resume_id: str) -> str:
    """Stable hash for the Resumes.content_hash UNIQUE column.

    Hashing resume_id (not file bytes) means re-generating the .pdf with a
    different font/seed won't churn the row — only a renamed resume_id does.
    """
    return hashlib.sha256(resume_id.encode("utf-8")).hexdigest()


def load_skill_id_map(cur) -> dict[str, int]:
    """canonical_id -> Skills.id, cached for the whole load."""
    cur.execute("SELECT canonical_id, id FROM Skills WHERE is_active = 1")
    return {cid: pk for cid, pk in cur.fetchall()}


def load_one(cur, data: dict[str, Any], resume_dir: Path,
             skill_id_map: dict[str, int]) -> dict[str, int]:
    """Insert one resume's metadata. Returns a small counts dict for the run."""
    resume_id = data["resume_id"]
    target_role_id = data["target_role_id"]
    name = data.get("name") or resume_id
    email = _synthetic_email(resume_id)
    skill_ids = data.get("skills", [])  # canonical ids

    # --- Candidates (idempotent on email) ---
    cur.execute(
        """
        INSERT INTO Candidates
            (full_name, email, target_role_id, seniority_band, source)
        VALUES (%s, %s, %s, 'fresher', 'synthetic')
        ON DUPLICATE KEY UPDATE
            full_name = VALUES(full_name),
            target_role_id = VALUES(target_role_id)
        """,
        (name, email, target_role_id),
    )
    candidate_inserted = cur.rowcount == 1  # 1 = new row; 2 = updated existing
    cur.execute("SELECT id FROM Candidates WHERE email = %s", (email,))
    candidate_id = cur.fetchone()[0]

    # --- Resumes (idempotent on content_hash; INSERT IGNORE) ---
    pdf_path = resume_dir / f"{resume_id}.pdf"
    cur.execute(
        """
        INSERT IGNORE INTO Resumes
            (candidate_id, file_path, file_format, content_hash, parsed_status)
        VALUES (%s, %s, 'pdf', %s, 'pending')
        """,
        (candidate_id, str(pdf_path.relative_to(PROJECT_ROOT)),
         _content_hash(resume_id)),
    )
    resume_inserted = cur.rowcount == 1  # INSERT IGNORE: 1 = new, 0 = duplicate

    # --- Candidate_Skills (idempotent on unique pair; INSERT IGNORE) ---
    linked = 0
    skipped_unknown = 0
    for cid in skill_ids:
        sid = skill_id_map.get(cid)
        if sid is None:
            # Skill referenced by the resume is not in the taxonomy yet.
            # Log-and-continue: don't fail the whole load over one unknown.
            skipped_unknown += 1
            continue
        cur.execute(
            """
            INSERT IGNORE INTO Candidate_Skills
                (candidate_id, skill_id, proficiency, evidence, source_section)
            VALUES (%s, %s, 'intermediate', %s, %s)
            """,
            (candidate_id, sid, EVIDENCE_INFERRED, SOURCE_SECTION_SKILLS),
        )
        if cur.rowcount > 0:
            linked += 1

    return {"candidate": 1,
            "candidate_new": int(candidate_inserted),
            "resume": 1,
            "resume_new": int(resume_inserted),
            "skills_linked": linked,
            "skills.unknown": skipped_unknown}


def load_all(conn, resume_dir: Path = DEFAULT_RESUME_DIR) -> dict[str, int]:
    """Load every *.json label in resume_dir. Returns aggregate counts."""
    cur = conn.cursor()
    skill_id_map = load_skill_id_map(cur)
    if not skill_id_map:
        raise RuntimeError(
            "Skills table is empty — run db_init with the taxonomy seed first.")
    files = sorted(resume_dir.glob("*.json"))
    totals = {"candidates": 0, "candidates_new": 0,
              "resumes": 0, "resumes_new": 0,
              "skills_linked": 0, "skills.unknown": 0}
    resume_dir_resolved = resume_dir.resolve()
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if data.get("source") and data["source"] != "synthetic_generator":
            # Only the synthetic label schema is handled here; real resumes
            # arrive via the Week-4 parser, not this loader.
            continue
        r = load_one(cur, data, resume_dir_resolved, skill_id_map)
        totals["candidates"] += r["candidate"]
        totals["candidates_new"] += r["candidate_new"]
        totals["resumes"] += r["resume"]
        totals["resumes_new"] += r["resume_new"]
        totals["skills_linked"] += r["skills_linked"]
        totals["skills.unknown"] += r["skills.unknown"]
    conn.commit()
    cur.close()
    return totals
