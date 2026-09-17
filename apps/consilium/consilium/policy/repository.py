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
    filters: dict = {"docstatus": ["<", 2]}
    if document_type:
        filters["document_type"] = document_type
    if document_owner:
        filters["document_owner"] = document_owner
    if primary_risk_category:
        filters["primary_risk_category"] = primary_risk_category
    if owning_operating_group:
        filters["owning_operating_group"] = owning_operating_group
    if in_force is not None:
        filters["is_active"] = int(in_force)
    if requires_review is not None:
        filters["requires_review"] = int(requires_review)

    or_filters = None
    if text:
        pattern = f"%{text}%"
        or_filters = [
            ["document_name", "like", pattern],
            ["document_abstract", "like", pattern],
            ["body_text", "like", pattern],
            ["name", "like", pattern],
        ]

    return frappe.get_list(
        DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=LIST_FIELDS,
        order_by="modified desc",
        limit_page_length=int(limit),
    )
