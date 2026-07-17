"""
Synthetic resume generator (Week 2).

Purpose
-------
Produce labeled, PII-free resumes that serve as GROUND TRUTH for the
Week 4 resume parser and the Week 6/7 matching + scoring engines.

Why synthetic first (see docs/research.md):
  - Every resume carries a known `target_role` + skill set -> we can
    compute precision/recall on parsing and matching. Real scraped
    resumes are unlabeled, so they can't drive evaluation.
  - faker produces fake but realistic PII -> zero privacy liability.
  - Balanced across the 5 data roles -> no class imbalance to fight.

Design
------
This module is pure logic (no file I/O) so it is fully unit-testable.
The CLI in scripts/generate_synthetic_resumes.py handles writing files.

A resume is built by sampling from the taxonomy:
  1. pick a target role (balanced)
  2. sample ~60-90% of that role's skills (a believable "strong" candidate)
  3. render free-text sections (summary, experience bullets) that mention
     the sampled skills by name -> gives the Week-4 parser something to find
  4. attach education, projects, certifications drawn from role templates

Determinism: every generator takes a `seed`. Same seed -> same resumes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml

# NOTE: Faker is intentionally NOT a module-level singleton. A singleton's
# RNG gets mutated by every caller, which breaks determinism when two
# generators with the same seed are created in one process (the second sees
# an already-advanced Faker state). Each ResumeGenerator owns its own seeded
# Faker instance via _new_faker(seed) -> reproducible output, a hard
# requirement for Week 6/7 evaluation.


def _new_faker(seed: int):
    """Return a freshly-seeded Faker instance, independent of any other."""
    from faker import Faker
    fk = Faker("en_US")
    fk.seed_instance(seed)
    return fk


# ============================================================
# Data model
# ============================================================

@dataclass
class SyntheticResume:
    """A single generated resume, in structured form.

    `skills` holds canonical skill IDs from the taxonomy — this is the
    ground-truth label the downstream engines are evaluated against.
    `text_sections` holds the free text that will be written to PDF/DOCX
    and fed to the Week-4 parser.
    """
    resume_id: str
    target_role_id: str          # taxonomy role id, e.g. "data_analyst"
    target_role_name: str
    name: str                    # faker-generated, fake
    email: str                   # faker-generated, fake
    phone: str                   # faker-generated, fake
    location: str
    summary: str
    skills: list[str]            # canonical skill IDs (ground truth)
    skill_names: list[str]       # human-readable skill names (for text)
    education: list[dict]
    experience: list[dict]
    projects: list[dict]
    certifications: list[str]
    generated_at: str

    def to_text(self) -> str:
        """Render the resume as plain text (for parser input + debugging)."""
        lines = [
            self.name,
            f"{self.email} | {self.phone} | {self.location}",
            "",
            "SUMMARY",
            self.summary,
            "",
            "SKILLS",
            ", ".join(self.skill_names),
            "",
        ]
        if self.experience:
            lines.append("EXPERIENCE")
            for job in self.experience:
                lines.append(f"{job['title']} - {job['company']} "
                             f"({job['duration']})")
                for b in job["bullets"]:
                    lines.append(f"  - {b}")
            lines.append("")
        if self.projects:
            lines.append("PROJECTS")
            for p in self.projects:
                lines.append(f"{p['name']}")
                lines.append(f"  {p['description']}")
            lines.append("")
        if self.education:
            lines.append("EDUCATION")
            for e in self.education:
                lines.append(f"{e['degree']} - {e['school']} ({e['year']})")
            lines.append("")
        if self.certifications:
            lines.append("CERTIFICATIONS")
            for c in self.certifications:
                lines.append(f"  - {c}")
        return "\n".join(lines).strip()


# ============================================================
# Generator
# ============================================================

DEEP_INDUSTRY_ID = "data_analytics"

# Per-role experience title pools (believable seniority bands for freshers).
_ROLE_TITLES = {
    "data_analyst": ["Data Analyst Intern", "Junior Data Analyst",
                     "Data Analyst", "Business Data Analyst"],
    "bi_analyst": ["BI Analyst Intern", "Junior BI Analyst",
                   "Business Intelligence Analyst", "BI Analyst"],
    "data_scientist": ["Data Science Intern", "Junior Data Scientist",
                       "Data Scientist", "Associate Data Scientist"],
    "data_engineer": ["Data Engineer Intern", "Junior Data Engineer",
                      "Data Engineer", "Associate Data Engineer"],
    "ml_engineer": ["ML Engineer Intern", "Junior ML Engineer",
                    "Machine Learning Engineer", "Associate ML Engineer"],
}

# Plausible degree + school pools shared across roles.
_DEGREES = ["B.Sc. Computer Science", "B.Sc. Statistics",
            "B.Sc. Mathematics", "B.Tech Information Technology",
            "B.Com", "BBA Business Analytics", "M.Sc Data Science",
            "MBA Data Science & Decision Science"]

_CERTIFICATIONS_BY_ROLE = {
    "data_analyst": ["Google Data Analytics Certificate",
                     "Microsoft Power BI Data Analyst (PL-300)"],
    "bi_analyst": ["Microsoft Power BI Data Analyst (PL-300)",
                   "Tableau Desktop Specialist"],
    "data_scientist": ["Google Data Analytics Certificate",
                       "IBM Data Science Professional Certificate"],
    "data_engineer": ["Google Data Engineering Certificate",
                      "Databricks Data Engineer Associate"],
    "ml_engineer": ["AWS Machine Learning Specialty",
                    "TensorFlow Developer Certificate"],
}


class ResumeGenerator:
    """Taxonomy-driven synthetic resume generator.

    Parameters
    ----------
    taxonomy_path : Path
        Location of skill_taxonomy.yaml.
    seed : int
        RNG seed for deterministic output.
    """

    def __init__(self, taxonomy_path, seed: int = 42):
        self.seed = seed
        self._rng = random.Random(seed)
        # Own Faker instance per generator -> true determinism (see module note).
        self._fk = _new_faker(seed)
        with open(taxonomy_path, "r", encoding="utf-8") as fh:
            self.taxonomy = yaml.safe_load(fh)
        self._roles = self._index_roles()

    # ---------- taxonomy helpers ----------

    def _index_roles(self) -> dict[str, dict]:
        """Flatten taxonomy into {role_id: role_dict} for the deep industry."""
        out = {}
        for ind in self.taxonomy.get("industries", []):
            if ind.get("id") != DEEP_INDUSTRY_ID:
                continue
            for role in ind.get("roles", []):
                out[role["id"]] = role
        return out

    @property
    def role_ids(self) -> list[str]:
        return sorted(self._roles.keys())

    def _all_skill_names_for_role(self, role_id: str) -> list[tuple[str, str]]:
        """Return [(skill_id, skill_name), ...] for a role, deduped."""
        seen, out = set(), []
        for cat in self._roles[role_id].get("categories", []):
            for sk in cat.get("skills", []):
                sid, sname = sk["id"], sk["name"]
                if sid not in seen:
                    seen.add(sid)
                    out.append((sid, sname))
        return out

    # ---------- generation ----------

    def generate_one(self, resume_id: str, role_id: str) -> SyntheticResume:
        if role_id not in self._roles:
            raise ValueError(f"role '{role_id}' not in deep vertical "
                             f"({sorted(self._roles)})")
        role = self._roles[role_id]
        fk = self._fk

        # Sample a believable fraction of the role's skills (60-90%).
        all_skills = self._all_skill_names_for_role(role_id)
        frac = self._rng.uniform(0.60, 0.90)
        k = max(3, int(round(len(all_skills) * frac)))
        sampled = self._rng.sample(all_skills, k)
        skill_ids = [s[0] for s in sampled]
        skill_names = [s[1] for s in sampled]

        name = fk.name()
        email = fk.email()
        phone = fk.phone_number()
        location = f"{fk.city()}, {fk.country()}"

        summary = self._summary(role["name"], skill_names)
        experience = self._experience(role_id, skill_names)
        projects = self._projects(skill_names)
        education = self._education()
        certs = self._certs(role_id)

        return SyntheticResume(
            resume_id=resume_id,
            target_role_id=role_id,
            target_role_name=role["name"],
            name=name,
            email=email,
            phone=phone,
            location=location,
            summary=summary,
            skills=skill_ids,
            skill_names=skill_names,
            education=education,
            experience=experience,
            projects=projects,
            certifications=certs,
            generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )

    def generate_batch(self, n_per_role: int = 20) -> list[SyntheticResume]:
        """Generate `n_per_role` resumes for EACH deep role, balanced."""
        out = []
        for role_id in self.role_ids:
            for i in range(n_per_role):
                rid = f"{role_id}_{i:04d}"
                out.append(self.generate_one(rid, role_id))
        return out

    # ---------- section renderers ----------

    def _summary(self, role_name: str, skills: list[str]) -> str:
        top = skills[:3]
        templates = [
            f"Detail-oriented {role_name} with hands-on experience in "
            f"{', '.join(top)}. Passionate about turning data into "
            f"actionable business insights.",
            f"Results-driven {role_name} skilled in {', '.join(top)}. "
            f"Looking to apply analytical thinking to real-world problems.",
            f"Motivated {role_name} familiar with {', '.join(top)} and "
            f"eager to contribute to data-driven decision making.",
        ]
        return self._rng.choice(templates)

    def _experience(self, role_id: str, skills: list[str]) -> list[dict]:
        fk = self._fk
        n = self._rng.randint(1, 2)  # freshers: 1-2 roles
        titles = _ROLE_TITLES.get(role_id, ["Analyst"])
        out = []
        for _ in range(n):
            n_bullets = self._rng.randint(2, 4)
            # Each bullet mentions 1-2 sampled skills by name -> parser bait.
            bullets = []
            for _ in range(n_bullets):
                picked = self._rng.sample(skills, k=min(2, len(skills)))
                verbs = ["Built", "Developed", "Analyzed", "Automated",
                         "Designed", "Optimized", "Delivered"]
                bullet = (f"{self._rng.choice(verbs)} "
                          f"{', '.join(p.lower() for p in picked)} "
                          f"solution that improved team efficiency "
                          f"by {self._rng.randint(10, 40)}%.")
                bullets.append(bullet)
            out.append({
                "title": self._rng.choice(titles),
                "company": fk.company(),
                "duration": f"{fk.date(pattern='%b %Y')} - "
                            f"{self._rng.choice(['Present', fk.date(pattern='%b %Y')])}",
                "bullets": bullets,
            })
        return out

    def _projects(self, skills: list[str]) -> list[dict]:
        n = self._rng.randint(1, 2)
        out = []
        for i in range(n):
            picked = self._rng.sample(skills, k=min(2, len(skills)))
            name = f"Project: {picked[0]} {'& ' + picked[1] if len(picked) > 1 else ''} Dashboard".strip()
            out.append({
                "name": name,
                "description": (f"End-to-end project leveraging "
                                f"{', '.join(p.lower() for p in picked)} "
                                f"to deliver actionable insights."),
            })
        return out

    def _education(self) -> list[dict]:
        fk = self._fk
        degree = self._rng.choice(_DEGREES)
        return [{
            "degree": degree,
            "school": f"{fk.city()} University",
            "year": str(self._rng.randint(2019, 2025)),
        }]

    def _certs(self, role_id: str) -> list[str]:
        pool = _CERTIFICATIONS_BY_ROLE.get(role_id, [])
        if not pool:
            return []
        n = self._rng.randint(0, min(2, len(pool)))
        return self._rng.sample(pool, n)


# Convenience for downstream code that just wants parsed taxonomy roles.
def load_deep_roles(taxonomy_path) -> dict[str, str]:
    """Return {role_id: role_name} for the deep vertical only."""
    with open(taxonomy_path, "r", encoding="utf-8") as fh:
        tax = yaml.safe_load(fh)
    out = {}
    for ind in tax.get("industries", []):
        if ind.get("id") == DEEP_INDUSTRY_ID:
            for r in ind.get("roles", []):
                out[r["id"]] = r["name"]
    return out
