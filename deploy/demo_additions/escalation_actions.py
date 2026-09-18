"""DEMONSTRATION data for the escalation portal's actions, pathway participants and revert.

    from deploy.demo_additions import escalation_actions
    escalation_actions.run(frappe)   # inside a connected site; the caller commits

Builds on the escalations ``deploy/demo_data.py`` has already made (found by
title, not by reference, so a fresh site's numbering does not matter) and
changes nothing else. Idempotent: every step looks for what it would create and
skips it when it is there. Every step is taken **as the persona who would take
it**, through the same entry points the portal calls, so ownership, the
permission checks and the audit trail are the ones a real user leaves.

* **A risk acceptance awaiting a named approver.** On "Rising trend in
  sales-practice complaints", the Chief Compliance Officer (the response owner)
  proposes carrying the elevated complaint-handling times while the campaign is
  reviewed, and asks the Chief Risk Officer to approve it. Signed in as the
  Chief Risk Officer, the matter page offers **Decide**, and the register lists
  it under *Waiting on you*.
* **A matter with a revertible history.** On "Key-person dependency in treasury
  liquidity operations" the Treasurer rewrites the trigger and the description
  as the situation worsens. The first save keeps the matter as it stood as a
  baseline version, so the page's *Revision history* offers **Revert** to it.
* **A forum whose change was reverted.** On the Asset-Liability Committee the
  Risk Governance Office Lead changes the escalation threshold, then reverts it
  with a reason: the forum's chain shows the change, the revert and the
  ``Version Revert Log``. The field is not a watched one, so the forum stays
  compliant — a watched field would have sent it back for review.

Everything is fictitious, and every record is owned by an ``@demo.example``
persona like the rest of the demonstration data.
"""

from __future__ import annotations

DOMAIN = "demo.example"

COMPLAINTS_MATTER = "Rising trend in sales-practice complaints"
TREASURY_MATTER = "Key-person dependency in treasury liquidity operations"
ALCO = "Asset-Liability Committee"

ACCEPTANCE_NAME = "Accept elevated complaint-handling times during the sales-campaign review"
REVISED_TRIGGER = "All three intraday liquidity specialists now under notice; no trained cover in place."
REVISED_DESCRIPTION = (
    "Intraday liquidity management depends on three specialists. Two resigned in the quarter and the third "
    "has now given notice; the cross-training plan has not started."
)
ALCO_THRESHOLD = "Liquidity coverage below the management trigger for two consecutive days."
REVERT_REASON = "The threshold change had not been approved by the committee; restoring the approved wording."


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


def acceptance_awaiting_decision(frappe, notes: list[str]) -> None:
    from consilium.escalation import approvals

    matter = _matter(frappe, COMPLAINTS_MATTER)
    if not matter:
        notes.append(f"skipped: no matter titled {COMPLAINTS_MATTER!r}")
        return
    existing = frappe.db.get_value("Risk Acceptance", {"risk_acceptance_name": ACCEPTANCE_NAME}, "name")
    if existing:
        notes.append(f"exists: {existing} on {matter}")
        return
    today = frappe.utils.getdate(frappe.utils.nowdate())
    with _As(frappe, U("chief.compliance.officer")):
        approvals.add_risk_acceptance(matter, {
            "risk_acceptance_name": ACCEPTANCE_NAME,
            "start_date": str(today),
            "end_date": str(frappe.utils.add_months(today, 3)),
            "accountable_executive": U("head.retail.banking"),
            "reassessment_frequency_months": 1,
            "rationale": "Complaint-handling times of up to 30 days (against a 15-day standard) are carried while "
                         "the sales campaign is reviewed; extra handlers would take longer to train than the review "
                         "will last, and every complaint is still logged and acknowledged within two days.",
        })
        name = frappe.db.get_value("Risk Acceptance", {"risk_acceptance_name": ACCEPTANCE_NAME}, "name")
        approvals.request_risk_acceptance_approval(name, U("chief.risk.officer"))
    notes.append(f"created: {name} on {matter}, awaiting chief.risk.officer")


def revertible_history(frappe, notes: list[str]) -> None:
    matter = _matter(frappe, TREASURY_MATTER)
    if not matter:
        notes.append(f"skipped: no matter titled {TREASURY_MATTER!r}")
        return
    doc = frappe.get_doc("Escalation Matter", matter)
    if doc.escalation_trigger == REVISED_TRIGGER:
        notes.append(f"exists: revised history on {matter}")
        return
    if not doc.is_editable:
        notes.append(f"skipped: {matter} is not editable")
        return
    with _As(frappe, U("treasurer")):
        doc = frappe.get_doc("Escalation Matter", matter)
        doc.escalation_trigger = REVISED_TRIGGER
        doc.description = REVISED_DESCRIPTION
        doc.save()
    versions = frappe.db.count("Document Version", {"subject_doctype": "Escalation Matter", "subject_name": matter})
    notes.append(f"created: {matter} revised by treasurer; {versions} versions, the first revertible")


def forum_revert(frappe, notes: list[str]) -> None:
    from consilium.consilium_core import revision

    forum = frappe.db.get_value("Governance Forum", {"forum_name": ALCO}, "name")
    if not forum:
        notes.append(f"skipped: no forum named {ALCO!r}")
        return
    if frappe.db.exists("Version Revert Log", {"subject_doctype": "Governance Forum", "subject_name": forum}):
        notes.append(f"exists: revert on {forum}")
        return
    if not frappe.db.get_value("Governance Forum", forum, "is_editable"):
        notes.append(f"skipped: {forum} is not editable")
        return
    lead = U("risk.governance.lead")
    with _As(frappe, lead):
        doc = frappe.get_doc("Governance Forum", forum)
        doc.escalation_threshold = ALCO_THRESHOLD
        doc.save()
        chain = revision.history("Governance Forum", forum)["versions"]
        target = next(v for v in chain if v["can_revert"])
        revision.revert("Governance Forum", forum, target["name"], REVERT_REASON)
    notes.append(f"created: change and revert on {forum}")


def run(frappe) -> list[str]:
    """Load the demonstration. Returns one note per step; the caller commits."""
    notes: list[str] = []
    for step in (acceptance_awaiting_decision, revertible_history, forum_revert):
        savepoint = f"escalation_actions_{step.__name__}"
        frappe.db.savepoint(savepoint)
        try:
            step(frappe, notes)
        except Exception as exc:  # one step failing must not undo the others
            frappe.db.rollback(save_point=savepoint)
            notes.append(f"failed: {step.__name__}: {type(exc).__name__}: {exc}")
    return notes
