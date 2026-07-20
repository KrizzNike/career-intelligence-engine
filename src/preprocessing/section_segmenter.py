"""
Section segmentation for parsed resumes (Week 4).

Purpose
-------
Split a cleaned list of blocks into labeled section spans so the
extractors know the *context* each block was written in. Context is what
makes extraction defensible:
    - A skill mentioned under SKILLS => evidence='explicit'
    - The same skill mentioned under EXPERIENCE => evidence='inferred'
    - The same skill mentioned under PROJECTS => evidence='inferred'
  The Week-7 readiness scorer and the RAG advisor both rely on this
  evidence split to make a score *explainable* ("we counted SQL from
  your Skills section AND your project X") rather than a black-box sum.

How it works
------------
Two paths converge on the same section map:

  DOCX path: the loader already classified each block with kind =
    'title' | 'heading' | 'subheading' | 'bullet' | 'normal'. A block
    with kind='heading' or style 'Heading 1' starts a new SECTOR, and its
    text is the section label (matched to a canonical name below).
  PDF path: blocks are all kind='normal'; we detect section starts by
    matching block text against known resume headings (case-insensitive
    on a curated label set), since PDF text commonly yields UPPERCASE
    labels ('SKILLS', 'EXPERIENCE') that lack style metadata.

Both paths assign blocks into sections keyed by a CANONICAL section name
(summary, skills, experience, projects, education, certifications, other).
Anything before the first known heading (the name + contact line) goes
into a synthetic 'header' section we use to extract the candidate name
and contact info.

Inputs
------
list[Block] (cleaned). The block list comes from src.preprocessing.clean_text.

Outputs
-------
Sections = dict[canonical_section_name -> list[Block]]

Testing example
---------------
    from src.data_ingestion.resume_loader import load_resume
    from src.preprocessing.clean_text import clean
    from src.preprocessing.section_segmenter import segment
    d = load_resume("data/raw/resumes/synthetic/bi_analyst_0000.docx")
    c = clean(blocks=d.blocks)
    secs = segment(c.blocks)
    assert "skills" in secs and "experience" in secs
"""
from __future__ import annotations

from src.data_ingestion.resume_loader import Block, SECTION_LABELS


# Canonical section names we reduce every variant to.
CANON_SECTIONS = (
    "summary", "skills", "experience", "projects",
    "education", "certifications",
)

# Header (name + contact) is synthetic — not a real resume heading.
HEADER = "header"


def _canonical(label: str) -> str | None:
    """Map a free-form heading text to a canonical section name, if known."""
    norm = label.strip().lower().rstrip(":").rstrip(".").strip()
    if not norm:
        return None
    # Exact-then-substring against known section labels.
    if norm in SECTION_LABELS:
        for canon in CANON_SECTIONS:
            if canon in norm or norm in canon:
                # 'technical skills' -> 'skills'; 'work experience' -> 'experience'
                return canon
        return None
    # Substring match (e.g. 'Professional Experience')
    for canon in CANON_SECTIONS:
        if canon in norm:
            return canon
    # One-off synonyms the curated SECTION_LABELS set captures.
    synonyms = {
        "objective": "summary", "profile": "summary", "about": "summary",
        "core competencies": "skills", "technical skills": "skills",
        "work experience": "experience", "professional experience": "experience",
        "work history": "experience", "employment": "experience",
        "personal projects": "projects", "key projects": "projects",
        "academic": "education", "education & training": "education",
        "certificates": "certifications", "licenses": "certifications",
    }
    if norm in synonyms:
        return synonyms[norm]
    return None


def _is_heading(block: Block) -> bool:
    """True if this block starts a new section (DOCX kind/style OR PDF label)."""
    if block.kind in ("heading",):
        return True
    if block.style and "heading 1" in block.style.lower():
        return True
    # PDF fallback: a 'normal' block whose text IS a known section label.
    return _canonical(block.text) is not None


def segment(blocks: list[Block]) -> dict[str, list[Block]]:
    """Return {canonical_section -> list[blocks]}.

    Anything before the first recognized heading lands in the synthetic
    'header' section (name + contact line). Unrecognized heading text
    becomes its own bucket under its raw text so nothing is silently
    dropped — downstream can inspect 'other' for surprises.
    """
    sections: dict[str, list[Block]] = {HEADER: []}
    current = HEADER
    for b in blocks:
        if _is_heading(b):
            canon = _canonical(b.text)
            current = canon if canon else f"other::{b.text.strip().lower()}"
            sections.setdefault(current, [])
            # The heading block itself is NOT added to the section body;
            # its text is the label, already consumed to pick `current`.
            continue
        sections.setdefault(current, []).append(b)
    return sections
