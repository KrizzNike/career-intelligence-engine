-- ============================================================
-- Career Intelligence Engine — DDL 01: database + charset
-- ------------------------------------------------------------
-- Creates the database if missing and switches to it. The DB was already
-- created manually in Phase 0; this makes the project reproducible from
-- a fresh MySQL install and keeps all subsequent DDL database-agnostic.
--
-- Business purpose: a single, dedicated schema isolates the platform's
-- data from other databases on the server and enforces utf8mb4 so
-- resumes with emojis / CJK / accents never corrupt on insert.
-- ============================================================

CREATE DATABASE IF NOT EXISTS career_intelligence
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE career_intelligence;

-- Sanity check (run after this file):
--   SELECT @@character_set_database, @@collation_database;
-- Expected: utf8mb4 / utf8mb4_unicode_ci
