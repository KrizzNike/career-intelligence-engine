-- ============================================================
-- Career Intelligence Engine — Analytical SQL (Week 3)
-- ------------------------------------------------------------
-- Query templates that answer the business questions the ProjectGuide
-- lists for the matching / readiness / dashboard features. They are
-- written now so the schema is *structurally provable* against real
-- questions (not just "tables exist"). Match_Results, Career_Readiness
-- and Recommendations are empty in Week 3 — those queries return 0 rows
-- until Weeks 5-7 populate them, which is the correct expected state.
--
-- Business purpose is stated above each query (ProjectGuide: "Every query
-- must explain the business decision it supports.")
-- ============================================================

USE career_intelligence;

-- ==========================================================
-- A1. Skill popularity across the MARKET (candidate side)
-- ----------------------------------------------------------
-- Business question: "Which skills are most common among our candidate
-- pool?" Supports content/roadmap decisions and acts as the denominator
-- for gap analysis (Week 7).
-- ==========================================================
SELECT s.canonical_id,
       s.canonical_name,
       st.category_id,
       COUNT(DISTINCT cs.candidate_id) AS candidate_count
FROM Skills s
JOIN Candidate_Skills cs ON cs.skill_id = s.id
LEFT JOIN Skill_Taxonomy st ON st.id = s.taxonomy_id
GROUP BY s.canonical_id, s.canonical_name, st.category_id
ORDER BY candidate_count DESC
LIMIT 20;

-- ==========================================================
-- A2. Skill demand by ROLE — derived from the taxonomy
-- ----------------------------------------------------------
-- Business question: "What does each role require?" This is the market
-- requirement surface the gap engine compares the candidate against.
-- Uses Skill_Taxonomy importance (critical/high/medium/low).
-- ==========================================================
SELECT st.role_id,
       st.node_name AS role_name,
       st.category_id,
       st.skill_id,
       st.importance
FROM Skill_Taxonomy st
WHERE st.node_type = 'skill'
  AND st.industry_id = 'data_analytics'
ORDER BY st.role_id,
         FIELD(st.importance, 'critical', 'high', 'medium', 'low'),
         st.skill_id;

-- ==========================================================
-- A3. Candidates per target role (distribution / balance)
-- ----------------------------------------------------------
-- Business question: "Is our candidate pool balanced across roles?"
-- Guides whether to oversample roles in future data collection.
-- ==========================================================
SELECT target_role_id,
       COUNT(*)                AS candidate_count,
       ROUND(AVG(
         (SELECT COUNT(*) FROM Candidate_Skills cs
          WHERE cs.candidate_id = c.id)
       ), 1)                   AS avg_skills_per_candidate
FROM Candidates c
GROUP BY target_role_id
ORDER BY candidate_count DESC;

-- ==========================================================
-- A4. Top-N most-skilled candidates (readiness proxy until Week 7)
-- ----------------------------------------------------------
-- Business question: "Who are our strongest candidates by raw breadth?"
-- Once Career_Readiness is populated, replace ORDER BY with the
-- readiness_score; the shape stays identical — that's the point of
-- keeping the score denormalized and time-versioned.
-- ==========================================================
SELECT c.id, c.full_name, c.target_role_id,
       COUNT(cs.skill_id)    AS skills_count,
       SUM(CASE WHEN st.importance = 'critical' THEN 1 ELSE 0 END)
                            AS critical_skills
FROM Candidates c
JOIN Candidate_Skills cs ON cs.candidate_id = c.id
JOIN Skills s ON s.id = cs.skill_id
LEFT JOIN Skill_Taxonomy st ON st.id = s.taxonomy_id
GROUP BY c.id, c.full_name, c.target_role_id
ORDER BY skills_count DESC
LIMIT 10;

-- ==========================================================
-- A5. Skill GAP candidates — market-required skills a candidate LACKS
-- ----------------------------------------------------------
-- Business question: "For role X, which skills are candidates most
-- often missing?" This is the engine behind Week-7 gap analysis and
-- Week-11 learning-planner recommendations.
--
-- Gap = skill is in the role's taxonomy (required/market surface) but
-- the candidate has no Candidate_Skills row for it.
-- ==========================================================
SELECT st.skill_id,
       s.canonical_name,
       st.importance,
       (SELECT COUNT(DISTINCT c2.id) FROM Candidates c2
        WHERE c2.target_role_id = st.role_id
          AND NOT EXISTS (
              SELECT 1 FROM Candidate_Skills cs2
              WHERE cs2.candidate_id = c2.id AND cs2.skill_id = s.id
          ))  AS candidates_missing_skill,
       (SELECT COUNT(*) FROM Candidates c3
        WHERE c3.target_role_id = st.role_id) AS total_role_candidates
FROM Skill_Taxonomy st
JOIN Skills s ON s.canonical_id = st.skill_id
WHERE st.node_type = 'skill'
  AND st.industry_id = 'data_analytics'
ORDER BY candidates_missing_skill DESC,
         FIELD(st.importance, 'critical', 'high', 'medium', 'low')
LIMIT 15;

-- ==========================================================
-- A6. Star-schema fact preview — rows the Power BI fact view returns
-- ----------------------------------------------------------
-- Business question: "Does the analytics layer expose one row per
-- (candidate, skill, role) with has_skill / is_required / gap_flag?"
-- Week-8 Power BI consumes v_fact_candidate_match directly.
-- ==========================================================
SELECT
    role_id,
    skill_name,
    SUM(has_skill)                  AS candidates_with_skill,
    SUM(is_required_by_market)      AS market_required_hits,
    SUM(gap_flag)                   AS gap_hits
FROM v_fact_candidate_match
GROUP BY role_id, skill_name
ORDER BY gap_hits DESC, role_id
LIMIT 15;
