"""Reading the inventory: search, filter, the hierarchy and the interconnectivity view.

The inventory is the thing the rest of the platform depends on, so reading it is
a first-class part of the module rather than something each screen invents.

Everything here goes through the framework's permitted query, which means the
permission engine filters the results — a role that cannot read a forum does not
see it in a search either. Free-text matching uses ``LIKE`` with a leading
wildcard, which is not indexable by a B-tree; 03-schema.md §7.4 records the
trigram index that makes it so, and it is deployment configuration rather than
schema.
"""

from __future__ import annotations

import frappe

LIST_FIELDS = [
    "name", "forum_name", "forum_type", "compliance_status", "primary_risk_category",
    "owning_operating_group", "committee_chair", "forum_owner", "is_active", "next_review_on",
]

#: Tagged dimension -> (child table, its link column).
TAGGED_DIMENSIONS = {
    "business_unit": ("Forum Business Unit", "business_unit"),
    "risk_type": ("Forum Risk Type", "risk_type"),
    "legal_entity": ("Forum Legal Entity", "legal_entity"),
    "jurisdiction": ("Forum Jurisdiction", "jurisdiction"),
    "governance_responsibility": ("Forum Governance Responsibility", "governance_responsibility"),
}


def _tagged_names(dimension: str, value: str) -> list[str]:
    child, column = TAGGED_DIMENSIONS[dimension]
    return frappe.get_all(
        child, filters={column: value, "parenttype": "Governance Forum"}, pluck="parent", distinct=True
    ) or [""]


def search(
    text: str | None = None,
    *,
    filters: dict | None = None,
    tagged: dict | None = None,
    limit: int = 20,
    start: int = 0,
    order_by: str = "modified desc",
    user: str | None = None,
) -> list[dict]:
    """Search and filter the inventory, permissions respected.

    ``filters`` takes any forum field. ``tagged`` takes any of the multi-valued
    dimensions — ``{"risk_type": "RT-1"}`` — and narrows to forums carrying it.
    """
    conditions = dict(filters or {})
    for dimension, value in (tagged or {}).items():
        conditions["name"] = ["in", _tagged_names(dimension, value)]

    or_filters = None
    if text:
        pattern = f"%{text}%"
        # Name is the forum's identifier; forum_name and description are the two
        # free-text fields a user searches by.
        or_filters = {"name": ["like", pattern], "forum_name": ["like", pattern],
                      "description": ["like", pattern]}

    return frappe.get_list(
        "Governance Forum",
        filters=conditions,
        or_filters=or_filters,
        fields=LIST_FIELDS,
        limit_page_length=limit,
        limit_start=start,
        order_by=order_by,
        user=user,
        ignore_permissions=False,
    )


def hierarchy(root: str | None = None) -> list[dict]:
    """The parent/child tree, one level at a time."""
    return frappe.get_all(
        "Governance Forum",
        filters={"parent_forum": root} if root else {"parent_forum": ["in", [""]]},
        fields=["name", "forum_name", "forum_type", "compliance_status"],
        order_by="forum_name",
    )


def interconnectivity(forum: str) -> dict:
    """Every relationship a forum has, in both directions.

    The reverse direction is a query over the child table rather than a stored
    mirror, so the two sides cannot disagree.
    """
    outbound = frappe.get_all(
        "Forum Link",
        filters={"parent": forum, "parenttype": "Governance Forum"},
        fields=["linked_forum", "direction", "relationship_type", "parentfield"],
    )
    inbound = frappe.get_all(
        "Forum Link",
        filters={"linked_forum": forum, "parenttype": "Governance Forum"},
        fields=["parent", "direction", "relationship_type", "parentfield"],
    )
    return {
        "forum": forum,
        "parent_forum": frappe.db.get_value("Governance Forum", forum, "parent_forum"),
        "children": [row["name"] for row in hierarchy(forum)],
        "outbound": outbound,
        "inbound": inbound,
    }


def stamp_attestation(task) -> str | None:
    """Denormalise the latest completed attestation onto the forum.

    Reads the task's semantic flags: a task that is still open has not attested
    anything, whatever its label says.
    """
    if isinstance(task, str):
        task = frappe.get_doc("Attestation Task", task)
    if task.subject_doctype != "Governance Forum" or task.is_open or not task.responded_on:
        return None
    frappe.db.set_value(
        "Governance Forum", task.subject_name, "last_attested_on",
        str(task.responded_on)[:10], update_modified=False,
    )
    return task.subject_name


def refresh_last_attested(campaign: str | None = None) -> list[str]:
    """Sweep: stamp every forum whose attestation has completed."""
    filters = {"subject_doctype": "Governance Forum", "is_open": 0}
    if campaign:
        filters["campaign"] = campaign
    stamped = []
    for name in frappe.get_all("Attestation Task", filters=filters, pluck="name"):
        forum = stamp_attestation(name)
        if forum:
            stamped.append(forum)
    return stamped


def unattested() -> list[dict]:
    """Active forums that have never completed an attestation."""
    # Written as SQL on purpose. Both of the framework's ways of asking "this date
    # is empty" — ``["in", [None, ""]]`` and ``["is", "not set"]`` — compile to a
    # comparison against the empty string, and PostgreSQL rejects that for a date
    # column. 03-schema.md §13 item 5 anticipated finding more of these.
    return frappe.db.sql(
        """SELECT "name", "forum_name", "last_attested_on", "forum_owner"
           FROM "tabGovernance Forum"
           WHERE "is_active" = 1 AND "last_attested_on" IS NULL
           ORDER BY "forum_name" """,
        as_dict=True,
    )
