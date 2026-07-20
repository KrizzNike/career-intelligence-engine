"""
Parse JDs CLI (Week 5).

For every .txt JD in data/raw/jobs/<dir>:
  1. load the file
  2. clean -> segment -> parse (src.nlp.jd_parser)
  3. persist to MySQL (src.nlp.jd_persistence)

Usage:
    python scripts/parse_jds.py
    python scripts/parse_jds.py --dir data/raw/jobs/synthetic --limit 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from src.config import get_env, PROJECT_ROOT  # noqa: E402
from src.nlp.skill_matcher import load_skill_index  # noqa: E402
from src.nlp.jd_parser import parse_jd  # noqa: E402
from src.nlp.jd_persistence import persist_parsed_jd  # noqa: E402

import mysql.connector  # noqa: E402


def _connect():
    load_dotenv(PROJECT_ROOT / ".env")
    return mysql.connector.connect(
        host=get_env("DB_HOST", "localhost"),
        port=int(get_env("DB_PORT", "3306")),
        user=get_env("DB_USER", "root"),
        password=get_env("DB_PASSWORD", ""),
        database=get_env("DB_NAME", "career_intelligence"),
        charset="utf8mb4", use_pure=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse all JDs.")
    ap.add_argument("--dir", default="data/raw/jobs/synthetic")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    jd_dir = (PROJECT_ROOT / args.dir).resolve()
    if not jd_dir.exists():
        print(f"[error] JD dir not found: {jd_dir}")
        return 1

    txt_files = sorted(jd_dir.glob("*.txt"))
    if args.limit:
        txt_files = txt_files[: args.limit]
    if not txt_files:
        print(f"[error] no .txt JDs in {jd_dir}")
        return 1

    print(f"[init] loading skill index ...")
    idx = load_skill_index()
    print(f"[init] indexed {len(idx.skills)} skills, {len(idx.patterns)} patterns")

    conn = _connect()
    summary = {"parsed": 0, "failed": 0, "job_postings": 0,
               "job_skills_required": 0, "job_skills_preferred": 0}
    try:
        from tqdm import tqdm
        it = tqdm(txt_files, desc="parsing JDs", unit="jd")
    except ImportError:
        it = txt_files

    for fp in it:
        jd_id = fp.stem
        try:
            parsed = parse_jd(fp, idx)
            counts = persist_parsed_jd(conn, parsed, jd_id)
            summary["parsed"] += 1
            summary["job_postings"] += counts.get("job_postings", 0)
            summary["job_skills_required"] += counts.get("job_skills_required", 0)
            summary["job_skills_preferred"] += counts.get("job_skills_preferred", 0)
        except KeyboardInterrupt:
            print("\n[interrupt] committing partial work ...")
            conn.commit()
            break
        except Exception as e:  # noqa: BLE001
            summary["failed"] += 1
            it.write(f"  [fail] {jd_id}: {type(e).__name__}: {e}")
    conn.close()

    print()
    print("[ok] JD parse run complete.")
    for k, v in summary.items():
        print(f"  {k:25s} {v}")
    if summary["failed"]:
        print(f"\n[warn] {summary['failed']} JDs failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
