"""Retention, legal hold and disposal.

Three rules, enforced here rather than trusted to convention:

1. A record under retention cannot be modified or deleted. The refusal names the
   retention class that caused it and is audited out of band.
2. A legal hold overrides scheduled disposal entirely and unconditionally. It
   does not suspend retention accrual and it does not change the class.
3. Disposal is never automatic: an event is scheduled, may be held, must be
   approved, and only then executed.

The guards run from a wildcard ``doc_events`` hook, so they hold for every
DocType in the platform, including ones other modules add later.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_months, getdate, nowdate

from consilium.consilium_core import audit

CACHE_KEY = "consilium_core:retention_doctypes"

#: Never guarded: framework plumbing, and the retention machinery itself, which
#: would otherwise be unable to record a hold or close a disposition.
EXEMPT_DOCTYPES = {
    "Retention Class",
    "Retention Assignment",
    "Legal Hold",
    "Archive Record",
    "Disposition Event",
    "Governance Refusal Log",
    "Workflow State Flag",
    "DocType",
    "DocField",
    "DocPerm",
    "Series",
    "Version",
    "Error Log",
    "Comment",
    "Activity Log",
    "Access Log",
    "Scheduled Job Log",
    "Prepared Report",
    "File",
}


def _loads(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


def clear_cache(*args, **kwargs) -> None:
    frappe.cache().delete_value(CACHE_KEY)


def _controlled_doctypes() -> dict[str, bool]:
    """DocTypes that any active assignment, hold or archive row refers to."""
    cached = frappe.cache().get_value(CACHE_KEY)
    if cached is not None:
        return cached

    controlled: dict[str, bool] = {}
    for doctype, filters in (
        ("Retention Assignment", {"is_active": 1}),
        ("Legal Hold", {"is_active": 1}),
    ):
        if not frappe.db.table_exists(doctype):
            continue
        field = "target_doctype" if doctype == "Retention Assignment" else "scope_doctype"
        for value in frappe.get_all(doctype, filters=filters, pluck=field):
            controlled[value] = True
    if frappe.db.table_exists("Archive Record"):
        for value in frappe.get_all("Archive Record", pluck="subject_doctype", distinct=True):
            controlled[value] = True

    frappe.cache().set_value(CACHE_KEY, controlled)
    return controlled


def _matches(target_doctype: str, record_filter, name: str) -> bool:
    filters = _loads(record_filter)
    filters["name"] = name
    try:
        return bool(frappe.db.exists(target_doctype, filters))
    except Exception:
        # A filter naming a field the DocType does not have is a configuration
        # error, not a licence to bypass the control.
        frappe.log_error(title="Consilium: unusable retention filter", message=frappe.get_traceback())
        return True


def active_legal_hold(doctype: str, name: str) -> str | None:
    if not frappe.db.table_exists("Legal Hold"):
        return None
    for hold in frappe.get_all(
        "Legal Hold",
        filters={"scope_doctype": doctype, "is_active": 1},
        fields=["name", "scope_filter"],
    ):
        if _matches(doctype, hold.scope_filter, name):
            return hold.name
    return None


def effective_retention(doctype: str, name: str) -> dict | None:
    """The winning retention assignment for one record, or None."""
    if not frappe.db.table_exists("Retention Assignment"):
        return None
    candidates = frappe.get_all(
        "Retention Assignment",
        filters={"target_doctype": doctype, "is_active": 1},
        fields=["name", "record_filter", "retention_class", "priority"],
        order_by="priority desc, modified desc",
    )
    for assignment in candidates:
        if _matches(doctype, assignment.record_filter, name):
            return assignment
    return None


def retention_lock(doctype: str, name: str) -> dict | None:
    """Why this record is locked, or None if it is not.

    ``{"reason": str, "retention_class": str|None, "legal_hold": str|None}``
    """
    hold = active_legal_hold(doctype, name)
    if hold:
        return {
            "reason": f"{doctype} {name} is under legal hold {hold}. "
            "A legal hold suspends disposal and freezes the record until it is released.",
            "retention_class": None,
            "legal_hold": hold,
        }

    if frappe.db.table_exists("Archive Record") and frappe.db.exists(
        "Archive Record", {"subject_doctype": doctype, "subject_name": name}
    ):
        return {
            "reason": f"{doctype} {name} has been archived under retention. "
            "An archived record is read-only; disposal is the only way out, and it is approved, not automatic.",
            "retention_class": None,
            "legal_hold": None,
        }

    assignment = effective_retention(doctype, name)
    if assignment:
        retention_class = frappe.db.get_value(
            "Retention Class", assignment["retention_class"], ["name", "requires_worm", "title"], as_dict=True
        )
        if retention_class and retention_class.requires_worm:
            return {
                "reason": f"{doctype} {name} is retained under retention class "
                f"{retention_class.name} ({retention_class.title}), which requires write-once handling. "
                "It cannot be modified or deleted while the class applies.",
                "retention_class": retention_class.name,
                "legal_hold": None,
            }
    return None


def _guarded(doc) -> bool:
    if doc.doctype in EXEMPT_DOCTYPES or getattr(doc, "istable", 0):
        return False
    if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
        return False
    if frappe.flags.in_import or frappe.flags.in_setup_wizard:
        return False
    return doc.doctype in _controlled_doctypes()


def guard_modification(doc, method=None) -> None:
    """``before_validate`` hook: refuse a change to a retained or held record."""
    if doc.is_new() or not _guarded(doc):
        return
    lock = retention_lock(doc.doctype, doc.name)
    if not lock:
        return
    audit.refuse(
        lock["reason"],
        subject_doctype=doc.doctype,
        subject_name=doc.name,
        attempted_action="Modify",
        control="retention",
        retention_class=lock["retention_class"],
        legal_hold=lock["legal_hold"],
    )


def guard_deletion(doc, method=None) -> None:
    """``on_trash`` hook: refuse a delete of a retained or held record."""
    if not _guarded(doc):
        return
    lock = retention_lock(doc.doctype, doc.name)
    if not lock:
        return
    audit.refuse(
        lock["reason"],
        subject_doctype=doc.doctype,
        subject_name=doc.name,
        attempted_action="Delete",
        control="retention",
        retention_class=lock["retention_class"],
        legal_hold=lock["legal_hold"],
    )


def disposition_due_date(retention_class: str, subject_doctype: str, subject_name: str) -> str:
    """When the retention period expires, from the class's trigger event."""
    cls = frappe.get_doc("Retention Class", retention_class)
    trigger_fields = {
        "Creation": "creation",
        "Last Modification": "modified",
        "Effective Date": "effective_date",
        "Retirement": "retired_on",
        "Closure": "closed_on",
        "Disbandment": "disbanded_on",
    }
    fieldname = trigger_fields.get(cls.trigger_event, "creation")
    meta = frappe.get_meta(subject_doctype)
    if fieldname not in ("creation", "modified") and not meta.has_field(fieldname):
        fieldname = "creation"
    start = frappe.db.get_value(subject_doctype, subject_name, fieldname) or nowdate()
    return add_months(getdate(start), int(cls.retention_period_months or 0))


def schedule_disposition(archive_record: str) -> str:
    """Schedule the disposal of an archived record. Held at once if a hold applies."""
    archive = frappe.get_doc("Archive Record", archive_record)
    hold = active_legal_hold(archive.subject_doctype, archive.subject_name)
    cls = frappe.get_doc("Retention Class", archive.retention_class)
    event = frappe.get_doc(
        {
            "doctype": "Disposition Event",
            "archive_record": archive.name,
            "due_on": archive.disposition_due_on,
            "action": cls.disposition_action,
            "status": "Held" if hold else "Scheduled",
            "held_by_legal_hold": hold,
        }
    ).insert(ignore_permissions=True)
    return event.name


def execute_disposition(disposition_event: str, evidence: dict | None = None) -> None:
    """Execute an approved disposal. A legal hold refuses this outright."""
    event = frappe.get_doc("Disposition Event", disposition_event)
    archive = frappe.get_doc("Archive Record", event.archive_record)

    hold = active_legal_hold(archive.subject_doctype, archive.subject_name)
    if hold:
        # Nothing is written here on purpose: the refusal below rolls this
        # transaction back, and the audit row is written out of band.
        audit.refuse(
            f"Disposal of {archive.subject_doctype} {archive.subject_name} is refused: "
            f"legal hold {hold} is in force and overrides the retention schedule entirely.",
            subject_doctype=archive.subject_doctype,
            subject_name=archive.subject_name,
            attempted_action="Dispose",
            control="legal hold",
            legal_hold=hold,
            context={"disposition_event": event.name},
        )

    if not event.approved_by:
        audit.refuse(
            f"Disposal of {archive.subject_doctype} {archive.subject_name} is refused: "
            "a disposition must be approved by a named person before it is executed. Disposal is never automatic.",
            subject_doctype=archive.subject_doctype,
            subject_name=archive.subject_name,
            attempted_action="Dispose",
            control="disposition approval",
            context={"disposition_event": event.name},
            exc=frappe.ValidationError,
        )

    event.status = "Executed"
    event.executed_on = frappe.utils.now()
    event.evidence = json.dumps(evidence or {})
    event.save(ignore_permissions=True)


def release_hold(legal_hold: str) -> None:
    """Release a hold and return everything it held to Scheduled."""
    hold = frappe.get_doc("Legal Hold", legal_hold)
    hold.released_on = hold.released_on or nowdate()
    hold.save(ignore_permissions=True)
    for name in frappe.get_all(
        "Disposition Event", filters={"held_by_legal_hold": legal_hold}, pluck="name"
    ):
        event = frappe.get_doc("Disposition Event", name)
        event.status = "Scheduled"
        event.held_by_legal_hold = None
        event.save(ignore_permissions=True)
