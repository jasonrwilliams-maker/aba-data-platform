"""
config.py — single source of truth for the ABA synthetic data generator.

Everything downstream (trajectory engine, sessions, claims, notes) reads from
here. To change the dataset, edit this file; the generator stays generic.

Design contract:
  - Fixed entities (staff, clients) are constants, referenced by stable string
    keys ("sam", "fatima") rather than DB ids, since ids are SERIAL and assigned
    at insert time. The generator builds a key->id map as it inserts.
  - The "stories" the dataset must demonstrate live in INJECT. Random-but-valid
    data proves nothing; these parameters are what make the analytics land.
  - Sections marked [SME] are clinically-informed guesses for SME to validate.
"""

import datetime as dt
import os

# ---------------------------------------------------------------------------
# DETERMINISM
# ---------------------------------------------------------------------------
# Set once. The generator seeds random, Faker, and numpy from this so the whole
# dataset regenerates byte-identically. Change it only to produce a new variant.
RANDOM_SEED = 20260525

# ---------------------------------------------------------------------------
# TIMELINE ANCHORS
# ---------------------------------------------------------------------------
# "Today" in the narrative: the Monday Kevin starts with Tyler, two days before
# Sam's and Gerdy's reassessments are due (Wednesday). All trajectories are
# generated backward/forward from here.
TODAY = dt.date(2026, 5, 25)
REASSESSMENT_DEADLINE = dt.date(2026, 5, 27)  # Wednesday
AUTH_PERIOD_WEEKS = 26
UNIT_MINUTES = 15

# ---------------------------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------------------------
# Read from environment / .env. Never hardcode credentials here — this file is
# the part of the repo most likely to end up public.
DB = dict(
    host=os.environ.get("POSTGRES_HOST", "localhost"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    dbname=os.environ.get("POSTGRES_DB", "aba_reimbursement_db"),
    user=os.environ.get("POSTGRES_USER", "my_aba_admin"),
    password=os.environ.get("POSTGRES_PASSWORD"),
)

# ---------------------------------------------------------------------------
# STAFF (fixed entities)
# ---------------------------------------------------------------------------
# credential values must already exist in the staff_credentials lookup.
STAFF = {
    "alexandre": dict(
        first_name="Alexandre", last_name="Beaumont",
        credential="BCBA-D", hire_date=dt.date(2023, 1, 9),
        is_owner=True, safety_trainings=["Safety Care"],
    ),
    "fatima": dict(
        first_name="Fatima", last_name="Okonkwo",
        credential="RBT", hire_date=dt.date(2024, 11, 18),
        is_owner=False, safety_trainings=[],
    ),
    "pierce": dict(
        first_name="Pierce", last_name="Halloran",
        credential="RBT", hire_date=dt.date(2025, 11, 17),
        is_owner=False, safety_trainings=["Safety Care"],  # cleared for SIB cases
    ),
    "kevin": dict(
        first_name="Kevin", last_name="Tran",
        credential="RBT", hire_date=dt.date(2026, 5, 25),  # starts today
        is_owner=False, safety_trainings=[],
    ),
}

# ---------------------------------------------------------------------------
# CLIENTS (fixed entities)
# ---------------------------------------------------------------------------
# Three deliberately different lifecycle stages. Each `primary_rbt` and
# `supervising_bcba` are STAFF keys.
CLIENTS = {
    "sam": dict(
        first_name="Sam", last_name="Westbrook",
        date_of_birth=dt.date(2022, 3, 14),
        diagnosis_code="F84.0", diagnosis_date=dt.date(2024, 9, 2),
        diagnosed_by="Developmental pediatrician (synthetic)",
        supervising_bcba="alexandre", primary_rbt="fatima",
        intake_date=dt.date(2024, 11, 25),  # ~18 months ago
        setting="home", payer="Virginia Medicaid", modifier="HN",
        pos_code="12",  # Home
        communication_profile="Vocal; strong mand repertoire; mid-case.",
    ),
    "gerdy": dict(
        first_name="Gerdy", last_name="Aldridge",
        date_of_birth=dt.date(2017, 4, 8),
        diagnosis_code="F84.0", diagnosis_date=dt.date(2025, 8, 19),
        diagnosed_by="Developmental pediatrician (synthetic)",
        supervising_bcba="alexandre", primary_rbt="pierce",
        intake_date=dt.date(2025, 4, 7),  # first episode; later discharged + restarting
        setting="home", payer="Anthem BCBS of Virginia", modifier="HN",
        pos_code="12",  # Home (Falls Church); school-age after-school window
        communication_profile="Nonverbal; AAC user; receptive > expressive; documented SIB.",
        # School-age: sessions M-F only, ~4:15pm-8:30pm. Tight window, no make-ups.
        school_age=True,
    ),
    "tyler": dict(
        first_name="Tyler", last_name="Mendoza",
        date_of_birth=dt.date(2023, 2, 11),
        diagnosis_code="F84.0", diagnosis_date=dt.date(2026, 3, 10),
        diagnosed_by="Children's National (synthetic)",
        supervising_bcba="alexandre", primary_rbt="kevin",
        intake_date=dt.date(2026, 5, 18),  # last week (assessment)
        setting="daycare", payer="Virginia Medicaid", modifier="HN",
        pos_code="03",  # [SME] daycare = School(03)? Other(99)? confirm w/ SME
        communication_profile="Brand new intake; limited baseline; elopement reported.",
    ),
}

# ---------------------------------------------------------------------------
# AUTHORIZATION SPECS  (units, not hours; 26-week periods)
# ---------------------------------------------------------------------------
# Per client, the per-code weekly target the BCBA REQUESTS each period. The
# generator builds a chain of back-to-back periods from intake to present and
# injects the requested-vs-approved gap per renewal (see INJECT below).
#
# 97151 (assessment) is handled separately — VA Medicaid doesn't require prior
# auth for it, so assessment "authorizations" exist only where the payer demands
# them. Tyler's 36-unit assessment was consumed last week.
AUTH_SPECS = {
    "sam":   {"97153": 100, "97155": 15, "97156": 1},   # units/week requested
    "gerdy": {"97153": 80,  "97155": 12, "97156": 1},
    "tyler": {"97153": 120, "97155": 18, "97156": 1},   # 30 hrs/wk push, early intervention
}

# 97156 is event-driven, not weekly-recurring. These are total caregiver-guidance
# sessions to scatter across each client's tenure (clustered around the triggers
# in the comments), NOT a steady cadence. [SME] validate counts/triggers.
CAREGIVER_GUIDANCE = {
    "sam":   6,   # over 18mo; cluster near behavior concerns / program transitions
    "gerdy": 3,   # over 6mo; AAC rollout + two SIB-protocol changes
    "tyler": 0,   # none yet; first one scheduled week 2 of services
}

# ---------------------------------------------------------------------------
# PROGRAM CATALOG 
# ---------------------------------------------------------------------------
# This is the scaffold, not the finished catalog. Shapes are modeled on the
# generic structure of a real ABA note (program -> targets, with a measurement
# type per target). SME should validate names and EXPAND Sam toward the
# described ~60% mastered/maintenance, ~40% acquisition mix across all 5 areas.
#
# skill_area must exist in skill_areas lookup: Play, Expressive, Receptive,
#   Adaptive, VPMTS
# measurement_type ∈ {percent, count, duration, narrative}
# status ∈ {acquisition, maintenance, mastered, discontinued}
PROGRAMS = {
    "sam": [
        dict(skill_area="Receptive", name="Body part identification",
             status="mastered",
             targets=[("Elbow", "percent"), ("Knee", "percent"), ("Wrist", "percent")]),
        dict(skill_area="Play", name="Cooperative turn-taking (3 min)",
             status="maintenance",
             targets=[("Turn-taking duration", "duration")]),
        dict(skill_area="Expressive", name="Tact expansion: community helpers",
             status="acquisition",
             targets=[("Firefighter", "percent"), ("Doctor", "percent"),
                      ("Mail carrier", "percent")]),
        dict(skill_area="Expressive", name="Intraverbal fluency (fill-ins)",
             status="acquisition",
             targets=[("Animal sounds fill-in", "percent")]),
        dict(skill_area="Expressive", name="Independent manding",
             status="maintenance",
             targets=[("Independent mand count", "count")]),
        dict(skill_area="VPMTS", name="Matching to sample",
             status="maintenance",
             targets=[("Identical match", "percent")]),
        # TODO[SME]: add ~6-10 more to reach the described mature mix.
    ],
    "gerdy": [
        dict(skill_area="Expressive", name="FCT: mand via AAC device",
             status="acquisition",
             targets=[("Independent device mand count", "count")]),
        dict(skill_area="Adaptive", name="Tolerance of denied access",
             status="acquisition",
             targets=[("Calm-wait duration", "duration")]),
        dict(skill_area="Receptive", name="Follow 1-step instruction",
             status="acquisition",
             targets=[("1-step instruction accuracy", "percent")]),
        # Behavior reduction (SIB) is tracked in behavior_incidents, NOT here.
        # TODO[SME]: confirm the FCT-heavy emphasis and add maintenance targets.
    ],
    "tyler": [
        dict(skill_area="Play", name="Pairing / rapport building",
             status="acquisition",
             targets=[("Approach-and-engage", "narrative")]),
        dict(skill_area="Expressive", name="Basic manding",
             status="acquisition",
             targets=[("Prompted mand count", "count")]),
        # Brand new — intentionally tiny. Good for Kevin's onboarding demo.
    ],
}

# ---------------------------------------------------------------------------
# INJECTED PATTERNS  ("the stories the data must tell")
# ---------------------------------------------------------------------------
# Each entry below is a deliberate, parameterized pattern the analytics layer
# is meant to surface. If these aren't injected, the dashboards have nothing
# interesting to show. Confirm/adjust the numbers with SME where flagged.
INJECT = dict(

    # --- 1. Payer approval behavior: requested != approved -----------------
    # Per payer, the fraction of REQUESTED 97153 units the payer typically
    # approves, with variability. Other codes approve near-full. This is what
    # makes "approval rate by payer" a real analytic.
    approval_ratio={
        "Virginia Medicaid":        dict(mean=0.88, sd=0.06),  # counters sometimes
        "Anthem BCBS of Virginia":  dict(mean=0.93, sd=0.04),  # approves higher
        "CareFirst BCBS":           dict(mean=0.85, sd=0.07),
    },
    # Payer decision cycle in days (submitted_at -> decision_at). SME: 1-30 day
    # range. Assessment decisions are faster than treatment decisions.
    decision_cycle_days=dict(assessment=(2, 7), treatment=(7, 18), hard_max=30),

    # --- 2. The Fatima December reconciliation finding ---------------------
    # On these many of Sam's December 2025 97153 sessions, the documented end
    # time was one unit (15 min) short of scheduled, but billing used the
    # scheduled amount: scheduled_units > documented_units, billed = scheduled.
    # Net over-billed = units_short * n_sessions. Bills at the 2025 historical
    # rate via lookup_rate. This is the killer vignette — keep it precise.
    fatima_discrepancy=dict(
        client="sam", provider="fatima",
        month=(2025, 12), n_sessions_affected=11, units_short_each=1,
    ),

    # --- 3. Supervision ratio (97155 as % of 97153) ------------------------
    # BACB best practice 10-20%; Alexandre targets ~15%. Inject one dip below
    # 10% (e.g., a stretch where Alexandre was out) so the compliance panel
    # has a real flag to surface. Solo-BCBA practices are genuinely exposed here.
    supervision_ratio_target=0.15,
    supervision_dip=dict(client="gerdy", weeks=("2026-02-09", "2026-02-22"), ratio=0.07),

    # --- 4. Utilization (delivered vs. planned) ----------------------------
    # Weekly cancellation/no-show probabilities. Gerdy's school-age window has
    # NO make-up slack, so cancellations directly depress utilization — a
    # different shape than Sam's. Tyler hasn't started (utilization n/a).
    cancellation_rate=dict(sam=0.05, gerdy=0.10, tyler=0.0),
    no_show_rate=dict(sam=0.02, gerdy=0.03, tyler=0.0),

    # --- 5. Behavior incidents (Gerdy, event-triggered) --------------------
    # Per-session probability that SIB occurs, clustered around demand /
    # denied-access antecedents. Sam minimal; Tyler occasional elopement.
    behavior=dict(
        gerdy=dict(per_session_prob=0.35, antecedents=["demand presented", "denied access"],
                   behaviors=["head-hitting", "hand-biting"],
                   interventions=["Functional Communication Training (FCT)",
                                  "Response Blocking", "Differential Reinforcement"]),
        sam=dict(per_session_prob=0.04, antecedents=["demand presented"],
                 behaviors=["task refusal"],
                 interventions=["Demand Fading", "Premack Principle"]),
        tyler=dict(per_session_prob=0.08, antecedents=["transition"],
                   behaviors=["elopement"], interventions=["Redirection"]),
    ),

    # --- 6. Claims status mix ----------------------------------------------
    # Most claims paid; a realistic denial slice gives the (deferred) financial
    # dashboard something to analyze. Recent claims still draft/submitted.
    claim_denial_rate=dict(default=0.06),
    claim_denial_reasons=[("CO-197", "Authorization missing/invalid"),
                          ("CO-16",  "Claim lacks required information"),
                          ("CO-50",  "Not deemed medically necessary")],

    # --- 7. Document expirations -------------------------------------------
    # Force at least one HIPAA auth / medical consent to expire within 30 days
    # so the expiration index ("what's expiring soon") has a live row to show.
    expiring_consent=dict(client="gerdy", document_type="hipaa_authorization",
                          expires=dt.date(2026, 6, 15)),
)

# ---------------------------------------------------------------------------
# GENERATION ORDER (for reference — the engine walks this top to bottom)
# ---------------------------------------------------------------------------
GENERATION_ORDER = [
    "staff",
    "clients",
    "service_locations",
    "client_documents",
    "assessment_authorizations",   # where payer requires them (Tyler 97151)
    "assessment_sessions",         # 97151/97152 -> produce the plan
    "treatment_plans",             # FK back to assessment session
    "ongoing_authorizations",      # chain of 26-wk periods; FK to plan
    "programs",
    "targets",
    "ongoing_sessions",            # 97153/97155 + scattered 97156
    "session_target_data",         # typed per target.measurement_type
    "behavior_incidents",
    "session_notes",
    "session_interventions",
    "claims",                      # amount_billed via lookup_rate(payer,cpt,mod,date)
    "audit_log",
]