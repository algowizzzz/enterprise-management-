"""Escalation routing — the matrix as data (E-4, E-7, E17-S1, E17-S2).

A matter's destination is not written in code. An approved `Escalation Matrix`
holds rules; each rule carries a condition over the matter's own attributes, the
severity it resolves to, the forums it routes to, the groups it notifies and the
service level it imposes. The first matching rule in priority order fires, and
the rule code is stored on the matter so a past routing decision stays
explicable — the same trace the classification engine keeps.

Forums themselves belong to the Governance module. This module only links to
them, and reads their escalation protocol and threshold defensively, because a
site may have the Escalation module installed before the Governance one.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate, now, nowdate

FORUM_DOCTYPE = "Governance Forum"

#: Matter fields a rule condition may test. Each is a plain attribute of the
#: matter: nothing here reads a workflow state.
CONDITION_FIELDS = (
    "escalation_type",
    "tier_1_risk_type",
    "tier_2_risk_type",
    "organizational_level",
    "material_entity_impact",
    "risk_appetite_breach",
    "systemic",
    "severity",
)

SEVERITY_ORDER = ("Low", "Medium", "High")


def _loads(value, default=None):
    """Parse a JSON payload. A doubly-encoded string is parsed twice: a JSON
    field that has been through a form round-trip often arrives that way."""
    if not value:
        return default if default is not None else {}
    for _ in range(2):
        if isinstance(value, dict | list):
            return value
        value = json.loads(value)
    return value


def active_matrices(as_of: str | None = None) -> list[str]:
    as_of = as_of or nowdate()
    names = []
    for row in frappe.get_all(
        "Escalation Matrix",
        filters={"is_active": 1},
        fields=["name", "effective_from", "effective_to"],
        order_by="effective_from desc",
    ):
        if row.effective_from and getdate(row.effective_from) > getdate(as_of):
            continue
        if row.effective_to and getdate(row.effective_to) < getdate(as_of):
            continue
        names.append(row.name)
    return names


def matrix_in_scope(matrix, matter) -> bool:
    """Scope is empty-means-any, on both axes."""
    risk_types = {row.risk_type for row in matrix.scope_risk_types}
    if risk_types and not ({matter.get("tier_1_risk_type"), matter.get("tier_2_risk_type")} & risk_types):
        return False
    legal_entities = {row.legal_entity for row in matrix.scope_legal_entities}
    if legal_entities:
        impacted = {
            row.entity_value
            for row in matter.get("impacted_entities") or []
            if row.entity_doctype == "Legal Entity"
        }
        if not (impacted & legal_entities):
            return False
    return True


def condition_matches(condition, matter) -> bool:
    condition = _loads(condition)
    for key, expected in condition.items():
        if key not in CONDITION_FIELDS:
            frappe.throw(
                _("{0} is not a routable attribute. Routable attributes are: {1}.").format(
                    key, ", ".join(CONDITION_FIELDS)
                ),
                title=_("Unroutable Condition"),
            )
        actual = matter.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif isinstance(expected, bool):
            if bool(int(actual or 0)) is not expected:
                return False
        elif str(actual or "") != str(expected):
            return False
    return True


def match_rule(matter, as_of: str | None = None) -> dict | None:
    """The first rule that matches, in priority order, across every live matrix."""
    for matrix_name in active_matrices(as_of):
        matrix = frappe.get_cached_doc("Escalation Matrix", matrix_name)
        if not matrix_in_scope(matrix, matter):
            continue
        for rule in sorted(matrix.rules, key=lambda r: (r.priority or 0, r.idx)):
            if not rule.is_active:
                continue
            if not condition_matches(rule.condition, matter):
                continue
            return {
                "matrix": matrix.name,
                "rule_code": rule.rule_code,
                "severity": rule.resulting_severity,
                "sla_definition": rule.sla_definition,
                "route_to_role": rule.route_to_role,
                "route_to_group": rule.get("route_to_group"),
                "forums": [
                    {"governance_forum": route.governance_forum, "role_in_escalation": route.role_in_escalation}
                    for route in matrix.routes
                    if route.rule_code == rule.rule_code
                ],
                "notify_groups": [
                    row.user_group for row in matrix.rule_notifications if row.rule_code == rule.rule_code
                ],
            }
    return None


def forum_protocol(forum: str) -> dict:
    """The forum's escalation protocol and threshold, shown to the user (E17-S1).

    Read through the metadata rather than by attribute, so that this module
    installs and runs before the Governance module defines the forum's fields.
    """
    empty = {"escalation_protocol": None, "escalation_threshold": None, "is_active": None}
    if not forum or not frappe.db.exists("DocType", FORUM_DOCTYPE):
        return empty
    meta = frappe.get_meta(FORUM_DOCTYPE)
    wanted = [f for f in ("escalation_protocol", "escalation_threshold", "is_active") if meta.has_field(f)]
    if not wanted:
        return empty
    values = frappe.db.get_value(FORUM_DOCTYPE, forum, wanted, as_dict=True) or {}
    return {**empty, **values}


def forum_is_selectable(forum: str) -> bool:
    """Only an active forum may be chosen as a pathway (E17-S1)."""
    protocol = forum_protocol(forum)
    return protocol["is_active"] is None or bool(protocol["is_active"])


@frappe.whitelist()
def propose_pathway(escalation_matter: str | None = None, matter: dict | None = None) -> dict:
    """Propose severity and destination for a matter — saved or still on screen."""
    if escalation_matter:
        frappe.has_permission("Escalation Matter", "read", doc=escalation_matter, throw=True)
        subject = frappe.get_doc("Escalation Matter", escalation_matter)
    else:
        subject = frappe.get_doc({"doctype": "Escalation Matter", **(_loads(matter) or {})})

    matched = match_rule(subject)
    if not matched:
        return {"matched": False, "forums": [], "severity": subject.get("severity")}

    forums = []
    for entry in matched["forums"]:
        forums.append({**entry, **forum_protocol(entry["governance_forum"])})
    return {"matched": True, **matched, "forums": forums}


def apply_routing(matter) -> None:
    """Set the matter's severity, matrix trace, service level and pathway.

    Severity is taken from the matrix unless a person has overridden it; the
    proposed destinations are added to the pathway, and destinations a person
    added are left alone.
    """
    matched = match_rule(matter)
    if not matched:
        return

    matter.escalation_matrix = matched["matrix"]
    matter.matched_matrix_rule = matched["rule_code"]
    if matter.severity_source != "Manual Override" and matched["severity"]:
        matter.severity = highest(matter.severity, matched["severity"]) if matter.auto_escalated else matched["severity"]
    if matched["sla_definition"]:
        matter.sla_definition = matched["sla_definition"]

    add_destinations(matter, matched["forums"], rule_code=matched["rule_code"])

    # The queue the rule names (E-5, E-8). Assignment is part of the route, so
    # a matter re-routed — flagged systemic, or raised by a breach — moves to
    # the new rule's queue with its forums.
    from consilium.escalation import assignment

    assignment.apply_assignment(matter, matched)


def add_destinations(matter, forums: list[dict], rule_code: str | None = None) -> list[str]:
    """Append proposed forums to the pathway, without duplicating one already there."""
    present = {row.governance_forum for row in matter.get("governance_forums") or []}
    added = []
    for entry in forums:
        forum = entry.get("governance_forum")
        if not forum or forum in present:
            continue
        protocol = forum_protocol(forum)
        matter.append(
            "governance_forums",
            {
                "governance_forum": forum,
                "role_in_escalation": entry.get("role_in_escalation") or "Decision",
                "escalation_protocol": protocol["escalation_protocol"],
                "escalation_threshold": protocol["escalation_threshold"],
                "proposed_by_rule": rule_code,
            },
        )
        present.add(forum)
        added.append(forum)
    return added


def validate_pathway(matter) -> None:
    """Every forum on the pathway must exist and be active (E17-S1)."""
    seen = set()
    for row in matter.get("governance_forums") or []:
        if row.governance_forum in seen:
            frappe.throw(
                _("Forum {0} appears twice on the pathway.").format(row.governance_forum),
                title=_("Duplicate Destination"),
            )
        seen.add(row.governance_forum)
        if not forum_is_selectable(row.governance_forum):
            frappe.throw(
                _("Forum {0} is not active and cannot be an escalation destination.").format(
                    row.governance_forum
                ),
                title=_("Inactive Forum"),
            )
        protocol = forum_protocol(row.governance_forum)
        row.escalation_protocol = protocol["escalation_protocol"]
        row.escalation_threshold = protocol["escalation_threshold"]


def highest(*severities) -> str | None:
    """The most severe of the values given. A breach-raised severity is never
    lowered again by a later pass of the matrix."""
    known = [s for s in severities if s in SEVERITY_ORDER]
    if not known:
        return next((s for s in severities if s), None)
    return max(known, key=SEVERITY_ORDER.index)


def raised_severity(severity: str | None) -> str | None:
    """The next severity up, or the same one at the top of the scale."""
    if severity not in SEVERITY_ORDER:
        return severity
    index = SEVERITY_ORDER.index(severity)
    return SEVERITY_ORDER[min(index + 1, len(SEVERITY_ORDER) - 1)]


# ------------------------------------------------ pathway participants (E-7)

#: Seat-role flags that make a seat holder someone a matter on the forum's
#: pathway must reach: the chair, the secretary, and every seat that attests for
#: the forum. The flags are the seat role's configuration, read by name of flag.
PARTICIPANT_FLAGS = ("is_chair_role", "is_secretary_role", "can_attest")


def forum_participants(forum: str, on_date=None) -> list[dict]:
    """The people holding the forum's officer and attesting seats on a date.

    Membership is the Governance module's record and the only authority on who
    sits where, so it is asked — as at the date — rather than the officer fields
    on the forum, which are a denormalised copy of it. A standing delegate in
    place on the date is included beside the seat holder: a delegate exists
    precisely so the seat is reachable while its holder is not.

    Returns ``[{"user", "forum", "seat_role", "capacity"}]``, one entry per
    person per forum. Empty when the Governance module is not installed.
    """
    if not forum or not frappe.db.exists("DocType", "Forum Membership"):
        return []
    try:
        from consilium.governance import membership
    except ImportError:
        return []

    on_date = on_date or nowdate()
    found: dict[str, dict] = {}
    for seat in membership.members_as_at(forum, on_date):
        if not seat.get("member"):
            continue
        role = membership.role_defaults(seat.get("forum_role")) or {}
        capacities = [flag for flag in PARTICIPANT_FLAGS if role.get(flag)]
        if not capacities:
            continue
        label = frappe.db.get_value("Governance Forum Role", seat.get("forum_role"),
                                    "governance_forum_role_name") or seat.get("forum_role")
        found.setdefault(seat["member"], {
            "user": seat["member"], "forum": forum, "seat_role": seat.get("forum_role"),
            "seat_role_name": label, "capacity": "holder",
        })
        if membership.delegate_active_on(seat, on_date) and seat.get("delegate"):
            found.setdefault(seat["delegate"], {
                "user": seat["delegate"], "forum": forum, "seat_role": seat.get("forum_role"),
                "seat_role_name": label, "capacity": "delegate",
            })
    return list(found.values())


def pathway_participants(matter, on_date=None) -> dict[str, list[dict]]:
    """``{forum: participants}`` for every forum on the matter's pathway."""
    return {
        row.governance_forum: forum_participants(row.governance_forum, on_date)
        for row in matter.get("governance_forums") or []
        if row.governance_forum
    }


def stamp_notified(matter, forums) -> None:
    """Record on each pathway row that its forum's participants were told.

    Written straight to the row: the matter is not being edited, and a save
    here would re-run routing and the template on a record nobody changed.
    """
    stamp = now()
    for row in matter.get("governance_forums") or []:
        if row.governance_forum in forums and row.name:
            frappe.db.set_value("Escalation Forum Link", row.name, "notified_on", stamp, update_modified=False)
            row.notified_on = stamp


# ----------------------------------------------- the pathway, from the portal

#: The roles that may change a matter's pathway, beyond the superuser.
PATHWAY_ROLES = ("Escalation Owner",)


@frappe.whitelist(methods=["POST"])
def set_pathway(escalation_matter: str, forums) -> dict:
    """Replace the forums on a matter's pathway (E-7, E17-S1). Escalation Owner.

    ``forums`` is ``[{"governance_forum", "role_in_escalation"}]``. A row kept
    from the present pathway keeps what it already carries (the rule that
    proposed it, when its forum was notified, the motion that decided it).

    A forum the matrix routes the matter to cannot be taken off: routing adds it
    back on every save while its rule applies, so removing it would look as if
    it had worked and then quietly not have. The request is refused instead, and
    the role can still be changed.
    """
    from consilium.escalation import resolution

    matter = resolution.load_matter(escalation_matter, "write")
    resolution.authorise(matter, "change_pathway")
    wanted = _loads(forums, default=[])
    if not isinstance(wanted, list):
        frappe.throw(_("The pathway is a list of forums."), title=_("Invalid Pathway"))

    existing = {row.governance_forum: row for row in matter.get("governance_forums") or []}
    proposed = {entry["governance_forum"] for entry in (match_rule(matter) or {}).get("forums", [])}
    requested = [entry.get("governance_forum") for entry in wanted if entry.get("governance_forum")]
    removed = [forum for forum in existing if forum not in requested]
    locked = [forum for forum in removed if forum in proposed]
    if locked:
        frappe.throw(
            _("{0} cannot be taken off the pathway: matrix rule {1} routes this matter there. "
              "Change its role instead.").format(", ".join(locked), matter.matched_matrix_rule or ""),
            title=_("Routed By The Matrix"),
        )

    role_field = frappe.get_meta("Escalation Forum Link").get_field("role_in_escalation")
    roles = [o for o in (role_field.options or "").split("\n") if o]
    rows = []
    for entry in wanted:
        forum = entry.get("governance_forum")
        if not forum:
            continue
        if not frappe.db.exists(FORUM_DOCTYPE, forum):
            frappe.throw(_("Forum {0} does not exist.").format(forum), title=_("Unknown Forum"))
        role = entry.get("role_in_escalation") or role_field.default
        if role not in roles:
            frappe.throw(_("{0} is not a role a forum can play on a pathway.").format(role),
                         title=_("Unknown Role"))
        kept = existing.get(forum)
        row = kept.as_dict() if kept else {}
        row = {k: v for k, v in row.items() if k in ("proposed_by_rule", "notified_on", "decision_motion")}
        rows.append({**row, "governance_forum": forum, "role_in_escalation": role})

    matter.set("governance_forums", [])
    for row in rows:
        matter.append("governance_forums", row)
    matter.save(ignore_permissions=True)
    return resolution.workbench(matter.name)


def selectable_forums() -> list[dict]:
    """Active forums a person may put on a pathway, as ``{name, forum_name}``.

    The forum register belongs to the Governance module and is readable by its
    roles; an escalation owner often holds none of them and still has to name
    where a matter goes — the pathway is a link to the forum, not a view of it.
    So a reader of the register gets it through the permission engine, and
    anyone else gets only the names of active forums that are not marked
    confidential: enough to choose a destination, nothing about the forum.
    """
    if not frappe.db.exists("DocType", FORUM_DOCTYPE):
        return []
    if frappe.has_permission(FORUM_DOCTYPE, "read"):
        return frappe.get_list(FORUM_DOCTYPE, filters={"is_active": 1}, fields=["name", "forum_name"],
                               order_by="forum_name asc", limit_page_length=0)
    filters = {"is_active": 1}
    if frappe.get_meta(FORUM_DOCTYPE).has_field("confidential"):
        filters["confidential"] = 0
    return frappe.get_all(FORUM_DOCTYPE, filters=filters, fields=["name", "forum_name"], order_by="forum_name asc")
