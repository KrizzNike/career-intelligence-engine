# Career Intelligence Engine

**An Explainable AI-Powered Employability Analytics Platform** for skill assessment, career gap analysis, job matching, and personalized career guidance — "Google Maps for career development."

> Status: 🟡 Phase 0 — Project Initialization · 16-week roadmap · in progress

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
| Language | Python 3.14 (fallback 3.12 if ML wheels missing) | analytics ecosystem |
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

# 2. Create + activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment (NEVER commit .env)
copy .env.example .env
#   edit .env: set DB_PASSWORD and DB_USER for your MySQL

# 5. Verify the build
python scripts/smoke_test.py
#   expected: "OK - all directories present and config importable."
```

---

## 6. 16-Week Roadmap

| Month | Weeks | Theme |
|---|---|---|
| 1 Foundation | W1 Setup · W2 Data & taxonomy · W3 SQL design + ETL · W4 Resume parsing |
| 2 Analytics Engine | W5 JD analyzer · W6 Matching · W7 Readiness scoring · W8 Power BI |
| 3 AI Layer | W9 Embeddings · W10 RAG · W11 AI agents · W12 Streamlit |
| 4 Productization | W13 Testing · W14 Optimization · W15 Docs · W16 Deploy + portfolio |

---

## 7. License & Contribution

Private portfolio project. Contribution guidelines land in `CONTRIBUTING.md` at Week 15.

## 8. Author

Krish — MBA (Data Science & Decision Science) · Business Analytics specialization.
Built under structured mentor guidance following a 16-week product lifecycle.
