"""
Synthetic job-description generator (Week 5).

Purpose
-------
Produce labeled, PII-free JDs that mirror the Week-2 synthetic resumes:
each JD carries a known target_role + required/preferred skill set, which
becomes GROUND TRUTH for the Week-6 matching engine's evaluation.

Why synthetic (see docs/research.md):
  - Each JD is labeled with its role + canonical required skills -> we can
    compute matching precision/recall. Real scraped JDs are unlabeled.
  - No PII / ToU issues; offline; reproducible.
  - Balanced across the 5 data roles -> no class imbalance.

Design
------
Pure logic (no I/O), deterministic via seed. Mirrors synthetic_resume.py's
structure so the two can be developed and tested in parallel.

A JD samples ~70-95% of its role's skills as REQUIRED (rest optional), then
renders free-text sections (summary, responsibilities, requirements) that
mention those skills by name -> gives the JD parser real signal to find.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

import yaml

# Per-generator Faker (NOT a module singleton) — same determinism fix as
# synthetic_resume.py. Two generators with the same seed must produce the
# same output, which a shared Faker would break.


def _new_faker(seed: int):
    from faker import Faker
    fk = Faker("en_US")
    fk.seed_instance(seed)
    return fk


DEEP_INDUSTRY_ID = "data_analytics"

# Plausible job titles per role. Used as the JD headline.
_ROLE_TITLES = {
    "data_analyst": ["Junior Data Analyst", "Data Analyst",
                     "Senior Data Analyst", "Business Data Analyst"],
    "bi_analyst": ["BI Analyst", "Business Intelligence Analyst",
                   "Senior BI Analyst", "BI Developer"],
    "data_scientist": ["Junior Data Scientist", "Data Scientist",
                       "Senior Data Scientist", "Applied Scientist"],
    "data_engineer": ["Data Engineer", "Senior Data Engineer",
                      "Analytics Engineer", "Data Platform Engineer"],
    "ml_engineer": ["ML Engineer", "Machine Learning Engineer",
                    "Senior ML Engineer", "MLOps Engineer"],
}

# Per-role responsibility templates. The {skill} slot is filled at render
# time with 1-2 sampled required skills, giving the parser bait to find.
_RESPONSIBILITY_TEMPLATES = {
    "data_analyst": [
        "Analyze large datasets using {skill} to answer business questions",
        "Build dashboards and reports with {skill} for stakeholders",
        "Write efficient {skill} queries to extract insights",
        "Partner with business teams to define KPIs and track them",
    ],
    "bi_analyst": [
        "Design and maintain self-serve BI models using {skill}",
        "Build executive dashboards in {skill}",
        "Develop semantic layers and governed metrics with {skill}",
        "Optimize {skill} workloads for dashboard performance",
    ],
    "data_scientist": [
        "Build predictive models using {skill}",
        "Run experiments and A/B tests; report with {skill}",
        "Productionize {skill} models with the engineering team",
        "Derive insights from large datasets using {skill}",
    ],
    "data_engineer": [
        "Design and operate scalable {skill} pipelines",
        "Build and maintain {skill} data warehouses",
        "Implement ETL/ELT workflows with {skill}",
        "Ensure data quality across {skill} pipelines",
    ],
    "ml_engineer": [
        "Deploy and monitor {skill} models in production",
        "Build MLOps pipelines for {skill} model lifecycle",
        "Optimize {skill} serving infrastructure",
        "Collaborate with data scientists to ship {skill} models",
    ],
}

# Per-role requirement templates (years of experience lines).
_REQUIREMENT_TEMPLATES = {
    "data_analyst": [
        "{n}+ years of experience in data analysis or analytics role",
        "Bachelor's degree in a quantitative field",
    ],
    "bi_analyst": [
        "{n}+ years building dashboards and BI solutions",
        "Bachelor's degree in CS, IS, or related field",
    ],
    "data_scientist": [
        "{n}+ years of hands-on data science experience",
        "Advanced degree (MS or PhD) preferred",
    ],
    "data_engineer": [
        "{n}+ years building data pipelines and warehouses",
        "Bachelor's degree in CS or related field",
    ],
    "ml_engineer": [
        "{n}+ years deploying ML models to production",
        "MS or PhD in CS, ML, or related field preferred",
    ],
}


@dataclass
class SyntheticJD:
    """A single generated job description, in structured form."""
    jd_id: str                     # e.g. "data_analyst_0000"
    target_role_id: str            # taxonomy role id
    target_role_name: str
    job_title: str                 # e.g. "Senior Data Analyst"
    company: str                   # faker-generated
    location: str
    industry: str = DEEP_INDUSTRY_ID
    seniority_band: str = "mid"
    min_years_experience: int = 2
    required_skills: list[str] = field(default_factory=list)   # canonical IDs
    required_skill_names: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    preferred_skill_names: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_text(self) -> str:
        """Render the JD as plain text (parser input + debugging)."""
        lines = [
            f"{self.job_title}",
            f"{self.company} | {self.location}",
            "",
            "ABOUT THE ROLE",
            f"We are hiring a {self.job_title} to join our growing team. "
            f"The ideal candidate will work cross-functionally to deliver "
            f"data-driven impact.",
            "",
            "RESPONSIBILITIES",
        ]
        for r in self.responsibilities:
            lines.append(f"- {r}")
        lines.append("")
        lines.append("REQUIREMENTS")
        for r in self.requirements:
            lines.append(f"- {r}")
        lines.append("- Required skills: " + ", ".join(self.required_skill_names))
        if self.preferred_skill_names:
            lines.append("- Preferred skills: " + ", ".join(self.preferred_skill_names))
        return "\n".join(lines).strip()


class JDGenerator:
    """Taxonomy-driven synthetic JD generator. Deterministic per seed."""

    def __init__(self, taxonomy_path, seed: int = 42):
        self.seed = seed
        self._rng = random.Random(seed)
        self._fk = _new_faker(seed)
        with open(taxonomy_path, "r", encoding="utf-8") as fh:
            self.taxonomy = yaml.safe_load(fh)
        self._roles = self._index_roles()

    def _index_roles(self) -> dict[str, dict]:
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
        seen, out = set(), []
        for cat in self._roles[role_id].get("categories", []):
            for sk in cat.get("skills", []):
                if sk["id"] not in seen:
                    seen.add(sk["id"])
                    out.append((sk["id"], sk["name"]))
        return out

    def generate_one(self, jd_id: str, role_id: str) -> SyntheticJD:
        if role_id not in self._roles:
            raise ValueError(f"role '{role_id}' not in deep vertical")
        role = self._roles[role_id]
        fk = self._fk

        all_skills = self._all_skill_names_for_role(role_id)
        # Required = 70-95% of role skills; preferred = a subset of the rest.
        n_required = max(3, int(round(len(all_skills) * self._rng.uniform(0.70, 0.95))))
        shuffled = self._rng.sample(all_skills, len(all_skills))
        required = shuffled[:n_required]
        preferred_pool = shuffled[n_required:]
        n_preferred = min(len(preferred_pool),
                          self._rng.randint(0, max(0, min(3, len(preferred_pool)))))
        preferred = self._rng.sample(preferred_pool, n_preferred) if n_preferred else []

        required_ids = [s[0] for s in required]
        required_names = [s[1] for s in required]
        preferred_ids = [s[0] for s in preferred]
        preferred_names = [s[1] for s in preferred]

        title = self._rng.choice(_ROLE_TITLES.get(role_id, [role["name"]]))
        seniority = "fresher" if "Junior" in title else (
            "senior" if "Senior" in title else "mid")
        min_years = {"fresher": 0, "mid": 2, "senior": 5}.get(seniority, 2)

        responsibilities = self._responsibilities(role_id, required_names)
        requirements = self._requirements(role_id, min_years)

        return SyntheticJD(
            jd_id=jd_id,
            target_role_id=role_id,
            target_role_name=role["name"],
            job_title=title,
            company=fk.company(),
            location=f"{fk.city()}, {fk.country()}",
            industry=DEEP_INDUSTRY_ID,
            seniority_band=seniority,
            min_years_experience=min_years,
            required_skills=required_ids,
            required_skill_names=required_names,
            preferred_skills=preferred_ids,
            preferred_skill_names=preferred_names,
            responsibilities=responsibilities,
            requirements=requirements,
            generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )

    def generate_batch(self, n_per_role: int = 60) -> list[SyntheticJD]:
        out = []
        for role_id in self.role_ids:
            for i in range(n_per_role):
                jid = f"{role_id}_{i:04d}"
                out.append(self.generate_one(jid, role_id))
        return out

    # ---------- section renderers ----------

    def _responsibilities(self, role_id: str, skill_names: list[str]) -> list[str]:
        templates = _RESPONSIBILITY_TEMPLATES.get(role_id, [])
        if not templates or not skill_names:
            return []
        n = self._rng.randint(3, min(5, len(templates)))
        chosen = self._rng.sample(templates, n)
        out = []
        for tmpl in chosen:
            picked = self._rng.sample(skill_names, k=min(2, len(skill_names)))
            out.append(tmpl.format(skill=", ".join(picked)))
        return out

    def _requirements(self, role_id: str, min_years: int) -> list[str]:
        templates = _REQUIREMENT_TEMPLATES.get(role_id, [])
        n = min(len(templates), self._rng.randint(1, 2))
        chosen = self._rng.sample(templates, n)
        return [tmpl.format(n=min_years) for tmpl in chosen]


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
