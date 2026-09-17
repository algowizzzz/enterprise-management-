"""Intake, and the classification that routes it.

P-16 wants a dynamic question set whose answers produce a major/minor
classification, with a full audit trail. Core already has that engine, versioned
rule sets and an immutable assessment included, so this module writes none of it.
What it does is decide *which* rule set applies, hand the answers over, and copy
the outcome onto the request so routing and service levels can read it.

The property that matters, and that the tests pin down: a classification made
under one rule-set version does not change when the rules are later edited. Core
seals a rule set the first time it classifies anything and stores the version
label and the full evaluation trace on the assessment; a rule change is therefore
a new rule set, and the old assessment keeps answering for itself.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now, nowdate

from consilium.consilium_core import classification, sla

REQUEST_DOCTYPE = "Document Intake Request"
DOCUMENT_DOCTYPE = "Governing Document"


def active_rule_set(doctype: str = REQUEST_DOCTYPE) -> str | None:
    """The rule set in force for a DocType today: active, effective, newest first."""
    rows = frappe.get_all(
        "Classification Rule Set",
        filters={
            "applies_to_doctype": doctype,
            "is_active": 1,
            "effective_from": ["<=", nowdate()],
        },
        fields=["name", "effective_to", "effective_from", "version_label"],
        order_by="effective_from desc, creation desc",
    )
    for row in rows:
        if row.get("effective_to") and frappe.utils.getdate(row["effective_to"]) < frappe.utils.getdate(nowdate()):
            continue
        return row["name"]
    return None


def classify(request: str, answers: dict | str, *, rule_set: str | None = None):
    """Classify a request through Core's engine and copy the outcome onto it."""
    if isinstance(answers, str):
        answers = json.loads(answers)
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    rule_set = rule_set or active_rule_set()
    if not rule_set:
        frappe.throw(
            _("No active classification rule set applies to {0}. The questions and rules are data and "
              "must be configured before intake can be classified.").format(REQUEST_DOCTYPE)
        )

    assessment = classification.classify(
        rule_set,
        answers,
        subject_doctype=REQUEST_DOCTYPE,
        subject_name=doc.name,
    )
    doc.classification_assessment = assessment.name
    doc.change_classification = classification.effective_outcome(assessment.name)
    doc.workflow_state = "Classified"
    doc.save(ignore_permissions=True)
    start_service_level(doc)
    return assessment


def override(request: str, outcome: str, justification: str, approved_by: str | None = None):
    """Override an outcome through Core, then re-copy the effective outcome."""
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if not doc.classification_assessment:
        frappe.throw(_("{0} has not been classified, so there is nothing to override.").format(request))
    classification.override(doc.classification_assessment, outcome, justification, approved_by)
    doc.change_classification = classification.effective_outcome(doc.classification_assessment)
    doc.save(ignore_permissions=True)
    return doc


@frappe.whitelist()
def challenge(request: str, statement: str) -> dict:
    """Record a requester's challenge to their classification (E13-S3).

    A challenge is recorded, not acted on: it does not move the outcome. Moving
    the outcome is an override, which is a separate, approved act.
    """
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    doc.check_permission("write")
    if not (statement or "").strip():
        frappe.throw(_("A challenge needs a statement; that statement is the record of it."))
    doc.classification_challenge = statement
    doc.challenged_by = frappe.session.user
    doc.challenged_on = now()
    doc.save()
    return {"request": doc.name, "challenged_on": doc.challenged_on}


@frappe.whitelist()
def explain(request: str) -> dict:
    """The outcome, the rule that fired and the trace — what the requester sees."""
    frappe.has_permission(REQUEST_DOCTYPE, "read", doc=request, throw=True)
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if not doc.classification_assessment:
        return {"request": request, "classified": False}
    assessment = frappe.get_doc("Classification Assessment", doc.classification_assessment)
    return {
        "request": request,
        "classified": True,
        "rule_set": assessment.rule_set,
        "rule_set_version_label": assessment.rule_set_version_label,
        "matched_rule_code": assessment.matched_rule_code,
        "outcome": assessment.outcome,
        "effective_outcome": classification.effective_outcome(assessment.name),
        "outcome_rationale": assessment.outcome_rationale,
        "evaluation_trace": assessment.evaluation_trace,
        "challenge": doc.classification_challenge,
    }


def start_service_level(doc) -> str | None:
    """E13-S4: classification drives the service level, not only the route."""
    for name in frappe.get_all(
        "SLA Definition", filters={"target_doctype": REQUEST_DOCTYPE, "is_active": 1}, pluck="name"
    ):
        definition = frappe.get_doc("SLA Definition", name)
        if not sla.applies_to(definition, REQUEST_DOCTYPE, doc.name):
            continue
        clock = sla.start_clock(name, REQUEST_DOCTYPE, doc.name)
        frappe.db.set_value(REQUEST_DOCTYPE, doc.name, "sla_clock", clock.name)
        return clock.name
    return None


def create_document(request: str, **overrides) -> str:
    """Turn a classified request into a repository record.

    The request keeps the link, so the classification that routed the document's
    approval can always be traced back from the document itself.
    """
    doc = frappe.get_doc(REQUEST_DOCTYPE, request)
    if doc.created_document:
        return doc.created_document

    values = {
        "doctype": DOCUMENT_DOCTYPE,
        "document_name": doc.proposed_document_name or doc.name,
        "document_type": doc.proposed_document_type,
        "document_owner": doc.requester,
        "document_approver": doc.requester,
        "primary_risk_category": doc.primary_risk_category,
        "effective_on": doc.proposed_effective_date,
    }
    values.update(overrides)
    document = frappe.get_doc(values).insert(ignore_permissions=True)

    doc.created_document = document.name
    doc.workflow_state = "Fulfilled"
    doc.save(ignore_permissions=True)
    return document.name
