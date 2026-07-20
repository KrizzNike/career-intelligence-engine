"""
Text cleaning for parsed resumes (Week 4).

Purpose
-------
Take raw text a loader produces and return clean, parse-ready text +
normalized blocks. Cleaning is a SEPARATE stage from loading so the
same cleaner runs on text from any source (PyMuPDF, python-docx, or a
public scraped resume corpus later) and downstream extractors never
defend against encoding/bullet/hyphenation noise.

Operations (each documented with the bug it prevents):
  1. Encoding glyphs -> ASCII equivalents. PyMuPDF sometimes returns the
     Unicode replacement char (U+FFFD) for em-dashes/smart quotes the PDF
     font can't map. We collapse it to '-' and normalize smart punctuation.
  2. De-hyphenate line-wrap breaks: 'Py-\\nthon' -> 'Python'. Real resumes
     wrap words across lines; a naive join would split a skill name and
     silently lose it from skill matching.
  3. Bullet glyphs -> a single space so surrounding words don't merge
     after strip. (Bullets are also detected structurally via DOCX styles;
     this is mainly for PDF where styles are unavailable.)
  4. Collapse soft whitespace: runs of spaces/tabs -> one space; strip per
     line; drop empty lines.
  5. Fold non-ASCII letters to ASCII (cafe <- cafe, resume <- resume) so
     downstream regex skill matching runs on ASCII-normalized strings.

Inputs
------
Either raw text (str) or a list of Block. When blocks are given, each
block is cleaned and returned alongside the joined raw text.

Outputs
-------
CleanedText(text=..., blocks=[Block(...)])

Testing example
---------------
    from src.preprocessing.clean_text import clean
    c = clean(doc_text="Py-\\nthon, cafe resume - and more")
    assert "Python" in c.text and "cafe" in c.text

Dependencies
------------
stdlib only (re, unicodedata) — the cleaner stays pure and cheap.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.data_ingestion.resume_loader import Block


# Smart punctuation / problem glyphs -> ASCII replacements.
_PUNCT_MAP = {
    "—": "-",   # em dash
    "–": "-",   # en dash
    "’": "'",   # right single quote
    "‘": "'",   # left single quote
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "�": "-",    # replacement char -> separator (PyMuPDF em-dash mapping)
    " ": " ",    # non-breaking space
    "•": " ",    # bullet -> space (words around it must not merge)
}


def _normalize_punct(s: str) -> str:
    for src, dst in _PUNCT_MAP.items():
        s = s.replace(src, dst)
    return s


def _ascii_fold(s: str) -> str:
    """Fold accented letters to ASCII via NFKD; drop chars that won't fold."""
    out = unicodedata.normalize("NFKD", s)
    return out.encode("ascii", "ignore").decode("ascii")


# Bullet-like glyphs. Collapsed to a space (NOT removed) so 'X • Y' does
# not become 'XY'.
_BULLET_RE = re.compile(r"[•▪●◦⁃\*]")


def _de_hyphenate(text: str) -> str:
    """Merge a hyphen ending a line into the next word: 'Py-\\nthon'->'Python'.

    Only when the post-newline char is a lowercase letter (the canonical
    word-wrap signature), so hyphenated breaks like 'Skills -\\nAdvanced'
    survive intact.
    """
    return re.sub(r"(\w)-\s*\n\s*([a-z])", r"\1\2", text)


def _collapse_ws(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", ln).strip()
             for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


@dataclass
class CleanedText:
    text: str
    blocks: list[Block]


def clean_blocks(blocks: list[Block], fold_ascii: bool = True
                 ) -> tuple[list[Block], str]:
    """Clean blocks in place; return (cleaned_blocks, joined_clean_text).

    Block `kind` (set by the loader) is preserved — cleaning only touches
    text. `fold_ascii=False` keeps non-ASCII for NER downstream.
    """
    out: list[Block] = []
    parts: list[str] = []
    for b in blocks:
        t = _normalize_punct(b.text)
        t = _BULLET_RE.sub(" ", t)
        t = _collapse_ws(t)
        if fold_ascii:
            t = _ascii_fold(t)
        if not t:
            continue
        out.append(Block(text=t, style=b.style, kind=b.kind))
        parts.append(t)
    joined = _de_hyphenate("\n".join(parts))
    return out, joined


def clean(doc_text: str | None = None, blocks: list[Block] | None = None,
          fold_ascii: bool = True) -> CleanedText:
    """Unified entry point. Pass blocks for structural cleaning, or doc_text."""
    if blocks is not None:
        cleaned, joined = clean_blocks(list(blocks), fold_ascii=fold_ascii)
        return CleanedText(text=joined, blocks=cleaned)
    if doc_text is None:
        raise ValueError("clean() needs either doc_text or blocks")
    text = _normalize_punct(doc_text)
    text = _de_hyphenate(text)
    text = _BULLET_RE.sub(" ", text)
    text = _collapse_ws(text)
    if fold_ascii:
        text = _ascii_fold(text)
    return CleanedText(text=text, blocks=[])
