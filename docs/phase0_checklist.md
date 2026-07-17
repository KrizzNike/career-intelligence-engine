# Phase 0 — Project Initialization: Validation Checklist

Complete each item, tick the box, and **do not proceed to Phase 1 (Week 1) until all are ticked and confirmed with your mentor.**

## 0.1 Tooling verified
- [x] Git installed (`git --version` → 2.53.0)
- [x] Python 3.14.6 + pip on PATH
- [x] MySQL 8.0.45 installed and CLI on PATH (`mysql --version`)
- [ ] Visual Studio Build Tools 2022 (C++ workload) — **PENDING**: required to build PyMuPDF and the ML stack on 3.14 (see `requirements-ml.txt` and known blocker below)
- [ ] Power BI Desktop installed (needed from Week 8 — install now at https://aka.ms/pbiSingleInstaller)

## 0.2 Repository created
- [x] Project dir at `C:\Users\Krish\Documents\career-intelligence-engine`
- [x] `git init -b main` done; first commit `a5a99ae`
- [ ] GitHub remote pushed (see §0.7 below — pending your GitHub account login)

## 0.3 Environment & dependencies
- [x] `.venv` created and activated
- [x] `pip install -r requirements.txt` succeeded (Phase 0/1 pure-Python deps)
- [ ] `pip install -r requirements-ml.txt` — **PENDING build toolchain** (see requirements-ml.txt header for the 14/3.14 wheel status)

## 0.4 Smoke test
- [x] `python scripts/smoke_test.py` → "OK - all dirs present, config + Phase 0 deps import cleanly."
- [x] `path()` helper resolves, `src.config` importable

## 0.5 Configuration
- [ ] `.env` created from `.env.example` and filled with real MySQL credentials — **PENDING** (you will create `career_intelligence` DB and enter password)
- [x] `.gitignore` correctly excludes `.env`, `.venv/`, `data/raw/*.pdf`, models

## 0.6 Documentation
- [x] `README.md` with problem, architecture, stack, structure, roadmap, setup
- [x] This checklist (`docs/phase0_checklist.md`)

## 0.7 GitHub setup (pending)
- [ ] Create repo `career-intelligence-engine` on github.com
- [ ] `git remote add origin git@github.com:<your-handle>/career-intelligence-engine.git`
- [ ] `git push -u origin main`
- [ ] Add GitHub URL to README

---

## Known blocker (recorded 2026-07-17)

User chose to stay on **Python 3.14** and install VS Build Tools rather than downgrade to 3.12.
- Many data/ML packages have **no prebuilt 3.14 wheel**; source builds need a C++ toolchain.
- **Hard blocker at Week 9**: PyTorch has no 3.14 wheel and cannot be built on Windows.
  Therefore `sentence-transformers` (Week 6 advanced matching + Week 9 embeddings) will fail.
- **Planned mitigation**: when we reach Week 9, provision a small **Python 3.12 venv**
  *only* for the AI-layer weeks. Phase 1–8 continue on 3.14 once build tools are installed.

## Next milestone (Phase 1, Week 1)
Topic modeling completeness delayed by build tools; but Week 1 deliverables that need
only the pure-Python stack can proceed immediately once this checklist is fully ticked:
- README finalized, repo on GitHub
- Research notes on resume datasets + skill taxonomy drafts
- MySQL `career_intelligence` database created (DDL lands Week 3, but DB now)
