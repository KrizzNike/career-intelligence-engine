"""
Parser evaluation (Week 4).

Purpose
-------
Score the Week-4 resume parser against the Week-2 synthetic resumes'
GROUND TRUTH labels (data/raw/resumes/synthetic/*.json), the way a real
parser would be evaluated in industry. The guide explicitly forbids
skipping evaluation metrics.

What we evaluate (the two questions that matter):
  1. SKILL EXTRACTION: for each resume, the JSON 'skills' list is the
     set of canonical_ids the candidate truly has. We parse the .docx
     and compare the parser's {canonical_id} set to ground truth.
     Per-resume precision/recall are micro-averaged across all 600 to
     give precision, recall, F1 (the metrics a reviewer cares about).
  2. STRUCTURAL FIELDS: did we extract a name, at least one Education,
     at least one Experience? Reported as coverage (% of resumes with the
     field) since the synth generator guarantees these exist for every
     resume — coverage == recall-by-presence.

Why we parse .docx (not .pdf) for the score:
  The Week-2 generator renders .docx with explicit styles (Title,
  Heading 1/2, List Bullet) that segmenter + extractor handle richly;
  the .pdf is a downstream render of the same content. The .pdf parser
  is exercised by tests/test_resume_parser.py separately. Scoring on
  .docx isolates 'extraction quality' from 'PDF rendering loss'.

Usage
-----
    python scripts/evaluate_parser.py
    python scripts/evaluate_parser.py --dir data/raw/resumes/synthetic --limit 100

Output
------
A printed report: per-role and overall precision/recall/F1 + field
coverage. Exits 0 if overall F1 >= --min-f1 (default 0.80).
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
from src.nlp.resume_parser import parse_resume  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def evaluate(resume_dir: Path, limit: int | None) -> dict:
    idx = load_skill_index()
    files = sorted(resume_dir.glob("*.docx"))
    if limit:
        files = files[:limit]
    # role -> {tp, fp, fn}
    roles: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0})
    coverage = {"name": 0, "education": 0, "experience": 0,
                "projects": 0, "total": 0}

    for fp in files:
        rid = fp.stem
        json_fp = fp.with_suffix(".json")
        if not json_fp.exists():
            continue
        gt = json.loads(json_fp.read_text(encoding="utf-8"))
        gt_skills = set(gt.get("skills", []))
        # ground-truth structural presence (synth always fills these).
        role = gt.get("target_role_id", "unknown")

        parsed = parse_resume(fp, idx)
        pred_skills = {h.canonical_id for h in parsed.skills}

        tp = len(pred_skills & gt_skills)
        fp = len(pred_skills - gt_skills)
        fn = len(gt_skills - pred_skills)
        roles[role]["tp"] += tp
        roles[role]["fp"] += fp
        roles[role]["fn"] += fn

        coverage["total"] += 1
        coverage["name"] += 1 if parsed.name else 0
        coverage["education"] += 1 if parsed.education else 0
        coverage["experience"] += 1 if parsed.experience else 0
        coverage["projects"] += 1 if parsed.projects else 0

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
        "n_resumes": coverage["total"],
        "overall": {"precision": overall_p, "recall": overall_r,
                    "f1": overall_f1},
        "per_role": per_role,
        "coverage": coverage,
    }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate the resume parser.")
    ap.add_argument("--dir", default="data/raw/resumes/synthetic")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-f1", type=float, default=0.80,
                    help="Exit nonzero if overall F1 below this.")
    args = ap.parse_args()

    resume_dir = (PROJECT_ROOT / args.dir).resolve()
    print(f"[eval] parsing resumes in {resume_dir} ...")
    res = evaluate(resume_dir, args.limit)

    print(f"\n[eval] evaluated {res['n_resumes']} resumes (DOCX).")
    print(f"\n=== SKILL EXTRACTION (micro-averaged across all resumes) ===")
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
    print(f"\n=== STRUCTURAL COVERAGE (field present in parsed output) ===")
    for f in ("name", "education", "experience", "projects"):
        print(f"  {f:12s}: {cv[f]}/{n} = {_pct(cv[f] / n if n else 0)}")

    ok = ov["f1"] >= args.min_f1
    print(f"\n[{'ok' if ok else 'warn'}] overall F1 {_pct(ov['f1'])}"
          f" vs threshold {args.min_f1:.2f}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
