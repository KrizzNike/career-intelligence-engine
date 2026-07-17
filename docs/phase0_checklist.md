# Phase 0 — Project Initialization: Validation Checklist

Complete each item, tick the box, and **do not proceed to Phase 1 (Week 1) until all are ticked and confirmed with your mentor.**

> Last verified: 2026-07-17

## 0.1 Tooling verified
- [x] Git installed (`git --version` → 2.53.0)
- [x] Python 3.11.3 + pip — chosen for full ML-wheel coverage (was 3.14; switched because torch has no 3.14 Windows wheel)
- [x] MySQL 8.0.45 installed and CLI on PATH (`mysql --version`)
- [x] VS Build Tools — **NOT NEEDED**: 3.11 ships prebuilt wheels for the entire stack
- [x] Power BI Desktop installed (in `C:\Program Files\Microsoft Power BI Desktop\`)

## 0.2 Repository created
- [x] Project dir at `C:\Users\Krish\Documents\career-intelligence-engine`
- [x] `git init -b main` done; first commit `a5a99ae`
- [ ] GitHub remote pushed — **PENDING** (see §0.7 below — needs your GitHub login)

## 0.3 Environment & dependencies
- [x] `.venv` created and activated on **Python 3.11.3**
- [x] `pip install -r requirements.txt` succeeded (core deps)
- [x] `pip install -r requirements-ml.txt` succeeded — torch, sentence-transformers, spacy, sklearn, xgboost, langchain, chromadb, streamlit all import cleanly
- [x] `python -m spacy download en_core_web_md` — NER model loads, entities extracted

## 0.4 Smoke test
- [x] `python scripts/smoke_test.py` → 4 OK lines (dirs, core deps, ML stack, spaCy model)
- [x] `path()` helper resolves, `src.config` importable
- [ ] `python scripts/smoke_test.py --check-db` → **PENDING** `.env` (see §0.5)

## 0.5 Configuration
- [ ] `.env` created and `DB_PASSWORD` filled with real MySQL creds — **PENDING** (file exists, password still `changeme`)
- [x] `.gitignore` correctly excludes `.env`, `.venv/`, `data/raw/*.pdf`, models

## 0.6 Documentation
- [x] `README.md` with problem, architecture, stack, structure, roadmap, setup (updated for 3.11)
- [x] This checklist (`docs/phase0_checklist.md`)

## 0.7 GitHub setup (pending)
- [ ] Create repo `career-intelligence-engine` on github.com (Private, no README/.gitignore — you have all three)
- [ ] `git remote add origin https://github.com/<your-handle>/career-intelligence-engine.git`
- [ ] `git push -u origin main`
- [ ] Add GitHub URL to README

---

## Decision log: Python 3.14 → 3.11 (2026-07-17)

Originally chose Python 3.14 with the intent to install VS Build Tools later.
On audit, discovered Python 3.11 was already installed and that it has
**prebuilt wheels for the entire ML/RAG stack including torch** — which has
*no* 3.14 Windows wheel and cannot be built from source. Switching to 3.11
eliminates the ~6 GB Build Tools install and the planned Week-9 second venv,
and lets every layer of the roadmap run in a single virtual environment.

## Next milestone (Phase 1, Week 1)

Once §0.5 (DB + `.env`) and §0.7 (GitHub) are complete:
1. Run `python scripts/smoke_test.py --check-db` → must print `OK - DB connection`.
2. `git push` the Phase 0 close commit.
3. Begin **Week 1 — Research notes** (resume datasets + skill taxonomy draft) — no ML needed, pure Python + reading.
