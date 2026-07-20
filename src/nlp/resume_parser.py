"""
Resume parser (Week 4) — the Resume Intelligence Engine.

Purpose
-------
Orchestrate the Week-4 pipeline end-to-end on a single resume file and
return a STRUCTURED candidate profile:

    ParsedResume(
        name, email, phone, location,
        education=[{degree, institution, field_of_study, year}],
        experience=[{title, company, start, end, is_current, bullets}],
        projects=[{name, description, skills}],
        certifications=[{name, issuer}],
        skills=[SkillHit(...)],   # the matched skill hits, section-tagged
        source_path, file_format, meta,
    )

This module is the ONLY place that combines cleaning + segmentation +
field extraction + skill matching. It is pure logic (no I/O, no DB)
so it is fully unit-testable on fixture files (and evaluatable against
the 600 synthetic ground-truth labels).

Design choices (the "why"):
  - spaCy NER for the name + organization entities, with a regex /
    header-position fallback when NER misses (real resumes have
    idiosyncratic names). spaCy also tokens for downstream sentence
    similarity later, but here we use only NER + token surface.
  - Field extractors are pure functions over (sections, spacy_doc) so
    each is independently testable. The parser wires them together.
  - Skill matching runs on THREE inputs independently and then de-dupes
    by canonical_id, KEEPING the strongest evidence:
        skills section  -> explicit
        experience        -> inferred
        projects          -> inferred
    A skill found in both Skills + Experience surfaces once with
    evidence='explicit' (the strongest). This is what makes the Week-7
    readiness score explainable.

Inputs
------
A loaded ResumeDocument (from src.data_ingestion.resume_loader) OR a
file path (the parser lazily loads). Plus a loaded SkillIndex.

Outputs
-------
ParsedResume dataclass.

Dependencies
------------
spaCy (en_core_web_md — installed Week 3), the cleaner/segmenter/
skill_matcher modules, re. No MySQL here (the CLI does persistence).

Testing example
---------------
    from src.data_ingestion.resume_loader import load_resume
    from src.preprocessing.clean_text import clean
    from src.nlp.skill_matcher import load_skill_index
    from src.nlp.resume_parser import parse_resume
    idx = load_skill_index()
    p = parse_resume("data/raw/resumes/synthetic/bi_analyst_0000.docx", idx)
    assert p.name == "Allison Hill"
    assert "power_bi" in {h.canonical_id for h in p.skills}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.data_ingestion.resume_loader import Block, load_resume
from src.preprocessing.clean_text import clean
from src.preprocessing.section_segmenter import segment
from src.nlp.skill_matcher import SkillHit, SkillIndex, match

# spaCy is heavy; load lazily + cache the model so re-parsing 600 resumes
# does NOT reload the model 600 times. `en_core_web_md` is installed.
_NLP = None


def _nlp():
    global _NLP
    if _NLP is None:
        import spacy
        _NLP = spacy.load("en_core_web_md")
    return _NLP


# -----------------------------------------------------------------
# Field extractors — each pure, returns its piece.
# -----------------------------------------------------------------

_PHONE_RE = re.compile(
    r"(\+?\d[\d\s().-]{7,}\d)")
_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


@dataclass
class EducationEntry:
    degree: str = ""
    institution: str = ""
    field_of_study: str = ""
    year: int | None = None


@dataclass
class ExperienceEntry:
    title: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    is_current: bool = False
    bullets: list[str] = field(default_factory=list)


@dataclass
class ProjectEntry:
    name: str = ""
    description: str = ""
    skills: list[str] = field(default_factory=list)  # canonical_ids found


@dataclass
class CertEntry:
    name: str = ""
    issuer: str = ""


@dataclass
class ParsedResume:
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    education: list[EducationEntry] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    certifications: list[CertEntry] = field(default_factory=list)
    skills: list[SkillHit] = field(default_factory=list)
    source_path: str = ""
    file_format: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


# ---------- contact + name (header) ----------

def _extract_email(text: str) -> str:
    m = _EMAIL_RE.search(text)
    return m.group(0) if m else ""


def _extract_phone(text: str) -> str:
    for line in text.splitlines():
        m = _PHONE_RE.search(line)
        if m:
            return m.group(0)
    return ""


def _extract_location(text: str) -> str:
    """The trailing segment of the contact line, after the last '|'.

    Real resumes vary; this is a synthetic-target heuristic that degrades
    reasonably. We pick the header contact line and keep the part after
    the final '|' (which the generator renders as location).
    """
    for line in text.splitlines():
        if "@" in line and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if parts:
                return parts[-1]
    return ""


def _extract_name(blocks: list[Block], doc) -> str:
    """Prefer spaCy PERSON entity in header; fallback to first header line.

    The styled Title / first header line is the name in synth resumes; real
    resumes occasionally put a tagline there, so NER is safer when it
    returns a PERSON entity that agrees with that line.

    Order of preference:
      1. The first header line if it looks like a name (1-4 words, no
         digits / @ / pipe). This is the strongest synthetic signal and
         resists NER over-extension ('Angela Brown bennettpamela' from
         NER scanning the trailing email line).
      2. A PERSON entity that EQUALS the first header line, or is a
         clean prefix of it (so 'Angela Brown' wins over 'Angela Brown
         bennettpamela'). We deliberately do NOT accept 'first in ent'
         (that direction lets over-long entities through).
      3. Last-resort PERSON entity (2+ words) from the NER doc.
    """
    first = blocks[0].text.strip() if blocks else ""
    # (1) First-line heuristic.
    if first and not re.search(r"\d|@|\|", first) and 1 <= len(first.split()) <= 4:
        return first
    if doc:
        # (2) PERSON entity matching the first line cleanly.
        for ent in doc.ents:
            if ent.label_ == "PERSON" and len(ent.text.split()) >= 2:
                if first and (ent.text == first or first.startswith(ent.text)):
                    return ent.text
        # (3) Last-resort.
        for ent in doc.ents:
            if ent.label_ == "PERSON" and len(ent.text.split()) >= 2:
                return ent.text
    return ""


# ---------- education ----------

# Degree prefixes we recognize. Covers synth + common real-world forms.
_DEGREE_TOKENS = (
    "B.Sc", "BSc", "B.Tech", "B.E.", "BE", "B.E", "B.S", "BS",
    "B.A", "BA", "B.Com", "BBA",
    "M.Sc", "MSc", "M.Tech", "ME", "M.E", "M.E.", "M.S", "MS",
    "M.A", "MA", "MBA", "MCA",
    "Ph.D", "PhD", "Doctorate", "Diploma", "Bachelor", "Master",
    "Bachelor's", "Master's",
)
_DEGREE_RE = re.compile(
    r"(?P<degree>(?:M\.?Sc|M\.?Com|M\.?Tech|M\.?E\.?|M\.?S|M\.?A|M\.?Arch|"
    r"B\.?Sc|B\.?Com|B\.?Tech|B\.?E\.?|B\.?S|B\.?A|B\.?Arch|"
    r"BBA|BCA|MCA|MBA|Ph\.?D|Doctorate|Diploma|"
    r"Bachelors?|Masters?))\.?"
    r"(?:\s+(?P<field>[A-Za-z][A-Za-z &/.\-]{0,80}?))?"
    r"\s*[-—:]\s*"
    r"(?P<inst>[A-Za-z][A-Za-z .'\-]{3,80})\s*"
    r"\(?(?P<year>20[0-2][0-9])\)?",
    re.IGNORECASE,
)
# field is OPTIONAL and non-greedy so 'M.Sc Data Science - Foo U (2021)'
# captures field='Data Science' while 'B.Com - Foo U (2021)' (no field)
# skips it. Inst is required + year at the end.
# `body` is greedy-minimal: captures 'Data Science' (field-only) OR — when
# the institution starts immediately after the dash with no field — we
# treat the captured body as degree-field-no-institution and let the
# fallback handle it. In practice the synth generator always emits
# 'Degree [field] - Institution (year)', so body == field-or-empty and
# inst always captures. A separate handler splits body into field when
# it looks like a subject and not an institution name.


def _extract_education(edu_blocks: list[Block]) -> list[EducationEntry]:
    out: list[EducationEntry] = []
    for b in edu_blocks:
        line = b.text.strip()
        m = _DEGREE_RE.search(line)
        if m:
            field_of_study = (m.group("field") or "").strip()
            out.append(EducationEntry(
                degree=m.group("degree").strip(),
                institution=m.group("inst").strip(),
                field_of_study=field_of_study,
                year=int(m.group("year")),
            ))
            continue
        # Looser fallback: line alone is the degree (no institution/year).
        for tok in _DEGREE_TOKENS:
            if tok.lower() in line.lower():
                out.append(EducationEntry(degree=line))
                break
    return out


# ---------- experience ----------

_DATE_RANGE_RE = re.compile(
    r"\(?(?P<start>[A-Za-z]{3,9}\.?\s+(?:19|20)[0-9]{2}"
    r"|(?:19|20)[0-9]{2}"
    r"|Present|Current)\)?\s*[-—to]+\s*"
    r"\(?(?P<end>[A-Za-z]{3,9}\.?\s+(?:19|20)[0-9]{2}"
    r"|(?:19|20)[0-9]{2}"
    r"|Present|Current)\)?",
    re.IGNORECASE,
)


def _extract_experience(exp_blocks: list[Block]) -> list[ExperienceEntry]:
    """Extract experience entries from a section's blocks.

    Synth layout (DOCX has 'subheading' kind on title lines; PDF has all
    'normal'): each entry is one 'Title - Company (Mon YYYY - Present)'
    heading line, optionally followed by bullet lines '[Verb] ... solution
    that improved ... by N%.' until the next heading line.

    Rules:
      * A non-bullet line containing a date-range ALWAYS starts a new entry
        (handles both the DOCX 'subheading' case and PDF's merged line).
      * Bullet lines (explicit kind OR matching the synth bullet verb
        pattern) attach to the current entry.
      * A bare title line with no date (DOCX when title & date are split
        across two blocks) starts an entry; the next date-range line fills
        in the dates.
    """
    out: list[ExperienceEntry] = []
    cur: ExperienceEntry | None = None

    def is_bullet(text: str) -> bool:
        # The synth generator emits bullets like 'Built/Developed/... solution
        # that improved team efficiency by N%.' Use that signature for the
        # PDF case where the block kind is 'normal', not 'bullet'.
        return bool(re.match(
            r"^(Built|Developed|Analyzed|Automated|Designed|Optimized|"
            r"Delivered)\b", text))

    for b in exp_blocks:
        text = b.text.strip()
        if not text:
            continue
        mdate = _DATE_RANGE_RE.search(text)
        # Strip the date segment to see what TITLE text (if any) remains.
        title_only = _DATE_RANGE_RE.sub("", text).strip(" (-):—")
        is_bull = b.kind == "bullet" or is_bullet(text)
        # ----- a) bullet line -> attach to current entry -----
        if is_bull and cur is not None:
            cur.bullets.append(text)
            continue
        # ----- b) date-range on a non-bullet line -----
        if mdate and not is_bull:
            if title_only:
                # The line has title text + dates -> new entry. Handles
                # both PDF merged lines ('Title - Co (Mon YYYY - Present)')
                # and DOCX where the subheading carries the dates inline.
                title, company = _split_title_company(title_only)
                cur = ExperienceEntry(
                    title=title, company=company,
                    start=mdate.group("start"), end=mdate.group("end"),
                    is_current=mdate.group("end").lower()
                    in ("present", "current"),
                )
                out.append(cur)
            elif cur is not None and not cur.start:
                # No title text, just a date range. Two cases:
                #  - DOCX split layout: it's the DATE line for the current
                #    entry's title (already set by the subheading).
                #  - It's mid-text noise — fill dates if missing only.
                cur.start = mdate.group("start")
                cur.end = mdate.group("end")
                cur.is_current = cur.end.lower() in ("present", "current")
            # If title_only is empty AND cur already has dates, ignore
            # (avoid spurious empty entries).
            continue
        # ----- c) bare heading line (subheading) with NO date -----
        if b.kind in ("subheading", "heading"):
            title, company = _split_title_company(text.strip(" (-):—"))
            cur = ExperienceEntry(title=title, company=company)
            out.append(cur)
            continue
        # ----- d) leftover non-bullet normal line: bullet description -----
        if cur is not None:
            cur.bullets.append(text)
    return out


def _split_title_company(text: str) -> tuple[str, str]:
    """Split 'BI Analyst - Blake and Sons' -> ('BI Analyst', 'Blake and Sons')."""
    for sep in (" - ", "—", "  ", " at ", " | "):
        if sep in text:
            t, c = text.split(sep, 1)
            return t.strip(), c.strip()
    return text.strip(), ""


# ---------- projects ----------

def _extract_projects(proj_blocks: list[Block],
                      idx: SkillIndex) -> list[ProjectEntry]:
    out: list[ProjectEntry] = []
    cur: ProjectEntry | None = None
    for b in proj_blocks:
        text = b.text.strip()
        if not text:
            continue
        if b.kind == "subheading" or text.lower().startswith("project:"):
            cur = ProjectEntry(name=text)
            out.append(cur)
            continue
        if cur is None:
            # Bullet/normal without a heading yet — start one (PDF).
            cur = ProjectEntry(name="")
            out.append(cur)
        cur.description = text
        # Skills found in this project's text -> list of canonical_ids.
        cur.skills = [h.canonical_id for h in match(text, "projects", idx)]
    return [p for p in out if p.name or p.description]


# ---------- certifications ----------

# Issuers we instantiate to split 'name (code)' from issuer. For synth,
# lines look like 'Microsoft Power BI Data Analyst (PL-300)'. We capture
# the whole line as the cert name and try to extract a (code) tag.
_CERT_CODE_RE = re.compile(r"\((?P<code>[A-Z0-9\-]+)\)")
_KNOWN_ISSUERS = ("Microsoft", "Google", "AWS", "IBM", "Oracle", "SAS",
                  "Coursera", "Udacity", "LinkedIn", "Tableau", "Databricks")


def _extract_certs(cert_blocks: list[Block]) -> list[CertEntry]:
    out: list[CertEntry] = []
    for b in cert_blocks:
        text = b.text.strip()
        if not text:
            continue
        issuer = ""
        for iss in _KNOWN_ISSUERS:
            if text.lower().startswith(iss.lower()):
                issuer = iss
                break
        code = _CERT_CODE_RE.search(text)
        # The cert 'name' is the text without the trailing (code).
        name = _CERT_CODE_RE.sub("", text).strip() if code else text
        out.append(CertEntry(name=name, issuer=issuer))
    return out


# -----------------------------------------------------------------
# Orchestrator.
# -----------------------------------------------------------------

def parse_resume(source, idx: SkillIndex) -> ParsedResume:
    """Parse a resume file (path or ResumeDocument) into a ParsedResume.

    Pure logic — no DB writes. The CLI (scripts/parse_resumes.py) persists.
    """
    if isinstance(source, (str, Path)):
        doc = load_resume(source)
    else:
        doc = source

    cleaned = clean(blocks=doc.blocks)
    sections = segment(cleaned.blocks)

    header_blocks = sections.get("header", [])
    header_text = "\n".join(b.text for b in header_blocks)
    spacy_doc = _nlp()(header_text + "\n" + cleaned.text[:4000])

    name = _extract_name(header_blocks, spacy_doc)
    email = _extract_email(header_text)
    phone = _extract_phone(header_text)
    location = _extract_location(header_text)

    education = _extract_education(sections.get("education", []))
    experience = _extract_experience(sections.get("experience", []))
    projects = _extract_projects(sections.get("projects", []), idx)
    certifications = _extract_certs(sections.get("certifications", []))

    # Skill matching across the three relevant sections, strongest evidence wins.
    skill_hits: dict[str, SkillHit] = {}
    for sec_name in ("skills", "experience", "projects"):
        for b in sections.get(sec_name, []):
            for h in match(b.text, sec_name, idx):
                existing = skill_hits.get(h.canonical_id)
                if existing is None or (
                    existing.evidence != "explicit" and h.evidence == "explicit"
                ):
                    skill_hits[h.canonical_id] = h

    source_path = str(doc.source_path) if hasattr(doc, "source_path") else ""
    return ParsedResume(
        name=name, email=email, phone=phone, location=location,
        education=education, experience=experience, projects=projects,
        certifications=certifications,
        skills=list(skill_hits.values()),
        source_path=source_path, file_format=doc.file_format,
        meta={"n_sections": len(sections)},
    )
