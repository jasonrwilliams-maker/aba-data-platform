-- ============================================================================
-- ABA Clinical Data Platform — Reference Data Seed (v3)
-- ============================================================================
-- Changes from v1:
--   1. ON CONFLICT DO UPDATE replaces DO NOTHING. The seed file is now the
--      source of truth: edit the file, re-run it, database reflects changes.
--   2. Telehealth POS codes (02, 10) added. This clinic doesn't currently use
--      them but the codes exist in reference data because the system
--      supports them — important for equity in rural service delivery.
--
-- Idempotent by design: every INSERT uses ON CONFLICT DO UPDATE, so
-- running this file twice updates existing rows to match the file.
--
-- Sections flagged [VERIFY WITH SME] are clinically informed guesses.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. CPT CODES
-- ----------------------------------------------------------------------------
-- The seven ABA CPT codes defined by the AMA's Category I codeset.
-- ----------------------------------------------------------------------------

INSERT INTO cpt_codes (code, description, unit_minutes, allowed_renderers, requires_supervision_concurrent, notes) VALUES
    ('97151', 'Behavior identification assessment, administered by a physician or other qualified health care professional', 15, ARRAY['BCBA-D', 'BCBA'], FALSE, 'Initial and re-assessment. BCBA-administered. Produces the treatment plan.'),
    ('97152', 'Behavior identification supporting assessment, administered by one technician under the direction of a physician or other QHP', 15, ARRAY['RBT', 'BCaBA'], TRUE, 'RBT-administered assessment support. BCBA must direct.'),
    ('97153', 'Adaptive behavior treatment by protocol, administered by technician under direction of a physician or other QHP', 15, ARRAY['RBT', 'BCaBA', 'BCBA'], FALSE, 'The core direct-service code. RBT delivers the protocol.'),
    ('97155', 'Adaptive behavior treatment with protocol modification, administered by a physician or other QHP, with or without one technician', 15, ARRAY['BCBA-D', 'BCBA', 'BCaBA'], FALSE, 'BCBA modifies protocols in real time. Often concurrent with 97153.'),
    ('97156', 'Family adaptive behavior treatment guidance, administered by physician or other QHP (with or without the patient present), face-to-face with guardian(s)/caregiver(s)', 15, ARRAY['BCBA-D', 'BCBA'], FALSE, 'Caregiver training. With or without client present.'),
    ('97157', 'Multiple-family group adaptive behavior treatment guidance, administered by physician or other QHP, face-to-face with multiple sets of guardians/caregivers', 15, ARRAY['BCBA-D', 'BCBA'], FALSE, 'Group caregiver training across families.'),
    ('97158', 'Group adaptive behavior treatment with protocol modification, administered by physician or other QHP, face-to-face with multiple patients', 15, ARRAY['BCBA-D', 'BCBA'], FALSE, 'BCBA-led group services. Requires 2+ clients.')
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description,
    unit_minutes = EXCLUDED.unit_minutes,
    allowed_renderers = EXCLUDED.allowed_renderers,
    requires_supervision_concurrent = EXCLUDED.requires_supervision_concurrent,
    notes = EXCLUDED.notes;


-- ----------------------------------------------------------------------------
-- 2. STAFF CREDENTIALS
-- ----------------------------------------------------------------------------

INSERT INTO staff_credentials (credential, description, can_supervise, tier) VALUES
    ('BCBA-D', 'Board Certified Behavior Analyst — Doctoral', TRUE, 3),
    ('BCBA', 'Board Certified Behavior Analyst', TRUE, 3),
    ('BCaBA', 'Board Certified Assistant Behavior Analyst', TRUE, 2),
    ('RBT', 'Registered Behavior Technician', FALSE, 1)
ON CONFLICT (credential) DO UPDATE SET
    description = EXCLUDED.description,
    can_supervise = EXCLUDED.can_supervise,
    tier = EXCLUDED.tier;


-- ----------------------------------------------------------------------------
-- 3. SKILL AREAS
-- ----------------------------------------------------------------------------
-- [VERIFY WITH SME]: Descriptions are paraphrases. Names match her note.
-- ----------------------------------------------------------------------------

INSERT INTO skill_areas (name, description, display_order) VALUES
    ('Play', 'Cooperative and independent play skills, leisure engagement', 1),
    ('Expressive', 'Vocal/AAC manding, tacting, intraverbals, requesting', 2),
    ('Receptive', 'Following instructions, identifying items/concepts, listener skills', 3),
    ('Adaptive', 'Self-care, toileting, hygiene, daily living skills', 4),
    ('VPMTS', 'Visual Performance/Matching-to-Sample (puzzles, sorting, matching)', 5)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    display_order = EXCLUDED.display_order;


-- ----------------------------------------------------------------------------
-- 4. INTERVENTION TYPES
-- ----------------------------------------------------------------------------
-- [VERIFY WITH SME]: Categorization is best-read from ABA textbooks.
-- ----------------------------------------------------------------------------

INSERT INTO intervention_types (name, category, description) VALUES
    ('Environmental Modification', 'antecedent', 'Adjusting the physical/social environment to prevent target behaviors'),
    ('Transitional Countdown', 'antecedent', 'Verbal countdown before transitions to reduce resistance'),
    ('Demand Fading', 'antecedent', 'Gradual reduction of demand level to reduce escape behavior'),
    ('Premack Principle', 'antecedent', 'Pairing high-probability behavior to reinforce low-probability behavior'),
    ('Functional Communication Training (FCT)', 'replacement', 'Teaching a functional communicative response to replace problem behavior'),
    ('Differential Reinforcement', 'consequence', 'Reinforcing alternative/incompatible behaviors while extinguishing target behavior'),
    ('Redirection', 'consequence', 'Verbal or physical redirection to alternative activity'),
    ('Extinction', 'consequence', 'Withholding reinforcement that previously maintained the behavior'),
    ('Token Economy', 'consequence', 'Conditioned reinforcement system with exchangeable tokens'),
    ('Response Blocking', 'consequence', 'Physically preventing completion of self-injurious or dangerous behavior')
ON CONFLICT (name) DO UPDATE SET
    category = EXCLUDED.category,
    description = EXCLUDED.description;


-- ----------------------------------------------------------------------------
-- 5. PLACE OF SERVICE CODES
-- ----------------------------------------------------------------------------
-- CMS-standard POS codes. Telehealth (02, 10) included because the system
-- supports them even though this clinic currently doesn't use them. Important
-- for ABA-desert equity: rural BCBAs may use 02/10 for supervision (97155)
-- and caregiver guidance (97156). Direct 97153 is rarely telehealth-eligible
-- in state Medicaid programs.
-- ----------------------------------------------------------------------------

INSERT INTO place_of_service_codes (code, description) VALUES
    ('02', 'Telehealth Provided Other than in Patient''s Home'),
    ('03', 'School'),
    ('10', 'Telehealth Provided in Patient''s Home'),
    ('11', 'Office'),
    ('12', 'Home'),
    ('99', 'Other Place of Service')
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description;


-- ----------------------------------------------------------------------------
-- 6. PAYERS
-- ----------------------------------------------------------------------------

INSERT INTO payers (name, payer_type, state, auth_period_weeks, notes) VALUES
    ('Virginia Medicaid', 'medicaid', 'VA', 26, 'Primary payer. ~60% of revenue.'),
    ('Anthem BCBS of Virginia', 'commercial', 'VA', 26, 'Commercial payer.'),
    ('CareFirst BCBS', 'commercial', 'VA', 26, 'Commercial payer.')
ON CONFLICT (name) DO UPDATE SET
    payer_type = EXCLUDED.payer_type,
    state = EXCLUDED.state,
    auth_period_weeks = EXCLUDED.auth_period_weeks,
    notes = EXCLUDED.notes;

-- ----------------------------------------------------------------------------
-- 7. DOCUMENT TYPES
-- ----------------------------------------------------------------------------
-- Intake and ongoing documentation tracked at the client level. The four
-- required-for-intake types are the gates a new client clears before
-- services can begin. Documents with has_expiration = TRUE need to be
-- re-signed periodically — typically annually — and the schema's partial
-- index on expiration_date supports surfacing them for renewal.
-- [VERIFY WITH RIANE]: Set of types and which are required/expire.
-- ----------------------------------------------------------------------------

INSERT INTO document_types (name, description, required_for_intake, has_expiration) VALUES
    ('medical_consent_to_treat', 'Parent/guardian consent authorizing ABA services', TRUE, TRUE),
    ('diagnostic_report', 'Documented autism diagnosis from qualified provider', TRUE, FALSE),
    ('aba_referral', 'Referral for ABA services from primary care or specialist', TRUE, FALSE),
    ('hipaa_authorization', 'HIPAA authorization for use and disclosure of PHI', TRUE, TRUE),
    ('insurance_card', 'Copy of current insurance card (front and back)', FALSE, TRUE),
    ('release_of_information', 'Authorization to share records with named third parties', FALSE, TRUE),
    ('iep', 'Individualized Education Program (school-age clients)', FALSE, FALSE),
    ('prior_provider_records', 'Clinical records from previous ABA provider', FALSE, FALSE)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    required_for_intake = EXCLUDED.required_for_intake,
    has_expiration = EXCLUDED.has_expiration;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Expected counts: 7 CPT codes, 4 credentials, 5 skill areas,
-- 10 intervention types, 6 POS codes (4 in-person + 2 telehealth), 3 payers.
-- ============================================================================

-- SELECT 'cpt_codes' AS table_name, COUNT(*) AS row_count FROM cpt_codes
-- UNION ALL SELECT 'staff_credentials', COUNT(*) FROM staff_credentials
-- UNION ALL SELECT 'skill_areas', COUNT(*) FROM skill_areas
-- UNION ALL SELECT 'intervention_types', COUNT(*) FROM intervention_types
-- UNION ALL SELECT 'place_of_service_codes', COUNT(*) FROM place_of_service_codes
-- UNION ALL SELECT 'payers', COUNT(*) FROM payers;
