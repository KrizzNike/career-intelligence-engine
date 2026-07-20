"""
Parse resumes CLI (Week 4).

Purpose
-------
Orchestrate the full Week-4 pipeline over every resume the Week-3 loader
marked parsed_status='pending':
  1. load the file (PDF or DOCX)
  2. clean -> segment -> parse (src.nlp.resume_parser)
  3. persist structured fields to MySQL (src.nlp.resume_persistence)
  4. flip Resumes.parsed_status 'pending' -> 'parsed'

The candidate_id is resolved from the resume_id via the synthetic email
the Week-3 loader wrote ({resume_id}@synthetic.local). The resume_id is
inferred from the filename stem (e.g. 'bi_analyst_0000').

Usage
-----
    python scripts/parse_resumes.py                 # all pending
    python scripts/parse_resumes.py --limit 50      # sample (debug)
    python scripts/parse_resumes.py --dir data/raw/resumes/synthetic

Resilience:
  - A failed parse marks that Resumes row parsed_status='failed' (not
    'parsed') so Week 5+ only sees clean rows; the pipeline continues.
  - Malformed PDFs/encoding errors are caught, not fatal.

Exit 0 even with some failures (a 'some failed' summary is printed); the
called functions emit concrete counts.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from src.config import get_env, PROJECT_ROOT  # noqa: E402
from src.nlp.skill_matcher import load_skill_index  # noqa: E402
from src.nlp.resume_parser import parse_resume  # noqa: E402
from src.nlp.resume_persistence import persist_parsed_resume  # noqa: E402

import mysql.connector  # noqa: E402


def _connect():
    load_dotenv(PROJECT_ROOT / ".env")
    return mysql.connector.connect(
        host=get_env("DB_HOST", "localhost"),
        port=int(get_env("DB_PORT", "3306")),
        user=get_env("DB_USER", "root"),
        password=get_env("DB_PASSWORD", ""),
        database=get_env("DB_NAME", "career_intelligence"),
        charset="utf8mb4",
        use_pure=True,
    )


def _candidate_id_for_resume(cur, resume_id: str) -> int | None:
    email = f"{resume_id}@synthetic.local"
    cur.execute("SELECT id FROM Candidates WHERE email = %s", (email,))
    row = cur.fetchone()
    return row[0] if row else None


def _fail_resume(cur, resume_id: str) -> None:
    from src.nlp.resume_persistence import _resume_hash
    cur.execute("SELECT id FROM Resumes WHERE content_hash = %s",
                (_resume_hash(resume_id),))
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE Resumes SET parsed_status = 'failed', "
            "parsed_at = NOW(3) WHERE id = %s", (row[0],))


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse all pending resumes.")
    ap.add_argument("--dir", default="data/raw/resumes/synthetic",
                    help="Directory of resume files (relative to project root).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only parse the first N resumes (debug).")
    args = ap.parse_args()

    resume_dir = (PROJECT_ROOT / args.dir).resolve()
    if not resume_dir.exists():
        print(f"[error] resume dir not found: {resume_dir}")
        return 1

    # Build the work list from .docx (the structural source) so each
    # resume is parsed once. The same resume_id's .pdf yields identical
    # section labels — see docs/parser_design.md.
    docx_files = sorted(resume_dir.glob("*.docx"))
    if args.limit:
        docx_files = docx_files[: args.limit]
    if not docx_files:
        print("[error] no .docx resumes found in", resume_dir)
        return 1

    print(f"[init] loading skill index from MySQL ...")
    idx = load_skill_index()
    print(f"[init] indexed {len(idx.skills)} skills, {len(idx.patterns)} patterns")

    conn = _connect()
    cur = conn.cursor()
    summary = {"parsed": 0, "failed": 0,
               "education": 0, "experience": 0, "projects": 0,
               "certifications": 0, "cs_inserted": 0, "cs_upgraded": 0,
               "status_flipped": 0}
    try:
        from tqdm import tqdm
        it = tqdm(docx_files, desc="parsing", unit="cv")
    except ImportError:  # tqdm optional
        it = docx_files

    for fp in it:
        resume_id = fp.stem
        try:
            cand_id = _candidate_id_for_resume(cur, resume_id)
            if not cand_id:
                # No matching candidate row — skip (likely outer data not loaded).
                summary["failed"] += 1
                continue
            parsed = parse_resume(fp, idx)
            counts = persist_parsed_resume(conn, parsed, cand_id, resume_id)
            summary["parsed"] += 1
            for k in ("education", "experience", "projects", "certifications"):
                summary[k] += counts.get(k, 0)
            summary["cs_inserted"] += counts.get("candidate_skills_inserted", 0)
            summary["cs_upgraded"] += counts.get("candidate_skills_upgraded", 0)
            summary["status_flipped"] += counts.get("resume_status_flipped", 0)
        except KeyboardInterrupt:
            print("\n[interrupt] committing partial work ...")
            conn.commit()
            break
        except Exception as e:  # noqa: BLE001
            summary["failed"] += 1
            try:
                _fail_resume(cur, resume_id)
                conn.commit()
            except Exception:
                conn.rollback()
            it.write(f"  [fail] {resume_id}: {type(e).__name__}: {e}")
    cur.close()
    conn.close()

    print()
    print("[ok] parse run complete.")
    for k, v in summary.items():
        print(f"  {k:20s} {v}")
    if summary["failed"]:
        print(f"\n[warn] {summary['failed']} resumes failed — see rows with "
              "parsed_status='failed' for investigation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
