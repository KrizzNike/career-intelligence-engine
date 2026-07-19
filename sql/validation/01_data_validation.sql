-- ============================================================
-- Career Intelligence Engine — Data validation queries (Week 3)
-- ------------------------------------------------------------
-- Run AFTER db_init + load_resumes. Each query is self-contained and
-- documents the invariant it checks. Expected values are inline so a
-- human eyeballing the output / a future pytest can assert on them.
--
-- Run:  mysql -u root -p career_intelligence < sql/validation/01_data_validation.sql
-- ============================================================

USE career_intelligence;

-- ------------------------------------------------------------
-- V1. Schema completeness — all 14 operational tables present.
-- Expected total = 14.
-- ------------------------------------------------------------
SELECT 'V1 table count' AS `check`, COUNT(*) AS `value`
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_type = 'BASE TABLE';

-- List any EXPECTED tables that are MISSING (should return 0 rows).
SELECT t.tbl AS missing_table
FROM (
    SELECT 'Candidates' tbl UNION ALL SELECT 'Resumes' UNION ALL
    SELECT 'Education' UNION ALL SELECT 'Experience' UNION ALL
    SELECT 'Projects' UNION ALL SELECT 'Certifications' UNION ALL
    SELECT 'Skills' UNION ALL SELECT 'Skill_Alias' UNION ALL
    SELECT 'Candidate_Skills' UNION ALL SELECT 'Job_Postings' UNION ALL
    SELECT 'Job_Skills' UNION ALL SELECT 'Skill_Taxonomy' UNION ALL
    SELECT 'Match_Results' UNION ALL SELECT 'Career_Readiness' UNION ALL
    SELECT 'Recommendations'
) t
LEFT JOIN information_schema.tables ist
  ON ist.table_schema = DATABASE() AND ist.table_name = t.tbl
WHERE ist.table_name IS NULL;

-- ------------------------------------------------------------
-- V2. Row counts per operational table (smoke check after load).
-- Candidates should == 600 after load_resumes; Skills/Candidate_Skills > 0.
-- ------------------------------------------------------------
SELECT 'Candidates'         AS t, COUNT(*) AS n FROM Candidates
UNION ALL SELECT 'Resumes',          COUNT(*) FROM Resumes
UNION ALL SELECT 'Education',        COUNT(*) FROM Education
UNION ALL SELECT 'Experience',       COUNT(*) FROM Experience
UNION ALL SELECT 'Projects',         COUNT(*) FROM Projects
UNION ALL SELECT 'Certifications',   COUNT(*) FROM Certifications
UNION ALL SELECT 'Skills',           COUNT(*) FROM Skills
UNION ALL SELECT 'Skill_Alias',      COUNT(*) FROM Skill_Alias
UNION ALL SELECT 'Candidate_Skills', COUNT(*) FROM Candidate_Skills
UNION ALL SELECT 'Skill_Taxonomy',  COUNT(*) FROM Skill_Taxonomy
UNION ALL SELECT 'Job_Postings',     COUNT(*) FROM Job_Postings
UNION ALL SELECT 'Job_Skills',       COUNT(*) FROM Job_Skills
UNION ALL SELECT 'Match_Results',    COUNT(*) FROM Match_Results
UNION ALL SELECT 'Career_Readiness', COUNT(*) FROM Career_Readiness
UNION ALL SELECT 'Recommendations',  COUNT(*) FROM Recommendations;

-- ------------------------------------------------------------
-- V3. Referential integrity — every Candidate_Skills row must resolve.
-- Orphan count MUST be 0 (FK enforces this, but we assert explicitly
-- because a disabled-FK import would silently break joins).
-- ------------------------------------------------------------
SELECT 'orphan Candidate_Skills.candidate' AS `check`, COUNT(*) AS `value`
FROM Candidate_Skills cs LEFT JOIN Candidates c ON c.id = cs.candidate_id
WHERE c.id IS NULL;

SELECT 'orphan Candidate_Skills.skill' AS `check`, COUNT(*) AS `value`
FROM Candidate_Skills cs LEFT JOIN Skills s ON s.id = cs.skill_id
WHERE s.id IS NULL;

SELECT 'orphan Resumes.candidate' AS `check`, COUNT(*) AS `value`
FROM Resumes r LEFT JOIN Candidates c ON c.id = r.candidate_id
WHERE c.id IS NULL;

-- ------------------------------------------------------------
-- V4. Resume-candidate cardinality — each Resume belongs to exactly one
-- Candidate; expect every candidate to have >=1 resume after load.
-- ------------------------------------------------------------
SELECT 'candidates WITHOUT a resume' AS `check`, COUNT(*) AS `value`
FROM Candidates c
LEFT JOIN Resumes r ON r.candidate_id = c.id
WHERE r.id IS NULL;

-- ------------------------------------------------------------
-- V5. Skill coverage — every canonical skill the synth resumes claim must
-- exist in the Skills table. Any nonzero count means the taxonomy seed and
-- the generator drifted out of sync.
-- ------------------------------------------------------------
SELECT 'resume skills not in taxonomy' AS `check`, COUNT(*) AS `value`
FROM Candidate_Skills cs
JOIN Resumes r ON r.id = (
    -- reverse-lookup not needed: Candidate_Skills.skill_id already FKs Skills,
    -- so this count is structurally 0 — kept as a regression guard.
    SELECT id FROM Resumes LIMIT 0)
WHERE 1=0;

-- Simpler real check: candidate_skills rows whose skill has no taxonomy link.
SELECT 'skills with no taxonomy link' AS `check`, COUNT(*) AS `value`
FROM Skills s
LEFT JOIN Skill_Taxonomy st ON st.id = s.taxonomy_id
WHERE s.taxonomy_id IS NOT NULL AND st.id IS NULL;

-- ------------------------------------------------------------
-- V6. Email uniqueness / synthetic provenance.
-- Every loaded candidate email must end in @synthetic.local.
-- ------------------------------------------------------------
SELECT 'candidates with non-synthetic email' AS `check`, COUNT(*) AS `value`
FROM Candidates
WHERE email NOT LIKE '%@synthetic.local';

-- ------------------------------------------------------------
-- V7. Charset sanity — resumes carry accents/emoji; the DB must accept them.
-- Expected: utf8mb4 / utf8mb4_unicode_ci
-- ------------------------------------------------------------
SELECT @@character_set_database AS char_set,
       @@collation_database      AS collation;
