"""
Generate SQL INSERT statements from skill_taxonomy.yaml.

Reads the YAML, produces:
  1. Skill_Taxonomy rows (hierarchy nodes)
  2. Skills rows (canonical master list, deduped)
  3. Skill_Alias rows (from the 'aliases' field)

Output goes to stdout; redirect to a .sql file.
Usage:
    python scripts/taxonomy_to_sql.py > sql/dml/seed_taxonomy.sql
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_FILE = ROOT / "data" / "taxonomy" / "skill_taxonomy.yaml"


def _esc(val):
    """Escape a string for SQL single-quoted literal."""
    if val is None:
        return "NULL"
    return "'" + str(val).replace("'", "''") + "'"


def main():
    with open(TAXONOMY_FILE, "r", encoding="utf-8") as fh:
        tax = yaml.safe_load(fh)

    lines = []
    lines.append("-- Auto-generated from skill_taxonomy.yaml v{}".format(
        tax.get("schema_version", "?")))
    lines.append("-- Run AFTER 02_tables.sql creates the tables.")
    lines.append("")
    lines.append("USE career_intelligence;")
    lines.append("")

    # --- 1. Skill_Taxonomy hierarchy ---
    lines.append("-- Skill_Taxonomy (hierarchy nodes)")
    tax_rows = []
    id_map = {}  # (industry, role, category, skill) -> row index

    for ind in tax.get("industries", []):
        ind_id = ind["id"]
        # Industry node
        tax_rows.append((ind_id, None, None, None,
                         "industry", ind["name"], None, None))
        idx = len(tax_rows) - 1
        id_map[(ind_id,)] = idx + 1  # 1-based auto-increment offset

        for role in ind.get("roles", []):
            role_id = role["id"]
            tax_rows.append((ind_id, role_id, None, None,
                             "role", role["name"], idx + 1, None))
            role_idx = len(tax_rows) - 1
            id_map[(ind_id, role_id)] = role_idx + 1

            for cat in role.get("categories", []):
                cat_id = cat["id"]
                tax_rows.append((ind_id, role_id, cat_id, None,
                                 "category", cat["name"], role_idx + 1, None))
                cat_idx = len(tax_rows) - 1
                id_map[(ind_id, role_id, cat_id)] = cat_idx + 1

                for sk in cat.get("skills", []):
                    sk_id = sk["id"]
                    imp = sk.get("importance")
                    tax_rows.append((ind_id, role_id, cat_id, sk_id,
                                     "skill", sk["name"], cat_idx + 1, imp))
                    sk_idx = len(tax_rows) - 1
                    id_map[(ind_id, role_id, cat_id, sk_id)] = sk_idx + 1

                    for sub in sk.get("sub_skills", []) or []:
                        tax_rows.append((ind_id, role_id, cat_id, sk_id,
                                         "sub_skill", sub, sk_idx + 1, None))

    lines.append("INSERT INTO Skill_Taxonomy "
                 "(industry_id, role_id, category_id, skill_id, "
                 "node_type, node_name, parent_id, importance) VALUES")
    val_lines = []
    for r in tax_rows:
        vals = ", ".join(_esc(v) for v in r)
        val_lines.append(f"  ({vals})")
    lines.append(",\n".join(val_lines) + ";")
    lines.append("")

    # --- 2. Skills (canonical, deduped) + Skill_Alias ---
    # Collect unique (canonical_id, canonical_name, importance) across all roles.
    skill_map = {}  # canonical_id -> (name, importance, aliases)
    for ind in tax.get("industries", []):
        for role in ind.get("roles", []):
            for cat in role.get("categories", []):
                for sk in cat.get("skills", []):
                    sid = sk["id"]
                    if sid not in skill_map:
                        skill_map[sid] = (sk["name"],
                                          sk.get("importance", "medium"),
                                          sk.get("aliases", []))
                    else:
                        # Merge aliases from other role occurrences
                        existing = skill_map[sid]
                        for a in sk.get("aliases", []) or []:
                            if a not in existing[2]:
                                existing[2].append(a)

    # Skills table columns: canonical_id, canonical_name, taxonomy_id (FK).
    # `importance` is NOT a Skills column — it lives on the Skill_Taxonomy
    # node (per sql/ddl/02_tables.sql). We link taxonomy_id via the UPDATE
    # statement below, so the INSERT only carries the two identity columns.
    lines.append("-- Skills (canonical master list, deduped)")
    lines.append("INSERT INTO Skills (canonical_id, canonical_name) VALUES")
    skill_vals = []
    for sid, (name, _imp, _) in skill_map.items():
        skill_vals.append(f"  ({_esc(sid)}, {_esc(name)})")
    lines.append(",\n".join(skill_vals) + ";")
    lines.append("")

    # --- 3. Skill_Alias ---
    lines.append("-- Skill_Alias (alternate surface forms -> canonical skill)")
    lines.append("-- We resolve the canonical_id to Skills.id after insert using a subquery.")
    alias_vals = []
    for sid, (_, _, aliases) in skill_map.items():
        for a in aliases:
            alias_vals.append(f"  ({_esc(a)}, {_esc(a.lower().strip())}, "
                              f"(SELECT id FROM Skills WHERE canonical_id = {_esc(sid)}))")
    if alias_vals:
        # INSERT IGNORE: a normalized alias is globally UNIQUE. The taxonomy
        # may legitimately repeat an alias across a skill's multiple category
        # appearances (e.g. 'T-SQL' for SQL in two categories). INSERT IGNORE
        # keeps the first and silently skips the collision instead of aborting
        # the whole multi-row insert.
        lines.append("INSERT IGNORE INTO Skill_Alias "
                     "(alias_text, alias_text_norm, skill_id) VALUES")
        lines.append(",\n".join(alias_vals) + ";")
    else:
        lines.append("-- (no aliases defined yet)")
    lines.append("")

    # --- 4. Link Skills.taxonomy_id to first matching Skill_Taxonomy node ---
    lines.append("-- Link each Skill to its Skill_Taxonomy node (first match)")
    lines.append("UPDATE Skills s")
    lines.append("  JOIN Skill_Taxonomy st")
    lines.append("    ON st.skill_id = s.canonical_id AND st.node_type = 'skill'")
    lines.append("  SET s.taxonomy_id = st.id;")
    lines.append("")

    out = "\n".join(lines)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(out, encoding="utf-8")
        print(f"Wrote {len(tax_rows)} taxonomy rows + "
              f"{len(skill_map)} skills to {sys.argv[1]}")
    else:
        print(out)


if __name__ == "__main__":
    main()
