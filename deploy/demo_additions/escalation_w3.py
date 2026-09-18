"""DEMONSTRATION data for assignment by role or group, the systemic route, the
second-line challenge service level and time in each status (E-5, E-8, E-9, E-13).

    from deploy.demo_additions import escalation_w3
    escalation_w3.run(frappe)   # inside a connected site; the caller commits

Builds on the organisation and the enterprise escalation matrix
``deploy/demo_data.py`` has already made, and changes nothing it did not add
except the matrix itself. Idempotent: every step looks for what it would create
and skips it when it is there. Matters are raised, taken, moved and challenged
**as the persona who would do it**, through the same entry points the portal
calls, so ownership, the permission checks and the audit trail are the ones a
real user leaves.

* **Configuration.** The matrix gains a systemic rule (``R05-SYSTEMIC``: a
  matter flagged systemic goes to the Executive Risk Committee for decision and
  the Board Risk Committee for oversight, at High severity, in the queue of the
  *Head of Risk Governance* role), and two existing rules gain a group queue
  (technology matters to *Technology and Operations Leadership*, process
  failures to the *Risk Management Function*). Service levels are added for the
  time a matter may spend in each status, and for the second line's challenge
  of a systemic matter — a *Time In State* definition on the review flag,
  scoped to systemic matters.
* **A matter waiting in a group queue.** "Suspense-account breaks ageing beyond
  the reconciliation policy" is raised by the Chief Financial Officer with no
  response owner. Everyone in the Risk Management Function sees it in their
  inbox, with **Take ownership**.
* **A matter taken from a group queue.** "End-of-support database platform
  still hosts two customer-facing applications" is raised by the Chief
  Information Officer; the Head of Technology Risk takes ownership.
* **A systemic matter waiting for its higher owner.** "Complaint-handling
  timelines missed across three business lines" is raised by the Chief
  Compliance Officer, flagged systemic, with the Head of Personal and
  Commercial Banking as response owner. The systemic route takes it to the
  Executive Risk Committee and the Board Risk Committee, and it waits for the
  Chief Risk Officer (who holds the Head of Risk Governance role) to take it.
* **A systemic matter under challenge, with a history.** "Model inventory
  incomplete across risk, finance and treasury" was raised by the Chief Risk
  Officer nine days ago, moved on the next day and sent to the second line
  three days ago. Its page shows the time in each status against the targets
  (the day in triage is past its target), and the challenge clock running; the
  Second Line Reviewer's challenge round is stamped with that clock.

Everything is fictitious, and every record is owned by an ``@demo.example``
persona like the rest of the demonstration data.
"""

from __future__ import annotations

import json

DOMAIN = "demo.example"

MATRIX_CODE = "ENTERPRISE-ESC"
HEAD_ROLE = "Head of Risk Governance"
ERC = "Executive Risk Committee"
BRC = "Board Risk Committee"
BUSINESS_CALENDAR = "HEAD_OFFICE"

SYSTEMIC_RULE = {
    "rule_code": "R05-SYSTEMIC", "priority": 5, "condition": json.dumps({"systemic": True}),
    "resulting_severity": "High", "route_to_role": HEAD_ROLE, "sla_definition": "ESC-HIGH", "is_active": 1,
    "rule_description": "A systemic issue: to the Head of Risk Governance, the Executive Risk Committee for "
                        "decision and the Board Risk Committee for oversight.",
}
SYSTEMIC_ROUTES = [(ERC, "Decision"), (BRC, "Oversight")]
SYSTEMIC_GROUPS = ["Executive Risk Committee Members"]

#: Existing rules that gain a group queue: (rule code, user group).
GROUP_QUEUES = [
    ("R50-TECH", "Technology and Operations Leadership"),
    ("R75-PROCESS", "Risk Management Function"),
]

#: Time In State targets per status (E-13). Configuration names the statuses;
#: the code that measures them does not. (code, title, state field, value, hours,
#: calendar, applies when)
SERVICE_LEVELS = [
    ("ESC-STATE-OPEN", "Escalation: time in triage (Open)", "status", "Open", 8, "Business Hours", None),
    ("ESC-STATE-PROGRESS", "Escalation: time being worked (In Progress)", "status", "In Progress", 480, "24x7",
     None),
    ("ESC-STATE-REVIEW", "Escalation: time with the second line (Under Review)", "status", "Under Review", 120,
     "24x7", None),
    ("ESC-STATE-PENDING", "Escalation: time awaiting review (Pending Review)", "status", "Pending Review", 72,
     "24x7", None),
    ("ESC-CHALLENGE-SYSTEMIC", "Systemic escalation: second-line challenge", "requires_review", "1", 40,
     "Business Hours", {"systemic": 1}),
]

QUEUED_MATTER = "Suspense-account breaks ageing beyond the reconciliation policy"
TAKEN_MATTER = "End-of-support database platform still hosts two customer-facing applications"
SYSTEMIC_WAITING = "Complaint-handling timelines missed across three business lines"
SYSTEMIC_REVIEW = "Model inventory incomplete across risk, finance and treasury"

CHALLENGE_COMMENT = (
    "The inventory gap is described but not sized: show how many models are unrecorded in each function, "
    "and which of them feed capital or provisioning, before the remediation plan is accepted."
)


def U(key: str) -> str:
    return f"{key}@{DOMAIN}"


class _As:
    """Act as a persona for the length of a block, then restore the caller."""

    def __init__(self, frappe, user: str):
        self.frappe, self.user = frappe, user

    def __enter__(self):
        self.previous = self.frappe.session.user
        self.frappe.set_user(self.user)

    def __exit__(self, *exc):
        self.frappe.set_user(self.previous)


def _matter(frappe, title: str) -> str | None:
    return frappe.db.get_value("Escalation Matter", {"escalation_title": title}, "name")


def _forum(frappe, name: str) -> str | None:
    return frappe.db.get_value("Governance Forum", {"forum_name": name}, "name")


def _raise(frappe, persona: str, values: dict) -> str:
    """Raise a matter as ``persona`` through the guided form's entry point."""
    from consilium.escalation import templates

    today = frappe.utils.getdate(frappe.utils.nowdate())
    base = {
        "escalation_identification_date": str(frappe.utils.add_days(today, -1)),
        "escalation_date": str(today),
        "identified_by": U(persona),
        "impacted_entities": [{"entity_type": "Legal Entity", "entity_value": "BANK_SUB"}],
    }
    with _As(frappe, U(persona)):
        return templates.raise_escalation({**base, **values})["name"]


# ----------------------------------------------------------- configuration


def configure_service_levels(frappe, notes: list[str]) -> None:
    """The status and challenge targets. Created after the demonstration history
    is laid down, so the live clocks Core would otherwise start on each move
    (and then find superseded by the back-dated history) never exist."""
    lead = U("risk.governance.lead")
    added = []
    for code, title, field, value, hours, calendar, applies in SERVICE_LEVELS:
        if frappe.db.exists("SLA Definition", code):
            continue
        if calendar == "Business Hours" and not frappe.db.exists("Business Calendar", BUSINESS_CALENDAR):
            calendar = "24x7"
        doc = frappe.get_doc({
            "doctype": "SLA Definition", "sla_code": code, "title": title,
            "target_doctype": "Escalation Matter", "measure": "Time In State",
            "state_field": field, "state_value": value, "target_hours": hours, "warning_threshold_pct": 75,
            "calendar": calendar,
            "business_calendar": BUSINESS_CALENDAR if calendar == "Business Hours" else None,
            "applies_when": json.dumps(applies) if applies else None,
            "is_active": 1,
        }).insert(ignore_permissions=True)
        frappe.db.set_value("SLA Definition", doc.name, "owner", lead, update_modified=False)
        added.append(code)
    notes.append(f"configured: service levels {', '.join(added) or 'present'}")


def configure_routing(frappe, notes: list[str]) -> None:
    lead = U("risk.governance.lead")
    if not frappe.db.exists("Escalation Matrix", MATRIX_CODE):
        notes.append(f"skipped matrix: no matrix {MATRIX_CODE}")
        return
    matrix = frappe.get_doc("Escalation Matrix", MATRIX_CODE)
    changed = []
    if not any(rule.rule_code == SYSTEMIC_RULE["rule_code"] for rule in matrix.rules):
        matrix.append("rules", SYSTEMIC_RULE)
        for forum_name, role in SYSTEMIC_ROUTES:
            forum = _forum(frappe, forum_name)
            if forum:
                matrix.append("routes", {"rule_code": SYSTEMIC_RULE["rule_code"], "governance_forum": forum,
                                         "role_in_escalation": role})
        for group in SYSTEMIC_GROUPS:
            if frappe.db.exists("User Group", group):
                matrix.append("rule_notifications", {"rule_code": SYSTEMIC_RULE["rule_code"], "user_group": group})
        changed.append(SYSTEMIC_RULE["rule_code"])
    for code, group in GROUP_QUEUES:
        rule = next((r for r in matrix.rules if r.rule_code == code), None)
        if rule and not rule.route_to_group and frappe.db.exists("User Group", group):
            rule.route_to_group = group
            changed.append(code)
    if changed:
        with _As(frappe, lead):
            matrix.save(ignore_permissions=True)
    notes.append(f"configured: matrix rules {', '.join(changed) or 'present'}")


# ------------------------------------------------------------- the matters


def queued_matter(frappe, notes: list[str]) -> None:
    if (name := _matter(frappe, QUEUED_MATTER)):
        notes.append(f"exists: {name}")
        return
    name = _raise(frappe, "chief.financial.officer", {
        "escalation_title": QUEUED_MATTER, "escalation_type": "POLICY_BREACH",
        "tier_1_risk_type": "PROCESS", "tier_2_risk_type": "PROCESS_EXEC",
        "organizational_level": "OPERATING_GROUP", "accountable_executive": U("chief.financial.officer"),
        "escalation_trigger": "312 suspense items older than 30 days against a policy limit of 50.",
        "description": "A change to the payments ledger feed left unmatched items in two suspense accounts. "
                       "The reconciliation team has cleared new breaks but not the aged population.",
    })
    doc = frappe.db.get_value("Escalation Matter", name, ["assigned_group", "assignment_rule"], as_dict=True)
    notes.append(f"created: {name} waiting in {doc.assigned_group} ({doc.assignment_rule})")


def taken_matter(frappe, notes: list[str]) -> None:
    from consilium.escalation import assignment

    if (name := _matter(frappe, TAKEN_MATTER)):
        notes.append(f"exists: {name}")
        return
    name = _raise(frappe, "chief.information.officer", {
        "escalation_title": TAKEN_MATTER, "escalation_type": "POLICY_BREACH",
        "tier_1_risk_type": "TECHNOLOGY", "tier_2_risk_type": "TECH_OUTAGE",
        "organizational_level": "ENTERPRISE", "accountable_executive": U("chief.information.officer"),
        "escalation_trigger": "Vendor support ended; no security patches since the end of last quarter.",
        "description": "Two customer-facing applications still run on a database platform past its end of "
                       "support. Migration was deferred twice for capacity reasons.",
    })
    with _As(frappe, U("head.technology.risk")):
        assignment.take_ownership(name)
    notes.append(f"created: {name}, taken from its queue by head.technology.risk")


def systemic_waiting(frappe, notes: list[str]) -> None:
    if (name := _matter(frappe, SYSTEMIC_WAITING)):
        notes.append(f"exists: {name}")
        return
    name = _raise(frappe, "chief.compliance.officer", {
        "escalation_title": SYSTEMIC_WAITING, "escalation_type": "POLICY_BREACH",
        "tier_1_risk_type": "PEOPLE", "tier_2_risk_type": "PEOPLE_CONDUCT",
        "organizational_level": "ENTERPRISE", "accountable_executive": U("head.retail.banking"),
        "response_owner": U("head.retail.banking"), "systemic": 1,
        "escalation_trigger": "The 15-day complaint-handling standard missed in three business lines in the "
                              "same quarter, for the same root cause.",
        "description": "Complaint-handling timelines were missed in retail lending, cards and commercial "
                       "banking. The common cause is a shared case-management queue that was not resized.",
        "impacted_entities": [{"entity_type": "Line of Business", "entity_value": "PCB"},
                              {"entity_type": "Legal Entity", "entity_value": "BANK_SUB"}],
    })
    doc = frappe.db.get_value("Escalation Matter", name, ["matched_matrix_rule", "assigned_role", "severity"],
                              as_dict=True)
    notes.append(f"created: {name} on {doc.matched_matrix_rule} ({doc.severity}), waiting for {doc.assigned_role}")


def _move(frappe, name: str, persona: str, *, review: bool) -> None:
    """Move the matter to the first open state whose review flag is ``review``."""
    from consilium.escalation import resolution

    with _As(frappe, U(persona)):
        matter = frappe.get_doc("Escalation Matter", name)
        target = next(t["value"] for t in resolution.status_targets(matter) if bool(t["requires_review"]) is review)
        resolution.move_matter_status(name, target)


def _backdate(frappe, name: str, created, moves: list) -> None:
    """Put the matter's history on a demonstration timeline.

    The status durations are rebuilt from the change log, so the log is what
    is moved: the creation, then each logged status change in order. The
    matter's own resolution clock follows its new opening time. Core's status
    clocks are rebuilt from this history afterwards (``systemic_challenge``),
    exactly as the hourly job would.
    """
    from consilium.consilium_core import sla

    frappe.db.set_value("Escalation Matter", name, {"creation": created, "opened_on": created},
                        update_modified=False)
    versions = [
        row.name for row in frappe.get_all(
            "Version", filters={"ref_doctype": "Escalation Matter", "docname": name},
            fields=["name", "data"], order_by="creation asc")
        if any(entry and entry[0] == "status" for entry in json.loads(row.data or "{}").get("changed") or [])
    ]
    for version, when in zip(versions, moves):
        frappe.db.set_value("Version", version, "creation", when, update_modified=False)
    clock = frappe.db.get_value("Escalation Matter", name, "sla_clock")
    if clock:
        definition = frappe.get_doc("SLA Definition", frappe.db.get_value("SLA Clock", clock, "sla_definition"))
        frappe.db.set_value("SLA Clock", clock, {"started_on": created,
                                                 "target_on": sla.target_datetime(definition, created)},
                            update_modified=False)


def systemic_history(frappe, notes: list[str]) -> None:
    """Raise the systemic matter, move it twice, and put its history on a timeline."""
    if (name := _matter(frappe, SYSTEMIC_REVIEW)):
        notes.append(f"exists: {name}")
        return
    name = _raise(frappe, "chief.risk.officer", {
        "escalation_title": SYSTEMIC_REVIEW, "escalation_type": "CONTROL_FAIL",
        "tier_1_risk_type": "FINANCIAL", "tier_2_risk_type": "FIN_MODEL",
        "organizational_level": "ENTERPRISE", "accountable_executive": U("chief.risk.officer"),
        "response_owner": U("chief.risk.officer"), "systemic": 1,
        "escalation_trigger": "Model validation found 23 models in use that are missing from the inventory, "
                              "in three functions.",
        "description": "Risk, finance and treasury each keep models outside the enterprise inventory. None of "
                       "them has been independently validated, and some feed provisioning.",
    })
    _move(frappe, name, "chief.risk.officer", review=False)
    _move(frappe, name, "chief.risk.officer", review=True)

    now = frappe.utils.get_datetime(frappe.utils.now())
    created = frappe.utils.add_to_date(now, days=-9, as_datetime=True).replace(hour=9, minute=15, second=0)
    moves = [frappe.utils.add_to_date(created, days=1, hours=2, as_datetime=True),
             frappe.utils.add_to_date(now, days=-3, as_datetime=True).replace(hour=10, minute=30, second=0)]
    _backdate(frappe, name, created, moves)
    notes.append(f"created: {name}, with the second line since {moves[-1]}")


def systemic_challenge(frappe, notes: list[str]) -> None:
    """Core's status clocks rebuilt from the history, then the second line's round."""
    from consilium.consilium_core import sla
    from consilium.escalation import resolution, timing

    name = _matter(frappe, SYSTEMIC_REVIEW)
    if not name:
        notes.append(f"skipped: no matter titled {SYSTEMIC_REVIEW!r}")
        return
    if frappe.db.exists("Escalation Review", {"parent": name, "parenttype": "Escalation Matter"}):
        notes.append(f"exists: challenge round on {name}")
        return
    sla.clear_cache()
    sla.sync_state_clocks("Escalation Matter", names=[name])
    entered = frappe.db.get_value("SLA Clock", timing.open_challenge_clock(name), "started_on")
    with _As(frappe, U("second.line.reviewer")):
        resolution.record_review_round(name, "Challenged", CHALLENGE_COMMENT)
    # The round was opened when the matter reached the second line.
    for row in frappe.get_all("Escalation Review", filters={"parent": name, "parenttype": "Escalation Matter"},
                              pluck="name"):
        frappe.db.set_value("Escalation Review", row, "received_on", entered or frappe.utils.now(),
                            update_modified=False)
    sla.sweep()
    notes.append(f"created: challenge round on {name} against clock {timing.open_challenge_clock(name) or 'none'}")


def run(frappe) -> list[str]:
    """Load the demonstration. Returns one note per step; the caller commits."""
    notes: list[str] = []
    for step in (configure_routing, queued_matter, taken_matter, systemic_waiting, systemic_history,
                 configure_service_levels, systemic_challenge):
        savepoint = f"escalation_w3_{step.__name__}"
        frappe.db.savepoint(savepoint)
        try:
            step(frappe, notes)
        except Exception as exc:  # one step failing must not undo the others
            frappe.db.rollback(save_point=savepoint)
            notes.append(f"failed: {step.__name__}: {type(exc).__name__}: {exc}")
    return notes
