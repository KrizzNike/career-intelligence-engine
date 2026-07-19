-- ============================================================
-- Career Intelligence Engine — DDL 02: operational tables (3NF)
-- ------------------------------------------------------------
-- 14 tables per docs/data_model.md §2. Tables and their primary + foreign
-- keys live together (clearer than splitting); supplemental hot-path
-- indexes are added in 03_indexes.sql.
--
-- Idempotent: tables drop in REVERSE dependency order before CREATE so
-- scripts/db_init.py can re-run safely during development.
--
-- Conventions (see docs/data_model.md §5):
--   - utf8mb4 everywhere
--   - PK: BIGINT AUTO_INCREMENT id
--   - FK columns indexed automatically by InnoDB
--   - Timestamps in UTC, DATETIME(3) for ms precision
--   - Scores DECIMAL(5,2)  -> 0.00 to 100.00
-- ============================================================

USE career_intelligence;

-- Drop in reverse FK dependency order so re-runs never fail. We also
-- disable FK checks around the drops: even with correct ordering, a
-- stray FK from a future-added table (or a half-built state from a
-- previously failed run) can otherwise leave an orph* reference that
-- blocks the drop. Idempotent DDL should be bullet-proof, not order-
-- fragile.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS Recommendations;
DROP TABLE IF EXISTS Career_Readiness;
DROP TABLE IF EXISTS Match_Results;
DROP TABLE IF EXISTS Job_Skills;
DROP TABLE IF EXISTS Job_Postings;
DROP TABLE IF EXISTS Skill_Alias;
DROP TABLE IF EXISTS Candidate_Skills;
DROP TABLE IF EXISTS Skills;
DROP TABLE IF EXISTS Certifications;
DROP TABLE IF EXISTS Projects;
DROP TABLE IF EXISTS Experience;
DROP TABLE IF EXISTS Education;
DROP TABLE IF EXISTS Resumes;
DROP TABLE IF EXISTS Skill_Taxonomy;
DROP TABLE IF EXISTS Candidates;
SET FOREIGN_KEY_CHECKS = 1;

-- ------------------------------------------------------------
-- 1. Skill_Taxonomy  (created early; Skills references it)
--    Hierarchy node: industry -> role -> category -> skill -> sub_skill
--    One row per NODE (skill may be NULL for industry/role/category nodes).
-- ------------------------------------------------------------
CREATE TABLE Skill_Taxonomy (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    node_type       ENUM('industry','role','category','skill','sub_skill')
                    NOT NULL,
    industry_id     VARCHAR(64)  NOT NULL,         -- e.g. data_analytics
    role_id         VARCHAR(64)  NULL,             -- e.g. data_analyst
    category_id     VARCHAR(64)  NULL,
    skill_id        VARCHAR(64)  NULL,             -- canonical skill id
    node_name       VARCHAR(128) NOT NULL,
    parent_id       BIGINT       NULL,             -- self-reference for tree
    importance      ENUM('critical','high','medium','low') NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_tax_parent
        FOREIGN KEY (parent_id) REFERENCES Skill_Taxonomy(id),
    INDEX idx_tax_lookup (industry_id, role_id, skill_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. Skills — canonical skill master list (one row per skill id)
-- ------------------------------------------------------------
CREATE TABLE Skills (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    canonical_id    VARCHAR(64)  NOT NULL UNIQUE,  -- e.g. 'power_bi'
    canonical_name  VARCHAR(128) NOT NULL,         -- e.g. 'Power BI'
    taxonomy_id     BIGINT       NULL,             -- link into the tree
    is_active       TINYINT(1)   NOT NULL DEFAULT 1,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                    ON UPDATE CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_skill_tax
        FOREIGN KEY (taxonomy_id) REFERENCES Skill_Taxonomy(id),
    INDEX idx_skill_name (canonical_name)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2b. Skill_Alias — alternate surface forms -> canonical skill
--     The Week-4 parser resolves 'PowerBI', 'Microsoft Power BI',
--     'PBI' all to skill canonical_id 'power_bi' via this table.
-- ------------------------------------------------------------
CREATE TABLE Skill_Alias (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    alias_text      VARCHAR(128) NOT NULL,
    alias_text_norm VARCHAR(128) NOT NULL,         -- lowercased + trimmed
    skill_id        BIGINT       NOT NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_alias_skill
        FOREIGN KEY (skill_id) REFERENCES Skills(id) ON DELETE CASCADE,
    UNIQUE KEY uq_alias_norm (alias_text_norm)      -- one alias -> one skill
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3. Candidates — a person in the system
-- ------------------------------------------------------------
CREATE TABLE Candidates (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    full_name       VARCHAR(200) NOT NULL,
    email           VARCHAR(254) NOT NULL,
    phone           VARCHAR(40)  NULL,
    location        VARCHAR(200) NULL,
    target_role_id  VARCHAR(64)  NULL,             -- from taxonomy
    seniority_band  ENUM('fresher','entry','mid','senior')
                    NOT NULL DEFAULT 'fresher',
    linkedin_url    VARCHAR(254) NULL,
    source          VARCHAR(64)  NOT NULL DEFAULT 'synthetic',
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
                    ON UPDATE CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_candidate_email (email)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4. Resumes — a file uploaded by a candidate (1 candidate : M resumes)
-- ------------------------------------------------------------
CREATE TABLE Resumes (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    file_path       VARCHAR(512) NOT NULL,
    file_format     ENUM('pdf','docx','txt') NOT NULL,
    raw_text        MEDIUMTEXT   NULL,             -- extracted text (Week 4)
    content_hash    CHAR(64)     NOT NULL,         -- sha256, dedup
    parsed_status   ENUM('pending','parsed','failed')
                    NOT NULL DEFAULT 'pending',
    parsed_at       DATETIME(3)  NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_resume_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    UNIQUE KEY uq_resume_hash (content_hash),
    INDEX idx_resume_status (parsed_status)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 5. Education — degrees (1 candidate : M)
-- ------------------------------------------------------------
CREATE TABLE Education (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    degree          VARCHAR(200) NOT NULL,
    institution     VARCHAR(200) NULL,
    field_of_study  VARCHAR(200) NULL,
    start_year      SMALLINT     NULL,
    end_year        SMALLINT     NULL,
    gpa             DECIMAL(3,2) NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_edu_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    INDEX idx_edu_candidate (candidate_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 6. Experience — work history (1 candidate : M)
-- ------------------------------------------------------------
CREATE TABLE Experience (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    title           VARCHAR(200) NOT NULL,
    company         VARCHAR(200) NULL,
    location        VARCHAR(200) NULL,
    start_date      DATE         NULL,
    end_date        DATE         NULL,
    is_current      TINYINT(1)   NOT NULL DEFAULT 0,
    duration_months INT          NULL,             -- precomputed for analytics
    description     TEXT         NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_exp_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    INDEX idx_exp_candidate (candidate_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 7. Projects — portfolio projects (1 candidate : M)
-- ------------------------------------------------------------
CREATE TABLE Projects (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT         NULL,
    url             VARCHAR(254) NULL,
    tech_stack      JSON         NULL,             -- array of skill ids
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_proj_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    INDEX idx_proj_candidate (candidate_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 8. Certifications — certs (1 candidate : M)
-- ------------------------------------------------------------
CREATE TABLE Certifications (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    name            VARCHAR(200) NOT NULL,
    issuer          VARCHAR(200) NULL,
    issue_date      DATE         NULL,
    expiry_date     DATE         NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_cert_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    INDEX idx_cert_candidate (candidate_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 9. Candidate_Skills — M:N bridge (the matching engine's core)
-- ------------------------------------------------------------
CREATE TABLE Candidate_Skills (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    skill_id        BIGINT       NOT NULL,
    proficiency     ENUM('beginner','intermediate','advanced','expert')
                    NOT NULL DEFAULT 'intermediate',
    evidence        ENUM('explicit','inferred','self_reported')
                    NOT NULL DEFAULT 'inferred',
    source_section  ENUM('skills','experience','projects','certifications','education')
                    NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_cs_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    CONSTRAINT fk_cs_skill
        FOREIGN KEY (skill_id) REFERENCES Skills(id) ON DELETE RESTRICT,
    UNIQUE KEY uq_candidate_skill (candidate_id, skill_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 10. Job_Postings — a job description analyzed
-- ------------------------------------------------------------
CREATE TABLE Job_Postings (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_title       VARCHAR(200) NOT NULL,
    company         VARCHAR(200) NULL,
    role_id         VARCHAR(64)  NULL,             -- mapped to taxonomy
    industry        VARCHAR(64)  NULL,
    location        VARCHAR(200) NULL,
    seniority_band  ENUM('fresher','entry','mid','senior')
                    NOT NULL DEFAULT 'fresher',
    description     MEDIUMTEXT   NULL,
    content_hash    CHAR(64)     NOT NULL,         -- dedup
    source          VARCHAR(64)  NOT NULL DEFAULT 'kaggle_glassdoor',
    posted_date     DATE         NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_job_hash (content_hash),
    INDEX idx_job_role (role_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 11. Job_Skills — M:N bridge (mirror of Candidate_Skills)
-- ------------------------------------------------------------
CREATE TABLE Job_Skills (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id          BIGINT       NOT NULL,
    skill_id        BIGINT       NOT NULL,
    importance      ENUM('critical','high','medium','low')
                    NOT NULL DEFAULT 'medium',
    is_required     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_js_job
        FOREIGN KEY (job_id) REFERENCES Job_Postings(id) ON DELETE CASCADE,
    CONSTRAINT fk_js_skill
        FOREIGN KEY (skill_id) REFERENCES Skills(id) ON DELETE RESTRICT,
    UNIQUE KEY uq_job_skill (job_id, skill_id)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 12. Match_Results — candidate <-> job compatibility (one per pair)
-- ------------------------------------------------------------
CREATE TABLE Match_Results (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id       BIGINT       NOT NULL,
    job_id             BIGINT       NOT NULL,
    compatibility_score DECIMAL(5,2) NOT NULL,     -- 0-100
    skill_overlap_pct  DECIMAL(5,2) NOT NULL,      -- % of required skills present
    missing_skill_count INT         NOT NULL DEFAULT 0,
    match_method       ENUM('tfidf','embedding','hybrid')
                       NOT NULL DEFAULT 'tfidf',
    scored_at          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_match_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    CONSTRAINT fk_match_job
        FOREIGN KEY (job_id) REFERENCES Job_Postings(id) ON DELETE CASCADE,
    UNIQUE KEY uq_candidate_job (candidate_id, job_id),
    INDEX idx_match_score (compatibility_score DESC)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 13. Career_Readiness — composite score, time-versioned
-- ------------------------------------------------------------
CREATE TABLE Career_Readiness (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id       BIGINT       NOT NULL,
    target_role_id     VARCHAR(64)  NOT NULL,
    readiness_score    DECIMAL(5,2) NOT NULL,      -- composite 0-100
    tech_score         DECIMAL(5,2) NOT NULL,      -- 35%
    projects_score     DECIMAL(5,2) NOT NULL,      -- 25%
    experience_score   DECIMAL(5,2) NOT NULL,      -- 20%
    education_score    DECIMAL(5,2) NOT NULL,      -- 10%
    market_score       DECIMAL(5,2) NOT NULL,      -- 10%
    model_version      VARCHAR(32)  NOT NULL DEFAULT 'v0.1',
    scored_at          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_ready_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    INDEX idx_ready_trend (candidate_id, scored_at DESC)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 14. Recommendations — generated improvement actions
-- ------------------------------------------------------------
CREATE TABLE Recommendations (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    candidate_id    BIGINT       NOT NULL,
    readiness_id    BIGINT       NULL,             -- which scoring run produced it
    skill_id        BIGINT       NULL,             -- the skill being recommended
    rec_type        ENUM('skill_gap','learning_path','project_suggestion',
                         'certification','role_move')
                    NOT NULL,
    priority        ENUM('critical','high','medium','low')
                    NOT NULL DEFAULT 'medium',
    title           VARCHAR(200) NOT NULL,
    rationale       TEXT         NULL,
    created_at      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_rec_candidate
        FOREIGN KEY (candidate_id) REFERENCES Candidates(id) ON DELETE CASCADE,
    CONSTRAINT fk_rec_readiness
        FOREIGN KEY (readiness_id) REFERENCES Career_Readiness(id) ON DELETE SET NULL,
    CONSTRAINT fk_rec_skill
        FOREIGN KEY (skill_id) REFERENCES Skills(id) ON DELETE SET NULL,
    INDEX idx_rec_priority (candidate_id, priority)
) ENGINE=InnoDB;
