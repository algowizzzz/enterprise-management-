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


def tagged_filters(tagged: dict | None) -> list[list]:
    """Child-table filters for the multi-valued dimensions, in the framework's
    four-part form ``[child DocType, column, "=", value]``. The framework joins
    the child table and checks the reader's permission on the parent, so the
    same filters work over the REST interface and here."""
    out = []
    for dimension, value in (tagged or {}).items():
        if dimension not in TAGGED_DIMENSIONS:
            frappe.throw(frappe._("{0} is not a tagged dimension of a forum.").format(dimension))
        if value:
            child, column = TAGGED_DIMENSIONS[dimension]
            out.append([child, column, "=", value])
    return out


def _qualified_order(order_by: str | None) -> str | None:
    """Prefix bare sort fields with the forum's table.

    A tagged filter joins a child table, and both tables carry `name` and
    `modified`; PostgreSQL refuses an ambiguous `ORDER BY modified`."""
    if not order_by:
        return order_by
    parts = []
    for clause in order_by.split(","):
        bits = clause.strip().split()
        if bits and "." not in bits[0] and bits[0].replace("_", "").isalnum():
            bits[0] = f"`tabGovernance Forum`.`{bits[0]}`"
        parts.append(" ".join(bits))
    return ", ".join(parts)


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
    conditions = [[key, *(value if isinstance(value, (list, tuple)) else ["=", value])]
                  for key, value in (filters or {}).items()]
    # Each tagged dimension narrows by a join on its own child table, in the
    # database. The earlier form wrote every dimension to the same `name` key,
    # so asking for two dimensions silently kept only the last.
    conditions.extend(tagged_filters(tagged))

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
        order_by=_qualified_order(order_by),
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


# ------------------------------------------------------ portal entry points
#
# The inventory screen, the forum page and the home page read these. Each is a
# read, and each goes through the framework's permitted query for the records
# it returns, so a viewer is shown only what they may read anyway.

#: How each tagged dimension is offered as a filter: the address parameter is
#: the dimension key, the values come from the taxonomy the child table links to.
TAGGED_FILTERS = (
    ("business_unit", "Business unit", "Organization Unit", "org_unit_name"),
    ("risk_type", "Risk type", "Risk Type", "risk_type_name"),
    ("legal_entity", "Legal entity", "Legal Entity", "legal_entity_name"),
    ("jurisdiction", "Jurisdiction", "Jurisdiction", "jurisdiction_name"),
    ("governance_responsibility", "Governance responsibility", "Governance Responsibility",
     "governance_responsibility_name"),
)


@frappe.whitelist(methods=["GET"])
def inventory_filters() -> list[dict]:
    """The multi-valued dimensions the inventory can be filtered by, with their values.

    Retired taxonomy values are included and marked: a filter is how someone
    finds the forums that still carry a value retired since (E3-S2 keeps retired
    values out of pickers for *new* records, not out of searches over old ones).
    A dimension whose taxonomy the viewer cannot read is returned without values.
    """
    out = []
    for key, label, taxonomy, title_field in TAGGED_FILTERS:
        child, column = TAGGED_DIMENSIONS[key]
        try:
            values = frappe.get_list(
                taxonomy, fields=["name", f"{title_field} as label", "is_active"],
                order_by=f"is_active desc, {title_field} asc", limit_page_length=0,
            )
        except frappe.PermissionError:
            values = []
        out.append({
            "key": key, "label": label, "taxonomy": taxonomy, "child_doctype": child, "column": column,
            "values": [{"value": v["name"], "label": v["label"] or v["name"], "retired": not v["is_active"]}
                       for v in values],
        })
    return out


@frappe.whitelist(methods=["GET"])
def tagged_forum_names(tagged=None) -> list[str]:
    """The forums carrying every tagged value asked for, that the viewer may read.

    The inventory screen narrows its table with ``["name", "in", ...]`` built
    from this, rather than sending the child-table join over the REST interface:
    the shared table component sorts and searches by bare field names, and with a
    joined child table those are ambiguous on PostgreSQL. The trade-off is an
    address that grows with the number of matching forums, which for a forum
    inventory (hundreds, not millions) stays well within request limits.
    """
    tagged = frappe.parse_json(tagged) if isinstance(tagged, str) else (tagged or {})
    tagged = {key: value for key, value in tagged.items() if value}
    if not tagged:
        return []
    return frappe.get_list(
        "Governance Forum", filters=tagged_filters(tagged), pluck="name",
        order_by="`tabGovernance Forum`.`name` asc", limit_page_length=0, distinct=True,
    )


@frappe.whitelist(methods=["GET"])
def forum_map(include_inactive: int = 0) -> dict:
    """The organisation-wide interconnectivity picture (O-2): every forum the viewer
    may read, its place in the hierarchy, and the recorded links between forums.

    A link is returned only when the viewer may read both ends, so the map never
    names a forum the viewer could not open.
    """
    filters = {} if frappe.utils.cint(include_inactive) else {"is_active": 1}
    nodes = frappe.get_list(
        "Governance Forum", filters=filters,
        fields=["name", "forum_name", "forum_type", "compliance_status", "parent_forum", "is_active",
                "requires_review"],
        order_by="forum_name asc", limit_page_length=0,
    )
    visible = {row["name"] for row in nodes}
    for row in nodes:
        if row["parent_forum"] not in visible:
            # The parent exists but is out of view (inactive, or not readable):
            # the forum is drawn as a root rather than hung from nothing.
            row["parent_forum"] = None
    links = []
    for row in frappe.get_all(
        "Forum Link",
        filters={"parenttype": "Governance Forum", "parent": ["in", list(visible) or [""]]},
        fields=["parent", "linked_forum", "relationship_type", "direction", "parentfield"],
        order_by="parent asc, idx asc",
    ):
        if row["linked_forum"] not in visible or row["linked_forum"] == row["parent"]:
            continue
        # Direction is from the holder's point of view: an upstream link points
        # from this forum to the one it answers to; downstream the other way.
        source, target = (row["parent"], row["linked_forum"])
        if row["parentfield"] == "downstream_links":
            source, target = target, source
        links.append({"source": source, "target": target, "relationship_type": row["relationship_type"]})
    return {"nodes": nodes, "links": links}


ESCALATION_FIELDS = [
    "name", "escalation_id", "escalation_title", "severity", "status", "escalation_date",
    "accountable_executive", "is_open", "requires_review", "threshold_breached", "sensitive",
]


@frappe.whitelist(methods=["GET"])
def forum_escalations(forum: str, limit: int = 200) -> dict:
    """Escalation matters whose pathway includes this forum (O-5).

    The pathway rows are read to find candidates; the matters themselves are
    read through the framework's permitted list, so the sensitive-escalation
    restriction (a permission-query condition and a controller permission)
    applies exactly as on every other read path. Matters the viewer may not see
    are neither listed nor counted — a count would itself disclose them.
    """
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not frappe.has_permission("Escalation Matter", "read"):
        return {"forum": forum, "readable": False, "matters": []}
    pathway = frappe.get_all(
        "Escalation Forum Link",
        filters={"governance_forum": forum, "parenttype": "Escalation Matter"},
        fields=["parent", "role_in_escalation", "notified_on", "decision_motion"],
    )
    if not pathway:
        return {"forum": forum, "readable": True, "matters": []}
    roles = {}
    for row in pathway:
        roles.setdefault(row["parent"], []).append(row)
    matters = frappe.get_list(
        "Escalation Matter",
        filters={"name": ["in", list(roles)]},
        fields=ESCALATION_FIELDS,
        order_by="escalation_date desc",
        limit_page_length=frappe.utils.cint(limit) or 200,
    )
    for matter in matters:
        rows = roles.get(matter["name"], [])
        matter["role_in_escalation"] = ", ".join(sorted({r["role_in_escalation"] for r in rows if r["role_in_escalation"]}))
        notified = [r["notified_on"] for r in rows if r["notified_on"]]
        matter["notified_on"] = str(max(notified)) if notified else None
        matter["decision_motion"] = next((r["decision_motion"] for r in rows if r["decision_motion"]), None)
        if matter.get("escalation_date"):
            matter["escalation_date"] = str(matter["escalation_date"])
    return {"forum": forum, "readable": True, "matters": matters}
