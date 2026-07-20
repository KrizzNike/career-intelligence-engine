"""
Skill matcher (Week 4) — the heart of the platform.

Purpose
-------
Given free-text resume content (or any text), find which canonical
Skills are present, by matching surface forms against:
  - canonical skill names ('SQL' from 'SQL')
  - skill aliases     ('power_bi' from 'PowerBI', 'PBI', 'Microsoft BI')
This is the *single component* that downstream matching (Week 6),
readiness scoring (Week 7), and gap analysis all depend on. It must be:
  - DETERMINISTIC (same text -> same skills) so debugging is tractable.
  - ACL-safe: 'R' the language must not match the letter 'r' — done by
    requiring a word boundary and (for very short aliases) a length floor.
  - SECTION-AWARE: the caller passes the section a match came from so
    evidence ('explicit' from Skills section vs 'inferred' from bullets)
    is captured for explainable scoring (Week 7).

How matching works (3 passes, weakest to strongest):
  1. Alias scan: every Skill_Alias -> compiled boundary regex. Optional
     context rule for ambiguous aliases (length<=2 or common words).
  2. Canonical-name scan: the formal skill name, boundary-matched.
  3. Sub-skill passthrough: we do NOT create new Skills from sub_skills;
     noting them is a Week-7 enrichment, out of scope for matching.

Inputs
------
Optional skill_map: dict[canonical_id -> {name, id}] loaded once from
the DB by load_skill_index(). If omitted, the matcher is DIY-empty and
you must call load_skill_index() first (or pass one in).

Outputs
-------
match(text, section) -> list[SkillHit(canonical_id, skill_id, name,
                                       surface_form, evidence)]

Dependencies
------------
mysql-connector-python (.env loaded), re.

Testing example
---------------
    from src.nlp.skill_matcher import load_skill_index, match
    idx = load_skill_index()                 # hits MySQL
    hits = match('Built PowerBI and T-SQL solutions', section='experience', idx=idx)
    ids = {h.canonical_id for h in hits}
    assert 'power_bi' in ids and 'sql' in ids
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

try:
    from dotenv import load_dotenv
    from src.config import PROJECT_ROOT

    load_dotenv(PROJECT_ROOT / ".env")
except Exception:  # pragma: no cover
    pass


@dataclass
class SkillHit:
    canonical_id: str
    skill_id: int
    name: str
    surface_form: str  # the exact text that matched (for evidence UI)
    evidence: str       # 'explicit' | 'inferred' (section-derived)
    section: str


@dataclass
class SkillIndex:
    """In-memory index of canonical skills + aliases + compiled patterns."""
    skills: dict[str, dict[str, Any]]  # canonical_id -> {id, name}
    # compiled pattern -> (canonical_id, surface_form). Order matters:
    # longer/alias-first so 'Microsoft Power BI' wins before 'Power BI'.
    patterns: list[tuple[re.Pattern, str, str]]

    def __len__(self) -> int:
        return len(self.skills)


# Minimum-length floor below which an alias is treated as ambiguous and
# requires a surrounding-word check so it doesn't match random letters.
_AMBIGUOUS_LEN = 3


def _connect():
    import mysql.connector

    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "career_intelligence"),
        charset="utf8mb4",
        use_pure=True,
    )


def load_skill_index() -> SkillIndex:
    """Fetch Skills + Skill_Alias from MySQL, compile match patterns.

    Pattern ordering: aliases first (often longer/more specific), then
    canonical names; within each bucket, longest surface form first so
    'Microsoft Power BI' is tried before 'Power BI'. This prevents
    double-counting: we dedupe final hits by canonical_id.
    """
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id, canonical_id, canonical_name FROM Skills "
                "WHERE is_active = 1")
    skills: dict[str, dict[str, Any]] = {}
    for pk, cid, cname in cur.fetchall():
        skills[cid] = {"id": pk, "name": cname}

    # surface_form -> (canonical_id, is_alias)
    surface_items: list[tuple[str, str, bool]] = []
    cur.execute("SELECT alias_text, skill_id FROM Skill_Alias")
    alias_rows = cur.fetchall()
    cur.execute("SELECT canonical_id, canonical_name FROM Skills "
                "WHERE is_active = 1")
    name_rows = cur.fetchall()
    cur.close()
    conn.close()

    # Map skill_id -> canonical_id for aliases (we only have the FK).
    skills_by_pk = {v["id"]: cid for cid, v in skills.items()}
    for alias_text, skill_pk in alias_rows:
        cid = skills_by_pk.get(skill_pk)
        if cid and alias_text:
            surface_items.append((alias_text, cid, True))
    for cid, cname in name_rows:
        if cname:
            surface_items.append((cname, cid, False))

    # Longest-first sort so specific aliases outrank generic names.
    surface_items.sort(key=lambda x: len(x[0]), reverse=True)

    patterns: list[tuple[re.Pattern, str, str]] = []
    for surface, cid, _is_alias in surface_items:
        pat = _compile(surface)
        if pat is not None:
            patterns.append((pat, cid, surface))

    return SkillIndex(skills=skills, patterns=patterns)


def _compile(surface: str) -> re.Pattern | None:
    """Build a word-boundary regex for a surface form, case-insensitive.

    We escape regex metachars and use lookarounds so punctuation-adjacent
    matches still hit ('PowerBI,'). We deliberately do NOT require
    whitespace on both sides — 'SQL/Python' should still find both.
    """
    if not surface or not surface.strip():
        return None
    # Treat + as a literal in C++ / C# etc.
    pat = re.escape(surface)
    return re.compile(r"(?<![A-Za-z0-9])" + pat + r"(?![A-Za-z0-9])",
                      re.IGNORECASE)


def match(text: str, section: str, idx: SkillIndex) -> list[SkillHit]:
    """Return SkillHits for all canonical skills present in `text`.

    `section` is the section the text was drawn from; it drives evidence:
      'skills' section   -> 'explicit'
      any other section   -> 'inferred'
      'header'            -> '' (these aren't skills; caller filters)
    """
    if not text or not idx.patterns:
        return []
    evidence = "explicit" if section == "skills" else "inferred"
    seen: dict[str, SkillHit] = {}  # canonical_id -> first hit
    for pat, cid, surface in idx.patterns:
        if cid in seen:
            continue  # longest-first: earlier match wins for this skill
        m = pat.search(text)
        if m:
            sk = idx.skills.get(cid)
            if not sk:
                continue
            seen[cid] = SkillHit(
                canonical_id=cid,
                skill_id=sk["id"],
                name=sk["name"],
                surface_form=m.group(0),
                evidence=evidence,
                section=section,
            )
    return list(seen.values())
