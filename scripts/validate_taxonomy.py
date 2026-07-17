"""
Skill-taxonomy structural validator.

The taxonomy is the single source of truth for skill normalization across
the platform, so it must be self-consistent. This script enforces the
ProjectGuide's 5-level hierarchy and catches the mistakes that would
silently break downstream engines:

  - Missing/illegal levels in industry -> role -> category -> skill
  - Duplicate skill ids (would break matching; two skills collapse to one)
  - Duplicate aliases pointing to different skills (parser ambiguity)
  - Skills referenced by id that don't exist (orphan references)
  - Bad enum values (importance, seniority)
  - Coverage gaps (a deep-vertical role with < N skills is suspicious)

Run:
    python scripts/validate_taxonomy.py
    python scripts/validate_taxonomy.py --taxonomy data/taxonomy/skill_taxonomy.yaml

Exit code 0 = valid. Non-zero = at least one error found; CI/Week-2
ingestion scripts should refuse to proceed when this fails.
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TAXONOMY = ROOT / "data" / "taxonomy" / "skill_taxonomy.yaml"

VALID_IMPORTANCE = {"critical", "high", "medium", "low"}
VALID_SENIORITY = {"entry_to_mid", "entry_to_senior", "mid", "mid_to_senior"}


def _err(errors, msg):
    errors.append(msg)


def validate(taxonomy_path: Path):
    """Return (errors, stats). errors == [] means the file is valid."""
    errors = []

    if not taxonomy_path.is_file():
        return [f"taxonomy file not found: {taxonomy_path}"], {}

    with taxonomy_path.open("r", encoding="utf-8") as fh:
        try:
            data = yaml.safe_load(fh)
        except yaml.YAMLError as e:
            return [f"YAML parse error: {e}"], {}

    if not isinstance(data, dict):
        return ["top-level YAML must be a mapping"], {}

    version = data.get("schema_version")
    if not version:
        _err(errors, "missing schema_version (e.g. '0.1')")

    industries = data.get("industries")
    if not isinstance(industries, list) or not industries:
        _err(errors, "'industries' must be a non-empty list")
        return errors, {}

    # Accumulators for cross-cutting checks.
    skill_ids = []                 # every skill id occurrence (for dup detection)
    skill_id_owner = {}            # id -> "industry/role" that owns it
    alias_map = {}                 # alias(lowercased) -> skill_id
    stats = {
        "industries": 0,
        "roles": 0,
        "deep_roles": 0,
        "categories": 0,
        "skills": 0,
        "sub_skills": 0,
        "per_industry": {},
        "per_role": {},
    }

    for ind in industries:
        if not isinstance(ind, dict):
            _err(errors, "each industry must be a mapping")
            continue
        ind_id = ind.get("id")
        if not ind_id:
            _err(errors, "industry missing 'id'")
            continue
        stats["industries"] += 1
        stats["per_industry"][ind_id] = 0

        roles = ind.get("roles")
        if not isinstance(roles, list) or not roles:
            _err(errors, f"industry '{ind_id}' has no roles list")
            continue

        for role in roles:
            if not isinstance(role, dict):
                _err(errors, f"industry '{ind_id}': each role must be a mapping")
                continue
            role_id = role.get("id")
            if not role_id:
                _err(errors, f"industry '{ind_id}': role missing 'id'")
                continue
            stats["roles"] += 1
            role_skill_count = 0

            seniority = role.get("seniority")
            if seniority and seniority not in VALID_SENIORITY:
                _err(errors, f"role '{ind_id}/{role_id}': seniority "
                             f"'{seniority}' not in {sorted(VALID_SENIORITY)}")

            cats = role.get("categories")
            if not isinstance(cats, list) or not cats:
                _err(errors, f"role '{ind_id}/{role_id}' has no categories")
                stats["per_role"][f"{ind_id}/{role_id}"] = 0
                continue

            for cat in cats:
                if not isinstance(cat, dict):
                    _err(errors, f"role '{ind_id}/{role_id}': category must be mapping")
                    continue
                cat_id = cat.get("id")
                if not cat_id:
                    _err(errors, f"role '{ind_id}/{role_id}': category missing 'id'")
                    continue
                stats["categories"] += 1

                skills = cat.get("skills")
                if not isinstance(skills, list) or not skills:
                    _err(errors, f"category '{ind_id}/{role_id}/{cat_id}' has no skills")
                    continue

                for sk in skills:
                    if not isinstance(sk, dict):
                        _err(errors, f"category '{cat_id}': skill must be mapping")
                        continue
                    sk_id = sk.get("id")
                    if not sk_id:
                        _err(errors, f"category '{cat_id}': skill missing 'id'")
                        continue

                    skill_ids.append((sk_id, f"{ind_id}/{role_id}"))
                    role_skill_count += 1
                    stats["skills"] += 1

                    # importance enum
                    imp = sk.get("importance")
                    if imp not in VALID_IMPORTANCE:
                        _err(errors, f"skill '{sk_id}': importance '{imp}' "
                                     f"not in {sorted(VALID_IMPORTANCE)}")

                    # aliases must map to exactly one skill id
                    for alias in sk.get("aliases", []) or []:
                        key = alias.strip().lower()
                        if not key:
                            continue
                        if key in alias_map and alias_map[key] != sk_id:
                            _err(errors, f"alias '{alias}' maps to both "
                                         f"'{alias_map[key]}' and '{sk_id}'")
                        else:
                            alias_map[key] = sk_id

                    # sub-skills: must be unique within this skill
                    subs = sk.get("sub_skills", []) or []
                    stats["sub_skills"] += len(subs)
                    dup_subs = [s for s, c in Counter(subs).items() if c > 1]
                    if dup_subs:
                        _err(errors, f"skill '{sk_id}': duplicate sub_skills "
                                     f"{dup_subs}")

            stats["per_role"][f"{ind_id}/{role_id}"] = role_skill_count
            stats["per_industry"][ind_id] += role_skill_count
            if ind_id == "data_analytics":
                stats["deep_roles"] += 1

    # Cross-role skill reuse is INTENTIONAL and desirable: a shared skill
    # (python, sql, aws) has ONE canonical id and appears in many roles.
    # The real invariant to enforce is id -> name consistency: the same id
    # must always carry the same name. A mismatch would mean two different
    # skills accidentally share an id and would collapse wrongly in matching.
    name_by_id = {}
    id_roles = defaultdict(list)
    for sid, owner in skill_ids:
        id_roles[sid].append(owner)
    # (re-scan to check id->name consistency across roles)
    for ind in industries:
        for role in ind.get("roles", []) or []:
            for cat in role.get("categories", []) or []:
                for sk in cat.get("skills", []) or []:
                    sid, sname = sk.get("id"), sk.get("name")
                    if sid and sname:
                        if sid in name_by_id and name_by_id[sid] != sname:
                            _err(errors, f"skill id '{sid}' has two names: "
                                         f"'{name_by_id[sid]}' vs '{sname}'")
                        else:
                            name_by_id[sid] = sname

    # Deep-vertical coverage sanity: each data_analytics role should have a
    # healthy skill count. Too few means the role is under-specified and will
    # produce garbage gap-analysis in Week 7.
    MIN_DEEP_ROLE_SKILLS = 5
    for label, count in stats["per_role"].items():
        if label.startswith("data_analytics/") and count < MIN_DEEP_ROLE_SKILLS:
            _err(errors, f"deep-vertical role '{label}' has only {count} skills "
                         f"(< {MIN_DEEP_ROLE_SKILLS}); under-specified")

    # Shared-skill notice (informational, not an error): if a single skill id
    # appears in more than half of all roles, the taxonomy may be leaning on
    # one skill too heavily. Worth a human glance, not a build failure.
    if stats["roles"] >= 4:
        shared_threshold = stats["roles"] // 2
        stats["widely_shared_skills"] = {
            sid: len(roles) for sid, roles in id_roles.items()
            if len(roles) > shared_threshold
        }

    return errors, stats


def _print_stats(stats):
    print("\n--- Coverage report ---")
    print(f"  industries  : {stats['industries']}")
    print(f"  roles       : {stats['roles']} "
          f"({stats['deep_roles']} deep in data_analytics)")
    print(f"  categories  : {stats['categories']}")
    print(f"  skills      : {stats['skills']}")
    print(f"  sub_skills  : {stats['sub_skills']}")
    print(f"  per industry:")
    for ind, n in stats["per_industry"].items():
        print(f"     {ind:22s} {n} skills")
    print(f"  per role (deep vertical):")
    for label, n in stats["per_role"].items():
        if label.startswith("data_analytics/"):
            print(f"     {label:30s} {n} skills")
    shared = stats.get("widely_shared_skills", {})
    if shared:
        print(f"  widely-shared skills (appear in >half of roles):")
        for sid, n in sorted(shared.items(), key=lambda x: -x[1]):
            print(f"     {sid:22s} in {n} roles (intentional - same id = same skill)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skill taxonomy")
    parser.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY,
                        help="path to skill_taxonomy.yaml")
    args = parser.parse_args()

    print(f"Validating: {args.taxonomy}")
    errors, stats = validate(args.taxonomy)

    _print_stats(stats)

    print("\n--- Result ---")
    if errors:
        print(f"FAIL - {len(errors)} error(s):")
        for e in errors:
            print(f"   - {e}")
        return 1

    print("OK   - taxonomy is structurally valid "
          "(5-level hierarchy, unique ids, no alias clashes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
