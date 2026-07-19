"""Test configuration: a DB cursor fixture that skips tests when MySQL is down.

Why a fixture (not a per-test connect): every Week-3 test needs the same live
cursor, and skipping must be uniform — if the DB isn't there, ALL schema/loader
tests are meaningless. The fixture opens one connection per test (cheap on
localhost) and hands over a cursor.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# tests/conftest.py is one dir deep, so parents[1] is the project root.
# (parents[2] would be C:\Users\Krish\Documents — wrong; .env lives in
# the repo root, so the old `parents[2]` left DB_PASSWORD unset and made
# every DB test skip with "Access denied ... using password: NO".)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def cur():
    """Yield a live MySQL cursor, or skip the whole test if DB is unreachable."""
    from dotenv import load_dotenv
    from src.config import get_env
    import mysql.connector

    load_dotenv(ROOT / ".env")
    try:
        conn = mysql.connector.connect(
            host=get_env("DB_HOST", "localhost"),
            port=int(get_env("DB_PORT", "3306")),
            user=get_env("DB_USER", "root"),
            password=get_env("DB_PASSWORD", ""),
            database=get_env("DB_NAME", "career_intelligence"),
            charset="utf8mb4",
            use_pure=True,
        )
    except Exception as exc:  # DB not running / not seeded
        pytest.skip(f"MySQL not available: {exc}")
    cur = conn.cursor()
    yield cur
    cur.close()
    conn.close()
