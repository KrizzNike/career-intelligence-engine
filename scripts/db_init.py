"""
Career Intelligence Engine — database initializer (Week 3).

Purpose
-------
Idempotently stand up the full MySQL schema for the platform:
  1. DDL 01  -> database + charset
  2. DDL 02  -> 14 operational tables (3NF)
  3. DDL 03  -> supplemental hot-path indexes
  4. seed    -> Skill_Taxonomy + Skills + Skill_Alias from the taxonomy YAML
  5. views   -> star-schema analytics layer (4 dims + 1 fact) for Power BI

Why one orchestrator (not "run the .sql files by hand"):
  - Reproducibility: a single command recreates the whole schema from zero,
    which is what Week 4/5/6 pipelines and CI will call before they insert.
  - Order matters: tables must exist before indexes, taxonomy before skills,
    operational tables before views. Encoding that order in code (with the
    file list below) removes a class of "forgot to run 03_indexes.sql" bugs.
  - Idempotency: every DDL/DML/view file is written to be re-runnable
    (DROP ... IF EXISTS, INSERT ... ON DUPLICATE KEY). This script can be
    invoked any number of times during development.

Design
------
SQL files are executed as multi-statement scripts via the mysql connector's
multi=True. Connection params come from the environment (loaded from .env).

Usage
-----
    python scripts/db_init.py            # build + seed + views
    python scripts/db_init.py --reset    # DROP everything first (dev only)
    python scripts/db_init.py --skip-seed

Exit codes: 0 success, non-zero on any SQL error.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Allow running as `python scripts/db_init.py` from project root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_env  # noqa: E402

try:
    import mysql.connector
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "mysql-connector-python not installed. "
        "Run: pip install -r requirements.txt"
    ) from exc


# -----------------------------------------------------------------
# SQL files, in dependency order. Adding a new migration = append here.
# -----------------------------------------------------------------
SQL_FILES = [
    "sql/ddl/01_create_database.sql",
    "sql/ddl/02_tables.sql",
    "sql/ddl/03_indexes.sql",
    "sql/dml/01_seed_taxonomy.sql",
    "sql/views/star_schema.sql",
]


def _conn(database: str | None = "__default__"):
    """Open a connection using env vars (.env loaded via dotenv).

    If `database` is None, connect to the SERVER with no default database —
    needed after --reset (the DB was just dropped) so we can run
    01_create_database.sql which recreates it.
    """
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    if database == "__default__":
        database = get_env("DB_NAME", "career_intelligence")

    kwargs = dict(
        host=get_env("DB_HOST", "localhost"),
        port=int(get_env("DB_PORT", "3306")),
        user=get_env("DB_USER", "root"),
        password=get_env("DB_PASSWORD", ""),
        charset="utf8mb4",
        use_pure=True,
    )
    if database:
        kwargs["database"] = database
    return mysql.connector.connect(**kwargs)


_STMT_SPLIT = re.compile(r";\s*$", re.MULTILINE)

CREATE_OR_REPLACE_VIEW_OK = True  # placeholder for later view-version sanity


def _split_statements(sql_text: str) -> list[str]:
    """Split a .sql file into executable statements.

    Strips `--` comments and blank lines first, then splits on `;` at end of
    line. Sufficient for our hand-written DDL/DML/views — none of our SQL
    embeds a literal `\`;\\n` inside a string (the only failure mode of this
    naive splitter) as of Week 3.
    """
    kept = [ln for ln in sql_text.splitlines()
            if ln.strip() and not ln.strip().startswith("--")]
    cleaned = "\n".join(kept)
    return [s.strip() for s in _STMT_SPLIT.split(cleaned) if s.strip()]


def _run_script(cur, path: Path) -> None:
    """Execute a .sql file statement-by-statement (not multi=True).

    Why not multi=True: mysql-connector's pure-Python multi-statement path
    stops after the first OK packet when the script opens with `USE db;`,
    silently skipping every statement after it. Splitting and executing one
    statement at a time guarantees all statements run and gives clean,
    per-statement error reporting (the failing statement, not a vague
    multi-result failure).
    """
    sql = path.read_text(encoding="utf-8")
    if not sql.strip():
        print(f"  [skip] {path.name} (empty)")
        return
    stmts = _split_statements(sql)
    for stmt in stmts:
        cur.execute(stmt)
        while cur.nextset():  # drain any multi-row artifacts defensively
            pass


def _summary(cur) -> None:
    """Print post-build row counts for the key tables (a smoke check)."""
    cur.execute("SHOW TABLES")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\n  tables created: {len(tables)}")
    # Show counts for tables we actually seed during init.
    for t in ("Skill_Taxonomy", "Skills", "Skill_Alias"):
        if t in tables:
            cur.execute(f"SELECT COUNT(*) FROM `{t}`")
            print(f"  {t}: {cur.fetchone()[0]} rows")
    cur.execute(
        "SELECT table_name FROM information_schema.views "
        "WHERE table_schema = DATABASE()"
    )
    views = [r[0] for r in cur.fetchall()]
    if views:
        print(f"  views: {views}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Initialize the MySQL schema.")
    ap.add_argument(
        "--reset", action="store_true",
        help="DROP the database first (dev only — destroys all data).")
    ap.add_argument(
        "--skip-seed", action="store_true",
        help="Skip the taxonomy seed DML. WARNING: because the DDL files "
             "DROP+CREATE every table, re-running db_init WITHOUT --reset "
             "will WIPE loaded data (Candidates, Candidate_Skills, etc.). "
             "Use --skip-seed only when the taxonomy is already seeded AND "
             "you intend to rebuild empty tables + views. The safe order is: "
             "db_init --reset  ->  load_resumes  ->  tests.")
    args = ap.parse_args()

    if args.reset:
        # Connect WITHOUT a database to issue the DROP.
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        admin = mysql.connector.connect(
            host=get_env("DB_HOST", "localhost"),
            port=int(get_env("DB_PORT", "3306")),
            user=get_env("DB_USER", "root"),
            password=get_env("DB_PASSWORD", ""),
            charset="utf8mb4",
            use_pure=True,
        )
        acur = admin.cursor()
        db = get_env("DB_NAME", "career_intelligence")
        acur.execute(f"DROP DATABASE IF EXISTS `{db}`")
        acur.close()
        admin.close()
        print(f"[reset] dropped database `{db}`")

    files = [f for f in SQL_FILES
             if not (args.skip_seed and "seed_taxonomy" in f)]

    # After --reset the DB is gone, so connect without a default database;
    # 01_create_database.sql recreates it and issues USE. Otherwise connect
    # straight to career_intelligence.
    conn = _conn(database=None if args.reset else "__default__")
    cur = conn.cursor()
    try:
        for rel in files:
            path = ROOT / rel
            if not path.exists():
                print(f"  [missing] {rel} — skipping")
                continue
            print(f"[run] {rel}")
            _run_script(cur, path)
            conn.commit()
        _summary(cur)
        print("\n[ok] database initialized.")
    except mysql.connector.Error as e:
        print(f"\n[error] {e}")
        return 1
    finally:
        cur.close()
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
