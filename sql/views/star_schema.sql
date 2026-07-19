-- ============================================================
-- Career Intelligence Engine — Views: star schema for Power BI
-- ------------------------------------------------------------
-- One central fact table + four dimensions. Power BI connects to
-- these views directly — no raw-table joins in the dashboard layer.
--
-- Grain of fact_candidate_match: one row per (candidate, skill, role).
-- This single grain answers all dashboard questions:
--   "How many candidates have skill X?"      -> filter has_skill=1
--   "Average readiness for role Y?"           -> filter dim_role, avg score
--   "Biggest skill gaps across the market?"   -> filter gap_flag=1, count
--   "Readiness trend over time?"              -> group by dim_date.month
--
-- See docs/data_model.md §3 for the ER diagram and rationale.
-- ============================================================

USE career_intelligence;

DROP VIEW IF EXISTS v_fact_candidate_match;
DROP VIEW IF EXISTS v_dim_date;
DROP VIEW IF EXISTS v_dim_role;
DROP VIEW IF EXISTS v_dim_skill;
DROP VIEW IF EXISTS v_dim_candidate;

-- ------------------------------------------------------------
-- DIM: Candidate
-- One row per candidate with their latest readiness score.
-- ------------------------------------------------------------
CREATE VIEW v_dim_candidate AS
SELECT
    c.id                  AS candidate_id,
    c.full_name           AS candidate_name,
    c.email,
    c.location,
    c.target_role_id,
    c.seniority_band,
    c.source,
    COALESCE(cr.readiness_score, 0)    AS latest_readiness_score,
    COALESCE(cr.tech_score, 0)          AS latest_tech_score,
    COALESCE(cr.projects_score, 0)      AS latest_projects_score,
    COALESCE(cr.experience_score, 0)    AS latest_experience_score,
    COALESCE(cr.education_score, 0)     AS latest_education_score,
    COALESCE(cr.market_score, 0)        AS latest_market_score,
    cr.scored_at                         AS latest_scored_at,
    (SELECT COUNT(*) FROM Candidate_Skills cs WHERE cs.candidate_id = c.id)
                                 AS total_skills_count,
    (SELECT COUNT(*) FROM Education e WHERE e.candidate_id = c.id)
                                 AS education_count,
    (SELECT COUNT(*) FROM Experience ex WHERE ex.candidate_id = c.id)
                                 AS experience_count,
    (SELECT COUNT(*) FROM Projects p WHERE p.candidate_id = c.id)
                                 AS project_count,
    (SELECT COUNT(*) FROM Certifications cert WHERE cert.candidate_id = c.id)
                                 AS certification_count,
    c.created_at           AS candidate_created_at
FROM Candidates c
LEFT JOIN Career_Readiness cr
    ON cr.id = (
        SELECT id FROM Career_Readiness
        WHERE candidate_id = c.id
        ORDER BY scored_at DESC LIMIT 1
    );

-- ------------------------------------------------------------
-- DIM: Role
-- One row per role in the taxonomy with market-level aggregates.
-- ------------------------------------------------------------
CREATE VIEW v_dim_role AS
SELECT DISTINCT
    st.role_id,
    st.node_name                      AS role_name,
    st.industry_id                    AS industry_id,
    (SELECT node_name FROM Skill_Taxonomy
     WHERE industry_id = st.industry_id AND node_type = 'industry'
     LIMIT 1)                         AS industry_name,
    (SELECT COUNT(DISTINCT cs.candidate_id)
     FROM Candidate_Skills cs
     JOIN Skills s ON s.id = cs.skill_id
     WHERE s.taxonomy_id IN (
         SELECT id FROM Skill_Taxonomy
         WHERE role_id = st.role_id AND node_type = 'skill'
     ))                                AS candidate_count_with_role_skills,
    (SELECT COUNT(DISTINCT js.job_id)
     FROM Job_Skills js
     JOIN Skills s ON s.id = js.skill_id
     WHERE s.taxonomy_id IN (
         SELECT id FROM Skill_Taxonomy
         WHERE role_id = st.role_id AND node_type = 'skill'
     ))                                AS job_count_requiring_role_skills
FROM Skill_Taxonomy st
WHERE st.node_type = 'role'
  AND st.industry_id = 'data_analytics';

-- ------------------------------------------------------------
-- DIM: Skill
-- One row per canonical skill with market demand metrics.
-- ------------------------------------------------------------
CREATE VIEW v_dim_skill AS
SELECT
    s.id                   AS skill_id,
    s.canonical_id,
    s.canonical_name       AS skill_name,
    st.category_id,
    st.industry_id,
    (SELECT COUNT(DISTINCT cs.candidate_id)
     FROM Candidate_Skills cs WHERE cs.skill_id = s.id)
                           AS candidate_count,
    (SELECT COUNT(DISTINCT js.job_id)
     FROM Job_Skills js WHERE js.skill_id = s.id)
                           AS job_count,
    COALESCE(st.importance, 'medium') AS taxonomy_importance
FROM Skills s
LEFT JOIN Skill_Taxonomy st
    ON s.taxonomy_id = st.id;

-- ------------------------------------------------------------
-- DIM: Date
-- Standard calendar dimension for time-series analysis.
-- Built from Career_Readiness.scored_at (the scoring events).
-- ------------------------------------------------------------
CREATE VIEW v_dim_date AS
SELECT DISTINCT
    DATE(cr.scored_at)                AS date_id,
    cr.scored_at                     AS scored_at,
    YEAR(cr.scored_at)               AS score_year,
    MONTH(cr.scored_at)              AS score_month,
    QUARTER(cr.scored_at)            AS score_quarter,
    CONCAT(YEAR(cr.scored_at), '-Q',
           QUARTER(cr.scored_at))    AS year_quarter,
    DATE_FORMAT(cr.scored_at, '%Y-%m') AS `year_month`
FROM Career_Readiness cr;

-- ------------------------------------------------------------
-- FACT: Candidate Match
-- Central fact. Grain = (candidate, skill, role, scoring_event).
-- Pre-joined from the operational tables so Power BI does zero joins.
--
-- Note on the market-requirement join:
--   MySQL (incl. 8.0.45) does NOT support correlated references from a
--   derived table to the outer query without LATERAL. So instead of
--   `LEFT JOIN (SELECT ... WHERE jp.role_id = c.target_role_id) js`,
--   we LEFT JOIN Job_Skills + Job_Postings directly and predicate the
--   role match in the ON clause. DISTINCT collapsing is handled by the
--   fact's natural grain: one row per (candidate, skill), because the
--   Candidate_Skills LEFT JOIN is at most one row per (candidate, skill).
-- ------------------------------------------------------------
DROP VIEW IF EXISTS v_fact_candidate_match;
CREATE VIEW v_fact_candidate_match AS
SELECT
    c.id                            AS candidate_id,
    s.id                            AS skill_id,
    c.target_role_id                 AS role_id,
    DATE(cr.scored_at)              AS date_id,
    -- Does the candidate HAVE this skill?
    CASE WHEN cs.skill_id IS NOT NULL THEN 1 ELSE 0 END
                                   AS has_skill,
    -- Is this skill REQUIRED by at least one job in the candidate's role?
    -- js_required exists when a job's required Job_Skills row for this
    -- exact skill links to a Job_Postings row matching the candidate's role.
    CASE WHEN js.skill_id IS NOT NULL THEN 1 ELSE 0 END
                                   AS is_required_by_market,
    -- Gap = market requires it but candidate doesn't have it.
    CASE WHEN js.skill_id IS NOT NULL AND cs.skill_id IS NULL
         THEN 1 ELSE 0 END         AS gap_flag,
    -- Skill details (denormalized for Power BI field list)
    s.canonical_name                AS skill_name,
    st.category_id                  AS skill_category,
    st.importance                   AS skill_importance,
    -- Scoring context
    cr.readiness_score              AS readiness_score,
    cr.tech_score                   AS tech_score,
    cr.projects_score               AS projects_score,
    cr.experience_score             AS experience_score,
    cr.education_score              AS education_score,
    cr.market_score                 AS market_score,
    c.seniority_band                AS seniority_band,
    c.source                        AS candidate_source,
    cr.scored_at                    AS scored_at
FROM Candidates c
-- All skills defined for the candidate's target role (one row per skill).
JOIN Skill_Taxonomy st
    ON st.role_id = c.target_role_id
   AND st.node_type = 'skill'
   AND st.industry_id = 'data_analytics'
JOIN Skills s
    ON s.canonical_id = st.skill_id
-- Latest readiness score for this candidate (correlated subquery in the
-- JOIN condition is allowed -- it's a scalar subquery, not a derived table).
LEFT JOIN Career_Readiness cr
    ON cr.id = (
        SELECT id FROM Career_Readiness
        WHERE candidate_id = c.id
        ORDER BY scored_at DESC LIMIT 1
    )
-- Does the candidate actually have this skill?
LEFT JOIN Candidate_Skills cs
    ON cs.candidate_id = c.id AND cs.skill_id = s.id
-- Is this skill required by any job in the candidate's target role?
-- Direct join (no correlated derived table); one match is enough to flag.
LEFT JOIN Job_Skills js
    ON js.skill_id = s.id
   AND js.is_required = 1
   AND EXISTS (
        SELECT 1 FROM Job_Postings jp
        WHERE jp.id = js.job_id
          AND jp.role_id = c.target_role_id
   );

