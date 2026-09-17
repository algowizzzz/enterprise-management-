"""The explicit approval a risk acceptance requires (E16-S4).

A risk acceptance is a decision to carry a risk rather than fix it, so it may
not take effect on one person's say-so: the approval is a separate, recorded act.
Core owns the approval engine — delegation resolution, the bypass rule, the
version the decision was given against — so this module only asks it for a
decision and then stamps the outcome onto the acceptance.

The approval fields on `Risk Acceptance` are read-only in the schema precisely so
that this is the only path that can set them.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import approvals as core_approvals
from consilium.escalation import flags

APPROVAL_STEP = "Risk Acceptance"


def request_approval(risk_acceptance: str, approver: str, required_role: str | None = None):
    """Open a decision for the named approver. The acceptance stays without effect."""
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    decision = core_approvals.request_decision(
        subject_doctype="Risk Acceptance",
        subject_name=acceptance.name,
        approval_step=APPROVAL_STEP,
        assigned_to=approver,
        required_role=required_role,
    )
    frappe.db.set_value("Risk Acceptance", acceptance.name, "approval_decision", decision.name)
    return decision


def record_approval(risk_acceptance: str, decision_value: str, *, comments: str | None = None,
                    acting_user: str | None = None):
    """Record the approver's decision and stamp an approval onto the acceptance.

    ``decision_value`` is a configured `Approval Decision` value, passed through
    to Core as data. Whether it *means* approval is read from the flag map, not
    from the string.
    """
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    if not acceptance.approval_decision:
        frappe.throw(
            _("No approval has been requested for {0}.").format(acceptance.name),
            title=_("Nothing To Decide"),
        )

    decision = core_approvals.record_decision(
        acceptance.approval_decision, decision_value, comments=comments, acting_user=acting_user
    )
    approving = decision.decision in flags.approving_decisions()
    frappe.db.set_value(
        "Risk Acceptance",
        acceptance.name,
        {
            "approved_by": decision.acted_by if approving else None,
            "approved_on": decision.decided_on if approving else None,
        },
    )
    return decision


def is_approved(acceptance) -> bool:
    """An acceptance is approved when an approval was recorded against it.

    A forum motion is the other accepted route: an approval taken in a meeting is
    evidenced by the motion, not by an in-system decision.
    """
    if acceptance.approval_motion:
        return True
    if not (acceptance.approved_by and acceptance.approved_on):
        return False
    if not acceptance.approval_decision:
        return False
    decision = frappe.db.get_value(
        "Approval Decision", acceptance.approval_decision, ["decision", "is_open"], as_dict=True
    )
    return bool(decision) and not decision.is_open and decision.decision in flags.approving_decisions()
