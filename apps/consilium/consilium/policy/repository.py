"""Searching and filtering the repository (E11-S2).

Filtering is by type, owner, status, risk category and organisation; searching is
across the document's title and the extracted text of its current version. Both
go through the framework's query layer with ``ignore_permissions`` left off, so a
result the caller may not read never appears — which is the part of the
requirement that is easy to lose by writing raw SQL.

"Status" is expressed as the semantic flags, not as a state name: callers ask for
documents that are in force, or that need review, or that are still editable.
A state rename does not reach this module.
"""

from __future__ import annotations

import frappe

DOCTYPE = "Governing Document"

LIST_FIELDS = [
    "name", "document_name", "document_type", "lifecycle_phase", "document_owner",
    "primary_risk_category", "owning_operating_group", "version_label",
    "is_active", "is_editable", "requires_review", "effective_on", "next_review_on",
]


#: The most documents a content search hands to the inventory. A search that
#: matches more than this is too broad to read as a list anyway.
SEARCH_LIMIT = 500


def _like_pattern(text: str) -> str:
    """A LIKE pattern for the words as typed.

    A ``%`` or ``_`` in the text stays a wildcard. The framework escapes the
    value itself when it writes the filter into the query — doubling any
    backslash — so an escape added here would arrive as a literal backslash
    and match nothing. A wildcard can only widen a search the permission
    filter then narrows, so it is left alone rather than fought.
    """
    return f"%{text}%"


def _names_by_version_text(pattern: str) -> list[str]:
    """Documents whose *current version's* body matches.

    The record carries a copy of its body (``body_text``), but only an upload
    writes it: a revert makes an earlier text current without touching the
    copy, and a file upload has no text to copy. The version chain is the
    authority for the body, so the current version is searched too.

    This read is not permission-filtered — ``Document Version`` is readable only
    by oversight — and it does not need to be: it only nominates candidates,
    and ``search`` then lists them through ``get_list``, which applies the
    document's own permissions and handling rules. A name found here that the
    caller may not read is never returned.
    """
    return frappe.get_all(
        "Document Version",
        filters={"subject_doctype": DOCTYPE, "is_current": 1, "body_text": ["like", pattern]},
        pluck="subject_name",
        limit_page_length=SEARCH_LIMIT,
    )


@frappe.whitelist()
def search(
    text: str | None = None,
    document_type: str | None = None,
    document_owner: str | None = None,
    primary_risk_category: str | None = None,
    owning_operating_group: str | None = None,
    in_force: int | None = None,
    requires_review: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Filter the repository, and search it by title, reference, abstract and text (E11-S2).

    The text is matched, case-insensitively, against the title, the reference,
    the abstract (the document's summary), the body copied onto the record, and
    the body of its current version in the chain. Results come from
    ``frappe.get_list``, so the caller's permissions — the handling rules for
    confidential and restricted documents included — decide what is returned.
    """
    filters: dict = {"docstatus": ["<", 2]}
    if document_type:
        filters["document_type"] = document_type
    if document_owner:
        filters["document_owner"] = document_owner
    if primary_risk_category:
        filters["primary_risk_category"] = primary_risk_category
    if owning_operating_group:
        filters["owning_operating_group"] = owning_operating_group
    if in_force not in (None, ""):
        filters["is_active"] = int(in_force)
    if requires_review not in (None, ""):
        filters["requires_review"] = int(requires_review)

    or_filters = None
    text = (text or "").strip()
    if text:
        pattern = _like_pattern(text)
        or_filters = [
            ["document_name", "like", pattern],
            ["document_abstract", "like", pattern],
            ["body_text", "like", pattern],
            ["name", "like", pattern],
        ]
        by_version = _names_by_version_text(pattern)
        if by_version:
            or_filters.append(["name", "in", by_version])

    return frappe.get_list(
        DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=LIST_FIELDS,
        order_by="modified desc",
        limit_page_length=min(int(limit or 50), SEARCH_LIMIT),
    )


@frappe.whitelist(methods=["GET"])
def owners() -> list[dict]:
    """The owners of the documents the caller may read, for the inventory's owner filter.

    Counted through ``get_list``, so a person appears only as the owner of
    documents the caller could open, and the count is how many of those.
    """
    counts: dict[str, int] = {}
    for owner in frappe.get_list(DOCTYPE, filters={"docstatus": ["<", 2]}, pluck="document_owner",
                                 limit_page_length=0):
        if owner:
            counts[owner] = counts.get(owner, 0) + 1
    names = {
        row["name"]: row["full_name"]
        for row in frappe.get_all("User", filters={"name": ["in", list(counts) or [""]]},
                                  fields=["name", "full_name"])
    }
    return sorted(
        ({"user": user, "full_name": names.get(user) or user, "count": count} for user, count in counts.items()),
        key=lambda row: (row["full_name"] or "").lower(),
    )


@frappe.whitelist()
def version_history(document: str) -> list[dict]:
    """The version chain of one document, for its portal page.

    ``Document Version`` is readable directly only by administrators and audit,
    because a version row carries the full body and a snapshot of every field.
    The people who own and review a document still need to see that its chain
    exists and how it moved, so this returns the chain's *metadata* — number,
    label, origin, summary, whether published — to anyone who may read the
    document itself, and never the body or the snapshot.

    The read permission is checked on the document first; the chain is then read
    through Core's versioning engine rather than a second query of our own, so
    there is one definition of what a document's history is.
    """
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    from consilium.consilium_core import versioning

    chain = versioning.version_history(DOCTYPE, document)
    if not chain:
        return []
    extra = {
        row["name"]: row
        for row in frappe.get_all(
            "Document Version",
            filters={"name": ["in", [row["name"] for row in chain]]},
            fields=["name", "published", "change_classification", "creation", "owner"],
        )
    }
    out = []
    for row in chain:
        merged = dict(row)
        merged.update(extra.get(row["name"], {}))
        out.append(merged)
    return out
