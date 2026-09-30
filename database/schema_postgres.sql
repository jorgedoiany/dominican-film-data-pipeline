-- ─────────────────────────────────────────
-- DOMINICAN FILM INDUSTRY DATABASE
-- Schema Version: 2.0 (PostgreSQL)
-- ─────────────────────────────────────────
-- ── Productions (master table) ──
-- One row per project. project_id is the PUR identifier (e.g. PUR-0861),
-- the key that links certificates, validation files and resolutions.
CREATE TABLE IF NOT EXISTS productions (
    project_id TEXT PRIMARY KEY,
    film_title TEXT NOT NULL,
    commercial_title TEXT,
    pur_number INTEGER,
    cpnd_number INTEGER,
    production_year INTEGER,
    release_date DATE,
    type TEXT,
    genre TEXT,
    duration_min INTEGER,
    country_of_origin TEXT,
    coproduction_country TEXT,
    production_origin TEXT,
    status TEXT,
    director TEXT,
    screenplay_author TEXT,
    production_company TEXT,
    short_synopsis TEXT,
    synopsis_source TEXT,
    total_budget_approved FLOAT,
    original_language TEXT
);

-- ── CPND Certificates ──
CREATE TABLE IF NOT EXISTS cpnd_certificates (
    cpnd_id SERIAL PRIMARY KEY,
    cpnd_number TEXT UNIQUE NOT NULL,
    project_id TEXT REFERENCES productions(project_id),
    title TEXT NOT NULL,
    production_company TEXT,
    director TEXT,
    screenplay_author TEXT,
    total_amount_dop FLOAT,
    duration_min INTEGER,
    genre TEXT,
    issue_date DATE,
    renewal_date DATE,
    expiry_date DATE,
    validity_years INTEGER,
    is_latest INTEGER DEFAULT 1,
    source_file TEXT
);

-- ── PUR Certificates ──
CREATE TABLE IF NOT EXISTS pur_certificates (
    pur_id SERIAL PRIMARY KEY,
    pur_number TEXT UNIQUE NOT NULL,
    project_id TEXT REFERENCES productions(project_id),
    cpnd_number TEXT REFERENCES cpnd_certificates(cpnd_number),
    title TEXT NOT NULL,
    producer TEXT,
    executive_producer TEXT,
    production_company TEXT,
    director TEXT,
    screenplay_author TEXT,
    total_budget_dop FLOAT,
    investment_in_dr_dop FLOAT,
    duration_min INTEGER,
    original_language TEXT,
    genre TEXT,
    work_type TEXT CHECK(work_type IN ('cinematografica', 'audiovisual')),
    incentive_type TEXT CHECK(incentive_type IN ('art_34', 'art_39')),
    issue_date DATE,
    expiry_date DATE,
    source_file TEXT
);

-- ── Validation Files ──
CREATE TABLE IF NOT EXISTS validation_files (
    file_id SERIAL PRIMARY KEY,
    file_number INTEGER NOT NULL,
    project_id TEXT REFERENCES productions(project_id),
    pur_number TEXT REFERENCES pur_certificates(pur_number),
    fiscal_year INTEGER NOT NULL,
    incentive_type TEXT CHECK(incentive_type IN ('art_34', 'art_39')),
    total_validated_usd FLOAT,
    total_credit_usd FLOAT,
    UNIQUE(project_id, file_number)
);

-- ── CIPAC Resolutions ──
CREATE TABLE IF NOT EXISTS cipac_resolutions (
    resolution_id SERIAL PRIMARY KEY,
    resolution_number TEXT UNIQUE NOT NULL,
    year TEXT,
    file_id INTEGER REFERENCES validation_files(file_id),
    project_id TEXT REFERENCES productions(project_id),
    pur_number TEXT,
    cpnd_number TEXT,
    incentive_article TEXT CHECK(incentive_article IN ('art_34', 'art_39')),
    resolution_type TEXT DEFAULT 'approved' CHECK(resolution_type IN ('approved', 'rejected')),
    investor_name TEXT,
    investor_rnc TEXT,
    production_company TEXT,
    producer_rnc TEXT,
    foreign_producer TEXT,
    film_title TEXT,
    request_date DATE,
    resolution_date DATE,
    validated_amount_dop FLOAT,
    tax_credit_dop FLOAT,
    tax_credit_pct FLOAT,
    total_budget_approved FLOAT,
    total_budget_executed FLOAT,
    extraction_confidence FLOAT,
    needs_review INTEGER DEFAULT 0,
    review_reasons TEXT,
    manually_reviewed INTEGER DEFAULT 0,
    manual_note TEXT,
    source_file TEXT
);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_cpnd_project ON cpnd_certificates(project_id);

CREATE INDEX IF NOT EXISTS idx_pur_project ON pur_certificates(project_id);

CREATE INDEX IF NOT EXISTS idx_pur_cpnd ON pur_certificates(cpnd_number);

CREATE INDEX IF NOT EXISTS idx_vf_project ON validation_files(project_id);

CREATE INDEX IF NOT EXISTS idx_vf_pur ON validation_files(pur_number);

CREATE INDEX IF NOT EXISTS idx_cipac_project ON cipac_resolutions(project_id);

CREATE INDEX IF NOT EXISTS idx_cipac_file ON cipac_resolutions(file_id);