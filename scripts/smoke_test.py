"""
Phase 0 smoke test — confirms the Python environment and imports resolve.
Run from project root:
    .venv\\Scripts\\activate
    python scripts/smoke_test.py

Exits 0 if the foundation is sound.
"""
import sys
from pathlib import Path

# Ensure project root (where src/ lives) is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import PROJECT_ROOT, path  # noqa: E402

REQUIRED_DIRS = [
    "src/data_ingestion", "src/preprocessing", "src/nlp", "src/ml",
    "src/rag", "src/app", "src/utils",
    "data/raw", "data/processed", "sql/ddl", "tests/unit",
]


def main() -> int:
    print(f"Project root: {PROJECT_ROOT}")

    missing = [d for d in REQUIRED_DIRS if not (PROJECT_ROOT / d).is_dir()]
    if missing:
        print(f"FAIL - missing directories: {missing}")
        return 1

    # Confirm a path() helper resolves correctly
    target = path("src", "config.py")
    assert target.is_file(), f"path() misresolves -> {target}"
    print("OK - all directories present and config importable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
