"""Monitoring and violations, reachable from the document page (P-11, P-22).

``Monitoring Activity``, ``Monitoring Result`` and ``Policy Violation`` existed
with their rules in their controllers — a performed activity must carry
findings or evidence, a result rolls the activity's due date forward — but the
only way to write one was the desk. This module is the portal's door onto them.
It adds no rule of its own beyond who may record and when; the controllers
still decide whether a record is valid.

Who may record is ``lifecycle.ACTION_ROLES``, with one addition: the person a
monitoring activity names as responsible may record its result whatever roles
they hold, because that is what naming them responsible means.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import nowdate

DOCTYPE = "Governing Document"
ACTIVITY_DOCTYPE = "Monitoring Activity"
RESULT_DOCTYPE = "Monitoring Result"
VIOLATION_DOCTYPE = "Policy Violation"


def _options(doctype: str, fieldname: str) -> list[str]:
    field = frappe.get_meta(doctype).get_field(fieldname)
    return [option for option in (field.options or "").split("\n") if option] if field else []


def _load(document: str):
    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    return doc


def may_record_result(doc, activity: dict, user: str | None = None) -> bool:
    from consilium.policy import lifecycle

    user = user or frappe.session.user
    if not int(activity.get("is_active") or 0):
        return False
    if "record_monitoring_result" not in lifecycle.stage_actions(doc):
        return False
    return activity.get("responsible") == user or lifecycle.may_take(doc, "record_monitoring_result", user)


def monitoring_context(doc) -> dict:
    from consilium.policy import lifecycle

    user = frappe.session.user
    activities = frappe.get_all(
        ACTIVITY_DOCTYPE,
        filters={"document": doc.name},
        fields=["name", "activity_title", "description", "frequency", "responsible", "next_due_on",
                "is_active", "control_reference"],
        order_by="activity_title asc",
    )
    for row in activities:
        row["can_record"] = may_record_result(doc, row, user)
    results = frappe.get_all(
        RESULT_DOCTYPE,
        filters={"document": doc.name},
        fields=["name", "monitoring_activity", "period_label", "performed_by", "performed_on", "outcome",
                "findings", "resulting_violation"],
        order_by="performed_on desc, creation desc",
        limit=100,
    )
    violations = frappe.get_all(
        VIOLATION_DOCTYPE,
        filters={"document": doc.name, "docstatus": ["<", 2]},
        fields=["name", "violation_type", "severity", "occurred_on", "identified_on", "responsible_party",
                "description", "corrective_actions", "violation_status", "is_open", "resolved_on",
                "resulting_escalation", "external_reference"],
        order_by="identified_on desc, creation desc",
    )
    return {
        "document": doc.name,
        "activities": activities,
        "results": results,
        "violations": violations,
        "result_outcomes": _options(RESULT_DOCTYPE, "outcome"),
        "violation_types": _options(VIOLATION_DOCTYPE, "violation_type"),
        "severities": _options(VIOLATION_DOCTYPE, "severity"),
        "violation_statuses": _options(VIOLATION_DOCTYPE, "violation_status"),
        "actions": {
            "record_monitoring_result": any(row["can_record"] for row in activities),
            "log_violation": "log_violation" in lifecycle.stage_actions(doc)
            and lifecycle.may_take(doc, "log_violation", user),
            # Only an open violation moves; a closed one stays closed (its controller).
            "update_violation": "update_violation" in lifecycle.stage_actions(doc)
            and lifecycle.may_take(doc, "update_violation", user)
            and any(int(row["is_open"] or 0) for row in violations),
        },
    }


@frappe.whitelist(methods=["GET"])
def document_monitoring(document: str) -> dict:
    return monitoring_context(_load(document))


@frappe.whitelist(methods=["POST"])
def record_result(
    monitoring_activity: str,
    period_label: str,
    outcome: str,
    findings: str | None = None,
    performed_on: str | None = None,
) -> dict:
    """Record one performance of a monitoring activity."""
    from consilium.policy import lifecycle

    activity = frappe.db.get_value(
        ACTIVITY_DOCTYPE, monitoring_activity, ["name", "document", "responsible", "is_active"], as_dict=True
    )
    if not activity:
        frappe.throw(_("Monitoring activity {0} does not exist.").format(monitoring_activity))
    doc = _load(activity.document)
    lifecycle.authorise(doc, "record_monitoring_result", also_permitted=activity.responsible == frappe.session.user)
    if not int(activity.is_active or 0):
        frappe.throw(_("Monitoring activity {0} is no longer active.").format(monitoring_activity),
                     title=_("Activity Inactive"))
    if outcome not in _options(RESULT_DOCTYPE, "outcome"):
        frappe.throw(_("{0} is not a monitoring outcome.").format(outcome), title=_("Unknown Outcome"))
    frappe.get_doc(
        {
            "doctype": RESULT_DOCTYPE,
            "monitoring_activity": activity.name,
            "document": doc.name,
            "period_label": period_label,
            "performed_by": frappe.session.user,
            "performed_on": performed_on or nowdate(),
            "outcome": outcome,
            "findings": (findings or "").strip() or None,
        }
    ).insert(ignore_permissions=True)
    return monitoring_context(doc)


@frappe.whitelist(methods=["POST"])
def log_violation(
    document: str,
    violation_type: str,
    severity: str,
    description: str,
    identified_on: str | None = None,
    occurred_on: str | None = None,
    responsible_party: str | None = None,
    corrective_actions: str | None = None,
) -> dict:
    """Log a breach of a document (P-22).

    A new violation starts in the first status the DocType declares; where it
    goes from there is the desk's for now, and each status carries its own flags.
    """
    from consilium.policy import lifecycle

    doc = _load(document)
    lifecycle.authorise(doc, "log_violation")
    if violation_type not in _options(VIOLATION_DOCTYPE, "violation_type"):
        frappe.throw(_("{0} is not a violation type.").format(violation_type), title=_("Unknown Type"))
    if severity not in _options(VIOLATION_DOCTYPE, "severity"):
        frappe.throw(_("{0} is not a severity.").format(severity), title=_("Unknown Severity"))
    if not (description or "").strip():
        frappe.throw(_("A violation is logged with a description of what happened."), title=_("Description Required"))
    identified_on = identified_on or nowdate()
    if occurred_on and frappe.utils.getdate(occurred_on) > frappe.utils.getdate(identified_on):
        frappe.throw(_("A violation cannot be identified before it occurred."), title=_("Dates Out Of Order"))
    frappe.get_doc(
        {
            "doctype": VIOLATION_DOCTYPE,
            "document": doc.name,
            "violation_type": violation_type,
            "severity": severity,
            "description": description.strip(),
            "identified_on": identified_on,
            "occurred_on": occurred_on or None,
            "responsible_party": responsible_party or None,
            "corrective_actions": (corrective_actions or "").strip() or None,
            "violation_status": _options(VIOLATION_DOCTYPE, "violation_status")[0],
        }
    ).insert(ignore_permissions=True)
    return monitoring_context(doc)


@frappe.whitelist(methods=["POST"])
def update_violation(violation: str, violation_status: str, resolution_note: str | None = None,
                     corrective_actions: str | None = None) -> dict:
    """Move a violation on — investigating, remediating, resolved, dismissed (P-22).

    The moves themselves are the controller's to allow: it refuses reopening a
    closed violation and closing one without its resolution note, whichever
    route the change arrives by. This entry point adds who may make the move
    (``lifecycle.ACTION_ROLES``) and saves through the framework's own
    permission check, so the violation's DocPerm still has the last word.
    """
    from consilium.policy import lifecycle

    record = frappe.db.get_value(VIOLATION_DOCTYPE, violation, ["name", "document"], as_dict=True)
    if not record:
        frappe.throw(_("Violation {0} does not exist.").format(violation))
    doc = _load(record.document)
    lifecycle.authorise(doc, "update_violation")
    if violation_status not in _options(VIOLATION_DOCTYPE, "violation_status"):
        frappe.throw(_("{0} is not a violation status.").format(violation_status), title=_("Unknown Status"))
    target = frappe.get_doc(VIOLATION_DOCTYPE, violation)
    target.violation_status = violation_status
    if (resolution_note or "").strip():
        target.resolution_note = resolution_note.strip()
    if (corrective_actions or "").strip():
        target.corrective_actions = corrective_actions.strip()
    target.save()
    return monitoring_context(doc)
