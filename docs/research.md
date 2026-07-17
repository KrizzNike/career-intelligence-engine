# Week 1 — Research Notes: Data Strategy

> Decision: focus **Data & Analytics** vertical deeply in v0; other industries
> stubbed in the taxonomy for later expansion (per ProjectGuide §Primary Users).

This document records *why* each dataset is chosen, its license, target volume,
and known risks. Every choice here feeds directly into Week 2 (collection) and
Week 3 (the SQL `Candidates`/`Resumes`/`Job_Postings` schema).

---

## 1. Resume dataset (target: 3,000–5,000)

The ProjectGuide asks for 3k–5k resumes. Two practical problems:
- **Privacy & PII**: real resumes contain names, phones, emails. We must NOT
  redistribute PII, and synthesis avoids the issue entirely.
- **Labeling**: a resume is only useful if we know the target role (so we can
  score matching accuracy). Public dumps are usually unlabeled.

### 1a. Primary — synthetic resumes (we generate)
Generate with a templated + randomized generator (Week 2):
- Names drawn from faker (already-free), PII stays fake → no privacy risk.
- Each resume tagged with a **target role** from the taxonomy → built-in ground
  truth for Week 6/7 evaluation.
- Volume: generate ~3,000 across the 5 data roles, balanced.
- Format: both `.pdf` and `.docx` so the Week-4 parser handles both.

**Why synthetic first**: it gives us *labeled, PII-free, balanced, multi-format*
data on day one — which is exactly what ML evaluation needs. Real datasets are
added in 1b for realism, not as the backbone.

### 1b. Secondary — public resume corpora (realism + parsing stress-test)
| Source | Volume | License | Use |
|---|---|---|---|
| Kaggle *Resume Dataset* (snehaanurag / livecareer) | ~2.5k | CC0 / research | parser robustness on messy real PDFs |
| HuggingFace `lmeninno/resumes` or similar | varies | per-row | supplementary |

**Action**: download in Week 2, strip PII with a scrubber (phone/email/ssn regex
+ faker replacement) before any storage in `data/raw/`.

### 1c. Rejected options
- Web-scraping LinkedIn / Indeed ToU — legal risk, not worth it for a portfolio.
- Buying resume dumps — cost + PII liability.

---

## 2. Job-description dataset (target: 5,000–10,000)

### 2a. Primary — public JD datasets
| Source | Volume | License | Notes |
|---|---|---|---|
| Kaggle *Data Scientist Jobs* / *Glassdoor Jobs* (picken / rampal) | ~15k | CC0 | pre-scraped Glassdoor, has role+salary |
| HuggingFace `jacob-hugging-face/skill-X` style | varies | MIT | clean text |
| EMSI / Lightcast open skills | 30k+ skills | CC BY | the de-facto industry skill list — use as a **cross-check** against our taxonomy |

### 2b. Secondary — liveJD enrichment (optional, Week 6+)
If time allows, sample ~500 current JDs from the public *Arbeitnow* API (free,
no key, jobs-api by Adzuna/WhatJobs) to test drift over time. Not core.

### 2c. Volume plan
Filter the Kaggle Glassdoor dump to **data roles only** (Data Analyst, Data
Scientist, BI, Data Engineer, ML Engineer) → expect ~5–8k clean JDs after
dedup. That meets the 5k target from one source with zero scraping.

---

## 3. Skill knowledge base (= the taxonomy)

This Week-1 file: `data/taxonomy/skill_taxonomy.yaml`. It is *not* scraped — it
is hand-curated from three industry references so we control quality:

| Reference | Why we trust it |
|---|---|
| **O*NET** (US Dept of Labor) | gold-standard occupation→skills mapping, free |
| **ESCO** (EU) | multilingual skills taxonomy, CC BY |
| **Lightcast/EMSI open skills** | the list actually used by recruiters; ~30k skills |

Our taxonomy is a **subset**: deep on the 5 data roles, structured so adding a
new industry = adding one `industry:` block. Validation in
`scripts/validate_taxonomy.py` enforces the 5-level hierarchy from the guide.

---

## 4. RAG knowledge base (Week 10, stubbed here)

Will be built in Week 10 from:
- This taxonomy (skills + role paths).
- A curated set of ~50 articles on data-career roadmaps (CC-licensed blogs,
  archived locally — never re-distributed).
- The JD corpus above (chunked + embedded into Chroma).

No data collection needed in Week 1.

---

## 5. Data-quality rules (apply from Week 2 onward)

- **PII**: never store raw PII. Scrub on ingest, keep a hashed mapping table.
- **Encoding**: all text UTF-8; reject non-decodable resumes, log them.
- **Dedup**: hash JD text (simhash later, exact md5 first); drop dupes.
- **Balance**: synthetic resumes balanced by role; track per-role counts.
- **Provenance**: every raw file gets a `source`, `license`, `fetched_at`
  recorded in `data/raw/_manifest.csv` (built Week 2).

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Synthetic resumes too clean → parser overfits | mix in real Kaggle resumes (1b) for noise |
| JD datasets biased to US market | document the bias; flag for v2 |
| Taxonomy drifts over 16 weeks | version it (`taxonomy_v0`, `v1`...), changelog in YAML header |
| License misattribution | each dataset row above has explicit license; manifest records it |

---

## 7. Week 2 collection checklist (forward-look)

- [ ] Build `scripts/generate_synthetic_resumes.py` → 3,000 PDFs+DOCXs
- [ ] Download Kaggle resume dataset → scrub PII → `data/raw/resumes/real/`
- [ ] Download Kaggle Glassdoor JD dump → filter data roles → `data/raw/jobs/`
- [ ] Write `data/raw/_manifest.csv` with source/license/count per batch
- [ ] Smoke test: open 5 random files of each, confirm parseable text
