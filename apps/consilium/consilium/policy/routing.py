"""Conditional approval routing.

E12-S3 asks for three things: routing that depends on policy type, change type
and risk level; routing that is configuration; and the resulting path visible on
the record **before** submission. The third is the one that makes the first two
worth having — an approver who cannot see the path until they are in it cannot
challenge it.

So a route is an ``Approval Route`` record. Selection is: every active route for
the DocType, most specific first, first match wins. Resolution turns each step
into an assignee by reading the record, so a change of owner does not strand a
route. ``preview`` returns the resolved path without writing anything;
``instantiate`` writes it as Core ``Approval Decision`` rows.

Lineage adds one more step that no route carries: where the lineage edge to a
parent is marked ``owner_approval_required``, the parent's owner approves the
child's change (P-8, E12-S4). It is appended as a distinct step so it is visible
as its own approval rather than folded into someone else's.
"""

from __future__ import annotations

import frappe
from frappe import _

from consilium.consilium_core import approvals, classification, state_flags
from consilium.policy import lineage

DOCTYPE = "Governing Document"

PARENT_OWNER_STEP = "Parent Document Owner Approval"

#: Where a step's assignee comes from. The label is the field it reads.
ASSIGNEE_FIELD = {
    "Document Owner": "document_owner",
    "Document Approver": "document_approver",
    "Document Sponsor": "document_sponsor",
    "Document Liaison": "document_liaison",
}


def _risk_category_family(category: str | None) -> list[str]:
    """A category and all of its ancestors, so a route on a parent category matches."""
    if not category:
        return []
    family = [category]
    seen = {category}
    current = category
    while True:
        parent = frappe.db.get_value("Risk Category", current, "parent_risk_category")
        if not parent or parent in seen:
            break
        family.append(parent)
        seen.add(parent)
        current = parent
    return family


def _matches(route: dict, doc) -> bool:
    if route.get("document_type") and route["document_type"] != doc.get("document_type"):
        return False
    if route.get("change_classification"):
        if route["change_classification"] != (change_classification_of(doc) or ""):
            return False
    if route.get("primary_risk_category"):
        if route["primary_risk_category"] not in _risk_category_family(doc.get("primary_risk_category")):
            return False
    if route.get("handling_classification"):
        if route["handling_classification"] != doc.get("handling_classification"):
            return False
    return True


def _specificity(route: dict) -> int:
    return sum(
        1
        for key in ("document_type", "change_classification", "primary_risk_category", "handling_classification")
        if route.get(key)
    )


def change_classification_of(doc) -> str | None:
    """The classification this document's pending change was given.

    Read from the intake request that produced it, through the Core assessment,
    so the value used for routing is the same one the audit trail explains. An
    override on the assessment wins, because that is what was decided.
    """
    request = frappe.db.get_value(
        "Document Intake Request",
        {"created_document": doc.name, "docstatus": ["<", 2]},
        ["name", "classification_assessment", "change_classification"],
        as_dict=True,
    ) if doc.get("name") else None
    if not request:
        request = frappe.db.get_value(
            "Document Intake Request",
            {"subject_document": doc.get("name"), "docstatus": ["<", 2], "is_open": 1},
            ["name", "classification_assessment", "change_classification"],
            as_dict=True,
        ) if doc.get("name") else None
    if not request:
        return None
    if request.get("classification_assessment"):
        return classification.effective_outcome(request["classification_assessment"])
    return request.get("change_classification")


def select_route(doc) -> dict | None:
    routes = frappe.get_all(
        "Approval Route",
        filters={"target_doctype": doc.doctype, "is_active": 1},
        fields=["name", "priority", "document_type", "change_classification",
                "primary_risk_category", "handling_classification"],
        order_by="priority asc, modified asc",
    )
    candidates = [route for route in routes if _matches(route, doc)]
    if not candidates:
        return None
    candidates.sort(key=lambda route: (int(route["priority"] or 0), -_specificity(route)))
    return candidates[0]


def _resolve_assignee(step, doc) -> str | None:
    source = step.get("assignee_source")
    if source == "Named User":
        return step.get("assignee")
    if source == "Parent Document Owner":
        entries = lineage.parent_owner_approvals(doc)
        return entries[0]["owner"] if entries else None
    fieldname = ASSIGNEE_FIELD.get(source)
    return doc.get(fieldname) if fieldname else None


def resolved_steps(doc) -> list[dict]:
    """The approval path for this record, resolved but not written.

    A step whose assignee cannot be resolved falls back to the document
    approver, who is mandatory on every document; the fallback is reported in
    the step so it is visible rather than silent.
    """
    route = select_route(doc)
    steps: list[dict] = []

    if route:
        rows = frappe.get_all(
            "Approval Route Step",
            filters={"parent": route["name"], "parenttype": "Approval Route"},
            fields=["step_sequence", "approval_step", "required_role", "assignee_source",
                    "assignee", "mode", "is_mandatory", "condition"],
            order_by="step_sequence asc",
        )
        for row in rows:
            assignee = _resolve_assignee(row, doc)
            fallback = False
            if not assignee:
                assignee = doc.get("document_approver")
                fallback = True
            steps.append(
                {
                    "step_sequence": int(row["step_sequence"] or 0),
                    "approval_step": row["approval_step"],
                    "required_role": row["required_role"],
                    "assigned_to": assignee,
                    "mode": row["mode"] or "Sequential",
                    "is_mandatory": int(row["is_mandatory"] or 0),
                    "source": f"route:{route['name']}",
                    "assignee_fallback": fallback,
                }
            )

    next_sequence = max([step["step_sequence"] for step in steps], default=0) + 1
    for entry in lineage.parent_owner_approvals(doc):
        steps.append(
            {
                "step_sequence": next_sequence,
                "approval_step": f"{PARENT_OWNER_STEP} ({entry['document']})",
                "required_role": None,
                "assigned_to": entry["owner"],
                "mode": "Sequential",
                "is_mandatory": 1,
                "source": f"lineage:{entry['document']}",
                "assignee_fallback": False,
            }
        )
        next_sequence += 1

    return steps


@frappe.whitelist()
def preview(document: str) -> dict:
    """The approval path, visible on the record before it is submitted (E12-S3)."""
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    doc = frappe.get_doc(DOCTYPE, document)
    route = select_route(doc)
    return {
        "document": document,
        "route": route["name"] if route else None,
        "change_classification": change_classification_of(doc),
        "steps": resolved_steps(doc),
    }


def instantiate(doc) -> list[str]:
    """Write the resolved path as Core Approval Decision rows.

    Idempotent: a step that already has a decision row for this document is left
    alone, so re-routing after a change of owner does not duplicate history.
    """
    existing = {
        row["approval_step"]
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": doc.doctype, "subject_name": doc.name, "docstatus": ["<", 2]},
            fields=["approval_step"],
        )
    }
    classification_label = change_classification_of(doc)
    written = []
    for step in resolved_steps(doc):
        if step["approval_step"] in existing:
            continue
        if not step["assigned_to"]:
            frappe.throw(
                _("Approval step {0} has no assignee and the document has no approver to fall back to.").format(
                    step["approval_step"]
                )
            )
        decision = approvals.request_decision(
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            approval_step=step["approval_step"],
            step_sequence=step["step_sequence"],
            mode=step["mode"],
            required_role=step["required_role"],
            assigned_to=step["assigned_to"],
            classification_at_decision=classification_label,
        )
        written.append(decision.name)
    return written


def chain_status(doc) -> dict:
    """Whether the approval chain is complete, and why not if it is not.

    Completeness is read from the semantic flags, never from the decision label.
    ``is_open`` is carried on the decision row itself; ``requires_review`` — which
    marks an objection, whether a rejection, a request for changes or a bypass —
    is not a column on ``Approval Decision``, so it is read out of the configured
    flag map for the value the row holds. That is still a configuration lookup
    rather than a comparison: no decision name appears here.

    An objection is tolerated only when the row names an ``Exception
    Authorisation``, which is what P-25 demands.
    """
    steps = resolved_steps(doc)
    rows = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name, "docstatus": ["<", 2]},
        fields=["name", "approval_step", "decision", "is_open", "exception_authorisation",
                "assigned_to", "step_sequence"],
    )
    by_step = {row["approval_step"]: row for row in rows}

    missing, outstanding, objections = [], [], []
    for step in steps:
        if not step["is_mandatory"]:
            continue
        row = by_step.get(step["approval_step"])
        if not row:
            missing.append(step["approval_step"])
            continue
        if int(row["is_open"] or 0):
            outstanding.append(step["approval_step"])
            continue
        flags = state_flags.flags_for("Approval Decision", "decision", row["decision"]) or {}
        if int(flags.get("requires_review") or 0) and not row.get("exception_authorisation"):
            objections.append(step["approval_step"])

    return {
        "complete": not (missing or outstanding or objections),
        "expected_steps": [step["approval_step"] for step in steps if step["is_mandatory"]],
        "missing": missing,
        "outstanding": outstanding,
        "objections": objections,
    }
