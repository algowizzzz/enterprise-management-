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
    refuse_unapproved_wording(doc, body_text)

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


def refuse_unapproved_wording(doc, body_text: str | None) -> None:
    """P-24: an uploaded body is held to the approved glossary like any other edit.

    The glossary is enforced in the document's ``validate``, but a new version's
    text reaches the record through a column write that runs no ``validate`` —
    so an upload was the one way round the glossary. The text is checked here,
    before the version is written, with the same rule and the same audited
    refusal. Only the body is checked: the title and abstract are not changing.

    An uploaded *file* is not read. The platform does not extract text from the
    external editor's renditions, so a file's wording is checked only if the
    text is also supplied.
    """
    from consilium.consilium_core import audit
    from consilium.policy import glossary

    if not (body_text or "").strip():
        return
    proposed = frappe.get_doc(doc.as_dict())
    proposed.body_text = body_text
    findings = [row for row in glossary.check_document_text(proposed) if row["field"] == "body_text"]
    if not findings:
        return
    audit.refuse(
        _("The new version of {0} uses wording the approved glossary does not allow: {1}.").format(
            doc.document_name or doc.name,
            "; ".join(_("“{0}”, use “{1}”").format(item["found"], item["use"]) for item in findings),
        ),
        subject_doctype=DOCTYPE,
        subject_name=doc.name,
        attempted_action="Modify",
        control="glossary enforcement",
        context={"findings": findings, "route": "version upload"},
        exc=frappe.ValidationError,
    )


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


# --------------------------------------------------------------------------
# Portal entry points: versions (P-3, P-9) and publication (P-19)
#
# ``upload_version``, ``revert``, ``record_publication`` and ``withdraw`` had no
# caller from any screen. These wrap them with the portal's role and stage
# checks (``lifecycle.authorise``) and return the refreshed page payload.
# --------------------------------------------------------------------------


def _workflow_field(doc) -> str:
    from consilium.policy import lifecycle

    return lifecycle._workflow(doc.doctype).workflow_state_field


def version_rows(doc) -> list[dict]:
    """The chain's metadata, newest first, and whether each version can be reverted to.

    A version's snapshot carries the whole record, lifecycle phase included, and
    Core's revert writes the whole snapshot back. Reverting to a version captured
    in a different phase would therefore move the document through its lifecycle
    without the workflow — a route round the gates. Until Core leaves the
    workflow field out of a revert, only a version captured in the phase the
    document is in now is offered, and the rest say why not.
    """
    import json

    field = _workflow_field(doc)
    here = doc.get(field)
    rows = frappe.get_all(
        "Document Version",
        filters={"subject_doctype": DOCTYPE, "subject_name": doc.name},
        fields=["name", "version_number", "version_label", "origin", "is_current", "change_summary",
                "published", "change_classification", "creation", "owner", "body_file", "metadata_snapshot"],
        order_by="version_number desc",
    )
    for row in rows:
        snapshot = row.pop("metadata_snapshot", None)
        try:
            captured_in = (json.loads(snapshot) if isinstance(snapshot, str) else (snapshot or {})).get(field)
        except ValueError:
            captured_in = None
        row["has_file"] = 1 if row.pop("body_file", None) else 0
        row["captured_in"] = captured_in
        if int(row["is_current"] or 0):
            row["revertible"], row["not_revertible_because"] = False, _("This is the current version.")
        elif captured_in != here:
            row["revertible"] = False
            row["not_revertible_because"] = _(
                "Captured while the document was {0}; a revert would also move it back to {0}."
            ).format(captured_in or _("in an unrecorded phase"))
        else:
            row["revertible"], row["not_revertible_because"] = True, ""
    return rows


def publication_rows(doc) -> list[dict]:
    rows = frappe.get_all(
        PUBLICATION_DOCTYPE,
        filters={"document": doc.name, "docstatus": ["<", 2]},
        fields=["name", "document_version", "published_on", "published_by", "audience_type",
                "rendition_view_only", "rendition_print", "rendition_download", "notified_count",
                "notification_dispatched", "withdrawn_on"],
        order_by="published_on desc",
    )
    labels = {
        row["name"]: row["version_label"]
        for row in frappe.get_all(
            "Document Version",
            filters={"name": ["in", [r["document_version"] for r in rows] or [""]]},
            fields=["name", "version_label"],
        )
    }
    for row in rows:
        row["version_label"] = labels.get(row["document_version"])
        row["audiences"] = frappe.get_all(
            "Publication Audience",
            filters={"parent": row["name"], "parenttype": PUBLICATION_DOCTYPE},
            fields=["audience_kind", "audience_value"],
            order_by="idx asc",
        )
    return rows


def _load(document: str):
    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    return doc


def _fresh(doc) -> dict:
    from consilium.policy import lifecycle

    return lifecycle.portal_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["POST"])
def upload_new_version(
    document: str,
    change_summary: str,
    body_text: str | None = None,
    body_file: str | None = None,
    version_label: str | None = None,
) -> dict:
    """Take a new body into the chain, as uploaded text or an uploaded file.

    A file arrives through the framework's own upload (attached to this
    document); only a file attached to *this* document is accepted, so a
    version cannot be made to point at somebody else's attachment.
    """
    from consilium.policy import lifecycle, routing

    doc = _load(document)
    lifecycle.authorise(doc, "upload_version")
    body_text = (body_text or "").strip() or None
    body_file = (body_file or "").strip() or None
    if not (body_text or body_file):
        frappe.throw(_("A version needs a body: upload a file or enter the text."), title=_("Body Required"))
    if body_file and not frappe.db.exists(
        "File", {"file_url": body_file, "attached_to_doctype": DOCTYPE, "attached_to_name": doc.name}
    ):
        frappe.throw(
            _("{0} is not a file attached to {1}.").format(body_file, doc.name), title=_("Unknown File")
        )
    if not (change_summary or "").strip():
        frappe.throw(_("A version needs a change summary: it is the record of why the version exists."),
                     title=_("Summary Required"))
    upload_version(
        doc.name,
        change_summary=change_summary.strip(),
        body_file=body_file,
        body_text=body_text,
        version_label=(version_label or "").strip() or None,
        change_classification=routing.change_classification_of(doc),
    )
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def revert_version(document: str, target_version: str, justification: str) -> dict:
    """Revert to an earlier version, with the justification Core requires.

    Core refuses — and audits — a revert with no reason; this adds the stage
    check (content changes only while the document is editable) and the phase
    check described on ``version_rows``.
    """
    from consilium.policy import lifecycle

    doc = _load(document)
    lifecycle.authorise(doc, "revert_version")
    row = next((r for r in version_rows(doc) if r["name"] == target_version), None)
    if not row:
        frappe.throw(_("Version {0} does not belong to {1}.").format(target_version, doc.name),
                     title=_("Wrong Version"))
    if not row["revertible"]:
        frappe.throw(
            _("Version {0} cannot be reverted to. {1}").format(row["version_number"], row["not_revertible_because"]),
            title=_("Not Revertible"),
        )
    revert(doc.name, target_version, justification or "")
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def publish_record(
    document: str,
    audience_type: str,
    audiences=None,
    view_only=0,
    allow_print=0,
    allow_download=0,
) -> dict:
    """Record that the current version was published, to whom and in what renditions.

    Always the current version: the gates that put the document in force
    checked the approval chain of the current version, so that is the one
    whose publication has been earned. The affected parties are notified by
    ``record_publication`` from the document's applicability (P-21).
    """
    from consilium.policy import lifecycle

    doc = _load(document)
    lifecycle.authorise(doc, "record_publication")
    rows = frappe.parse_json(audiences) if isinstance(audiences, str) else (audiences or [])
    clean = [
        {"audience_kind": row.get("audience_kind"), "audience_value": row.get("audience_value")}
        for row in rows
        if row.get("audience_kind") and row.get("audience_value")
    ]
    view_only = frappe.utils.cint(view_only)
    record_publication(
        doc.name,
        audience_type=audience_type,
        audiences=clean,
        view_only=view_only,
        allow_print=0 if view_only else frappe.utils.cint(allow_print),
        allow_download=0 if view_only else frappe.utils.cint(allow_download),
    )
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_publication(publication: str) -> dict:
    from consilium.policy import lifecycle

    record = frappe.db.get_value(PUBLICATION_DOCTYPE, publication, ["document", "withdrawn_on"], as_dict=True)
    if not record:
        frappe.throw(_("Publication {0} does not exist.").format(publication))
    doc = _load(record.document)
    lifecycle.authorise(doc, "withdraw_publication")
    if record.withdrawn_on:
        frappe.throw(_("Publication {0} has already been withdrawn.").format(publication),
                     title=_("Already Withdrawn"))
    withdraw(publication)
    return _fresh(doc)


@frappe.whitelist(methods=["GET"])
def audience_preview(document: str) -> dict:
    """Who a publication would notify now, with names, shown before recording it."""
    from consilium.policy import lifecycle

    doc = _load(document)
    if not lifecycle.may_take(doc, "record_publication"):
        frappe.throw(_("Only the policy office previews a publication's audience."), frappe.PermissionError)
    preview = applicability.preview_audience(doc.name)
    return {**preview, "recipient_count": len(preview["recipients"])}
