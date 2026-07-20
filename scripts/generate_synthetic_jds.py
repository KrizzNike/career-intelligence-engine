"""
CLI: generate synthetic JDs as text files + JSON sidecars.

Produces balanced, labeled, PII-free JDs for the Week-5 JD parser and the
Week-6 matching engine's evaluation.

Usage:
    python scripts/generate_synthetic_jds.py --per-role 60
    python scripts/generate_synthetic_jds.py --per-role 60 --seed 7

Each JD produces TWO files:
    <id>.txt    human-readable JD (parser input)
    <id>.json   ground-truth labels (target_role + canonical required skills)
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import path  # noqa: E402
from src.data_ingestion.synthetic_jd import JDGenerator, SyntheticJD  # noqa: E402

TAXONOMY = path("data", "taxonomy", "skill_taxonomy.yaml")
DEFAULT_OUT = path("data", "raw", "jobs", "synthetic")
MANIFEST = path("data", "raw", "_manifest.csv")

SOURCE = "synthetic_jd_generator"
LICENSE = "CC0-1.0 (synthetic; no real PII)"


def write_txt(jd: SyntheticJD, dest: Path) -> None:
    dest.write_text(jd.to_text(), encoding="utf-8")


def write_json(jd: SyntheticJD, dest: Path) -> None:
    payload = {
        "jd_id": jd.jd_id,
        "target_role_id": jd.target_role_id,
        "target_role_name": jd.target_role_name,
        "job_title": jd.job_title,
        "company": jd.company,
        "industry": jd.industry,
        "seniority_band": jd.seniority_band,
        "min_years_experience": jd.min_years_experience,
        "required_skills": jd.required_skills,
        "required_skill_names": jd.required_skill_names,
        "preferred_skills": jd.preferred_skills,
        "preferred_skill_names": jd.preferred_skill_names,
        "generated_at": jd.generated_at,
        "source": SOURCE,
        "license": LICENSE,
    }
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def upsert_manifest(batch_name: str, count: int, out_root: Path) -> None:
    out_root = (Path.cwd() / out_root).resolve() if not out_root.is_absolute() \
        else out_root.resolve()
    rows: list[dict] = []
    fieldnames = ["batch", "source", "license", "count",
                  "generated_at", "path"]
    if MANIFEST.is_file():
        with MANIFEST.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    rows = [r for r in rows if r["batch"] != batch_name]
    rows.append({
        "batch": batch_name,
        "source": SOURCE,
        "license": LICENSE,
        "count": str(count),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "path": str(out_root.relative_to(ROOT)),
    })
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic JDs")
    ap.add_argument("--per-role", type=int, default=60,
                    help="JDs per deep role (default 60 -> 300 total)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    gen = JDGenerator(taxonomy_path=TAXONOMY, seed=args.seed)
    roles = gen.role_ids
    print(f"Generating {args.per_role} JDs x {len(roles)} roles "
          f"= {args.per_role * len(roles)} total (seed={args.seed})")
    print(f"Output: {args.out}")

    jds = gen.generate_batch(n_per_role=args.per_role)
    for jd in jds:
        stem = args.out / jd.jd_id
        write_txt(jd, stem.with_suffix(".txt"))
        write_json(jd, stem.with_suffix(".json"))

    total = args.per_role * len(roles)
    upsert_manifest(batch_name="synthetic_jds_v1", count=total, out_root=args.out)

    print(f"\nDone. {total} JDs, {total * 2} files written.")
    print(f"Manifest updated: {MANIFEST.relative_to(ROOT)}")
    from collections import Counter
    counts = Counter(jd.target_role_id for jd in jds)
    for rid in roles:
        print(f"  {rid:20s} {counts[rid]} JDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
