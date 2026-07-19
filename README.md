# Career Intelligence Engine

**An Explainable AI-Powered Employability Analytics Platform** for skill assessment, career gap analysis, job matching, and personalized career guidance — "Google Maps for career development."

> Status: 🟡 Phase 0 — Project Initialization · 16-week roadmap · in progress
>
> **Repo:** https://github.com/KrizzNike/career-intelligence-engine

---

## 1. Problem

Fresh graduates and early-career professionals apply blindly, get rejected without feedback, and don't know which roles fit them or which skills they lack. AI screening systems are black boxes. This project builds an **explainable decision-support system** — not a recruiter replacement — that tells a candidate:

1. **Where they stand** — a Career Readiness Score, broken down and explainable
2. **Why they fall short** — skill-gap analysis vs industry requirements
3. **Which roles fit** — candidate–job compatibility matching
4. **What to do next** — a personalized improvement roadmap

Primary users: fresh graduates (0–2 yrs). Architecture extensible to all industries.

---

## 2. Architecture (high-level)

```
Resume (PDF/DOCX) ──► Resume Intelligence Engine ──┐
                                                  ├─► Matching Engine ──► Compatibility Score
Job Descriptions ──► JD Intelligence Engine ─────┘         │
                                                          ├──► Career Readiness Score (explainable)
Skill Taxonomy ──► Skill Gap Analysis ─────────────┘        │
                                                          ├──► Career Recommendation Engine
RAG Knowledge Base + Ollama LLM ──► AI Agents ──────────► Advisor + Learning Planner
                                                          │
Power BI ◄──── Views over MySQL ──────────────────────────┘
Streamlit app ── candidate-facing UI
```

A complete write-up with component-level diagrams lands in `docs/architecture.md` during **Week 15**.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | full prebuilt wheels for the entire ML/NLP/RAG stack incl. torch — no compiler needed |
| Database | MySQL 8.0 | relational core, JSON type, window functions |
| Analytics | pandas, NumPy | standard data wrangling |
| NLP | spaCy, sentence-transformers | entity extraction + semantic embeddings |
| ML | scikit-learn, XGBoost | scoring + (optional) ranking model |
| RAG | LangChain + Ollama (local) + Chroma | private, no API cost |
| App | Streamlit | rapid candidate-facing UI |
| BI | Power BI | executive dashboards |
| VCS | Git + GitHub | collaboration + portfolio showcase |

---

## 4. Repository Structure

```
career-intelligence-engine/
├── data/            raw/ (resumes, jobs), processed/, taxonomy/, knowledge_base/
├── src/
│   ├── data_ingestion/   resume_loader.py, job_loader.py
│   ├── preprocessing/    clean_text.py, skill_normalization.py
│   ├── nlp/              resume_parser.py, embedding_generator.py
│   ├── ml/               feature_engineering.py, model_training.py, model_evaluation.py
│   ├── rag/              retriever.py, generator.py
│   ├── app/              streamlit_app.py
│   ├── utils/
│   └── config.py
├── sql/             ddl/ (CREATE TABLE), dml/ (INSERT), views/ (Power BI), validation/
├── tests/           unit/, data/, models/
├── notes/ (notebooks)     exploratory only — final logic lives in src/
├── docs/            architecture, data dictionary, model docs, user guide
├── config/
├── scripts/         CLI entry points (smoke_test, db_init, etc.)
├── dashboards/powerbi/   .pbix files + DAX exports
├── assets/diagrams/
├── requirements.txt
├── .env.example     <-- copy to .env, fill real values
├── .gitignore
└── README.md
```

---

## 5. Setup (Phase 0)

```bash
# 1. Clone (or you're already in it)
cd C:\Users\Krish\Documents\career-intelligence-engine

# 2. Create + activate virtual environment (Python 3.11 required)
py -3.11 -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies (both files; the second has the heavy ML/RAG wheels)
pip install -r requirements.txt
pip install -r requirements-ml.txt
python -m spacy download en_core_web_md   # NLP model, ~40MB

# 4. Create the database
mysql -u root -p -e "CREATE DATABASE career_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 5. Configure environment (NEVER commit .env)
copy .env.example .env
#   edit .env: set DB_PASSWORD to your real MySQL password

# 6. Verify the whole stack (deps + ML imports + spaCy model + DB)
python scripts/smoke_test.py --check-db
#   expected: 5 OK lines, exit 0
```

---

## 6. Week 3 — Database Design & ETL

**Goal:** stand up the relational core the whole platform writes against, and
prove it by loading the Week-2 synthetic data into it.

### Two-layer schema (see `docs/data_model.md`)
- **Operational layer (3NF, 14 tables)** — `sql/ddl/02_tables.sql`. Write
  integrity for ingestion + scoring: candidates → resumes → education /
  experience / projects / certifications; skills ↔ candidate_skills (M:N);
  job_postings ↔ job_skills; match_results, career_readiness,
  recommendations. All FKs enforced, `utf8mb4` throughout.
- **Analytics layer (star schema, views)** — `sql/views/star_schema.sql`.
  `v_fact_candidate_match` (one row per candidate×skill×role×date) +
  `v_dim_candidate/role/skill/date`, pre-joined so Power BI does zero joins.

### Reproduce
```bash
# 1. Build schema + seed taxonomy + create analytics views (idempotent)
python scripts/db_init.py

# 2. Load the 600 synthetic resume labels into Candidates/Resumes/Candidate_Skills
python scripts/load_resumes.py

# 3. Validate integrity + run analytical query templates
mysql -u root -p career_intelligence < sql/validation/01_data_validation.sql
mysql -u root -p career_intelligence < sql/validation/02_analytical_queries.sql

# 4. Unit tests (schema invariants + loader idempotency)
pytest tests/unit/test_db_init.py tests/unit/test_load_resumes.py
```

### Files
| Path | Role |
|---|---|
| `docs/data_model.md` | architecture rationale (why two layers, grain, optimization) |
| `sql/ddl/01..03` | database/charset, 14 tables, hot-path indexes |
| `sql/dml/01_seed_taxonomy.sql` | generated from `data/taxonomy/skill_taxonomy.yaml` via `scripts/taxonomy_to_sql.py` |
| `sql/views/star_schema.sql` | dim + fact views for Power BI |
| `sql/validation/01..02` | data-integrity checks + analytical query templates |
| `scripts/db_init.py` | orchestrator: DDL → seed → views |
| `scripts/load_resumes.py` + `src/data_ingestion/load_resumes_to_db.py` | ETL: resume labels → operational tables |
| `tests/unit/test_db_init.py`, `test_load_resumes.py` | schema + ETL tests |

**Expected after run:** 14 tables, 5 views, taxonomy seeded, 600 candidates with ~skills each, all resumes `parsed_status='pending'` for Week 4.

---

## 7. 16-Week Roadmap

| Month | Weeks | Theme |
|---|---|---|
| 1 Foundation | W1 Setup · W2 Data & taxonomy · W3 SQL design + ETL · W4 Resume parsing |
| 2 Analytics Engine | W5 JD analyzer · W6 Matching · W7 Readiness scoring · W8 Power BI |
| 3 AI Layer | W9 Embeddings · W10 RAG · W11 AI agents · W12 Streamlit |
| 4 Productization | W13 Testing · W14 Optimization · W15 Docs · W16 Deploy + portfolio |

---

## 8. License & Contribution

Private portfolio project. Contribution guidelines land in `CONTRIBUTING.md` at Week 15.

## 9. Author

Krish — MBA (Data Science & Decision Science) · Business Analytics specialization.
Built under structured mentor guidance following a 16-week product lifecycle.
