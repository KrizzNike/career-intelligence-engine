"""
CLI for the Week-3 resume metadata ETL.

Usage
-----
    python scripts/load_resumes.py                      # default dir
    python scripts/load_resumes.py --dir data/raw/resumes/synthetic

Prereq: `python scripts/db_init.py` must have been run (tables + seed exist).
Prints a summary (candidates loaded, skills linked, unknown skills skipped).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_env, PROJECT_ROOT  # noqa: E402
from src.data_ingestion.load_resumes_to_db import load_all  # noqa: E402


def _conn():
    from dotenv import load_dotenv
    import mysql.connector
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Load synthetic resume labels to DB.")
    ap.add_argument(
        "--dir", default="data/raw/resumes/synthetic",
        help="Directory of *.json resume label files (relative to project root).")
    args = ap.parse_args()
    resume_dir = (PROJECT_ROOT / args.dir).resolve()

    if not resume_dir.exists():
        print(f"[error] resume dir not found: {resume_dir}")
        return 1

    conn = _conn()
    try:
        totals = load_all(conn, resume_dir)
    except Exception as exc:
        print(f"[error] {exc}")
        return 1
    finally:
        conn.close()

    print("[ok] resume metadata loaded:")
    for k, v in totals.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
