"""The document lifecycle, and the gates that guard it.

Two rules shape this module.

**Nothing here compares a state name.** The states and the transitions between
them are rows in the framework's own ``Workflow`` tables — configuration an
administrator edits in a screen that already exists. A transition is performed
by naming an *action*; the configuration says what state that action leads to.
Semantic flags are then set from the new state by Core's ``state_flags``.

**A state can carry preconditions, and those are configuration too.** A
``Document Lifecycle Gate`` row says "entering this state requires this gate to
pass". The gate names a check, and the checks live in a registry here. That is
what makes E12-S6 — publication refused without a complete approval chain —
configuration rather than an ``if`` on the word Published: the gate row is what
binds the check to the state, and removing the row is an audited configuration
change rather than a code change.

A refused transition is written to the refusal log on its own connection, so the
refusal survives the rollback that the refusal itself causes.
"""

from __future__ import annotations

from collections.abc import Callable

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_workflow_name
from frappe.utils import nowdate

from consilium.consilium_core import audit, versioning
from consilium.policy import applicability, metadata, routing

DOCTYPE = "Governing Document"

#: gate code -> callable(doc) -> (passed, reason)
GATES: dict[str, Callable] = {}


def gate(code: str):
    def decorator(fn):
        GATES[code] = fn
        return fn

    return decorator


@gate("Complete Approval Chain")
def _complete_approval_chain(doc):
    status = routing.chain_status(doc)
    if status["complete"]:
        return True, ""
    parts = []
    if status["missing"]:
        parts.append("no approval has been requested for: " + ", ".join(status["missing"]))
    if status["outstanding"]:
        parts.append("still awaiting a decision: " + ", ".join(status["outstanding"]))
    if status["objections"]:
        parts.append(
            "carrying an objection or an unauthorised bypass: " + ", ".join(status["objections"])
        )
    return False, "; ".join(parts)


@gate("Current Version Required")
def _current_version_required(doc):
    if versioning.current_version(doc.doctype, doc.name):
        return True, ""
    return False, "the document has no version in its chain, so there is nothing to publish"


@gate("Publication Record Required")
def _publication_record_required(doc):
    exists = frappe.db.exists(
        "Document Publication", {"document": doc.name, "docstatus": ["<", 2], "withdrawn_on": ["is", "not set"]}
    )
    if exists:
        return True, ""
    return False, "no publication record exists for this document"


@gate("Implementation Plan Required")
def _implementation_plan_required(doc):
    if frappe.db.exists("Implementation Plan", {"document": doc.name, "docstatus": ["<", 2]}):
        return True, ""
    return False, "no implementation plan has been recorded"


@gate("Required Metadata Complete")
def _required_metadata_complete(doc):
    missing = metadata.missing_fields(doc)
    if not missing:
        return True, ""
    return False, "required metadata is missing: " + ", ".join(missing)


@gate("Applicability Recorded")
def _applicability_recorded(doc):
    if applicability.applicable_scopes(doc.name):
        return True, ""
    return False, (
        "no applicability is recorded, so no affected party could be identified or notified"
    )


def gates_for(doctype: str, state_field: str, state_value: str) -> list[dict]:
    return frappe.get_all(
        "Document Lifecycle Gate",
        filters={
            "target_doctype": doctype,
            "state_field": state_field,
            "state_value": state_value,
            "is_active": 1,
        },
        fields=["name", "gate", "notes"],
        order_by="creation asc",
    )


def check_gates(doc, state_field: str, state_value: str) -> list[str]:
    """Every failure reason for entering a state. Empty means the way is clear."""
    failures = []
    for row in gates_for(doc.doctype, state_field, state_value):
        check = GATES.get(row["gate"])
        if not check:
            frappe.throw(
                _("Lifecycle gate {0} names no known check. Gates are configuration; the check is code.").format(
                    row["gate"]
                )
            )
        passed, reason = check(doc)
        if not passed:
            failures.append(f"{row['gate']}: {reason}")
    return failures


def _workflow(doctype: str):
    name = get_workflow_name(doctype)
    if not name:
        frappe.throw(
            _("No active workflow is configured for {0}. The lifecycle is configuration and must be seeded.")
            .format(doctype)
        )
    return frappe.get_cached_doc("Workflow", name)


def available_actions(doc) -> list[dict]:
    """The transitions configuration offers from this record's current state."""
    workflow = _workflow(doc.doctype)
    current = doc.get(workflow.workflow_state_field)
    roles = set(frappe.get_roles())
    return [
        {
            "action": row.action,
            "next_state": row.next_state,
            "allowed_role": row.allowed,
            "permitted": row.allowed in roles or "Administrator" in roles,
        }
        for row in workflow.transitions
        if row.state == current
    ]


def _transition_for(workflow, doc, action: str):
    current = doc.get(workflow.workflow_state_field)
    for row in workflow.transitions:
        if row.state == current and row.action == action:
            return row
    return None


def perform(doc, action: str, *, exception_authorisation: str | None = None):
    """Take a configured action on a record, after its gates have passed.

    ``doc`` may be a document or a name. The action is looked up in
    configuration; there is no list of actions in this function.
    """
    if isinstance(doc, str):
        doc = frappe.get_doc(DOCTYPE, doc)

    workflow = _workflow(doc.doctype)
    transition = _transition_for(workflow, doc, action)
    if not transition:
        frappe.throw(
            _("{0} is not an action configured from this record's current state.").format(action),
            title=_("Transition Not Configured"),
        )

    failures = check_gates(doc, workflow.workflow_state_field, transition.next_state)
    if failures and not exception_authorisation:
        audit.refuse(
            _("{0} of {1} is refused. {2}").format(action, doc.name, " | ".join(failures)),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="lifecycle gate",
            context={"action": action, "next_state": transition.next_state, "failures": failures},
            exc=frappe.ValidationError,
        )
    if failures and exception_authorisation:
        _validate_exception(doc, exception_authorisation, failures)

    apply_workflow(doc, action)
    doc.reload()
    return doc


def _validate_exception(doc, exception_authorisation: str, failures: list[str]) -> None:
    """A bypass is only a bypass if someone authorised it, in writing, in advance."""
    row = frappe.db.get_value(
        "Exception Authorisation",
        exception_authorisation,
        ["subject_doctype", "subject_name", "approved_by", "valid_to"],
        as_dict=True,
    )
    if not row:
        frappe.throw(_("Exception authorisation {0} does not exist.").format(exception_authorisation))
    if (row["subject_doctype"], row["subject_name"]) != (doc.doctype, doc.name):
        frappe.throw(
            _("Exception authorisation {0} was issued for a different record.").format(exception_authorisation)
        )
    if not row.get("approved_by"):
        audit.refuse(
            _("Exception authorisation {0} has not been approved, so it cannot excuse: {1}").format(
                exception_authorisation, " | ".join(failures)
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="exception authorisation",
            exc=frappe.ValidationError,
        )
    if row.get("valid_to") and frappe.utils.getdate(row["valid_to"]) < frappe.utils.getdate(nowdate()):
        frappe.throw(_("Exception authorisation {0} has expired.").format(exception_authorisation))


@frappe.whitelist()
def transition(document: str, action: str, exception_authorisation: str | None = None) -> dict:
    """Perform a lifecycle action. Permission is the framework's; gates are ours."""
    doc = frappe.get_doc(DOCTYPE, document)
    doc.check_permission("write")
    perform(doc, action, exception_authorisation=exception_authorisation)
    return {
        "document": doc.name,
        "lifecycle_phase": doc.lifecycle_phase,
        "is_editable": int(doc.is_editable or 0),
        "is_active": int(doc.is_active or 0),
        "requires_review": int(doc.requires_review or 0),
    }


@frappe.whitelist()
def readiness(document: str) -> dict:
    """What stands between this record and each action available to it.

    This is what makes a refusal explicable before it happens rather than after.
    """
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    doc = frappe.get_doc(DOCTYPE, document)
    workflow = _workflow(doc.doctype)
    out = []
    for entry in available_actions(doc):
        failures = check_gates(doc, workflow.workflow_state_field, entry["next_state"])
        out.append({**entry, "blocked_by": failures})
    return {"document": document, "actions": out, "approval_chain": routing.chain_status(doc)}
