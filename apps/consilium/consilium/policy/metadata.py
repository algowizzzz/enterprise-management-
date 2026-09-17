"""Required metadata: finding what is missing, and correcting it in place.

E15-S5 asks for a maintenance view that lists incomplete records by field and
supports correcting them there. P-23 asks for something adjacent: when a
lifecycle event on one record invalidates a required field on **another**, the
other record's owner is given a task.

Both read the same definition of "required", which comes from two places and
neither of them is a constant in this file:

* the DocType's own ``reqd`` fields, which the framework already enforces on
  save but which historical and imported rows can predate;
* the ``required_fields`` list on the ``Document Template`` configured for the
  record's document type and action, which is P-15's per-type requirement and is
  editable without a deployment.

Correction is a normal write through the framework, so the permission engine and
the retention guards apply exactly as they would anywhere else.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

DOCTYPE = "Governing Document"

#: Fields the framework marks required but which are set by machinery rather
#: than by a person, so listing them as "missing metadata" would be noise.
_MACHINE_SET = {"workflow_state", "lifecycle_phase"}


def _loads(value):
    if not value:
        return []
    if isinstance(value, list | dict):
        return value
    return json.loads(value)


def template_required_fields(doctype: str, document_type: str | None, action: str = "New") -> list[str]:
    if doctype != DOCTYPE or not document_type:
        return []
    raw = frappe.db.get_value(
        "Document Template",
        {"document_type": document_type, "action": action, "is_active": 1},
        "required_fields",
    )
    fields = _loads(raw)
    if isinstance(fields, dict):
        fields = fields.get("fields", [])
    return [f for f in fields if isinstance(f, str)]


def required_fields_for(doc) -> list[str]:
    meta = frappe.get_meta(doc.doctype)
    required = {
        df.fieldname
        for df in meta.fields
        if df.reqd and df.fieldname not in _MACHINE_SET
    }
    required |= set(template_required_fields(doc.doctype, doc.get("document_type")))
    return sorted(f for f in required if meta.has_field(f))


def missing_fields(doc) -> list[str]:
    """Required fields this record does not carry a value for."""
    missing = []
    for fieldname in required_fields_for(doc):
        value = doc.get(fieldname)
        if isinstance(value, list):
            if not value:
                missing.append(fieldname)
        elif value in (None, "", 0) and not _is_meaningful_zero(doc, fieldname):
            missing.append(fieldname)
    return missing


def _is_meaningful_zero(doc, fieldname: str) -> bool:
    df = frappe.get_meta(doc.doctype).get_field(fieldname)
    return bool(df and df.fieldtype in ("Check", "Int", "Float", "Currency", "Percent"))


@frappe.whitelist()
def incomplete_records(doctype: str = DOCTYPE, limit: int = 200) -> list[dict]:
    """The maintenance view: records with required metadata missing (E15-S5)."""
    frappe.has_permission(doctype, "read", throw=True)
    out = []
    for name in frappe.get_all(doctype, filters={"docstatus": ["<", 2]}, pluck="name", limit=limit):
        doc = frappe.get_doc(doctype, name)
        missing = missing_fields(doc)
        if missing:
            out.append({"doctype": doctype, "name": name, "missing": missing})
    return out


@frappe.whitelist()
def correct(doctype: str, name: str, values: dict | str) -> dict:
    """Correct a record in place from the maintenance view.

    Deliberately a normal ``save``: the permission engine, the retention guards
    and the workflow's edit rules all apply. A maintenance screen that wrote
    around them would be a second, unaudited write path.
    """
    if isinstance(values, str):
        values = json.loads(values)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    meta = frappe.get_meta(doctype)
    for fieldname, value in values.items():
        if not meta.has_field(fieldname):
            frappe.throw(_("{0} has no field {1}.").format(doctype, fieldname))
        doc.set(fieldname, value)
    doc.save()
    resolved = resolve_tasks_for(doctype, name, list(values))
    return {"doctype": doctype, "name": name, "missing": missing_fields(doc), "tasks_resolved": resolved}


def raise_task(
    *,
    subject_doctype: str,
    subject_name: str,
    invalid_fieldname: str,
    trigger_event: str,
    trigger_doctype: str | None = None,
    trigger_name: str | None = None,
    assigned_to: str | None = None,
    due_in_days: int = 30,
) -> str | None:
    """Raise one remediation task, unless an open one already covers the field."""
    duplicate = frappe.db.exists(
        "Metadata Remediation Task",
        {
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": invalid_fieldname,
            "is_open": 1,
            "docstatus": ["<", 2],
        },
    )
    if duplicate:
        return None
    return frappe.get_doc(
        {
            "doctype": "Metadata Remediation Task",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": invalid_fieldname,
            "trigger_event": trigger_event,
            "trigger_doctype": trigger_doctype,
            "trigger_name": trigger_name,
            "assigned_to": assigned_to,
            "due_on": add_days(nowdate(), due_in_days),
            "task_status": "Raised",
        }
    ).insert(ignore_permissions=True).name


def resolve_tasks_for(subject_doctype: str, subject_name: str, fieldnames: list[str]) -> list[str]:
    """Close the open tasks a correction has just satisfied."""
    resolved = []
    for name in frappe.get_all(
        "Metadata Remediation Task",
        filters={
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": ["in", fieldnames],
            "is_open": 1,
            "docstatus": ["<", 2],
        },
        pluck="name",
    ):
        task = frappe.get_doc("Metadata Remediation Task", name)
        task.task_status = "Resolved"
        task.resolved_on = nowdate()
        task.resolution_note = _("Corrected in place from the metadata maintenance view.")
        task.save(ignore_permissions=True)
        resolved.append(name)
    return resolved


def raise_tasks_for_deactivated_parent(document) -> list[str]:
    """P-23. A document that stops being in force invalidates its children's parent link."""
    from consilium.policy import lineage

    raised = []
    for row in lineage.children(document.name):
        child = row["document"]
        owner = frappe.db.get_value(DOCTYPE, child, "document_owner")
        name = raise_task(
            subject_doctype=DOCTYPE,
            subject_name=child,
            invalid_fieldname="parent_document",
            trigger_event="Parent Retired",
            trigger_doctype=DOCTYPE,
            trigger_name=document.name,
            assigned_to=owner,
        )
        if name:
            raised.append(name)
    return raised


@frappe.whitelist()
def sweep(doctype: str = DOCTYPE, limit: int = 200) -> list[str]:
    """Raise a remediation task for every record the maintenance view lists."""
    raised = []
    for row in incomplete_records(doctype, limit=limit):
        owner = frappe.db.get_value(doctype, row["name"], "document_owner")
        for fieldname in row["missing"]:
            name = raise_task(
                subject_doctype=doctype,
                subject_name=row["name"],
                invalid_fieldname=fieldname,
                trigger_event="Missing Required Metadata",
                assigned_to=owner,
            )
            if name:
                raised.append(name)
    return raised
