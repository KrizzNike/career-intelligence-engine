"""
JD parser evaluation (Week 5).

Purpose
-------
Score the Week-5 JD parser against the synthetic JD ground-truth labels
(data/raw/jobs/synthetic/*.json). Same methodology as Week 4's
evaluate_parser.py: per-JD precision/recall/F1 on required_skills,
micro-averaged across all 300 JDs.

Usage
-----
    python scripts/evaluate_jd_parser.py
    python scripts/evaluate_jd_parser.py --dir data/raw/jobs/synthetic --limit 50

Output
------
Per-role and overall precision/recall/F1. Exits 0 if overall F1 >= --min-f1.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from dotenv import load_dotenv  # noqa: E402
from src.config import PROJECT_ROOT  # noqa: E402
from src.nlp.skill_matcher import load_skill_index  # noqa: E402
from src.nlp.jd_parser import parse_jd  # noqa: E402
from src.data_ingestion.jd_loader import load_jd  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def evaluate(jd_dir: Path, limit: int | None) -> dict:
    idx = load_skill_index()
    txt_files = sorted(jd_dir.glob("*.txt"))
    if limit:
        txt_files = txt_files[:limit]

    roles: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0})
    coverage = {"job_title": 0, "years": 0, "role_id": 0, "total": 0}

    for fp in txt_files:
        jd_id = fp.stem
        json_fp = fp.with_suffix(".json")
        if not json_fp.exists():
            continue
        gt = json.loads(json_fp.read_text(encoding="utf-8"))
        gt_skills = set(gt.get("required_skills", []))
        role = gt.get("target_role_id", "unknown")

        parsed = parse_jd(fp, idx)
        pred_skills = {h.canonical_id for h in parsed.required_skills}

        tp = len(pred_skills & gt_skills)
        fp = len(pred_skills - gt_skills)
        fn = len(gt_skills - pred_skills)
        roles[role]["tp"] += tp
        roles[role]["fp"] += fp
        roles[role]["fn"] += fn

        coverage["total"] += 1
        coverage["job_title"] += 1 if parsed.job_title else 0
        coverage["years"] += 1 if parsed.min_years_experience is not None else 0
        coverage["role_id"] += 1 if parsed.role_id == role else 0

    # Overall micro-avg.
    tot = {"tp": 0, "fp": 0, "fn": 0}
    for r in roles.values():
        for k in tot:
            tot[k] += r[k]
    overall_p, overall_r, overall_f1 = _prf(tot["tp"], tot["fp"], tot["fn"])

    per_role = {}
    for role, c in roles.items():
        per_role[role] = dict(zip(("precision", "recall", "f1"),
                                  _prf(c["tp"], c["fp"], c["fn"])))

    return {
        "n_jds": coverage["total"],
        "overall": {"precision": overall_p, "recall": overall_r, "f1": overall_f1},
        "per_role": per_role,
        "coverage": coverage,
    }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the JD parser.")
    ap.add_argument("--dir", default="data/raw/jobs/synthetic")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-f1", type=float, default=0.80)
    args = ap.parse_args()

    jd_dir = (PROJECT_ROOT / args.dir).resolve()
    print(f"[eval] parsing JDs in {jd_dir} ...")
    res = evaluate(jd_dir, args.limit)

    print(f"\n[eval] evaluated {res['n_jds']} JDs.")
    print(f"\n=== SKILL EXTRACTION (micro-averaged across all JDs) ===")
    ov = res["overall"]
    print(f"  precision: {_pct(ov['precision'])}")
    print(f"  recall:    {_pct(ov['recall'])}")
    print(f"  F1:        {_pct(ov['f1'])}")
    print(f"\n=== PER ROLE ===")
    for role, m in sorted(res["per_role"].items()):
        print(f"  {role:18s} P={_pct(m['precision'])}  "
              f"R={_pct(m['recall'])}  F1={_pct(m['f1'])}")
    cv = res["coverage"]
    n = cv["total"]
    print(f"\n=== STRUCTURAL COVERAGE ===")
    print(f"  job_title:    {cv['job_title']}/{n} = {_pct(cv['job_title'] / n if n else 0)}")
    print(f"  years_exp:    {cv['years']}/{n} = {_pct(cv['years'] / n if n else 0)}")
    print(f"  role_match:   {cv['role_id']}/{n} = {_pct(cv['role_id'] / n if n else 0)}")

    ok = ov["f1"] >= args.min_f1
    print(f"\n[{'ok' if ok else 'warn'}] overall F1 {_pct(ov['f1'])}"
          f" vs threshold {args.min_f1:.2f}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())