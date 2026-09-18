"""Restricted handling of sensitive escalations (E-16).

A sensitive matter is invisible to a user without the
`Sensitive Escalation Access` role — unless the matter names them (its raiser,
the person who identified it, its accountable executive, its response owner, or
a member of the group queue it is assigned to) — **on every read path**: the list view, search,
reports, the REST API and any query the desk builds. That is why the restriction
is a permission-query condition and a controller permission rather than anything
in the interface — both run inside the query builder and inside
`frappe.has_permission`, which every API read goes through.

The restriction rides along to the records that hang off a matter: an action
plan, a risk acceptance or a closure of a sensitive matter carries the same flag,
copied on save, so that reading the child record is not a way around it.

**Shared-file change requested.** These functions must be registered in
`consilium/hooks.py`:

    permission_query_conditions = {
        "Escalation Matter": "consilium.escalation.sensitivity.matter_conditions",
        "Action Plan": "consilium.escalation.sensitivity.action_plan_conditions",
        "Risk Acceptance": "consilium.escalation.sensitivity.risk_acceptance_conditions",
        "Escalation Closure": "consilium.escalation.sensitivity.closure_conditions",
    }
    has_permission = {
        "Escalation Matter": "consilium.escalation.sensitivity.has_permission",
        "Action Plan": "consilium.escalation.sensitivity.has_permission",
        "Risk Acceptance": "consilium.escalation.sensitivity.has_permission",
        "Escalation Closure": "consilium.escalation.sensitivity.has_permission",
    }

Until that lands the module's tests install the same entries at runtime; see
`consilium/escalation/tests/utils.py`.
"""

from __future__ import annotations

import frappe

SENSITIVE_ROLE = "Sensitive Escalation Access"

#: Every DocType that carries the flag and therefore the restriction.
RESTRICTED_DOCTYPES = ("Escalation Matter", "Action Plan", "Risk Acceptance", "Escalation Closure")

HOOK_NAMES = {
    "Escalation Matter": "matter_conditions",
    "Action Plan": "action_plan_conditions",
    "Risk Acceptance": "risk_acceptance_conditions",
    "Escalation Closure": "closure_conditions",
}


def may_see_sensitive(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return SENSITIVE_ROLE in frappe.get_roles(user)


#: The people a matter names. Each of them sees the matter, sensitive or not:
#: restricted handling keeps a matter from people with no part in it, not from
#: the person who raised it, answers for it or is asked to work it. The creator
#: of the record is its raiser.
NAMED_FIELDS = ("owner", "identified_by", "accountable_executive", "response_owner")

#: The queue field whose members are named too (E-5, E-8): a group is a list of
#: named people. A *role* queue is not — a role can be held by anyone an
#: administrator chooses, so a sensitive matter in a role queue reaches only the
#: cleared holders of the role.
NAMED_GROUP_FIELD = "assigned_group"

MATTER = "Escalation Matter"


def _named_clause(table: str, user: str) -> str:
    """SQL: the row of ``table`` (an Escalation Matter) names ``user``."""
    quoted = frappe.db.escape(user)
    fields = " or ".join(f"`{table}`.`{field}` = {quoted}" for field in NAMED_FIELDS)
    group = (
        f"`{table}`.`{NAMED_GROUP_FIELD}` in (select `parent` from `tabUser Group Member` "
        f"where `parenttype` = 'User Group' and `user` = {quoted})"
    )
    return f"{fields} or {group}"


def _conditions(doctype: str, user: str | None = None) -> str:
    user = user or frappe.session.user
    if may_see_sensitive(user):
        return ""
    open_rows = f"`tab{doctype}`.`sensitive` = 0 or `tab{doctype}`.`sensitive` is null"
    if doctype == MATTER:
        return f"({open_rows} or {_named_clause('tabEscalation Matter', user)})"
    # A record hanging off a matter is visible to the people that matter names,
    # so its page shows them its plans, acceptances and closure.
    named = f"select `m`.`name` from `tabEscalation Matter` `m` where {_named_clause('m', user)}"
    return f"({open_rows} or `tab{doctype}`.`escalation_matter` in ({named}))"


def matter_conditions(user: str | None = None) -> str:
    return _conditions("Escalation Matter", user)


def action_plan_conditions(user: str | None = None) -> str:
    return _conditions("Action Plan", user)


def risk_acceptance_conditions(user: str | None = None) -> str:
    return _conditions("Risk Acceptance", user)


def closure_conditions(user: str | None = None) -> str:
    return _conditions("Escalation Closure", user)


def names_user(matter, user: str) -> bool:
    """Whether the matter (a document or a dict of its fields) names ``user``."""
    if any(matter.get(field) == user for field in NAMED_FIELDS):
        return True
    group = matter.get(NAMED_GROUP_FIELD)
    return bool(group and frappe.db.exists(
        "User Group Member", {"parent": group, "parenttype": "User Group", "user": user}))


def _matter_of(doc):
    if doc.doctype == MATTER:
        return doc
    if not doc.get("escalation_matter"):
        return None
    return frappe.db.get_value(MATTER, doc.escalation_matter, [*NAMED_FIELDS, NAMED_GROUP_FIELD], as_dict=True)


def has_permission(doc, ptype=None, user=None, debug=False):
    """Deny every access to a sensitive record for a user without the right,
    unless the matter names them (see ``NAMED_FIELDS``).

    Returns ``None`` when it has nothing to say, which is how a controller hook
    declines to intervene: it may deny, never grant — a named person still needs
    a role that carries the access asked for.
    """
    if doc.doctype not in RESTRICTED_DOCTYPES:
        return None
    if not doc.get("sensitive"):
        return None
    user = user or frappe.session.user
    if may_see_sensitive(user):
        return True
    matter = _matter_of(doc)
    return bool(matter and names_user(matter, user))


def inherited_sensitivity(escalation_matter: str | None) -> int:
    if not escalation_matter:
        return 0
    return int(frappe.db.get_value("Escalation Matter", escalation_matter, "sensitive") or 0)


def propagate(matter_name: str, sensitive: int) -> None:
    """Carry a change of the flag down to the records that hang off the matter."""
    for doctype in ("Action Plan", "Risk Acceptance", "Escalation Closure"):
        for name in frappe.get_all(
            doctype, filters={"escalation_matter": matter_name}, pluck="name", ignore_permissions=True
        ):
            frappe.db.set_value(doctype, name, "sensitive", sensitive, update_modified=False)
