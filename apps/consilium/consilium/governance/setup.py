"""Configuration the Governance module needs in place before it can work.

Three things: the semantic state-flag rows for the module's workflow-bearing
records, the watched-field set that sends a forum back for compliance review,
and a default formation approval route.

All three are **data**. None of them is a constant in code: an administrator
edits the watched-field list, adds an approval step or renames a state without a
deployment. They are seeded here only so that a fresh site is usable.

**Why this is not wired into ``after_install``.** ``hooks.py`` is shared with
the other modules and is not this module's to edit. Until Core's install path
calls :func:`ensure_configuration`, it is invoked lazily — the governance
controllers call it, it is a cache hit after the first call, and it repairs
itself if the rows are removed. The Core change requested is one line in
``consilium/consilium_core/setup/install.py``.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import state_flags
from consilium.governance.state_flag_seed import FLAG_COLUMNS, GOVERNANCE_STATE_FLAGS

#: The fields whose modification sends a forum back for compliance review.
#: A guessed default (07-assumptions-and-gaps.md B-2), editable on day one.
#:
#: Table-valued fields — risk types, business units — are deliberately absent.
#: Core's comparison is ``before != after`` over the field value, and a child
#: table comes back as a list of documents that never compares equal, so a
#: watched table field would fire on every save. Adding them needs a Core
#: change: compare child tables by their link values.
FORUM_WATCHED_FIELDS = [
    ("forum_type", "Forum Type"),
    ("description", "Mandate"),
    ("committee_chair", "Committee Chair"),
    ("primary_risk_category", "Primary Risk Category"),
    ("parent_forum", "Parent Forum"),
    ("regulatory_required", "Regulatory Required"),
    ("owning_operating_group", "Owning Operating Group"),
]

#: The state a forum returns to when a watched field changes. Configuration:
#: written into the watched-field set, read back from it, never compared.
FORUM_REVIEW_STATE = "Pending"

DEFAULT_ROUTE_TITLE = "Standard Formation Approval"

#: step title, sequence, mode, required role, field on the request naming the assignee
DEFAULT_ROUTE_STEPS = [
    ("Risk Governance Office Evaluation", 1, "Sequential", "Risk Governance Office", None),
    ("Delegating Authority Approval", 2, "Sequential", None, "delegating_authority"),
    ("Sponsor Endorsement", 2, "Parallel", None, "forum_sponsor"),
]

#: G-8: the approval path may differ by materiality of change and by forum
#: type. These are the shipped examples of each; like the default they are
#: data, and an administrator edits, deactivates or adds to them on the desk.
#: ``formation.resolve_route`` picks the most specific active route that fits,
#: so a request these do not fit still follows the standard route.
#:
#: (title, request type, forum type code or None, materiality, description, steps)
#: where steps are as ``DEFAULT_ROUTE_STEPS``.
ROUTED_PATHS = [
    (
        "Minor Change Approval", "Modify", None, "Minor",
        "Shipped default. A minor change to an existing forum: the governance office evaluates and the "
        "sponsor endorses; the delegating authority is not asked again.",
        [
            ("Risk Governance Office Evaluation", 1, "Sequential", "Risk Governance Office", None),
            ("Sponsor Endorsement", 2, "Sequential", None, "forum_sponsor"),
        ],
    ),
    (
        "Material Change Approval", "Modify", None, "Material",
        "Shipped default. A material change to an existing forum goes through the full path and is then "
        "signed off by the head of risk governance.",
        [
            ("Risk Governance Office Evaluation", 1, "Sequential", "Risk Governance Office", None),
            ("Delegating Authority Approval", 2, "Sequential", None, "delegating_authority"),
            ("Sponsor Endorsement", 2, "Parallel", None, "forum_sponsor"),
            ("Head of Risk Governance Sign-off", 3, "Sequential", "Head of Risk Governance", None),
        ],
    ),
    (
        "Board Committee Formation Approval", "Any", "BOARD_CTTE", "Any",
        "Shipped default. A board committee holds authority delegated by the board, so the head of risk "
        "governance signs off after the delegating authority and the sponsor.",
        [
            ("Risk Governance Office Evaluation", 1, "Sequential", "Risk Governance Office", None),
            ("Delegating Authority Approval", 2, "Sequential", None, "delegating_authority"),
            ("Sponsor Endorsement", 2, "Parallel", None, "forum_sponsor"),
            ("Head of Risk Governance Sign-off", 3, "Sequential", "Head of Risk Governance", None),
        ],
    ),
    (
        "Working Group Formation Approval", "Any", "WORKING_GRP", "Any",
        "Shipped default. A working group is time-limited and holds no delegated authority, so the "
        "governance office evaluates and the sponsor endorses.",
        [
            ("Risk Governance Office Evaluation", 1, "Sequential", "Risk Governance Office", None),
            ("Sponsor Endorsement", 2, "Sequential", None, "forum_sponsor"),
        ],
    ),
]

CACHE_KEY = "consilium_governance:configured"


def clear_cache(*args, **kwargs) -> None:
    frappe.cache().delete_value(CACHE_KEY)


def ensure_state_flags() -> int:
    """Load the module's flag rows. Rows an administrator has edited are left alone."""
    written = 0
    touched = set()
    for row in GOVERNANCE_STATE_FLAGS:
        doctype, state_field, state_value = row[0], row[1], row[2]
        if not frappe.db.exists("DocType", doctype):
            continue
        existing = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
            "name",
        )
        if existing:
            continue
        values = dict(zip(FLAG_COLUMNS, row[3:], strict=True))
        frappe.get_doc(
            {
                "doctype": "Workflow State Flag",
                "target_doctype": doctype,
                "state_field": state_field,
                "state_value": state_value,
                **values,
            }
        ).insert(ignore_permissions=True)
        written += 1
        touched.add(doctype)
    for doctype in touched:
        state_flags.clear_cache(doctype)
    return written


def ensure_watched_fields() -> bool:
    """The forum's watched-field set, if an administrator has not made one."""
    if frappe.db.exists("Watched Field Set", "Governance Forum"):
        return False
    field_set = frappe.get_doc(
        {
            "doctype": "Watched Field Set",
            "target_doctype": "Governance Forum",
            "is_active": 1,
            "on_change_action": "Reset Workflow State",
            "reset_to_state": FORUM_REVIEW_STATE,
        }
    )
    for fieldname, label in FORUM_WATCHED_FIELDS:
        field_set.append("fields", {"fieldname": fieldname, "label": label, "compare_mode": "Any Change"})
    field_set.insert(ignore_permissions=True)
    return True


def ensure_approval_route() -> bool:
    """A default formation approval route, if none is configured."""
    if frappe.db.exists("Formation Approval Route", DEFAULT_ROUTE_TITLE):
        return False
    route = frappe.get_doc(
        {
            "doctype": "Formation Approval Route",
            "route_title": DEFAULT_ROUTE_TITLE,
            "request_type": "Any",
            "is_active": 1,
            "description": "Shipped default. Steps are configuration: reorder, add or parallelise without a deployment.",
        }
    )
    for title, sequence, mode, role, field in DEFAULT_ROUTE_STEPS:
        route.append(
            "steps",
            {
                "step_title": title,
                "step_sequence": sequence,
                "mode": mode,
                "required_role": role if role and frappe.db.exists("Role", role) else None,
                "assign_to_field": field,
                "is_active": 1,
            },
        )
    route.insert(ignore_permissions=True)
    return True


def ensure_routed_paths() -> list[str]:
    """The G-8 example routes (``ROUTED_PATHS``), each only if missing.

    A route for a forum type is seeded only where that type exists, found by
    its code, so a site with its own forum-type vocabulary gets the materiality
    routes and nothing that names a type it does not have. A role step whose
    role does not exist is left without one rather than failing the seed.
    """
    if not frappe.db.table_exists("Formation Approval Route") or not frappe.get_meta(
        "Formation Approval Route"
    ).has_field("change_materiality"):
        return []
    created = []
    for title, request_type, type_code, materiality, description, steps in ROUTED_PATHS:
        if frappe.db.exists("Formation Approval Route", title):
            continue
        forum_type = None
        if type_code:
            forum_type = frappe.db.get_value("Governance Forum Type", {"forum_type_code": type_code}, "name")
            if not forum_type:
                continue
        route = frappe.get_doc(
            {
                "doctype": "Formation Approval Route",
                "route_title": title,
                "request_type": request_type,
                "forum_type": forum_type,
                "change_materiality": materiality,
                "is_active": 1,
                "description": description,
            }
        )
        for step_title, sequence, mode, role, field in steps:
            route.append(
                "steps",
                {
                    "step_title": step_title,
                    "step_sequence": sequence,
                    "mode": mode,
                    "required_role": role if role and frappe.db.exists("Role", role) else None,
                    "assign_to_field": field,
                    "is_active": 1,
                },
            )
        route.insert(ignore_permissions=True)
        created.append(route.name)
    return created


def ensure_configuration(force: bool = False) -> dict:
    """Idempotent. Cheap after the first call, and self-repairing if rows go."""
    if not force and frappe.cache().get_value(CACHE_KEY):
        return {"state_flags": 0, "watched_fields": False, "approval_route": False}
    result = {
        "state_flags": ensure_state_flags(),
        "watched_fields": ensure_watched_fields(),
        "approval_route": ensure_approval_route(),
        "routed_paths": ensure_routed_paths(),
    }
    frappe.cache().set_value(CACHE_KEY, 1)
    return result


def apply_governance_flags(doc) -> None:
    """``validate`` helper: make sure the map is loaded, then set the flags."""
    if not state_flags.get_flag_map(doc.doctype):
        ensure_configuration(force=True)
    state_flags.apply_state_flags(doc)
