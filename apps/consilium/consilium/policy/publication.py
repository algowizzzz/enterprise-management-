"""Publication, and the version that is published.

The document editor is a separate application. Documents arrive here as uploads
and we hold the authoritative body and its version chain, so this module never
edits a body; it records that a **particular version** was published, to a stated
audience, with stated renditions, and that the affected parties were told.

Who is told is not a list kept here. It is resolved from the document's
applicability at the moment of publication — E11-S5 — and the dispatch rows Core
writes are the evidence.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import versioning
from consilium.policy import applicability

DOCTYPE = "Governing Document"
PUBLICATION_DOCTYPE = "Document Publication"


def upload_version(
    document: str,
    *,
    change_summary: str,
    body_file: str | None = None,
    body_text: str | None = None,
    version_label: str | None = None,
    classification_assessment: str | None = None,
    change_classification: str | None = None,
):
    """Take an uploaded rendition into the chain as a new version.

    ``origin`` is Uploaded because that is what happened: the body was authored
    elsewhere and handed to us. The chain, the hash and the metadata snapshot are
    ours from this point.
    """
    doc = frappe.get_doc(DOCTYPE, document)
    doc.check_permission("write")
    if not doc.is_editable:
        frappe.throw(
            _("{0} is not editable in its current state, so a new version cannot be taken.").format(document),
            title=_("Not Editable"),
        )

    version = versioning.create_version(
        doc,
        change_summary=change_summary,
        origin="Uploaded",
        body_file=body_file,
        body_text=body_text,
        version_label=version_label,
        classification_assessment=classification_assessment,
        change_classification=change_classification,
        retention_class=doc.retention_class,
    )
    frappe.db.set_value(
        DOCTYPE,
        document,
        {
            "current_version": version.name,
            "version_label": version.version_label,
            "body_text": body_text,
        },
    )
    return version


def revert(document: str, target_version: str, justification: str, *, approved_by: str | None = None):
    """Revert through Core: a new version is written; nothing is rewritten."""
    doc = frappe.get_doc(DOCTYPE, document)
    doc.check_permission("write")
    log = versioning.revert_to_version(
        DOCTYPE, document, target_version, justification, approved_by=approved_by
    )
    resulting = frappe.db.get_value("Version Revert Log", log.name, "resulting_version")
    label = frappe.db.get_value("Document Version", resulting, "version_label")
    frappe.db.set_value(DOCTYPE, document, {"current_version": resulting, "version_label": label})
    return log


def record_publication(
    document: str,
    *,
    audience_type: str = "All Employees",
    audiences: list[dict] | None = None,
    document_version: str | None = None,
    view_only: int = 0,
    allow_print: int = 1,
    allow_download: int = 1,
):
    """Record that a version was published, and notify who applicability reaches."""
    doc = frappe.get_doc(DOCTYPE, document)
    doc.check_permission("write")

    if not document_version:
        current = versioning.current_version(DOCTYPE, document)
        if not current:
            frappe.throw(_("{0} has no version to publish.").format(document))
        document_version = current.name

    record = frappe.get_doc(
        {
            "doctype": PUBLICATION_DOCTYPE,
            "document": document,
            "document_version": document_version,
            "published_on": now(),
            "published_by": frappe.session.user,
            "audience_type": audience_type,
            "audiences": audiences or [],
            "rendition_view_only": view_only,
            "rendition_print": allow_print,
            "rendition_download": allow_download,
        }
    ).insert(ignore_permissions=True)

    frappe.db.set_value("Document Version", document_version, "published", 1)

    dispatched = applicability.notify_affected(document, "published")
    frappe.db.set_value(
        PUBLICATION_DOCTYPE,
        record.name,
        {"notification_dispatched": 1 if dispatched else 0, "notified_count": len(dispatched)},
    )
    record.reload()
    return record


def withdraw(publication: str, on_date=None):
    doc = frappe.get_doc(PUBLICATION_DOCTYPE, publication)
    doc.check_permission("write")
    doc.withdrawn_on = on_date or frappe.utils.nowdate()
    doc.save()
    return doc


@frappe.whitelist()
def publication_history(document: str) -> list[dict]:
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    return frappe.get_all(
        PUBLICATION_DOCTYPE,
        filters={"document": document, "docstatus": ["<", 2]},
        fields=["name", "document_version", "published_on", "published_by", "audience_type",
                "notified_count", "withdrawn_on"],
        order_by="published_on asc",
    )
