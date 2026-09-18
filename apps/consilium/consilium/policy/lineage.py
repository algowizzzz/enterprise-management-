"""Document lineage — parent, child, addendum, supersession.

P-4 gives a document a parent and gives a parent children and addenda. Two
things follow that the requirement does not spell out:

1. **The graph must be navigable both ways.** A child names its parent in
   ``parent_document``; a parent names its children and addenda in the
   ``relationships`` table. Either direction alone would make one of the two
   questions a table scan, so both are read here and merged.

2. **A cycle has to be impossible.** A document that is its own ancestor makes
   every lineage query non-terminating and makes "who must approve this" have no
   answer. The check runs on validate, over both directions of the graph, and a
   cycle is refused and audited.

P-8's parent-owner approval is derived from this graph, never hand-added: if the
lineage edge between a document and its parent is marked
``owner_approval_required``, the parent's owner becomes a distinct approval step
on the child.
"""

from __future__ import annotations

import frappe
from frappe import _

from consilium.consilium_core import audit

DOCTYPE = "Governing Document"

#: Edge types that make the related document a descendant of this one.
DESCENDANT_TYPES = ("Child", "Addendum")


def _relationship_rows(document: str, types=DESCENDANT_TYPES) -> list[dict]:
    return frappe.get_all(
        "Document Relationship",
        filters={"parent": document, "parenttype": DOCTYPE, "relationship_type": ["in", list(types)]},
        fields=["related_document", "relationship_type", "owner_approval_required", "notes"],
    )


def children(document: str) -> list[dict]:
    """Every document one step below this one, from both directions of the graph."""
    seen: dict[str, dict] = {}
    for row in _relationship_rows(document):
        seen[row["related_document"]] = {
            "document": row["related_document"],
            "relationship_type": row["relationship_type"],
            "owner_approval_required": int(row["owner_approval_required"] or 0),
            "edge": "relationship",
        }
    for name in frappe.get_all(DOCTYPE, filters={"parent_document": document}, pluck="name"):
        seen.setdefault(
            name,
            {"document": name, "relationship_type": "Child", "owner_approval_required": 0, "edge": "parent_link"},
        )
    return sorted(seen.values(), key=lambda row: row["document"])


def parents(document: str) -> list[str]:
    """Every document one step above this one, from both directions of the graph."""
    found = []
    direct = frappe.db.get_value(DOCTYPE, document, "parent_document")
    if direct:
        found.append(direct)
    found.extend(
        frappe.get_all(
            "Document Relationship",
            filters={
                "parenttype": DOCTYPE,
                "related_document": document,
                "relationship_type": ["in", list(DESCENDANT_TYPES)],
            },
            pluck="parent",
        )
    )
    return sorted(set(found))


def ancestors(document: str, *, _seen: set[str] | None = None) -> list[str]:
    """Every document above this one. Terminates even on a graph that has a cycle."""
    seen = _seen if _seen is not None else set()
    out: list[str] = []
    for name in parents(document):
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        out.extend(ancestors(name, _seen=seen))
    return out


def descendants(document: str, *, _seen: set[str] | None = None) -> list[str]:
    seen = _seen if _seen is not None else set()
    out: list[str] = []
    for row in children(document):
        name = row["document"]
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
        out.extend(descendants(name, _seen=seen))
    return out


def _proposed_parents(doc) -> list[str]:
    found = []
    if doc.get("parent_document"):
        found.append(doc.parent_document)
    for row in frappe.get_all(
        "Document Relationship",
        filters={
            "parenttype": DOCTYPE,
            "related_document": doc.name,
            "relationship_type": ["in", list(DESCENDANT_TYPES)],
        },
        pluck="parent",
    ):
        found.append(row)
    return found


def validate_lineage(doc) -> None:
    """Refuse a lineage that would put a document in its own ancestry.

    Runs on validate, so a cycle never reaches the database. Both the upward
    link and the downward relationship rows are considered, because a cycle can
    be introduced from either end.
    """
    if doc.is_new():
        # A new record has no name yet and nothing can point at it, so only a
        # self-reference through the relationship table is possible.
        for row in doc.get("relationships") or []:
            if row.related_document and row.related_document == doc.get("name"):
                _refuse(doc, doc.name)
        return

    if doc.get("parent_document") == doc.name:
        _refuse(doc, doc.name)

    for row in doc.get("relationships") or []:
        if row.related_document == doc.name:
            _refuse(doc, doc.name)

    # Walking up from each proposed parent must never reach this document.
    for parent in _proposed_parents(doc):
        if parent == doc.name or doc.name in ancestors(parent):
            _refuse(doc, parent)

    # Walking down from each declared descendant must never reach it either.
    for row in doc.get("relationships") or []:
        if row.relationship_type in DESCENDANT_TYPES and row.related_document:
            if doc.name in descendants(row.related_document):
                _refuse(doc, row.related_document)


def _refuse(doc, other: str) -> None:
    audit.refuse(
        _(
            "Lineage is refused: {0} would become its own ancestor through {1}. "
            "A document cannot appear in its own parent chain."
        ).format(doc.name or doc.get("document_name"), other),
        subject_doctype=DOCTYPE,
        subject_name=doc.name or "",
        attempted_action="Other",
        control="lineage cycle",
        exc=frappe.ValidationError,
    )


def parent_owner_approvals(doc) -> list[dict]:
    """The parent owners whose approval this document's lineage requires (P-8).

    Derived from the graph, in both directions: a relationship row on the parent
    that names this document, or a relationship row on this document that names
    its parent, either marked ``owner_approval_required``.
    """
    required: dict[str, dict] = {}

    for row in frappe.get_all(
        "Document Relationship",
        filters={
            "parenttype": DOCTYPE,
            "related_document": doc.name,
            "relationship_type": ["in", list(DESCENDANT_TYPES)],
            "owner_approval_required": 1,
        },
        fields=["parent", "relationship_type"],
    ):
        required[row["parent"]] = {"document": row["parent"], "relationship_type": row["relationship_type"]}

    for row in doc.get("relationships") or []:
        if not row.owner_approval_required or not row.related_document:
            continue
        if row.related_document in parents(doc.name):
            required[row.related_document] = {
                "document": row.related_document,
                "relationship_type": row.relationship_type,
            }

    for name, entry in required.items():
        entry["owner"] = frappe.db.get_value(DOCTYPE, name, "document_owner")
    return [entry for entry in required.values() if entry.get("owner")]


def _readable(names: list[str], user: str | None = None) -> set[str]:
    """The documents in ``names`` this user may read, handling rules included.

    ``has_permission`` on each one, not a query: the Governing Document
    permission hook (``handling.has_permission``) is what decides whether a
    Confidential or Restricted document is visible to this person, and a
    query that bypassed it would be a second, weaker answer.
    """
    user = user or frappe.session.user
    return {name for name in set(names) if frappe.has_permission(DOCTYPE, "read", doc=name, user=user)}


@frappe.whitelist()
def lineage_of(document: str) -> dict:
    """The whole picture for one document, for the record view.

    The graph itself is walked in full — a restricted document in the middle of
    a family still connects its parent to its children — but only documents the
    viewer may read are *named*. A restricted child is not listed at all, not
    even as a count: that it exists, and what it is called, is itself what its
    handling protects.
    """
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    graph = {
        "parents": parents(document),
        "ancestors": ancestors(document),
        "children": children(document),
        "descendants": descendants(document),
    }
    names = graph["parents"] + graph["ancestors"] + graph["descendants"] + [row["document"] for row in graph["children"]]
    visible = _readable(names)
    return {
        "document": document,
        "parents": [name for name in graph["parents"] if name in visible],
        "ancestors": [name for name in graph["ancestors"] if name in visible],
        "children": [row for row in graph["children"] if row["document"] in visible],
        "descendants": [name for name in graph["descendants"] if name in visible],
    }
