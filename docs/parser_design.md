# Resume Parser Design (Week 4)

## Pipeline

```
Resume file (PDF/DOCX)
     │
     ▼  ① FILE LOADING  (src.data_ingestion.resume_loader)
ResumeDocument(blocks, raw_text)
     │
     ▼  ② TEXT CLEANING  (src.preprocessing.clean_text)
CleanedText(blocks, text)
     │
     ▼  ③ SECTION SEGMENTATION  (src.preprocessing.section_segmenter)
Dict[section_name → blocks]
     │
     ▼  ④ FIELD EXTRACTION  (src.nlp.resume_parser)
ParsedResume(name, email, phone, location,
             education[], experience[],
             projects[], certifications[],
             skills[SkillHit...])
     │
     ▼  ⑤ SKILL MATCHING  (src.nlp.skill_matcher)
Alias-aware, evidence-tagged (explicit/inferred)
     │
     ▼  ⑥ PERSISTENCE  (src.nlp.resume_persistence + scripts/parse_resumes.py)
MySQL: Education / Experience / Projects / Certifications /
       Candidate_Skills (evidence upgrade) /
       Resumes.parsed_status = 'parsed'
```

## Key design decisions

1. **Loader → Cleaner → Parser split.** Loading, cleaning, and extraction are separate so the cleaner works on any text source (PDF, DOCX, future API data) and extraction is format-agnostic.

2. **Hybrid parsing (NER + regex + taxonomy lookup).** Name extraction uses spaCy NER with a first-line heuristic fallback. Education/experience use targeted regex patterns. Skills use the canonical `Skill_Alias` table from MySQL (loaded into a `SkillIndex` once) with word-boundary matching.

3. **Evidence tagging.** Every matched skill records its source section. Skills found in the explicit "Skills" section get evidence='explicit'; those found in experience/project bullets get 'inferred'. This powers explainable scoring in Week 7.

4. **PDF vs DOCX parity.** DOCX carries style metadata (Title, Heading 1), giving free segmentation. PDF has no styles; section headers are detected by UPPERCASE label matching. Both feed the same extractors.

5. **Idempotent persistence.** Rows for a candidate's Education/Experience/Projects/Certifications are deleted before re-insert on re-parse. Resumes are keyed by content_hash (sha256 of resume_id).

## Fallbacks
- Name: NER PERSON → first line (1-4 words, no digits/@)
- Education: strict regex (degree + field + institution + year) → loose token fallback
- Skill matching: alias lookup → canonical name match; no match = silently skipped
- PDF date format: `Mon YYYY - Present` and `YYYY - YYYY` both handled

## Evaluation method
- 600 synthetic resumes with ground-truth JSON labels
- Skill extraction: precision / recall / F1 per resume → micro-averaged across all 600
- Structural coverage: % of resumes with name/education/experience/projects extracted
- Threshold: overall F1 ≥ 0.80
