"""The glossary: versioned centrally, surfaced in context.

P-24 and E15-S3 ask for a centrally maintained, versioned, audited glossary.
Versioning is Core's — every publication of a term writes a ``Document Version``
through ``consilium_core.versioning``, so the definition in force on a past date
has exactly one answer and a revert is a new version rather than an edit.

E15-S4 asks for terms to be surfaced in context. The document editor is a
separate application, so this module does not annotate a document body. It
supplies the definitions that apply to a document — the terms linked to it, plus
every enterprise-scope term — and the viewer renders them. That keeps the
authority for the definitions here and the presentation where it belongs.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import nowdate

from consilium.consilium_core import versioning

TERM_DOCTYPE = "Glossary Term"
DOCUMENT_DOCTYPE = "Governing Document"


def publish(term: str, *, approved_by: str | None = None, change_summary: str | None = None):
    """Put a term in force, writing the version that records what it then said."""
    doc = frappe.get_doc(TERM_DOCTYPE, term)
    doc.check_permission("write")

    # A NULL scope document does not compare equal to an empty string in
    # PostgreSQL, so the two cases are expressed separately rather than coerced.
    filters = {
        "term": doc.term,
        "scope_level": doc.scope_level,
        "is_active": 1,
        "name": ["!=", doc.name],
        "docstatus": ["<", 2],
        "scope_document": doc.scope_document if doc.scope_document else ["is", "not set"],
    }
    clash = frappe.db.get_value(TERM_DOCTYPE, filters, "name")
    if clash:
        frappe.throw(
            _("{0} is already in force at this scope as {1}. Supersede it rather than defining it twice.")
            .format(doc.term, clash),
            title=_("Duplicate Term"),
        )

    doc.term_status = "Published"
    doc.approved_by = approved_by or frappe.session.user
    doc.approved_on = nowdate()
    doc.save()
    doc.reload()

    previous = versioning.current_version(TERM_DOCTYPE, doc.name)
    version = versioning.create_version(
        doc,
        change_summary=change_summary or _("Definition put in force."),
        origin="Authored",
        version_label=str(int(previous.version_number) + 1 if previous else 1),
        body_text=doc.definition,
        published=1,
    )
    frappe.db.set_value(
        TERM_DOCTYPE, doc.name, {"current_version": version.name, "version_label": version.version_label}
    )
    doc.reload()
    return doc


def supersede(term: str, new_definition: str, *, change_summary: str, approved_by: str | None = None):
    """Replace a definition with a new one, keeping the old wording recoverable."""
    doc = frappe.get_doc(TERM_DOCTYPE, term)
    doc.check_permission("write")
    doc.definition = new_definition
    doc.save()
    return publish(term, approved_by=approved_by, change_summary=change_summary)


def history(term: str) -> list[dict]:
    return versioning.version_history(TERM_DOCTYPE, term)


def revert(term: str, target_version: str, justification: str, *, approved_by: str | None = None):
    """Restore a previous definition — through Core, so it writes a new version."""
    frappe.get_doc(TERM_DOCTYPE, term).check_permission("write")
    log = versioning.revert_to_version(
        TERM_DOCTYPE, term, target_version, justification, approved_by=approved_by
    )
    resulting = frappe.db.get_value("Version Revert Log", log.name, "resulting_version")
    label = frappe.db.get_value("Document Version", resulting, "version_label")
    frappe.db.set_value(TERM_DOCTYPE, term, {"current_version": resulting, "version_label": label})
    return log


@frappe.whitelist()
def definitions_for(document: str) -> list[dict]:
    """The terms that apply to a document, for contextual display (E15-S4).

    Terms linked to the document explicitly, plus every enterprise-scope term in
    force. Only terms whose semantic flag says they are in force are returned; a
    proposed or deprecated definition is never shown as authoritative.
    """
    frappe.has_permission(DOCUMENT_DOCTYPE, "read", doc=document, throw=True)

    linked = frappe.get_all(
        "Glossary Term Link",
        filters={"parent": document, "parenttype": DOCUMENT_DOCTYPE},
        fields=["glossary_term", "context_note"],
    )
    notes = {row["glossary_term"]: row["context_note"] for row in linked}

    names = set(notes)
    names |= set(
        frappe.get_all(
            TERM_DOCTYPE,
            filters={"scope_level": "Enterprise", "is_active": 1, "docstatus": ["<", 2]},
            pluck="name",
        )
    )
    names |= set(
        frappe.get_all(
            TERM_DOCTYPE,
            filters={"scope_document": document, "is_active": 1, "docstatus": ["<", 2]},
            pluck="name",
        )
    )
    if not names:
        return []

    rows = frappe.get_all(
        TERM_DOCTYPE,
        filters={"name": ["in", sorted(names)], "is_active": 1, "docstatus": ["<", 2]},
        fields=["name", "term", "definition", "scope_level", "enforce_usage", "version_label"],
        order_by="term asc",
    )
    for row in rows:
        row["context_note"] = notes.get(row["name"])
        row["synonyms"] = frappe.get_all(
            "Glossary Synonym",
            filters={"parent": row["name"], "parenttype": TERM_DOCTYPE},
            pluck="synonym",
        )
    return rows
