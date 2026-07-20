"""
JD text loader (Week 5).

Reads a .txt job description file (synthetic) or accepts raw text. Returns a
RawJD intermediate that the parser consumes. Intentionally simple vs the
resume loader: JDs are flat text (no styles, no PDFs to wrangle).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RawJD:
    source_path: str
    raw_text: str
    file_format: str   # "txt" | "inline"

    @property
    def n_chars(self) -> int:
        return len(self.raw_text)


def load_jd(path: str | Path) -> RawJD:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    ext = p.suffix.lower().lstrip(".")
    if ext != "txt":
        raise ValueError(f"unsupported JD format: {ext} ({p})")
    return RawJD(
        source_path=str(p),
        raw_text=p.read_text(encoding="utf-8"),
        file_format="txt",
    )


def load_jd_text(text: str, source_path: str = "<inline>") -> RawJD:
    """Construct a RawJD directly from text (used by Streamlit / API later)."""
    if not text or not text.strip():
        raise ValueError("empty JD text")
    return RawJD(source_path=source_path, raw_text=text, file_format="inline")
