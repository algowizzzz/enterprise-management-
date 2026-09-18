"""Approval decisions.

The framework records that a workflow action happened. Several requirements need
more: the basis of the approval, whether a delegate acted, which document version
the approval was given against, and whether a bypass was authorised. That is what
an ``Approval Decision`` carries, and it is why a bypass without an exception
authorisation is refused here rather than left to convention.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import audit, delegation, versioning


def request_decision(
    *,
    subject_doctype: str,
    subject_name: str,
    approval_step: str,
    assigned_to: str,
    step_sequence: int = 1,
    mode: str = "Sequential",
    required_role: str | None = None,
    classification_at_decision: str | None = None,
    based_on_version: str | None = None,
):
    if based_on_version is None:
        current = versioning.current_version(subject_doctype, subject_name)
        based_on_version = current.name if current else None
    return frappe.get_doc(
        {
            "doctype": "Approval Decision",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "approval_step": approval_step,
            "step_sequence": step_sequence,
            "mode": mode,
            "required_role": required_role,
            "assigned_to": assigned_to,
            "classification_at_decision": classification_at_decision,
            "based_on_version": based_on_version,
            "decision": "Pending",
        }
    ).insert(ignore_permissions=True)


#: The step mode that must wait its turn. Configuration vocabulary for the
#: ``mode`` column, not a workflow state: the column never moves.
SEQUENTIAL = "Sequential"


def waiting_on(decision_row) -> list[dict]:
    """Earlier steps that must be decided before this one may be (E7-S4).

    A **sequential** step waits for every step of the same record, and of the
    same approval cycle, with a lower sequence number that is still open. A
    **parallel** step waits for nothing: that is what parallel means, and steps
    that share a sequence number are peers either way.

    "The same cycle" is the version the decision was raised against. A document
    that is reopened after publication raises a fresh set of steps against its
    new version, and last cycle's abandoned rows must not block this one's.
    Openness is read from the semantic flag, never from the decision label.
    """
    if isinstance(decision_row, str):
        decision_row = frappe.get_doc("Approval Decision", decision_row)
    if (decision_row.mode or SEQUENTIAL) != SEQUENTIAL:
        return []
    rows = frappe.get_all(
        "Approval Decision",
        filters={
            "subject_doctype": decision_row.subject_doctype,
            "subject_name": decision_row.subject_name,
            "is_open": 1,
            "docstatus": ["<", 2],
            "step_sequence": ["<", int(decision_row.step_sequence or 0)],
            "name": ["!=", decision_row.name],
        },
        fields=["name", "approval_step", "step_sequence", "assigned_to", "based_on_version"],
        order_by="step_sequence asc, creation asc",
    )
    cycle = decision_row.based_on_version or None
    return [row for row in rows if (row.based_on_version or None) == cycle]


def is_turn(decision_row) -> bool:
    """Whether this step may be decided now, as far as ordering goes."""
    return not waiting_on(decision_row)


def record_decision(
    decision_row,
    decision: str,
    *,
    comments: str | None = None,
    acting_user: str | None = None,
    exception_authorisation: str | None = None,
):
    """Record a decision, resolving delegation and refusing an unauthorised bypass.

    A sequential step decided before the steps ahead of it is refused, and the
    refusal audited: the order of a route is part of its control, not a
    suggestion (E7-S4). A **bypass** is exempt, because it carries its own
    ``Exception Authorisation`` — a skip is by definition out of turn, and the
    authorisation is the record of why.
    """
    if isinstance(decision_row, str):
        decision_row = frappe.get_doc("Approval Decision", decision_row)
    acting_user = acting_user or frappe.session.user

    if not exception_authorisation:
        ahead = waiting_on(decision_row)
        if ahead:
            audit.refuse(
                _("Approval step {0} on {1} {2} is sequential and cannot be decided yet: {3} must be "
                  "decided first.").format(
                    decision_row.approval_step, decision_row.subject_doctype, decision_row.subject_name,
                    ", ".join(f"{row.approval_step} ({row.assigned_to})" for row in ahead),
                ),
                subject_doctype=decision_row.subject_doctype,
                subject_name=decision_row.subject_name,
                attempted_action="Other",
                control="sequential approval order",
                context={"approval_decision": decision_row.name,
                         "waiting_on": [row.name for row in ahead]},
                exc=frappe.ValidationError,
            )

    resolution = delegation.resolve_actor(
        decision_row.assigned_to,
        delegation.ACTION_APPROVE,
        acting_user=acting_user,
        doctype=decision_row.subject_doctype,
        name=decision_row.subject_name,
    )
    if not resolution["permitted"]:
        audit.refuse(
            f"{acting_user} may not decide approval step {decision_row.approval_step} on "
            f"{decision_row.subject_doctype} {decision_row.subject_name}: {resolution['reason']}",
            subject_doctype=decision_row.subject_doctype,
            subject_name=decision_row.subject_name,
            attempted_action="Other",
            control="delegation",
            context={"approval_decision": decision_row.name},
        )

    decision_row.decision = decision
    decision_row.comments = comments
    decision_row.decided_on = now()
    decision_row.acted_by = acting_user
    decision_row.acting_delegation = resolution["delegation"]
    if exception_authorisation:
        decision_row.exception_authorisation = exception_authorisation
    decision_row.save(ignore_permissions=True)
    return decision_row


def outstanding(subject_doctype: str, subject_name: str) -> list[str]:
    """Steps still awaiting a decision. Reads the semantic flag, not the label."""
    return frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": subject_doctype, "subject_name": subject_name, "is_open": 1},
        pluck="name",
        order_by="step_sequence asc",
    )
