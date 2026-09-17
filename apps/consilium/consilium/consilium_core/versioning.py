"""The document version chain, and revert.

The framework's own change history is a forward diff trail, not a snapshot
store, which is why this exists. A ``Document Version`` is an immutable snapshot
of a record: its field state, and where there is one, the body file and its hash.

**Revert writes a new version.** It never mutates or deletes a version row, and
it is itself an audited act carrying actor, timestamp, source version and a
mandatory reason. The chain therefore always reads forward, and "what did this
record say on a given date" has exactly one answer.

Two fields on a version row change after insert — ``is_current`` and
``superseded_by``. Both are chain linkage, written only by this module and only
through the controller's explicit exception. Everything else is frozen.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import audit

#: Keys that belong to the framework, not to the record's own field state.
_SNAPSHOT_SKIP = {"modified", "modified_by", "creation", "owner", "docstatus", "idx", "doctype"}


def snapshot_of(doc) -> dict:
    data = doc.as_dict(convert_dates_to_str=True, no_nulls=False)
    return {k: v for k, v in data.items() if not k.startswith("_") and k not in _SNAPSHOT_SKIP}


def _sha256(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def current_version(subject_doctype: str, subject_name: str):
    name = frappe.db.get_value(
        "Document Version",
        {"subject_doctype": subject_doctype, "subject_name": subject_name, "is_current": 1},
        "name",
    )
    return frappe.get_doc("Document Version", name) if name else None


def version_history(subject_doctype: str, subject_name: str) -> list[dict]:
    return frappe.get_all(
        "Document Version",
        filters={"subject_doctype": subject_doctype, "subject_name": subject_name},
        fields=["name", "version_number", "version_label", "origin", "is_current", "change_summary"],
        order_by="version_number asc",
    )


def _next_version_number(subject_doctype: str, subject_name: str) -> int:
    highest = frappe.db.sql(
        """SELECT COALESCE(MAX("version_number"), 0) FROM "tabDocument Version"
           WHERE "subject_doctype" = %s AND "subject_name" = %s""",
        (subject_doctype, subject_name),
    )[0][0]
    return int(highest) + 1


def _link_chain(previous, new_version_name: str) -> None:
    """Close the previous version. The only mutation this module performs."""
    previous.flags.consilium_chain_update = True
    previous.is_current = 0
    previous.superseded_by = new_version_name
    previous.save(ignore_permissions=True)


def create_version(
    subject,
    *,
    change_summary: str,
    origin: str = "Authored",
    body_file: str | None = None,
    body_text: str | None = None,
    version_label: str | None = None,
    classification_assessment: str | None = None,
    change_classification: str | None = None,
    retention_class: str | None = None,
    published: int = 0,
    metadata_snapshot: dict | None = None,
):
    """Append a version to a record's chain and make it current."""
    if isinstance(subject, str):
        raise TypeError("create_version takes the subject document, not its name")
    if not change_summary:
        frappe.throw(_("A version needs a change summary: it is the record of why the version exists."))

    previous = current_version(subject.doctype, subject.name)
    snapshot = metadata_snapshot if metadata_snapshot is not None else snapshot_of(subject)

    version = frappe.get_doc(
        {
            "doctype": "Document Version",
            "subject_doctype": subject.doctype,
            "subject_name": subject.name,
            "version_number": _next_version_number(subject.doctype, subject.name),
            "version_label": version_label,
            "body_file": body_file,
            "body_text": body_text,
            "body_sha256": _sha256(body_text) if body_text else None,
            "metadata_snapshot": json.dumps(snapshot, default=str),
            "change_summary": change_summary,
            "change_classification": change_classification,
            "classification_assessment": classification_assessment,
            "created_from_version": previous.name if previous else None,
            "is_current": 1,
            "origin": origin,
            "published": published,
            "retention_class": retention_class,
        }
    ).insert(ignore_permissions=True)

    if previous:
        _link_chain(previous, version.name)

    return version


def revert_to_version(
    subject_doctype: str,
    subject_name: str,
    target_version: str,
    justification: str,
    *,
    approved_by: str | None = None,
    apply_to_subject: bool = True,
):
    """Restore a prior version by writing a **new** version containing its content.

    Returns the ``Version Revert Log`` row. The target version, and every version
    between it and the head, are left exactly as they were.
    """
    if not (justification or "").strip():
        audit.refuse(
            f"Revert of {subject_doctype} {subject_name} is refused: a revert carries a mandatory "
            "reason, because the revert is itself an auditable act.",
            subject_doctype=subject_doctype,
            subject_name=subject_name,
            attempted_action="Revert",
            control="revert justification",
            exc=frappe.ValidationError,
        )

    target = frappe.get_doc("Document Version", target_version)
    if (target.subject_doctype, target.subject_name) != (subject_doctype, subject_name):
        frappe.throw(_("Version {0} does not belong to {1} {2}.").format(target_version, subject_doctype, subject_name))

    head = current_version(subject_doctype, subject_name)
    if not head:
        frappe.throw(_("{0} {1} has no version chain to revert.").format(subject_doctype, subject_name))
    if head.name == target.name:
        frappe.throw(_("Version {0} is already current; there is nothing to revert to.").format(target_version))

    snapshot = json.loads(target.metadata_snapshot or "{}")

    subject = frappe.get_doc(subject_doctype, subject_name)
    if apply_to_subject:
        meta = frappe.get_meta(subject_doctype)
        for fieldname, value in snapshot.items():
            if fieldname in ("name", "parent", "parenttype", "parentfield"):
                continue
            if meta.has_field(fieldname):
                subject.set(fieldname, value)
        subject.save(ignore_permissions=True)
        subject.reload()

    resulting = create_version(
        subject,
        change_summary=f"Reverted to version {target.version_number}. {justification}".strip(),
        origin="Reverted",
        version_label=target.version_label,
        body_file=target.body_file,
        body_text=target.body_text,
        change_classification=target.change_classification,
        retention_class=target.retention_class,
        metadata_snapshot=snapshot,
    )

    return frappe.get_doc(
        {
            "doctype": "Version Revert Log",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "from_version": head.name,
            "target_version": target.name,
            "resulting_version": resulting.name,
            "reverted_by": frappe.session.user,
            "reverted_on": now(),
            "justification": justification,
            "approved_by": approved_by,
        }
    ).insert(ignore_permissions=True)
