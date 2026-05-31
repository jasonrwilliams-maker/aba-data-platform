-- ============================================================================
-- ABA Clinical Data Platform — Rates Addendum
-- ============================================================================
-- Purpose: Add reimbursement rate modeling to the schema.
--
-- This file does three things in sequence:
--   1. Adds a `modifier` column to the claims table (CPT modifiers like HN,
--      HO matter for billing — VA Medicaid 97153 pays $15.00 standard,
--      $23.48 with HN home modifier, $46.63 with HO office modifier).
--   2. Creates the `payer_rates` table with payer + code + modifier +
--      effective dating support.
--   3. Seeds the rates with anchored-to-reality data: VA Medicaid 2026
--      published rates, plausible commercial multipliers, and one historical
--      rate change to exercise the effective-dating logic.
--
-- Design notes:
--   - Modifier is nullable. NULL modifier = "applies to billing without a
--     modifier" (the standard rate). Specific modifier = override rate.
--   - Effective dating uses an exclusion constraint to prevent overlapping
--     active rates for the same payer + code + modifier combination.
--   - `effective_to` is nullable. NULL = "currently active until superseded."
--     The exclusion constraint uses COALESCE to treat NULL as 'infinity'.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. SCHEMA MIGRATION: Add modifier column to claims
-- ----------------------------------------------------------------------------
-- CPT modifiers are two-character codes that adjust the meaning or
-- reimbursement of the base CPT code. Common ABA modifiers:
--   HN — Home-based service
--   HO — Office-based service
--   HM — Less than bachelor degree level (paraprofessional)
--   95 — Telemedicine service rendered via real-time interactive
--        audio and video telecommunications system
--   GT — Telemedicine via interactive audio and video (legacy)
--
-- Modifiers stack with POS codes but aren't the same thing. POS tells the
-- payer WHERE service happened; modifier tells them WHAT KIND of service.
-- ----------------------------------------------------------------------------

ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS modifier VARCHAR(2);

COMMENT ON COLUMN claims.modifier IS
    'Optional CPT modifier (HN, HO, 95, etc.) affecting rate and meaning';


-- ----------------------------------------------------------------------------
-- 2. PAYER_RATES TABLE
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS payer_rates (
    id              SERIAL PRIMARY KEY,
    payer_id        INTEGER NOT NULL REFERENCES payers(id),
    cpt_code        VARCHAR(5) NOT NULL REFERENCES cpt_codes(code),
    -- NULL modifier = rate for billing without any modifier (the standard rate).
    -- Specific value = setting-specific override (HN, HO, etc.)
    modifier        VARCHAR(2),
    -- Optional credential tier. NULL = applies regardless of credential.
    -- Most VA Medicaid rates don't tier by credential; some commercial do.
    renderer_credential VARCHAR(20) REFERENCES staff_credentials(credential),
    rate_per_unit   DECIMAL(10,2) NOT NULL,
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    notes           TEXT,
    CHECK (rate_per_unit >= 0),
    CHECK (effective_to IS NULL OR effective_to > effective_from),

    -- No two active rates for the same payer + code + modifier + credential.
    -- COALESCE makes NULL effective_to behave as 'infinity' for overlap checks.
    EXCLUDE USING gist (
        payer_id WITH =,
        cpt_code WITH =,
        COALESCE(modifier, '') WITH =,
        COALESCE(renderer_credential, '') WITH =,
        daterange(effective_from, COALESCE(effective_to, 'infinity'::date), '[)') WITH &&
    )
);

CREATE INDEX IF NOT EXISTS idx_payer_rates_lookup
    ON payer_rates (payer_id, cpt_code, modifier, effective_from);

COMMENT ON TABLE payer_rates IS
    'Reimbursement rate fee schedules per payer, CPT, modifier, and credential, with effective dating';


-- ----------------------------------------------------------------------------
-- 3. SEED RATES
-- ----------------------------------------------------------------------------
-- VA Medicaid rates from the 2026 published fee schedule. Commercial rates
-- are plausible benchmarks (no published commercial fee schedules):
--   Anthem BCBS of VA: ~115% of Medicaid (typical commercial benchmark)
--   CareFirst BCBS:    ~105% of Medicaid (lower end of commercial)
--
-- One historical rate change is included to exercise effective-dating:
-- VA Medicaid raised its 2026 rates by approximately 5% over the 2025
-- fee schedule. This block represents the late-2024 through 2025 rates,
-- so a session billed in December 2025 (e.g., the kind of session the
-- reconciliation work surfaces) pulls these rates rather than the 2026
-- ones. The two periods are non-overlapping by construction:
-- effective_to = 2025-12-31, effective_from = 2026-01-01.
--
-- For commercial payers, modifier-specific rates aren't published, so we
-- only seed the no-modifier ("standard") rate for them and let the
-- application fall back to standard when no modifier-specific rate exists.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 3a. VIRGINIA MEDICAID — current rates (effective 2026-01-01)
-- ----------------------------------------------------------------------------

INSERT INTO payer_rates (payer_id, cpt_code, modifier, rate_per_unit, effective_from, notes)
SELECT p.id, vals.cpt_code, vals.modifier, vals.rate_per_unit, '2026-01-01'::date, vals.notes
FROM payers p
CROSS JOIN (VALUES
    -- 97153 Direct technician services — three modifiers, three rates
    ('97153', NULL,  15.00, 'Standard (no modifier)'),
    ('97153', 'HN',  23.48, 'Home-based modifier'),
    ('97153', 'HO',  46.63, 'Office-based modifier'),

    -- 97155 BCBA protocol modification — single rate
    ('97155', NULL,  42.00, 'BCBA-rendered protocol modification'),

    -- 97156 Caregiver guidance — single rate
    ('97156', NULL,  38.00, 'BCBA-rendered caregiver guidance'),

    -- Assessment codes (no prior auth required, but we still bill them)
    ('97151', NULL,  46.00, 'BCBA initial/reassessment'),
    ('97152', NULL,  20.00, 'Technician-supporting assessment')
) AS vals(cpt_code, modifier, rate_per_unit, notes)
WHERE p.name = 'Virginia Medicaid';


-- ----------------------------------------------------------------------------
-- 3b. VIRGINIA MEDICAID — historical rates (late 2024 through end of 2025)
-- ----------------------------------------------------------------------------
-- ~5% lower than 2026 rates. This exercise the effective-dating logic:
-- a session billed in December 2025 should pull these rates, not the 2026
-- rates. The two periods are non-overlapping (the 2025 rates have
-- effective_to = 2025-12-31, the 2026 rates have effective_from = 2026-01-01).
-- ----------------------------------------------------------------------------

INSERT INTO payer_rates (payer_id, cpt_code, modifier, rate_per_unit, effective_from, effective_to, notes)
SELECT p.id, vals.cpt_code, vals.modifier, vals.rate_per_unit,
       '2024-07-01'::date, '2025-12-31'::date, vals.notes
FROM payers p
CROSS JOIN (VALUES
    ('97153', NULL,  14.25, 'Standard (no modifier) — pre-2026'),
    ('97153', 'HN',  22.31, 'Home-based modifier — pre-2026'),
    ('97153', 'HO',  44.30, 'Office-based modifier — pre-2026'),
    ('97155', NULL,  39.90, 'BCBA-rendered protocol modification — pre-2026'),
    ('97156', NULL,  36.10, 'BCBA-rendered caregiver guidance — pre-2026'),
    ('97151', NULL,  43.70, 'BCBA initial/reassessment — pre-2026'),
    ('97152', NULL,  19.00, 'Technician-supporting assessment — pre-2026')
) AS vals(cpt_code, modifier, rate_per_unit, notes)
WHERE p.name = 'Virginia Medicaid';


-- ----------------------------------------------------------------------------
-- 3c. ANTHEM BCBS OF VIRGINIA — current rates (115% of Medicaid baseline)
-- ----------------------------------------------------------------------------
-- Commercial payers don't publish modifier-tiered fee schedules. We only
-- model the standard (no-modifier) rate; the application falls back to it
-- when a more specific match isn't found.
-- ----------------------------------------------------------------------------

INSERT INTO payer_rates (payer_id, cpt_code, modifier, rate_per_unit, effective_from, notes)
SELECT p.id, vals.cpt_code, NULL::varchar(2), vals.rate_per_unit, '2025-01-01'::date,
       'Plausible commercial benchmark — ~115% of VA Medicaid'
FROM payers p
CROSS JOIN (VALUES
    ('97153', 17.25),
    ('97155', 48.30),
    ('97156', 43.70),
    ('97151', 52.90),
    ('97152', 23.00)
) AS vals(cpt_code, rate_per_unit)
WHERE p.name = 'Anthem BCBS of Virginia';


-- ----------------------------------------------------------------------------
-- 3d. CAREFIRST BCBS — current rates (105% of Medicaid baseline)
-- ----------------------------------------------------------------------------

INSERT INTO payer_rates (payer_id, cpt_code, modifier, rate_per_unit, effective_from, notes)
SELECT p.id, vals.cpt_code, NULL::varchar(2), vals.rate_per_unit, '2025-01-01'::date,
       'Plausible commercial benchmark — ~105% of VA Medicaid'
FROM payers p
CROSS JOIN (VALUES
    ('97153', 15.75),
    ('97155', 44.10),
    ('97156', 39.90),
    ('97151', 48.30),
    ('97152', 21.00)
) AS vals(cpt_code, rate_per_unit)
WHERE p.name = 'CareFirst BCBS';


-- ============================================================================
-- LOOKUP FUNCTION (optional convenience)
-- ============================================================================
-- This function encapsulates the rate-lookup logic: given a payer, code,
-- modifier, and service date, return the rate that was in effect. Use this
-- in claim generation code instead of writing the JOIN manually each time.
--
-- Lookup order:
--   1. Exact match on payer + code + modifier + active on service_date
--   2. Fall back to payer + code + NULL modifier (standard rate) if no
--      modifier-specific rate exists
-- ============================================================================

CREATE OR REPLACE FUNCTION lookup_rate(
    p_payer_id INTEGER,
    p_cpt_code VARCHAR(5),
    p_modifier VARCHAR(2),
    p_service_date DATE
)
RETURNS DECIMAL(10,2) AS $$
DECLARE
    v_rate DECIMAL(10,2);
BEGIN
    -- First: exact match on modifier
    SELECT rate_per_unit INTO v_rate
    FROM payer_rates
    WHERE payer_id = p_payer_id
      AND cpt_code = p_cpt_code
      AND modifier IS NOT DISTINCT FROM p_modifier
      AND effective_from <= p_service_date
      AND (effective_to IS NULL OR effective_to >= p_service_date)
    LIMIT 1;

    -- Fallback: standard (NULL modifier) rate if specific modifier missed
    IF v_rate IS NULL AND p_modifier IS NOT NULL THEN
        SELECT rate_per_unit INTO v_rate
        FROM payer_rates
        WHERE payer_id = p_payer_id
          AND cpt_code = p_cpt_code
          AND modifier IS NULL
          AND effective_from <= p_service_date
          AND (effective_to IS NULL OR effective_to >= p_service_date)
          ORDER BY effective_from DESC
        LIMIT 1;
    END IF;

    RETURN v_rate;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION lookup_rate IS
    'Returns the effective rate for a payer/CPT/modifier on a given service date, falling back to standard (no-modifier) rate if specific modifier not found.';