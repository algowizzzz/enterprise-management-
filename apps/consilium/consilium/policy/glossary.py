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

import html as _html
import re as _re

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


# --------------------------------------------------------------- enforcement
#
# P-24: "enforce the use of official definitions by preventing users from
# creating or applying terms not in the approved glossary".
#
# What counts as an unapproved term. The glossary records what is approved (a
# term in force) and two kinds of wording that are not: a term's **synonyms**,
# and a **retired** term, one that is out of force and names the term that
# superseded it. A document may not use every English phrase that happens to be
# missing from the glossary, because that would refuse ordinary prose. So for
# every term that is in force, applies to the document and has ``enforce_usage``
# set:
#
# * a synonym used **instead of** the official term is refused. A synonym used
#   alongside it is accepted, which is the usual defined-term convention
#   ("Politically Exposed Person (PEP)", then "PEP");
# * the wording of a retired term that the enforced term superseded is refused
#   wherever it appears, because it is the old definition in the old words.
#
# A term applies to a document when it is enterprise-scope, or scoped to the
# document, to the document's parent (its family), or linked to it. "In force"
# and "retired" are read from the semantic flag ``is_active`` and from
# ``superseded_by``, never from the status label.
#
# The text checked is the document's name, abstract and body text: what a
# reader reads. Matching ignores case, needs whole words, and ignores markup.

ENFORCED_FIELDS = ("document_name", "document_abstract", "body_text")
_TAGS = _re.compile(r"<[^>]+>")


def _plain(text: str | None) -> str:
    return _re.sub(r"\s+", " ", _html.unescape(_TAGS.sub(" ", text or ""))).strip()


def _phrase(term: str) -> _re.Pattern:
    words = [_re.escape(word) for word in term.split()]
    return _re.compile(r"(?<!\w)" + r"\s+".join(words) + r"(?!\w)", _re.IGNORECASE)


def _applicable_term_names(document: str | None, parent: str | None, linked: list[str]) -> set[str]:
    names = set(linked)
    names |= set(frappe.get_all(TERM_DOCTYPE, filters={"scope_level": "Enterprise"}, pluck="name"))
    scoped_to = [value for value in (document, parent) if value]
    if scoped_to:
        names |= set(frappe.get_all(TERM_DOCTYPE, filters={"scope_document": ["in", scoped_to]}, pluck="name"))
    return names


def enforced_terms(document: str | None = None, *, parent: str | None = None,
                   linked: list[str] | None = None) -> list[dict]:
    """The enforced terms in force for a document, each with its forbidden wordings."""
    names = _applicable_term_names(document, parent, linked or [])
    if not names:
        return []
    terms = frappe.get_all(
        TERM_DOCTYPE,
        filters={"name": ["in", sorted(names)], "is_active": 1, "enforce_usage": 1, "docstatus": ["<", 2]},
        fields=["name", "term"],
        order_by="term asc",
    )
    for row in terms:
        row["synonyms"] = [
            value for value in frappe.get_all(
                "Glossary Synonym", filters={"parent": row["name"], "parenttype": TERM_DOCTYPE}, pluck="synonym"
            )
            if value and value.strip().lower() != row["term"].strip().lower()
        ]
        row["retired"] = [
            value for value in frappe.get_all(
                TERM_DOCTYPE, filters={"superseded_by": row["name"], "is_active": 0}, pluck="term"
            )
            if value and value.strip().lower() != row["term"].strip().lower()
        ]
    return terms


def unapproved_usage(text: str | None, terms: list[dict]) -> list[dict]:
    """Every unapproved wording found in ``text``, with the term to use instead."""
    plain = _plain(text)
    if not plain:
        return []
    findings = []
    for row in terms:
        official = _phrase(row["term"])
        uses_official = bool(official.search(plain))
        # Occurrences of the official term are blanked first, so a synonym that
        # is part of it ("Appetite" in "Risk Appetite") is not counted twice.
        remainder = official.sub(" ", plain)
        for synonym in row["synonyms"]:
            if uses_official:
                continue
            if _phrase(synonym).search(remainder):
                findings.append({"found": synonym, "use": row["term"], "term": row["name"], "kind": "synonym"})
        for retired in row["retired"]:
            if _phrase(retired).search(remainder):
                findings.append({"found": retired, "use": row["term"], "term": row["name"], "kind": "retired"})
    return findings


def check_document_text(doc) -> list[dict]:
    terms = enforced_terms(
        doc.name,
        parent=doc.get("parent_document"),
        linked=[row.glossary_term for row in (doc.get("glossary_terms") or []) if row.glossary_term],
    )
    if not terms:
        return []
    findings = []
    for field in ENFORCED_FIELDS:
        for finding in unapproved_usage(doc.get(field), terms):
            findings.append({**finding, "field": field})
    return findings


def enforce_on_document(doc) -> None:
    """Called from the Governing Document ``validate``.

    Only text that changed is checked, so a term enforced today does not refuse
    an unrelated edit to a document written before it. The wording must be put
    right the next time that text is edited.
    """
    from consilium.consilium_core import audit

    if frappe.flags.in_import or frappe.flags.in_migrate or frappe.flags.in_patch:
        return
    before = None if doc.is_new() else doc.get_doc_before_save()
    if before is not None and all(before.get(field) == doc.get(field) for field in ENFORCED_FIELDS):
        return
    findings = check_document_text(doc)
    if before is not None:
        unchanged = {field for field in ENFORCED_FIELDS if before.get(field) == doc.get(field)}
        findings = [finding for finding in findings if finding["field"] not in unchanged]
    if not findings:
        return
    labels = {df.fieldname: df.label for df in frappe.get_meta(DOCUMENT_DOCTYPE).fields}
    audit.refuse(
        _("{0} uses wording the approved glossary does not allow: {1}.").format(
            doc.document_name or doc.name,
            "; ".join(
                _("“{0}” in {1}, use “{2}”").format(
                    item["found"], labels.get(item["field"], item["field"]), item["use"])
                for item in findings
            ),
        ),
        subject_doctype=DOCUMENT_DOCTYPE,
        subject_name=doc.name or doc.document_name,
        attempted_action="Modify",
        control="glossary enforcement",
        context={"findings": findings},
        exc=frappe.ValidationError,
    )


@frappe.whitelist(methods=["GET"])
def in_context(document: str) -> dict:
    """Definitions for display beside a document, and where each one is used.

    ``GET /api/method/consilium.policy.glossary.in_context?document=GDOC-...``

    Returns ``definitions_for`` (which checks read permission on the document),
    each with ``used`` and ``occurrences`` counted in the current text, sorted
    so the terms the document actually uses come first. It also returns
    ``findings``, the unapproved wordings in the current text, so the page can
    show them. They are reported here and refused only when that text is next
    saved.
    """
    rows = definitions_for(document)
    doc = frappe.get_doc(DOCUMENT_DOCTYPE, document)
    text = " ".join(_plain(doc.get(field)) for field in ENFORCED_FIELDS)
    for row in rows:
        count = len(_phrase(row["term"]).findall(text))
        for synonym in row.get("synonyms") or []:
            count += len(_phrase(synonym).findall(_phrase(row["term"]).sub(" ", text)))
        row["occurrences"] = count
        row["used"] = count > 0
    rows.sort(key=lambda row: (not row["used"], (row.get("term") or "").lower()))
    return {"document": document, "terms": rows, "findings": check_document_text(doc)}
