# Helper module so every script can locate project root + load env consistently
import os
from pathlib import Path

# Project root = parent of src/
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_env(key: str, default=None) -> str:
    """Return env var, falls back to .env (loaded lazily so tests don't need dotenv)."""
    val = os.environ.get(key)
    if val is None and default is not None:
        return default
    return val


def path(*parts: str) -> Path:
    """Resolve a path relative to project root."""
    return PROJECT_ROOT.joinpath(*parts)
