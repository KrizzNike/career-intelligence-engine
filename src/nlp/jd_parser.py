"""
JD parser (Week 5) — the Job Description Intelligence Engine.

Purpose
-------
Take raw JD text and return a STRUCTURED job profile:
    ParsedJD(job_title, company, location, industry, role_id, seniority_band,
             min_years_experience, required_skills[], preferred_skills[],
             responsibilities[], requirements[])

Mirrors src.nlp.resume_parser but for JDs. REUSES the Week-4 cleaner
(clean_text.clean) and skill matcher (skill_matcher.match) — the only
JD-specific work is:
  - role classification (which taxonomy role is this JD for?)
  - seniority + years-of-experience regex
  - responsibilities / requirements section split
  - required vs preferred skill split (preferred == "(Nice to have|Bonus)")

Industry insight: JDs and resumes are different dialects. A JD says
"5+ years building scalable ETL pipelines"; a resume says "Developed PySpark
ETL into Snowflake". Both are the same canonical skill (etl_elt). The skill
matcher (reused) collapses both to canonical IDs, which is what lets the
Week-6 matching engine compute candidate_skills ∩ job_skills.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.data_ingestion.jd_loader import RawJD, load_jd
from src.preprocessing.clean_text import clean
from src.preprocessing.section_segmenter import CANON_SECTIONS
from src.nlp.skill_matcher import SkillHit, SkillIndex, match

# spaCy is heavy; load lazily + cache the model.
_NLP = None


def _nlp():
    global _NLP
    if _NLP is None:
        import spacy
        _NLP = spacy.load("en_core_web_md")
    return _NLP


# -----------------------------------------------------------------
# Data model
# -----------------------------------------------------------------

@dataclass
class ParsedJD:
    job_title: str = ""
    company: str = ""
    location: str = ""
    industry: str = ""
    role_id: str = ""               # taxonomy role id, classified
    seniority_band: str = "mid"
    min_years_experience: int | None = None
    required_skills: list[SkillHit] = field(default_factory=list)
    preferred_skills: list[SkillHit] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    source_path: str = ""
    meta: dict = field(default_factory=dict)


# -----------------------------------------------------------------
# Section segmentation for JDs (simpler than resumes)
# -----------------------------------------------------------------

_JD_SECTION_LABELS = {
    "about the role": "about",
    "about us": "about",
    "summary": "about",
    "overview": "about",
    "responsibilities": "responsibilities",
    "what you'll do": "responsibilities",
    "the role": "responsibilities",
    "requirements": "requirements",
    "qualifications": "requirements",
    "what you'll need": "requirements",
    "preferred qualifications": "preferred",
    "nice to have": "preferred",
    "bonus": "preferred",
    "bonus points": "preferred",
}


def _segment_jd(lines: list[str]) -> dict[str, list[str]]:
    """Split JD lines into canonical sections. Anything before a recognized
    heading (the title + company line) lands in 'header'."""
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for ln in lines:
        norm = ln.strip().rstrip(":").strip().lower()
        if norm in _JD_SECTION_LABELS:
            current = _JD_SECTION_LABELS[norm]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(ln)
    return sections


# -----------------------------------------------------------------
# Extractors (each pure, returns its piece)
# -----------------------------------------------------------------

# "5+ years", "3-5 years", "2 years of experience"
# Range form captured first so "3-5 years" yields 3, not a stray "5 years".
_YEARS_RANGE_RE = re.compile(
    r"(?P<lo>\d{1,2})\s*[-–to]+\s*(?P<hi>\d{1,2})\s*years?",
    re.IGNORECASE,
)
_YEARS_RE = re.compile(
    r"(?P<n>\d{1,2})\s*(?:\+\s*)?years?",
    re.IGNORECASE,
)


def _extract_years(requirement_lines: list[str]) -> int | None:
    """Pick the MINIMUM years-of-experience from requirement lines."""
    candidates: list[int] = []
    for ln in requirement_lines:
        # First sweep: consume range forms ("3-5 years" -> 3, the band's low).
        consumed = ln
        for m in list(_YEARS_RANGE_RE.finditer(ln)):
            try:
                candidates.append(int(m.group("lo")))
            except ValueError:
                continue
            # Blank the matched span so the single-number regex doesn't
            # re-match the high end of the range as a separate candidate.
            consumed = consumed.replace(m.group(0), " ", 1)
        # Second sweep: standalone "5+ years" / "2 years".
        for m in _YEARS_RE.finditer(consumed):
            try:
                candidates.append(int(m.group("n")))
            except ValueError:
                continue
    if not candidates:
        return None
    return min(candidates)


def _infer_seniority(job_title: str, years: int | None) -> str:
    t = job_title.lower()
    if "junior" in t or "entry" in t or "graduate" in t:
        return "fresher"
    if "senior" in t or "lead" in t or "staff" in t or "principal" in t:
        return "senior"
    if years is not None and years <= 1:
        return "fresher"
    if years is not None and years >= 5:
        return "senior"
    return "mid"


# Map keyword fragments in the job title to taxonomy role ids.
_TITLE_ROLE_HINTS = {
    "data analyst": "data_analyst",
    "business data analyst": "data_analyst",
    "bi analyst": "bi_analyst",
    "business intelligence": "bi_analyst",
    "bi developer": "bi_analyst",
    "data scientist": "data_scientist",
    "applied scientist": "data_scientist",
    "data engineer": "data_engineer",
    "analytics engineer": "data_engineer",
    "data platform": "data_engineer",
    "ml engineer": "ml_engineer",
    "machine learning": "ml_engineer",
    "mlops": "ml_engineer",
}


def _classify_role(job_title: str, idx: SkillIndex) -> str:
    """Classify which taxonomy role this JD best fits.

    Strategy:
      1. Keyword match on the job title (highest signal).
      2. Fallback: which deep-vertical role shares the most canonical
         skills with the JD's matched skills.
    """
    t = job_title.lower()
    for hint, role_id in _TITLE_ROLE_HINTS.items():
        if hint in t:
            return role_id
    # Fallback: not implemented fully (would need JD skills first); default.
    return "data_analyst"


def _extract_header(header_lines: list[str]) -> tuple[str, str, str]:
    """Pull (job_title, company, location) from the JD header."""
    if not header_lines:
        return "", "", ""
    title = header_lines[0].strip()
    company, location = "", ""
    if len(header_lines) > 1:
        second = header_lines[1]
        # Format: "Company | Location"
        if "|" in second:
            parts = [p.strip() for p in second.split("|")]
            company = parts[0]
            location = parts[-1] if len(parts) > 1 else ""
        else:
            company = second.strip()
    return title, company, location


def _is_preferred_context(line: str) -> bool:
    """True if a responsibility/requirement line is in a 'preferred' context."""
    low = line.lower()
    return any(k in low for k in ("preferred", "nice to have", "bonus", "a plus"))


# -----------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------

def parse_jd(source, idx: SkillIndex) -> ParsedJD:
    """Parse a JD file (path) or RawJD into a ParsedJD. Pure logic, no DB."""
    if isinstance(source, (str, Path)):
        raw = load_jd(source)
    else:
        raw = source

    cleaned = clean(doc_text=raw.raw_text)
    lines = [ln for ln in cleaned.text.splitlines() if ln.strip()]
    sections = _segment_jd(lines)

    header_lines = sections.get("header", [])
    job_title, company, location = _extract_header(header_lines)

    responsibilities = [ln.lstrip("- ").strip()
                        for ln in sections.get("responsibilities", [])
                        if ln.strip()]
    requirement_lines = [ln for ln in sections.get("requirements", [])
                         if ln.strip()]
    preferred_lines = [ln for ln in sections.get("preferred", [])
                       if ln.strip()]

    # Merge 'preferred' lines into requirements for skill matching but flag
    # any skill matched ONLY in preferred context as preferred.
    all_requirement_lines = requirement_lines + preferred_lines
    years = _extract_years(all_requirement_lines)
    seniority = _infer_seniority(job_title, years)
    role_id = _classify_role(job_title, idx)

    # Skill matching across responsibilities + requirements (both are JD
    # signals). We classify each hit as required vs preferred based on which
    # section/line it came from.
    required_hits: dict[str, SkillHit] = {}
    preferred_hits: dict[str, SkillHit] = {}

    for ln in responsibilities + requirement_lines:
        for h in match(ln, "requirements", idx):
            # 'requirements' section passed to match() so evidence = 'inferred'
            # (JDs don't have a Skills section like resumes do).
            if h.canonical_id not in required_hits:
                required_hits[h.canonical_id] = h
    for ln in preferred_lines:
        for h in match(ln, "requirements", idx):
            if h.canonical_id not in required_hits:
                preferred_hits.setdefault(h.canonical_id, h)

    return ParsedJD(
        job_title=job_title,
        company=company,
        location=location,
        industry="data_analytics",
        role_id=role_id,
        seniority_band=seniority,
        min_years_experience=years,
        required_skills=list(required_hits.values()),
        preferred_skills=list(preferred_hits.values()),
        responsibilities=responsibilities,
        requirements=[ln.lstrip("- ").strip() for ln in requirement_lines],
        source_path=str(raw.source_path),
        meta={"n_sections": len(sections)},
    )
