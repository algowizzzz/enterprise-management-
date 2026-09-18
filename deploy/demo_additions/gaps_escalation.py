"""DEMONSTRATION data for the configurable escalation workflow (E-8) and the
risk-acceptance approval chain (E-9).

    from deploy.demo_additions import gaps_escalation
    gaps_escalation.run(frappe)   # inside a connected site; the caller commits

Builds on the escalations ``deploy/demo_data.py`` and
``deploy/demo_additions/escalation_w3.py`` have already made (found by title,
not by reference, so a fresh site's numbering does not matter). Idempotent:
every step looks for what it would create or switch on and skips it when it is
there. The acceptance is proposed, sent and decided **as the persona who would
do it**, through the same entry points the portal calls, so ownership, the
permission checks and the audit trail are the ones a real user leaves.

* **A stricter workflow for High severity.** The platform seeds its own
  High-severity transition rules switched off (``ESC-HIGH-*``); this switches
  them on. A High matter may then only be sent to second-line review from its
  first state, is handed back by the reviewer, and only then may be closed.
  Every other severity keeps the catch-all rule (``ESC-ANY``): any move, as
  before. On the matter page of a High matter still in its first state, *Move
  the status* offers only the review states, and *Close the matter* is not
  offered until the matter has been through review.
* **An approval chain for High-severity risk acceptances.** The route
  ``RAR-HIGH`` asks, first, for a second-line risk review by a holder of the
  *Escalation Reviewer* role chosen when approval is requested; then, side by
  side, for sign-off by the Chief Financial Officer and the Chief Operating
  Officer. Other severities keep the single independent approver.
* **A High-severity acceptance in the middle of its chain.** On "Complaint-
  handling timelines missed across three business lines" the matter's
  response owner proposes carrying the longer resolution times while the
  handling model is rebuilt, and asks for approval, choosing the Second Line
  Reviewer for the first step (or, where that persona is not independent of
  the matter, the first independent reviewer the page offers); the reviewer
  approves. The acceptance now waits on the Chief Financial Officer and the
  Chief Operating Officer, both of whom see it in *My work* and can decide it
  on the matter's page; it has no effect until both approve.

Everything is fictitious, and every record is owned by an ``@demo.example``
persona like the rest of the demonstration data.
"""

from __future__ import annotations

DOMAIN = "demo.example"

HIGH_MATTER = "Complaint-handling timelines missed across three business lines"
ACCEPTANCE_NAME = "Carry longer complaint-resolution times while the handling model is rebuilt"
ROUTE_CODE = "RAR-HIGH"


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


def stricter_high_workflow(frappe, notes: list[str]) -> None:
    from consilium.escalation.setup import install

    install.ensure_transition_rules()
    codes = [row[0] for row in install.TRANSITION_RULES if row[0].startswith("ESC-HIGH-")]
    missing = [code for code in codes if not frappe.db.exists("Escalation Transition Rule", code)]
    if missing:
        notes.append(f"skipped: transition rules not seeded: {', '.join(missing)}")
        return
    off = [code for code in codes if not frappe.db.get_value("Escalation Transition Rule", code, "is_active")]
    if not off:
        notes.append(f"exists: {len(codes)} High-severity transition rules active")
        return
    for code in off:
        doc = frappe.get_doc("Escalation Transition Rule", code)
        doc.is_active = 1
        doc.save(ignore_permissions=True)
    notes.append(f"created: {len(off)} High-severity transition rules switched on (review before closure)")


def high_severity_route(frappe, notes: list[str]) -> None:
    if frappe.db.exists("Risk Acceptance Approval Route", ROUTE_CODE):
        notes.append(f"exists: route {ROUTE_CODE}")
        return
    frappe.get_doc({
        "doctype": "Risk Acceptance Approval Route",
        "route_code": ROUTE_CODE,
        "route_title": "High-severity risk acceptance",
        "severity": "High",
        "priority": 50,
        "is_active": 1,
        "description": "A High-severity acceptance is reviewed by the second line first, then signed off by "
                       "finance and operations side by side.",
        "steps": [
            {"step_sequence": 1, "approval_step": "Second-line risk review", "mode": "Sequential",
             "required_role": "Escalation Reviewer", "assignee_source": "Chosen At Request"},
            {"step_sequence": 2, "approval_step": "Finance sign-off", "mode": "Sequential",
             "assignee_source": "Named User", "assignee": U("chief.financial.officer")},
            {"step_sequence": 2, "approval_step": "Operations sign-off", "mode": "Sequential",
             "assignee_source": "Named User", "assignee": U("chief.operating.officer")},
        ],
    }).insert(ignore_permissions=True)
    notes.append(f"created: route {ROUTE_CODE} (second line, then finance and operations in parallel)")


def acceptance_mid_chain(frappe, notes: list[str]) -> None:
    from consilium.escalation import approvals

    matter = frappe.db.get_value("Escalation Matter", {"escalation_title": HIGH_MATTER}, "name")
    if not matter:
        notes.append(f"skipped: no matter titled {HIGH_MATTER!r}")
        return
    existing = frappe.db.get_value("Risk Acceptance", {"risk_acceptance_name": ACCEPTANCE_NAME}, "name")
    if existing:
        notes.append(f"exists: {existing} on {matter}")
        return
    if frappe.db.get_value("Escalation Matter", matter, "severity") != "High":
        notes.append(f"skipped: {matter} is no longer High severity")
        return
    today = frappe.utils.getdate(frappe.utils.nowdate())
    owner = frappe.db.get_value("Escalation Matter", matter, "response_owner") or U("head.retail.banking")
    with _As(frappe, owner):
        approvals.add_risk_acceptance(matter, {
            "risk_acceptance_name": ACCEPTANCE_NAME,
            "start_date": str(today),
            "end_date": str(frappe.utils.add_months(today, 4)),
            "accountable_executive": owner,
            "reassessment_frequency_months": 1,
            "rationale": "Resolution times of up to 45 days (against 30) are carried in the three affected business "
                         "lines while the complaint-handling model is rebuilt; every complaint is still acknowledged "
                         "within two days, and vulnerable customers are handled by the specialist team.",
        })
        name = frappe.db.get_value("Risk Acceptance", {"risk_acceptance_name": ACCEPTANCE_NAME}, "name")
        acceptance = frappe.get_doc("Risk Acceptance", name)
        plan = approvals.planned_chain(frappe.get_doc("Escalation Matter", matter), acceptance, owner)
        if not plan:
            notes.append(f"skipped: no approval route applies to {matter}; {name} left with its author")
            return
        chosen = {}
        for step in plan["steps"]:
            if not step["chosen"]:
                continue
            offered = [person.name for person in step["candidates"]]
            if not offered:
                notes.append(f"skipped: nobody independent can take {step['approval_step']!r}; {name} left with its author")
                return
            chosen[step["key"]] = U("second.line.reviewer") if U("second.line.reviewer") in offered else offered[0]
        approvals.request_risk_acceptance_approval(name, approvers=chosen)
    first = approvals.cycle_steps(frappe.get_doc("Risk Acceptance", name))[0].assigned_to
    with _As(frappe, first):
        approvals.decide_risk_acceptance(
            name, "Approved",
            "Second-line review: the interim standard is proportionate and the vulnerable-customer carve-out holds.",
        )
    waiting = [step.assigned_to for step in approvals.cycle_steps(frappe.get_doc("Risk Acceptance", name))
               if step.is_open]
    notes.append(f"created: {name} on {matter}, second-line step approved, waiting on {', '.join(waiting)}")


def run(frappe) -> list[str]:
    """Load the demonstration. Returns one note per step; the caller commits."""
    notes: list[str] = []
    for step in (stricter_high_workflow, high_severity_route, acceptance_mid_chain):
        savepoint = f"gaps_escalation_{step.__name__}"
        frappe.db.savepoint(savepoint)
        try:
            step(frappe, notes)
        except Exception as exc:  # one step failing must not undo the others
            frappe.db.rollback(save_point=savepoint)
            notes.append(f"failed: {step.__name__}: {type(exc).__name__}: {exc}")
    return notes
