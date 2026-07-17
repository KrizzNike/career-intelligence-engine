"""
Phase 0 environment smoke test.

Confirms the venv, project layout, config helpers, and that every
dependency the project will need across all 16 weeks imports cleanly.

Run from project root:
    .venv\\Scripts\\activate
    python scripts/smoke_test.py [--check-db]

Exit code 0 => foundation sound.
  --check-db   also try a live MySQL connection (requires .env configured).
               Without the flag, the DB check is skipped gracefully so the
               smoke test still passes before the database exists.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import PROJECT_ROOT, path  # noqa: E402

# Dirs that must exist for the mandated src/ layout (ProjectGuide §Python).
REQUIRED_DIRS = [
    "src/data_ingestion", "src/preprocessing", "src/nlp", "src/ml",
    "src/rag", "src/app", "src/utils",
    "data/raw", "data/processed", "sql/ddl", "tests/unit",
]

# Pure-Python Phase 0/1 deps. Lightweight, imported every run.
CORE_IMPORTS = [
    ("dotenv", "python-dotenv"),
    ("pymysql", "PyMySQL"),
    ("sqlalchemy", "SQLAlchemy"),
    ("docx", "python-docx"),
    ("pdfplumber", "pdfplumber"),
    ("loguru", "loguru"),
    ("rich", "rich"),
    ("pydantic", "pydantic"),
    ("pytest", "pytest"),
]

# Heavy ML/NLP/RAG deps from requirements-ml.txt. These cover Week 4 (parsing)
# through Week 12 (Streamlit). Importing them proves the wheel stack resolved
# correctly - critical because this is what failed on Python 3.14.
ML_IMPORTS = [
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("sklearn", "scikit-learn"),
    ("xgboost", "xgboost"),
    ("spacy", "spacy"),
    ("torch", "torch"),
    ("sentence_transformers", "sentence-transformers"),
    ("langchain", "langchain"),
    ("langchain_ollama", "langchain-ollama"),
    ("chromadb", "chromadb"),
    ("streamlit", "streamlit"),
]

# spaCy language model - imported by package name, not a PyPI distribution.
SPACY_MODEL = "en_core_web_md"


def _import_block(title, imports):
    """Import each (module, dist) pair, return list of error strings."""
    errors = []
    for mod, distname in imports:
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{distname} ({mod}): {type(e).__name__}: {e}")
    return errors


def check_spacy_model():
    """Load the spaCy model and run a tiny NER probe."""
    try:
        import spacy
        nlp = spacy.load(SPACY_MODEL)
        doc = nlp("Data analyst skilled in Python, SQL and AWS.")
        ents = [(e.text, e.label_) for e in doc.ents]
        if not ents:
            return f"{SPACY_MODEL} loaded but recognised no entities"
        return None
    except Exception as e:  # noqa: BLE001
        return f"{SPACY_MODEL}: {type(e).__name__}: {e}"


def check_db():
    """Optional live MySQL connection check. Returns (ok, message)."""
    try:
        import os
        import dotenv
        dotenv.load_dotenv(path(".env"))
        host = os.environ.get("DB_HOST", "localhost")
        port = int(os.environ.get("DB_PORT", "3306"))
        user = os.environ.get("DB_USER", "root")
        password = os.environ.get("DB_PASSWORD", "")
        db = os.environ.get("DB_NAME", "career_intelligence")
        import pymysql
        conn = pymysql.connect(host=host, port=port, user=user,
                               password=password, database=db, connect_timeout=5)
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
        conn.close()
        return True, f"MySQL {version} @ {host}:{port}/{db}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0 smoke test")
    parser.add_argument("--check-db", action="store_true",
                        help="also attempt a live MySQL connection")
    args = parser.parse_args()

    print(f"Python : {sys.version.split()[0]}")
    print(f"Root   : {PROJECT_ROOT}")
    print()

    # 1. Directory layout
    missing = [d for d in REQUIRED_DIRS if not (PROJECT_ROOT / d).is_dir()]
    if missing:
        print(f"FAIL - missing dirs: {missing}")
        return 1

    # 2. path() helper
    target = path("src", "config.py")
    assert target.is_file(), f"path() misresolves -> {target}"

    # 3. Core imports
    errors = _import_block("Core", CORE_IMPORTS)
    if errors:
        print("FAIL - core import errors:")
        for e in errors:
            print(f"   - {e}")
        return 1
    print("OK   - dirs present, config + core deps import cleanly")

    # 4. ML stack (the part that mattered for the Python-version choice)
    errors = _import_block("ML", ML_IMPORTS)
    if errors:
        print("WARN - ML import errors (install requirements-ml.txt):")
        for e in errors:
            print(f"   - {e}")
    else:
        print(f"OK   - ML/NLP/RAG stack ({len(ML_IMPORTS)} packages) imports cleanly")

    # 5. spaCy model
    err = check_spacy_model()
    if err:
        print(f"WARN - spaCy model: {err}")
        print("       run: python -m spacy download en_core_web_md")
    else:
        print(f"OK   - spaCy model '{SPACY_MODEL}' loads + NER works")

    # 6. Optional DB check
    if args.check_db:
        ok, msg = check_db()
        flag = "OK  " if ok else "FAIL"
        print(f"{flag} - DB connection: {msg}")
        if not ok:
            return 1
    else:
        print("SKIP - DB connection (pass --check-db once .env is configured)")

    print()
    print("Smoke test complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
