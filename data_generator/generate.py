"""
generate.py — the machine that turns config.py into loadable SQL.

Run:  python generate.py   ->  writes 03_generate_tenant_data.sql

Pipeline: config.py (facts) -> generate.py (machine) -> SQL file -> database.

STAGES
  1: harness + fixed entities (staff, clients, locations, documents)
  2: assessment auths + 97151 sessions, treatment plans, ongoing auth chain
     (with requested-vs-approved gaps), programs, targets
  3: the session calendar (97153 direct + 97155 supervision + 97156 caregiver),
     session target data, behavior incidents, notes, the lone Fatima December
     discrepancy, claims (priced via lookup_rate), and a small audit sample
"""

import datetime as dt
import random
from decimal import Decimal

import config

random.seed(config.RANDOM_SEED)

PERIOD_DAYS = 182
ASSESSMENT_UNITS = {"initial": 36, "reassessment": 20}

# Which RBT delivers each client's direct (97153) services.
RBT = {"sam": "fatima", "gerdy": "pierce", "tyler": "kevin"}


# ---------------------------------------------------------------------------
# HARNESS
# ---------------------------------------------------------------------------
class Raw:
    def __init__(self, sql):
        self.sql = sql


def q(value):
    if isinstance(value, Raw):
        return value.sql
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, dt.datetime):
        return "'" + value.isoformat(sep=" ") + "'"
    if isinstance(value, dt.date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, (list, tuple)):
        if not value:
            return "ARRAY[]::text[]"
        return "ARRAY[" + ", ".join(q(v) for v in value) + "]::text[]"
    return "'" + str(value).replace("'", "''") + "'"


def payer_ref(name):
    return Raw(f"(SELECT id FROM payers WHERE name = {q(name)})")


class Writer:
    def __init__(self):
        self.lines = []

    def section(self, title):
        self.lines += ["", "-- " + "-" * 73, "-- " + title, "-- " + "-" * 73]

    def insert(self, table, row):
        cols = ", ".join(row.keys())
        vals = ", ".join(q(v) for v in row.values())
        self.lines.append(f"INSERT INTO {table} ({cols}) VALUES ({vals});")

    def raw(self, sql):
        self.lines.append(sql)

    def text(self):
        return "\n".join(self.lines) + "\n"


ids = {t: {} for t in ("staff", "clients", "service_locations", "client_documents",
                       "authorizations", "treatment_plans", "sessions",
                       "programs", "targets")}


def alloc(table, key=None):
    nid = len(ids[table]) + 1
    ids[table][key if key is not None else nid] = nid
    return nid


w = Writer()
w.raw("-- ============================================================================")
w.raw("-- ABA Clinical Data Platform — Tenant Data (generated; do not hand-edit)")
w.raw(f"-- Generated from config.py with RANDOM_SEED={config.RANDOM_SEED}")
w.raw("-- Re-runnable: TRUNCATE clears tenant data, preserves reference tables.")
w.raw("-- ============================================================================")
w.raw("")
w.raw("BEGIN;")
w.raw("")
w.raw("TRUNCATE staff, clients RESTART IDENTITY CASCADE;")

# Cross-stage state.
initial_plan = {}          # client_key -> first plan id
client_targets = {}        # client_key -> [(target_id, mtype, status)]
service_spans = []         # approved 97153 spans Stage 3 turns into sessions
session_rows = []          # (session_id, client_key, cpt, date, rendering_key) for claims/audit
fatima_dec_count = 0       # how many December discrepancy rows we actually placed


# ---------------------------------------------------------------------------
# STAGE 1
# ---------------------------------------------------------------------------
def gen_staff():
    w.section("staff")
    for key, s in config.STAFF.items():
        sid = alloc("staff", key)
        w.insert("staff", dict(
            id=sid, first_name=s["first_name"], last_name=s["last_name"],
            credential=s["credential"], npi=f"{1000000000 + sid}",
            email=f"{s['first_name'].lower()}@tidewater-aba.example",
            hire_date=s["hire_date"], termination_date=None,
            is_owner=s["is_owner"], safety_trainings=s["safety_trainings"]))


def gen_clients():
    w.section("clients")
    for key, c in config.CLIENTS.items():
        cid = alloc("clients", key)
        w.insert("clients", dict(
            id=cid, first_name=c["first_name"], last_name=c["last_name"],
            date_of_birth=c["date_of_birth"], diagnosis_code=c["diagnosis_code"],
            diagnosis_date=c["diagnosis_date"], diagnosed_by=c["diagnosed_by"],
            supervising_bcba_id=ids["staff"][c["supervising_bcba"]],
            intake_date=c["intake_date"], discharge_date=None,
            communication_profile=c["communication_profile"], notes=None))


def gen_service_locations():
    w.section("service_locations")
    labels = {"home": "Primary residence", "daycare": "Bright Beginnings Daycare"}
    for key, c in config.CLIENTS.items():
        lid = alloc("service_locations", key)
        w.insert("service_locations", dict(
            id=lid, client_id=ids["clients"][key],
            label=labels.get(c["setting"], c["setting"].title()), address=None,
            place_of_service_code=c["pos_code"], is_primary=True, active=True))


def gen_client_documents():
    w.section("client_documents")
    required = [("medical_consent_to_treat", True), ("diagnostic_report", False),
                ("aba_referral", False), ("hipaa_authorization", True)]
    exp = config.INJECT["expiring_consent"]
    for key, c in config.CLIENTS.items():
        received = c["intake_date"]
        for doc_type, expires in required:
            did = alloc("client_documents")
            if key == exp["client"] and doc_type == exp["document_type"]:
                expiration = exp["expires"]
            elif expires:
                expiration = received + dt.timedelta(days=365)
            else:
                expiration = None
            w.insert("client_documents", dict(
                id=did, client_id=ids["clients"][key], document_type=doc_type,
                received_date=received, expiration_date=expiration, file_path=None,
                uploaded_by_id=ids["staff"]["alexandre"],
                uploaded_at=dt.datetime.combine(received, dt.time(9, 0)), notes=None))


# ---------------------------------------------------------------------------
# STAGE 2
# ---------------------------------------------------------------------------
def split_units(total):
    if total > 24:
        h = total // 2
        return [h, total - h]
    return [total]


def add_assessment(client_key, plan_type, around_date):
    c = config.CLIENTS[client_key]
    units = ASSESSMENT_UNITS[plan_type]
    aid = alloc("authorizations")
    w.insert("authorizations", dict(
        id=aid, client_id=ids["clients"][client_key], payer_id=payer_ref(c["payer"]),
        cpt_code="97151", treatment_plan_id=None,
        units_requested=units, units_authorized=units, units_per_week_planned=units,
        period_start=around_date, period_end=around_date + dt.timedelta(days=13),
        authorization_number=f"ASMT-{client_key[:3].upper()}-{around_date:%y%m}",
        submitted_at=dt.datetime.combine(around_date - dt.timedelta(days=7), dt.time(10)),
        decision_at=dt.datetime.combine(around_date - dt.timedelta(days=2), dt.time(10)),
        approved_date=around_date - dt.timedelta(days=2), status="approved", notes=None))

    first = None
    day = around_date
    for chunk in split_units(units):
        sid = alloc("sessions")
        if first is None:
            first = sid
        start = dt.datetime.combine(day, dt.time(10))
        end = start + dt.timedelta(minutes=chunk * config.UNIT_MINUTES)
        w.insert("sessions", dict(
            id=sid, client_id=ids["clients"][client_key], cpt_code="97151",
            authorization_id=aid, rendering_provider_id=ids["staff"]["alexandre"],
            supervising_bcba_id=ids["staff"]["alexandre"],
            service_location_id=ids["service_locations"][client_key],
            place_of_service_code=c["pos_code"], scheduled_start=start, scheduled_end=end,
            actual_start=start, actual_end=end, scheduled_units=chunk,
            documented_units=chunk, billed_units=chunk, status="locked",
            signed_by_id=ids["staff"]["alexandre"], signed_at=end + dt.timedelta(days=1),
            locked_at=end + dt.timedelta(days=2),
            notes="Initial assessment" if plan_type == "initial" else "Reassessment"))
        session_rows.append((sid, client_key, "97151", day, "alexandre", aid))
        claim_units[sid] = chunk          # assessment sessions are billable too
        day += dt.timedelta(days=1)
    return first


def approved_97153(client_key, period_index, requested):
    if period_index == 0:
        return requested
    if client_key == "sam" and period_index == 2:
        return 2080                                  # the LinkedIn-post counter
    r = config.INJECT["approval_ratio"][config.CLIENTS[client_key]["payer"]]
    return int(round(requested * max(0.6, min(1.0, random.gauss(r["mean"], r["sd"])))))


def add_treatment_plan(client_key, plan_type, period, src_session, state):
    c = config.CLIENTS[client_key]
    p_start, p_end = period
    pid = alloc("treatment_plans")
    if state == "drafting":
        bs = gs = sub = lock = gname = None
    else:
        if state == "completed":
            bs = dt.datetime.combine(p_start - dt.timedelta(days=3), dt.time(16))
            gs = dt.datetime.combine(p_start - dt.timedelta(days=2), dt.time(16))
            sub = dt.datetime.combine(p_start - dt.timedelta(days=1), dt.time(9))
            lock = dt.datetime.combine(p_start + dt.timedelta(days=1), dt.time(9))
        else:
            base = config.TODAY - dt.timedelta(days=4)
            bs = dt.datetime.combine(base, dt.time(16))
            gs = dt.datetime.combine(base + dt.timedelta(days=1), dt.time(16))
            sub = dt.datetime.combine(base + dt.timedelta(days=2), dt.time(9))
            lock = None
        gname = f"Parent/Guardian of {c['first_name']}"
    w.insert("treatment_plans", dict(
        id=pid, client_id=ids["clients"][client_key], plan_type=plan_type,
        period_start=p_start, period_end=p_end, source_assessment_session_id=src_session,
        clinical_narrative=f"{plan_type.title()} treatment plan for {c['first_name']}.",
        signed_by_bcba_id=ids["staff"]["alexandre"] if bs else None, signed_at=bs,
        signed_by_guardian_at=gs, guardian_name=gname,
        submitted_to_payer_id=payer_ref(c["payer"]) if sub else None,
        submitted_at=sub, locked_at=lock, generated_pdf_path=None, notes=None))
    return pid


def add_period_auths(client_key, plan_id, period, state, period_index,
                     session_end=None):
    """Create the three ongoing auths for a period; record an approved-97153
    span for Stage 3 to turn into sessions."""
    c = config.CLIENTS[client_key]
    p_start, p_end = period
    span_auths = {}
    for cpt, weekly in config.AUTH_SPECS[client_key].items():
        requested = weekly * 26
        aid = alloc("authorizations")
        if state == "pending":
            authorized, decision_at, approved_date, status = None, None, None, "pending"
            submitted_at = dt.datetime.combine(config.TODAY - dt.timedelta(days=5), dt.time(10))
        else:
            authorized = approved_97153(client_key, period_index, requested) if cpt == "97153" else requested
            if state == "current_approved":
                submitted_at = dt.datetime.combine(config.TODAY - dt.timedelta(days=14), dt.time(10))
                decision_at = dt.datetime.combine(config.TODAY - dt.timedelta(days=7), dt.time(10))
            else:
                submitted_at = dt.datetime.combine(p_start - dt.timedelta(days=14), dt.time(10))
                decision_at = submitted_at + dt.timedelta(
                    days=random.randint(*config.INJECT["decision_cycle_days"]["treatment"]))
            approved_date = decision_at.date()
            status = "approved"
        w.insert("authorizations", dict(
            id=aid, client_id=ids["clients"][client_key], payer_id=payer_ref(c["payer"]),
            cpt_code=cpt, treatment_plan_id=plan_id, units_requested=requested,
            units_authorized=authorized, units_per_week_planned=weekly,
            period_start=p_start, period_end=p_end,
            authorization_number=f"{cpt}-{client_key[:3].upper()}-P{period_index + 1}",
            submitted_at=submitted_at, decision_at=decision_at,
            approved_date=approved_date, status=status, notes=None))
        span_auths[cpt] = (aid, authorized)

    # Only approved 97153 spans become sessions.
    if status == "approved" and span_auths["97153"][1]:
        s_end = session_end or min(p_end, config.TODAY)
        s_start = max(p_start, config.TODAY) if state == "current_approved" else p_start
        service_spans.append(dict(
            client_key=client_key, auths=span_auths, start=s_start, end=s_end,
            weekly_97153=span_auths["97153"][1] / 26.0,
            weekly_97155=span_auths["97155"][1] / 26.0,
            future=(state == "current_approved")))


def gen_authorizations_and_plans():
    w.section("authorizations, assessment sessions, treatment plans")

    # --- Sam & Tyler: continuous chain through the current period ---
    for client_key in ("sam", "tyler"):
        c = config.CLIENTS[client_key]
        start = c["intake_date"]
        periods = []
        while start <= config.TODAY:
            periods.append((start, start + dt.timedelta(days=PERIOD_DAYS - 1)))
            start = periods[-1][1] + dt.timedelta(days=1)
        last = len(periods) - 1
        for i, period in enumerate(periods):
            ptype = "initial" if i == 0 else "reassessment"
            if i < last:
                state = "completed"
            elif client_key == "sam":
                state = "drafting"            # Wednesday deadline
            else:
                state = "current_approved"    # Tyler, just approved
            assess = period[0] if state == "completed" else config.TODAY - dt.timedelta(days=7)
            src = add_assessment(client_key, ptype, assess)
            plan = add_treatment_plan(client_key, ptype, period, src, state)
            if i == 0:
                initial_plan[client_key] = plan
            if state != "drafting":
                add_period_auths(client_key, plan, period, state, i)

    # --- Gerdy: episode 1 (spring–summer 2025) -> discharge -> restart now ---
    g = config.CLIENTS["gerdy"]
    ep1 = (g["intake_date"], g["intake_date"] + dt.timedelta(days=PERIOD_DAYS - 1))
    # First episode: assessment + initial plan + approved auths, but services
    # stop ~late September (parents pull before/around the school year). The
    # gap that follows is what carries the "she left and came back" story.
    src = add_assessment("gerdy", "initial", ep1[0])
    plan = add_treatment_plan("gerdy", "initial", ep1, src, "completed")
    initial_plan["gerdy"] = plan
    discharge = dt.date(2025, 9, 26)
    add_period_auths("gerdy", plan, ep1, "completed", 0, session_end=discharge)

    # ~8-month gap (no auths, no sessions) — then the restart this week.
    restart = (config.TODAY, config.TODAY + dt.timedelta(days=PERIOD_DAYS - 1))
    src2 = add_assessment("gerdy", "reassessment", config.TODAY - dt.timedelta(days=7))
    plan2 = add_treatment_plan("gerdy", "reassessment", restart, src2, "pending")
    add_period_auths("gerdy", plan2, restart, "pending", 1)   # pending -> no sessions yet


def gen_programs_and_targets():
    w.section("programs and targets")
    for client_key, programs in config.PROGRAMS.items():
        intake = config.CLIENTS[client_key]["intake_date"]
        plan_id = initial_plan[client_key]
        client_targets[client_key] = []
        for prog in programs:
            pid = alloc("programs")
            status = prog["status"]
            w.insert("programs", dict(
                id=pid, client_id=ids["clients"][client_key],
                skill_area=prog["skill_area"], program_name=prog["name"], status=status,
                started_date=intake,
                mastered_date=intake + dt.timedelta(days=120) if status == "mastered" else None,
                maintenance_date=intake + dt.timedelta(days=90) if status == "maintenance" else None,
                discontinued_date=None, introduced_in_plan_id=plan_id, notes=None))
            for tname, mtype in prog["targets"]:
                tid = alloc("targets")
                w.insert("targets", dict(
                    id=tid, program_id=pid, target_name=tname, measurement_type=mtype,
                    mastery_criterion="80% across 3 consecutive sessions", status=status,
                    started_date=intake,
                    mastered_date=intake + dt.timedelta(days=120) if status == "mastered" else None,
                    notes=None))
                client_targets[client_key].append((tid, mtype, status))


# ---------------------------------------------------------------------------
# STAGE 3 — sessions, data, incidents, notes, claims, audit
# ---------------------------------------------------------------------------

def target_value(mtype, status, progress):
    """Return (percent, count, dur, text) with exactly one populated — the
    bonobo-proof rule. `progress` is 0..1 across the program's life."""
    if mtype == "percent":
        base = {"mastered": 92, "maintenance": 88, "acquisition": 35,
                "discontinued": 50}[status]
        if status == "acquisition":
            base = 35 + 50 * progress
        val = max(0, min(100, base + random.gauss(0, 6)))
        return (round(val, 1), None, None, None)
    if mtype == "count":
        base = 2 + int(10 * progress) if status == "acquisition" else random.randint(6, 14)
        return (None, max(0, base + random.randint(-2, 2)), None, None)
    if mtype == "duration":
        return (None, None, random.randint(45, 600), None)
    return (None, None, None, random.choice(
        ["Engaged with full prompting.", "Independent with intermittent prompts.",
         "Tolerated activity for the full interval.", "Required redirection mid-task."]))


def add_session(client_key, cpt, day, units, rendering_key, auth_id, completed,
                documented=None, billed=None):
    c = config.CLIENTS[client_key]
    sid = alloc("sessions")
    hour = 10 if c["setting"] != "home" or not c.get("school_age") else 16
    start = dt.datetime.combine(day, dt.time(hour))
    end = start + dt.timedelta(minutes=units * config.UNIT_MINUTES)
    documented = units if (completed and documented is None) else documented
    billed = (documented if billed is None else billed) if completed else None
    w.insert("sessions", dict(
        id=sid, client_id=ids["clients"][client_key], cpt_code=cpt, authorization_id=auth_id,
        rendering_provider_id=ids["staff"][rendering_key],
        supervising_bcba_id=ids["staff"]["alexandre"],
        service_location_id=ids["service_locations"][client_key],
        place_of_service_code=c["pos_code"], scheduled_start=start, scheduled_end=end,
        actual_start=start if completed else None, actual_end=end if completed else None,
        scheduled_units=units, documented_units=documented, billed_units=billed,
        status="locked" if completed else "scheduled",
        signed_by_id=ids["staff"][rendering_key] if completed else None,
        signed_at=end + dt.timedelta(days=1) if completed else None,
        locked_at=end + dt.timedelta(days=2) if completed else None, notes=None))
    if completed:
        session_rows.append((sid, client_key, cpt, day, rendering_key, auth_id))
    return sid


def gen_sessions():
    global fatima_dec_count
    w.section("sessions (direct, supervision, caregiver), data, incidents, notes")

    # Sam's early-history absence clusters (a vacation, an illness week).
    sam_intake = config.CLIENTS["sam"]["intake_date"]
    sam_blackouts = []
    for offset in (40, 150):                      # ~weeks 6 and 21
        s0 = sam_intake + dt.timedelta(days=offset)
        sam_blackouts += [s0 + dt.timedelta(days=d) for d in range(7)]

    for span in service_spans:
        ck = span["client_key"]
        rbt = RBT[ck]
        beh = config.INJECT["behavior"].get(ck, {})
        absence = (config.INJECT["cancellation_rate"].get(ck, 0)
                   + config.INJECT["no_show_rate"].get(ck, 0))
        daily = max(4, round(span["weekly_97153"] / 5))     # ~5 weekday sessions
        weekly_sup = span["weekly_97155"]
        seen_weeks = set()

        day = span["start"]
        while day <= span["end"]:
            if day.weekday() < 5:                            # Mon–Fri
                future = day >= config.TODAY
                missed = (ck == "sam" and day in sam_blackouts) or (random.random() < absence)
                if missed and not future:
                    # cancelled/no-show: a row, but unbilled, no child data
                    add_session(ck, "97153", day, daily, rbt, span["auths"]["97153"][0],
                                completed=False)
                    # mark it cancelled rather than scheduled
                    w.lines[-1] = w.lines[-1].replace("'scheduled'",
                        "'no_show'" if random.random() < 0.3 else "'cancelled'")
                else:
                    # Fatima December discrepancy: documented 1 unit short, billed full.
                    doc = billed = None
                    if (ck == "sam" and day.year == 2025 and day.month == 12
                            and fatima_dec_count < config.INJECT["fatima_discrepancy"]["n_sessions_affected"]
                            and not future):
                        doc = daily - config.INJECT["fatima_discrepancy"]["units_short_each"]
                        billed = daily
                        fatima_dec_count += 1
                    sid = add_session(ck, "97153", day, daily, rbt,
                                      span["auths"]["97153"][0], completed=not future,
                                      documented=doc, billed=billed)
                    if not future:
                        add_session_children(ck, sid, day, span)

                # one supervision session per ISO week (BCBA, concurrent-ish)
                wk = day.isocalendar()[:2]
                if wk not in seen_weeks and weekly_sup >= 1 and not future:
                    seen_weeks.add(wk)
                    add_session(ck, "97155", day, max(1, round(weekly_sup)),
                                "alexandre", span["auths"]["97155"][0], completed=True)
            day += dt.timedelta(days=1)

        # caregiver guidance (97156): event-driven, scattered across the span
        n = config.CAREGIVER_GUIDANCE.get(ck, 0)
        span_days = (span["end"] - span["start"]).days
        for _ in range(n):
            d = span["start"] + dt.timedelta(days=random.randint(10, max(11, span_days - 5)))
            while d.weekday() >= 5:
                d += dt.timedelta(days=1)
            if d < config.TODAY:
                add_session(ck, "97156", d, 4, "alexandre", span["auths"]["97156"][0],
                            completed=True)


def add_session_children(ck, sid, day, span):
    """Target data, behavior incidents, a note, and interventions for one
    completed 97153 session."""
    # session_target_data — a subset of the client's targets, typed correctly
    targets = client_targets.get(ck, [])
    intake = config.CLIENTS[ck]["intake_date"]
    progress = max(0.0, min(1.0, (day - intake).days / 365.0))
    for tid, mtype, status in random.sample(targets, k=min(len(targets),
                                                           random.randint(3, max(3, len(targets))))):
        pct, cnt, dur, txt = target_value(mtype, status, progress)
        w.insert("session_target_data", dict(
            session_id=sid, target_id=tid, measurement_type=mtype,
            value_percent=pct, value_count=cnt, value_duration_sec=dur,
            value_text=txt, notes=None))

    # behavior incidents — event-triggered (mostly Gerdy)
    beh = config.INJECT["behavior"].get(ck)
    if beh and random.random() < beh["per_session_prob"]:
        w.insert("behavior_incidents", dict(
            session_id=sid,
            incident_time=dt.datetime.combine(day, dt.time(11, random.randint(0, 59))),
            antecedent=random.choice(beh["antecedents"]),
            behavior=random.choice(beh["behaviors"]),
            consequence="Intervention applied; behavior de-escalated.",
            duration_sec=random.randint(20, 240),
            intensity=random.choice(["low", "moderate", "moderate", "high"]),
            intervention_used=random.choice(beh["interventions"]), notes=None))
        for iv in random.sample(beh["interventions"], k=min(2, len(beh["interventions"]))):
            w.insert("session_interventions", dict(session_id=sid, intervention_name=iv))

    # a short SOAP-ish note
    w.insert("session_notes", dict(
        session_id=sid, attendees=[config.CLIENTS[ck]["first_name"], "RBT"],
        skill_acquisition_methods=["DTT", "NET"],
        session_narrative=("Session ran as scheduled across active programs; "
                           "client engaged with prompting as needed."),
        progress_toward_goals="Steady progress on acquisition targets.",
        progress_made_note=None, barriers_to_treatment=None,
        medical_concerns=False, medical_concerns_detail=None,
        created_at=dt.datetime.combine(day, dt.time(18)),
        updated_at=dt.datetime.combine(day, dt.time(18))))


def gen_claims_and_audit():
    w.section("claims (priced via lookup_rate) and audit sample")
    reasons = config.INJECT["claim_denial_reasons"]
    denial_rate = config.INJECT["claim_denial_rate"]["default"]

    for sid, ck, cpt, day, rkey, auth_id in session_rows:
        c = config.CLIENTS[ck]
        # 97153 in the home bills with the HN modifier; everything else standard.
        modifier = "HN" if (cpt == "97153" and c["setting"] == "home") else None
        units = {"97151": 18, "97155": None, "97156": 4}.get(cpt)  # filled below
        # recover billed units from nothing stored -> recompute by cpt/role
        # (assessment chunks were 18/20; supervision/caregiver fixed; 97153 daily)
        # Simpler: re-derive from the session we just need a number; use a lookup.
        units = claim_units.get(sid)
        if not units:
            continue
        mod_sql = q(modifier)
        rate = f"lookup_rate({payer_ref(c['payer']).sql}, '{cpt}', {mod_sql}, '{day}')"
        amount = Raw(f"({rate}) * {units}")

        recent = (config.TODAY - day).days < 30
        if recent:
            status, paid, dreason, dtext = "submitted", None, None, None
            sub = dt.datetime.combine(day + dt.timedelta(days=2), dt.time(9))
            adj = pay = None
        elif random.random() < denial_rate:
            code, text = random.choice(reasons)
            status, paid, dreason, dtext = "denied", None, code, text
            sub = dt.datetime.combine(day + dt.timedelta(days=2), dt.time(9))
            adj = dt.datetime.combine(day + dt.timedelta(days=21), dt.time(9))
            pay = None
        else:
            status, dreason, dtext = "paid", None, None
            paid = amount
            sub = dt.datetime.combine(day + dt.timedelta(days=2), dt.time(9))
            adj = dt.datetime.combine(day + dt.timedelta(days=21), dt.time(9))
            pay = dt.datetime.combine(day + dt.timedelta(days=28), dt.time(9))

        w.insert("claims", dict(
            session_id=sid, authorization_id=auth_id, payer_id=payer_ref(c["payer"]),
            cpt_code=cpt, units_billed=units, amount_billed=amount, amount_paid=paid,
            status=status, submitted_at=sub, adjudicated_at=adj, paid_at=pay,
            denial_reason_code=dreason, denial_reason_text=dtext, modifier=modifier,
            notes=None))

    # small audit sample: plan signings + the Fatima reconciliation review
    w.insert("audit_log", dict(
        occurred_at=dt.datetime.combine(config.TODAY, dt.time(8, 30)),
        actor_staff_id=ids["staff"]["alexandre"], table_name="sessions",
        record_id=0, action="read", client_id=ids["clients"]["sam"],
        change_detail=Raw("'{\"report\":\"december reconciliation\"}'::jsonb"),
        request_metadata=None))


# claim_units is populated as sessions are created (so we know billed units).
claim_units = {}
_orig_add_session = add_session
def add_session(client_key, cpt, day, units, rendering_key, auth_id, completed,
                documented=None, billed=None):           # noqa: F811
    sid = _orig_add_session(client_key, cpt, day, units, rendering_key, auth_id,
                            completed, documented, billed)
    if completed:
        claim_units[sid] = billed if billed is not None else (
            documented if documented is not None else units)
    return sid


# ---------------------------------------------------------------------------
def main():
    gen_staff(); gen_clients(); gen_service_locations(); gen_client_documents()
    gen_authorizations_and_plans()
    gen_programs_and_targets()
    gen_sessions()
    gen_claims_and_audit()

    w.section("reset sequences")
    for table in ("staff", "clients", "service_locations", "client_documents",
                  "authorizations", "treatment_plans", "sessions", "programs", "targets"):
        n = len(ids[table])
        if n:
            w.raw(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {n}, true);")
    w.raw("")
    w.raw("COMMIT;")

    with open("03_generate_tenant_data.sql", "w") as f:
        f.write(w.text())
    print("Generated 03_generate_tenant_data.sql")
    for t in ids:
        print(f"  {t:20s} {len(ids[t]):5d}")
    print(f"  fatima_dec_discrepancy_rows {fatima_dec_count}")


if __name__ == "__main__":
    main()