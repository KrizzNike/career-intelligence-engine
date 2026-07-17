"""
Phase 0 environment smoke test.
Confirms the venv, project layout, config helpers, and that the
Phase 0/1 pure-Python dependencies import cleanly.

Run from project root:
    .venv\\Scripts\\activate
    python scripts/smoke_test.py

Exit code 0 => foundation sound.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import PROJECT_ROOT, path  # noqa: E402

REQUIRED_DIRS = [
    "src/data_ingestion", "src/preprocessing", "src/nlp", "src/ml",
    "src/rag", "src/app", "src/utils",
    "data/raw", "data/processed", "sql/ddl", "tests/unit",
]

REQUIRED_IMPORTS = [
    ("dotenv", "python-dotenv"),
    ("pymysql", "PyMySQL"),
    ("sqlalchemy", "SQLAlchemy"),
    ("docx", "python-docx"),
    ("pdfplumber", "pdfplumber"),
    ("loguru", "loguru"),
    ("rich", "rich"),
    ("dotenv", "python-dotenv"),
    ("pydantic", "pydantic"),
    ("pytest", "pytest"),
]


def main() -> int:
    print(f"Python : {sys.version.split()[0]}")
    print(f"Root   : {PROJECT_ROOT}")

    missing = [d for d in REQUIRED_DIRS if not (PROJECT_ROOT / d).is_dir()]
    if missing:
        print(f"FAIL - missing dirs: {missing}")
        return 1

    target = path("src", "config.py")
    assert target.is_file(), f"path() misresolves -> {target}"

    import_errors = []
    for mod, distname in REQUIRED_IMPORTS:
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            import_errors.append(f"{distname} ({mod}): {e}")

    if import_errors:
        print("FAIL - import errors:")
        for e in import_errors:
            print(f"   - {e}")
        return 1

    print("OK   - all dirs present, config + Phase 0 deps import cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
