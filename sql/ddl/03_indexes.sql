-- ============================================================
-- Career Intelligence Engine — DDL 03: supplemental hot-path indexes
-- ------------------------------------------------------------
-- PKs, UNIQUE constraints, and FK columns are already indexed (see
-- 02_tables.sql). This file adds the COMPOSITE / covering indexes that
-- the documented hot queries need but the automatic indexes don't cover.
--
-- Each index below is paired with the query it accelerates; see
-- docs/data_model.md §4 for the full optimization rationale.
-- ============================================================

USE career_intelligence;

-- ------------------------------------------------------------
-- Matching engine (Week 6): "given a job, fetch all required skills"
-- Bridge already has UNIQUE(job_id, skill_id) which covers this; but we
-- also query "for a candidate, which of THEIR skills match a job's
-- required skills" — that join benefits from a skill-leading index.
-- ------------------------------------------------------------
CREATE INDEX idx_js_skill_job ON Job_Skills (skill_id, job_id);
CREATE INDEX idx_cs_skill_cand ON Candidate_Skills (skill_id, candidate_id);

-- ------------------------------------------------------------
-- Power BI: skill popularity across the market (count of jobs requiring
-- each skill). Group-by on Skills + join to Job_Skills.
-- ------------------------------------------------------------
CREATE INDEX idx_js_skill_importance ON Job_Skills (skill_id, importance);

-- ------------------------------------------------------------
-- Skill lookup by alias during parsing (Week 4). The Skill_Alias unique
-- index is on alias_text_norm; add a leading index on skill_id so we can
-- cheaply enumerate all aliases of one skill.
-- ------------------------------------------------------------
CREATE INDEX idx_alias_skill_lead ON Skill_Alias (skill_id);

-- ------------------------------------------------------------
-- Career readiness leaderboard: top-N candidates for a target role.
-- Filter by role, sort by score. Per-candidate trend index already
-- exists; this is the cross-candidate (leaderboard) view.
-- ------------------------------------------------------------
CREATE INDEX idx_ready_role_score
    ON Career_Readiness (target_role_id, readiness_score DESC);

-- ------------------------------------------------------------
-- Recommendations view: "show me the candidate's critical gaps first".
-- Existing index (candidate_id, priority) covers this; add a per-priority
-- skill index so "which skills are most-recommended across all
-- candidates" is fast (Week 8 Power BI market gap view).
-- ------------------------------------------------------------
CREATE INDEX idx_rec_skill_type
    ON Recommendations (skill_id, rec_type, priority);
