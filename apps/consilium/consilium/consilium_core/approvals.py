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


def record_decision(
    decision_row,
    decision: str,
    *,
    comments: str | None = None,
    acting_user: str | None = None,
    exception_authorisation: str | None = None,
):
    """Record a decision, resolving delegation and refusing an unauthorised bypass."""
    if isinstance(decision_row, str):
        decision_row = frappe.get_doc("Approval Decision", decision_row)
    acting_user = acting_user or frappe.session.user

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
