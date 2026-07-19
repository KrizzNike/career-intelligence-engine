# Week 3 — Data Model: Career Intelligence Engine

> Architecture decision (recorded 2026-07-17): **hybrid operational + analytics**
> — a normalized 3NF schema for write integrity during ingestion/scoring,
> with a star-schema view layer on top for Power BI performance.

This document explains *why* each table exists, how they relate, and what
business question each one answers. The SQL itself lives under `sql/`.

---

## 1. Two-layer architecture

```
   ┌────────────────────────────────────────────────────────────────┐
   │  ANALYTICS LAYER  (star schema, exposed as VIEWS for Power BI)  │
   │                                                                │
   │     fact_candidate_match  ◄── central fact                     │
   │   dim_candidate  dim_skill  dim_role  dim_date                 │
   └────────────────────────────────────────────────────────────────┘
                              ▲ built on top of
   ┌────────────────────────────────────────────────────────────────┐
   │  OPERATIONAL LAYER  (3NF, written to by ingestion/scoring)     │
   │                                                                │
   │  Candidates ─── Resumes ──┬── Education                       │
   │             └── Experience │── Projects                       │
   │                           └── Certifications                  │
   │  Candidate_Skills ── Skills ── Skill_Taxonomy                 │
   │  Job_Postings ── Job_Skills                                   │
   │  Match_Results ── Career_Readiness ── Recommendations          │
   └────────────────────────────────────────────────────────────────┘
```

**Why two layers?**
- **Operational** guarantees *write integrity* (no orphan skills, no
  duplicated candidates) via foreign keys + 3NF normalization. It is what
  the Python ingestion + scoring engines write to.
- **Analytics** denormalizes for *read speed*. Power BI shouldn't join 6
  tables to render a bar chart; the star schema pre-joins into one fact +
  dimensions, so the dashboard refresh is sub-second.

This is the same pattern used by every modern data platform (Snowflake +
dbt models, BigQuery + Looker, etc.). Building it now means Week-8 Power
BI is just "point at the views."

---

## 2. Operational tables (13, per ProjectGuide)

All tables use `utf8mb4` (full Unicode — resumes contain emojis, CJK
names, accented characters). PKs are `BIGINT AUTO_INCREMENT`; all FKs are
indexed.

| # | Table | Purpose | Grain (one row =) |
|---|---|---|---|
| 1 | `Candidates` | a person in the system | one candidate |
| 2 | `Resumes` | a resume version uploaded by a candidate | one resume file |
| 3 | `Education` | degrees earned | one degree per candidate |
| 4 | `Experience` | work history entries | one job per candidate |
| 5 | `Projects` | portfolio projects listed | one project per candidate |
| 6 | `Certifications` | certs earned | one cert per candidate |
| 7 | `Skills` | canonical skill master list (from taxonomy) | one skill |
| 8 | `Candidate_Skills` | which skills a candidate has (M:N) | one candidate×skill |
| 9 | `Job_Postings` | a job description analyzed | one job |
| 10 | `Job_Skills` | which skills a job requires (M:N) | one job×skill |
| 11 | `Skill_Taxonomy` | hierarchy: industry→role→category→skill | one taxonomy node |
| 12 | `Match_Results` | candidate↔job compatibility score | one candidate×job match |
| 13 | `Career_Readiness` | composite readiness score + sub-scores | one candidate per scoring run |
| 14 | `Recommendations` | generated improvement actions | one recommendation |

> The guide names 13; we add `Certifications` (also in the guide's resume
> extraction spec) as a 14th for clean normalization — extracting a cert
> into a TEXT column would block analytics. Total: 14 tables.

### 2.1 Key relationships
- `Candidates (1) ──< (M) Resumes` — a candidate can upload multiple resume versions.
- `Candidates (1) ──< (M) Candidate_Skills >── (1) Skills` — the M:N bridge,
  the heart of the matching engine.
- `Skills (1) ──< (M) Skill_Taxonomy` — every skill references its taxonomy node.
- `Job_Postings (1) ──< (M) Job_Skills >── (1) Skills` — mirror of candidate side.
- `Match_Results (candidate_id, job_id)` — uniquely scored pair (UNIQUE constraint).
- `Career_Readiness (candidate_id, scored_at)` — time-versioned, so we can
  track a candidate's score *improving* over time (key for Week-7 narrative).
- `Recommendations (candidate_id, ...)` — generated per scoring run.

### 2.2 Scoring columns (Week 7)
`Career_Readiness` stores the composite score AND its explainable parts:
```
readiness_score   DECIMAL(5,2)   -- overall 0-100
tech_score        DECIMAL(5,2)   -- 35%
projects_score    DECIMAL(5,2)   -- 25%
experience_score  DECIMAL(5,2)   -- 20%
education_score   DECIMAL(5,2)   -- 10%
market_score      DECIMAL(5,2)   -- 10%
```
These match the ProjectGuide §Career Readiness Score weights exactly.

---

## 3. Star schema (analytics layer, Power BI target)

One central fact + four dimensions, exposed as views in `sql/views/`:

```
                      ┌─────────────────────┐
                      │ dim_candidate       │
                      │  candidate_id       │
                      │  target_role        │
                      │  seniority_band     │
                      └──────────┬──────────┘
                                 │
┌─────────────────┐   ┌──────────▼──────────┐   ┌─────────────────┐
│ dim_skill       │   │ fact_candidate_match│   │ dim_role        │
│  skill_id       ├──►│  candidate_id       │◄──┤  role_id        │
│  skill_name     │   │  skill_id           │   │  role_name      │
│  category       │   │  role_id            │   │  industry       │
│  industry       │   │  match_score        │   └─────────────────┘
└─────────────────┘   │  has_skill (0/1)    │
                      │  is_required (0/1)  │   ┌─────────────────┐
                      │  gap_flag (0/1)     ├──►│ dim_date        │
                      │  date_id            │   │  date_id        │
                      └──────────┬──────────┘   │  scored_at      │
                                 │              │  month / quarter│
                                 └──────────────┘
```

**Grain of `fact_candidate_match`**: one row per *(candidate, skill, role, date)*.
This grain lets a single fact table answer ALL of these dashboard questions:
- "How many candidates have skill X?" → filter `has_skill=1`, group by skill.
- "What's the average match score for role Y?" → filter role, avg(match_score).
- "Which skills are the biggest gaps?" → `gap_flag=1`, count by skill.
- "Has readiness improved month over month?" → group by `dim_date.month`.

This is the design choice that makes Week-8 Power BI fast and easy.

---

## 4. Optimization notes

| Hot query (who runs it) | Optimization |
|---|---|
| Power BI: skill counts by role (Week 8) | Star-schema view pre-joined; covering index on `(skill_id, role_id)` |
| Matching engine: candidate skills for a job (Week 6) | Composite index on `Candidate_Skills(candidate_id, skill_id)`; same on `Job_Skills(job_id, skill_id)` |
| Resume parser: find existing skill by name/alias (Week 4) | Unique index on `Skills(canonical_name)` + `Skill_Alias(alias_text)` lookup table |
| Readiness trend over time (Week 7) | Index on `Career_Readiness(candidate_id, scored_at DESC)` |
| De-dup of job postings (Week 5) | Hash column `Job_Postings.content_hash` with UNIQUE index |

All foreign keys get an automatic index in MySQL (InnoDB), so the
bridges `Candidate_Skills` and `Job_Skills` are covered for join order.

---

## 5. Naming conventions

- `snake_case` everywhere; table names plural (`Candidates`, `Skills`).
- PK column: `id` (table-implicit) or `<table>_id` in FKs.
- Timestamps: `created_at`, `updated_at` (UTC, `DATETIME(3)`).
- Booleans: `is_*` / `has_*` prefixes, stored as `TINYINT(1)`.
- Enums stored as `ENUM(...)` (not magic ints) for readability.
- Scores: `DECIMAL(5,2)` (0.00–100.00).

---

## 6. Idempotency

All DDL files use `DROP TABLE IF EXISTS` in reverse-dependency order before
`CREATE`, so `scripts/db_init.py` can be re-run safely during development.
Production would use migrations (e.g. Alembic / Flyway); we note this as a
v2 improvement.
