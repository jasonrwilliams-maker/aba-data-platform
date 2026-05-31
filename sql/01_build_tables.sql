CREATE EXTENSION IF NOT EXISTS btree_gist;


-- ----------------------------------------------------------------------------
-- SECTION 1: ENUMs
-- ----------------------------------------------------------------------------
-- Closed vocabularies that change rarely and deliberately. Faster than
-- VARCHAR + CHECK because PostgreSQL stores them as 4-byte integers
-- internally and prevents typos at the type level.
--
-- Tradeoff: adding values requires ALTER TYPE ... ADD VALUE. Removing
-- values is hard. Use ENUMs only for vocabularies you're confident won't
-- churn. Use lookup tables for vocabularies that might gain entries
-- (interventions, payers, skill areas — those stay as tables).
-- ----------------------------------------------------------------------------

CREATE TYPE measurement_type AS ENUM (
    'percent',
    'count',
    'duration',
    'narrative'
);

CREATE TYPE program_status AS ENUM (
    'acquisition',
    'maintenance',
    'mastered',
    'discontinued'
);

CREATE TYPE target_status AS ENUM (
    'acquisition',
    'maintenance',
    'mastered',
    'discontinued'
);

CREATE TYPE session_status AS ENUM (
    'scheduled',
    'in_progress',
    'completed',
    'no_show',
    'cancelled',
    'documented',
    'signed',
    'locked'
);

CREATE TYPE authorization_status AS ENUM (
    'pending',
    'approved',
    'denied',
    'expired'
);

CREATE TYPE treatment_plan_type AS ENUM (
    'initial',
    'reassessment'
);

CREATE TYPE claim_status AS ENUM (
    'draft',
    'submitted',
    'accepted',
    'denied',
    'paid',
    'appealed',
    'written_off'
);

CREATE TYPE audit_action AS ENUM (
    'create',
    'read',
    'update',
    'delete',
    'sign',
    'lock'
);

CREATE TYPE incident_intensity AS ENUM (
    'low',
    'moderate',
    'high'
);


-- ----------------------------------------------------------------------------
-- SECTION 2: LOOKUP TABLES
-- ----------------------------------------------------------------------------
-- Domain vocabularies that may evolve. Kept as tables (not ENUMs) because
-- adding new entries should be a data operation, not a schema migration.
-- ----------------------------------------------------------------------------

CREATE TABLE cpt_codes (
    code            VARCHAR(5) PRIMARY KEY,
    description     TEXT NOT NULL,
    unit_minutes    INTEGER NOT NULL DEFAULT 15,
    allowed_renderers TEXT[] NOT NULL,
    requires_supervision_concurrent BOOLEAN NOT NULL DEFAULT FALSE,
    notes           TEXT
);

CREATE TABLE staff_credentials (
    credential      VARCHAR(20) PRIMARY KEY,
    description     TEXT NOT NULL,
    can_supervise   BOOLEAN NOT NULL DEFAULT FALSE,
    tier            INTEGER NOT NULL
);

CREATE TABLE skill_areas (
    name            VARCHAR(20) PRIMARY KEY,
    description     TEXT,
    display_order   INTEGER NOT NULL
);

CREATE TABLE intervention_types (
    name            VARCHAR(50) PRIMARY KEY,
    category        VARCHAR(30),
    description     TEXT
);

CREATE TABLE place_of_service_codes (
    code            VARCHAR(2) PRIMARY KEY,
    description     VARCHAR(100) NOT NULL
);

CREATE TABLE payers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    payer_type      VARCHAR(20) NOT NULL,
    state           CHAR(2),
    auth_period_weeks INTEGER NOT NULL DEFAULT 26,
    notes           TEXT
);


-- ----------------------------------------------------------------------------
-- SECTION 3: PEOPLE
-- ----------------------------------------------------------------------------

CREATE TABLE staff (
    id              SERIAL PRIMARY KEY,
    first_name      VARCHAR(50) NOT NULL,
    last_name       VARCHAR(50) NOT NULL,
    credential      VARCHAR(20) NOT NULL REFERENCES staff_credentials(credential),
    npi             VARCHAR(10),
    email           VARCHAR(100),
    hire_date       DATE NOT NULL,
    termination_date DATE,
    is_owner        BOOLEAN NOT NULL DEFAULT FALSE,
    safety_trainings TEXT[]
);

CREATE TABLE clients (
    id              SERIAL PRIMARY KEY,
    first_name      VARCHAR(50) NOT NULL,
    last_name       VARCHAR(50) NOT NULL,
    date_of_birth   DATE NOT NULL,
    diagnosis_code  VARCHAR(10) NOT NULL,
    diagnosis_date  DATE,
    diagnosed_by    VARCHAR(200),
    supervising_bcba_id INTEGER NOT NULL REFERENCES staff(id),
    intake_date     DATE NOT NULL,
    discharge_date  DATE,
    communication_profile TEXT,
    notes           TEXT
);

CREATE TABLE service_locations (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    label           VARCHAR(50) NOT NULL,
    address         TEXT,
    place_of_service_code VARCHAR(2) NOT NULL REFERENCES place_of_service_codes(code),
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);


-- ----------------------------------------------------------------------------
-- SECTION 4: AUTHORIZATIONS & TREATMENT PLANS
-- ----------------------------------------------------------------------------
-- CIRCULAR REFERENCE RESOLVED:
--
-- Before: authorizations REQUIRED a treatment_plan, but treatment_plans
-- pointed to an assessment session, which needed an auth, which needed a
-- plan... infinite loop on initial intake.
--
-- After: authorizations can exist without a treatment_plan (assessment
-- authorizations precede the plan they produce). Treatment plans reference
-- the assessment session that informed them. Ongoing-service authorizations
-- (97153/97155/97156) DO reference a treatment plan, because they require
-- one to exist.
-- ----------------------------------------------------------------------------

-- AUTHORIZATIONS COME FIRST in v3 because sessions FK to them, and treatment
-- plans FK to sessions. The dependency direction matters for table creation.
CREATE TABLE authorizations (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    payer_id        INTEGER NOT NULL REFERENCES payers(id),
    cpt_code        VARCHAR(5) NOT NULL REFERENCES cpt_codes(code),
    -- NULLABLE: assessment authorizations (97151) exist before the
    -- treatment_plan they produce. FK gets populated for ongoing-service
    -- authorizations once the plan is signed.
    treatment_plan_id INTEGER,  -- FK added after treatment_plans is created
    units_authorized INTEGER NOT NULL,
    units_per_week_planned INTEGER NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    authorization_number VARCHAR(50),
    approved_date   DATE,
    status          authorization_status NOT NULL DEFAULT 'pending',
    notes           TEXT,
    CHECK (period_end > period_start),
    CHECK (units_authorized > 0),
    CHECK (units_per_week_planned > 0),

    -- EXCLUSION CONSTRAINT: no two APPROVED authorizations for the same
    -- client + CPT code can have overlapping date ranges. This is enforced
    -- by the database itself; application code cannot violate it. Pending
    -- and denied auths are exempt (renewals overlapping current periods
    -- are normal during the approval window).
    EXCLUDE USING gist (
        client_id WITH =,
        cpt_code WITH =,
        daterange(period_start, period_end, '[]') WITH &&
    ) WHERE (status = 'approved')
);


CREATE TABLE treatment_plans (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    plan_type       treatment_plan_type NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    -- The assessment session(s) that produced this plan. FK added after
    -- sessions table is created (forward reference).
    source_assessment_session_id INTEGER,
    clinical_narrative TEXT,
    signed_by_bcba_id INTEGER REFERENCES staff(id),
    signed_at       TIMESTAMPTZ,
    submitted_to_payer_id INTEGER REFERENCES payers(id),
    submitted_at    TIMESTAMPTZ,
    locked_at       TIMESTAMPTZ,
    generated_pdf_path TEXT,
    notes           TEXT,
    CHECK (period_end > period_start)
);

-- Now we can add the FK from authorizations to treatment_plans
ALTER TABLE authorizations
    ADD CONSTRAINT fk_auth_treatment_plan
    FOREIGN KEY (treatment_plan_id) REFERENCES treatment_plans(id);


-- ----------------------------------------------------------------------------
-- SECTION 5: PROGRAM CATALOG
-- ----------------------------------------------------------------------------

CREATE TABLE programs (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    skill_area      VARCHAR(20) NOT NULL REFERENCES skill_areas(name),
    program_name    TEXT NOT NULL,
    status          program_status NOT NULL DEFAULT 'acquisition',
    started_date    DATE NOT NULL,
    mastered_date   DATE,
    maintenance_date DATE,
    discontinued_date DATE,
    introduced_in_plan_id INTEGER REFERENCES treatment_plans(id),
    notes           TEXT
);

CREATE TABLE targets (
    id              SERIAL PRIMARY KEY,
    program_id      INTEGER NOT NULL REFERENCES programs(id),
    target_name     TEXT NOT NULL,
    measurement_type measurement_type NOT NULL,
    mastery_criterion TEXT,
    status          target_status NOT NULL DEFAULT 'acquisition',
    started_date    DATE NOT NULL,
    mastered_date   DATE,
    notes           TEXT
);


-- ----------------------------------------------------------------------------
-- SECTION 6: SESSIONS
-- ----------------------------------------------------------------------------
-- CHANGE FROM V1: authorization_id is now NOT NULL. Every billable session
-- bills against some auth — even assessment sessions, which bill against
-- the assessment authorization the payer issues before the treatment plan
-- exists. No more orphan sessions.
-- ----------------------------------------------------------------------------

CREATE TABLE sessions (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    cpt_code        VARCHAR(5) NOT NULL REFERENCES cpt_codes(code),
    -- NOT NULL now. Sessions always bill against an auth.
    authorization_id INTEGER NOT NULL REFERENCES authorizations(id),

    rendering_provider_id INTEGER NOT NULL REFERENCES staff(id),
    supervising_bcba_id INTEGER REFERENCES staff(id),

    service_location_id INTEGER REFERENCES service_locations(id),
    place_of_service_code VARCHAR(2) NOT NULL REFERENCES place_of_service_codes(code),

    scheduled_start TIMESTAMPTZ NOT NULL,
    scheduled_end   TIMESTAMPTZ NOT NULL,
    actual_start    TIMESTAMPTZ,
    actual_end      TIMESTAMPTZ,

    scheduled_units INTEGER NOT NULL,
    documented_units INTEGER,
    billed_units    INTEGER,

    status          session_status NOT NULL DEFAULT 'scheduled',

    signed_by_id    INTEGER REFERENCES staff(id),
    signed_at       TIMESTAMPTZ,
    locked_at       TIMESTAMPTZ,

    notes           TEXT,
    CHECK (scheduled_end > scheduled_start),
    CHECK (actual_end IS NULL OR actual_start IS NULL OR actual_end > actual_start)
);

-- Now we can add the FK from treatment_plans back to sessions
ALTER TABLE treatment_plans
    ADD CONSTRAINT fk_source_assessment_session
    FOREIGN KEY (source_assessment_session_id) REFERENCES sessions(id);


-- ----------------------------------------------------------------------------
-- SECTION 7: SESSION DATA
-- ----------------------------------------------------------------------------

-- BONOBO-PROOF CHECK CONSTRAINT: each measurement_type clause requires both
-- the matching value column to be populated AND the other three to be NULL.
-- No way to insert a row where a 'percent' record also has a count or
-- duration value. The constraint enforces single-value-per-row at the
-- database level, regardless of what application code does.
CREATE TABLE session_target_data (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    target_id       INTEGER NOT NULL REFERENCES targets(id),
    measurement_type measurement_type NOT NULL,
    value_percent   DECIMAL(5,2),
    value_count     INTEGER,
    value_duration_sec INTEGER,
    value_text      TEXT,
    notes           TEXT,
    UNIQUE (session_id, target_id),

    CHECK (
        (measurement_type = 'percent'
            AND value_percent IS NOT NULL
            AND value_count IS NULL
            AND value_duration_sec IS NULL
            AND value_text IS NULL)
        OR
        (measurement_type = 'count'
            AND value_count IS NOT NULL
            AND value_percent IS NULL
            AND value_duration_sec IS NULL
            AND value_text IS NULL)
        OR
        (measurement_type = 'duration'
            AND value_duration_sec IS NOT NULL
            AND value_percent IS NULL
            AND value_count IS NULL
            AND value_text IS NULL)
        OR
        (measurement_type = 'narrative'
            AND value_text IS NOT NULL
            AND value_percent IS NULL
            AND value_count IS NULL
            AND value_duration_sec IS NULL)
    ),

    -- Additional value-range guards
    CHECK (value_percent IS NULL OR (value_percent >= 0 AND value_percent <= 100)),
    CHECK (value_count IS NULL OR value_count >= 0),
    CHECK (value_duration_sec IS NULL OR value_duration_sec >= 0)
);

CREATE TABLE behavior_incidents (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    incident_time   TIMESTAMPTZ,
    antecedent      TEXT NOT NULL,
    behavior        TEXT NOT NULL,
    consequence     TEXT NOT NULL,
    duration_sec    INTEGER,
    intensity       incident_intensity,
    intervention_used VARCHAR(50) REFERENCES intervention_types(name),
    notes           TEXT,
    CHECK (duration_sec IS NULL OR duration_sec > 0)
);

CREATE TABLE session_notes (
    session_id      INTEGER PRIMARY KEY REFERENCES sessions(id),
    attendees       TEXT[],
    skill_acquisition_methods TEXT[],
    session_narrative TEXT NOT NULL,
    progress_toward_goals TEXT,
    progress_made_note TEXT,
    barriers_to_treatment TEXT,
    medical_concerns BOOLEAN NOT NULL DEFAULT FALSE,
    medical_concerns_detail TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- If medical concerns flagged, detail is required
    CHECK (medical_concerns = FALSE OR medical_concerns_detail IS NOT NULL)
);

CREATE TABLE session_interventions (
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    intervention_name VARCHAR(50) NOT NULL REFERENCES intervention_types(name),
    PRIMARY KEY (session_id, intervention_name)
);


-- ----------------------------------------------------------------------------
-- SECTION 8: CLAIMS
-- ----------------------------------------------------------------------------

CREATE TABLE claims (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES sessions(id),
    authorization_id INTEGER NOT NULL REFERENCES authorizations(id),
    payer_id        INTEGER NOT NULL REFERENCES payers(id),
    cpt_code        VARCHAR(5) NOT NULL REFERENCES cpt_codes(code),
    units_billed    INTEGER NOT NULL,
    amount_billed   DECIMAL(10,2),
    amount_paid     DECIMAL(10,2),
    status          claim_status NOT NULL DEFAULT 'draft',
    submitted_at    TIMESTAMPTZ,
    adjudicated_at  TIMESTAMPTZ,
    paid_at         TIMESTAMPTZ,
    denial_reason_code VARCHAR(10),
    denial_reason_text TEXT,
    notes           TEXT,
    CHECK (units_billed > 0),
    CHECK (amount_billed IS NULL OR amount_billed >= 0),
    CHECK (amount_paid IS NULL OR amount_paid >= 0),
    -- If denied, denial reason required
    CHECK (status != 'denied' OR denial_reason_code IS NOT NULL)
);


-- ----------------------------------------------------------------------------
-- SECTION 9: AUDIT LOG
-- ----------------------------------------------------------------------------

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_staff_id  INTEGER REFERENCES staff(id),
    table_name      VARCHAR(50) NOT NULL,
    record_id       INTEGER NOT NULL,
    action          audit_action NOT NULL,
    client_id       INTEGER REFERENCES clients(id),
    change_detail   JSONB,
    request_metadata JSONB
);

CREATE INDEX idx_audit_client ON audit_log (client_id, occurred_at DESC);
CREATE INDEX idx_audit_actor ON audit_log (actor_staff_id, occurred_at DESC);
CREATE INDEX idx_audit_record ON audit_log (table_name, record_id);


-- ----------------------------------------------------------------------------
-- SECTION 10: OPERATIONAL INDEXES
-- ----------------------------------------------------------------------------

CREATE INDEX idx_sessions_bcba_date
    ON sessions (supervising_bcba_id, scheduled_start);

CREATE INDEX idx_sessions_client_date
    ON sessions (client_id, scheduled_start);

CREATE INDEX idx_sessions_reconciliation
    ON sessions (client_id, scheduled_start)
    WHERE billed_units IS NOT NULL
      AND documented_units IS NOT NULL
      AND billed_units != documented_units;

CREATE INDEX idx_behavior_session ON behavior_incidents (session_id);

CREATE INDEX idx_target_data_target_session
    ON session_target_data (target_id, session_id);

-- New for v2: authorization period lookups (utilization queries)
CREATE INDEX idx_auth_client_period
    ON authorizations (client_id, period_start, period_end);

-- Indexes for Foreign Keys to prevent sequential scans during table joins
CREATE INDEX idx_sessions_authorization ON sessions (authorization_id);
CREATE INDEX idx_targets_program ON targets (program_id);
CREATE INDEX idx_claims_authorization ON claims (authorization_id);
CREATE INDEX idx_claims_session ON claims (session_id);
CREATE INDEX idx_authorizations_treatment_plan ON authorizations (treatment_plan_id);
CREATE INDEX idx_clients_supervising_bcba ON clients (supervising_bcba_id);

-- ============================================================================
-- END OF SCHEMA v3
-- ============================================================================
