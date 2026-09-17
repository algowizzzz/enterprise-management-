"""Restricted handling of sensitive escalations (E-16).

A sensitive matter is invisible to a user without the
`Sensitive Escalation Access` role **on every read path**: the list view, search,
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


def _conditions(doctype: str, user: str | None = None) -> str:
    if may_see_sensitive(user):
        return ""
    return f"(`tab{doctype}`.`sensitive` = 0 or `tab{doctype}`.`sensitive` is null)"


def matter_conditions(user: str | None = None) -> str:
    return _conditions("Escalation Matter", user)


def action_plan_conditions(user: str | None = None) -> str:
    return _conditions("Action Plan", user)


def risk_acceptance_conditions(user: str | None = None) -> str:
    return _conditions("Risk Acceptance", user)


def closure_conditions(user: str | None = None) -> str:
    return _conditions("Escalation Closure", user)


def has_permission(doc, ptype=None, user=None, debug=False):
    """Deny every access to a sensitive record for a user without the right.

    Returns ``None`` when it has nothing to say, which is how a controller hook
    declines to intervene: it may deny, never grant.
    """
    if doc.doctype not in RESTRICTED_DOCTYPES:
        return None
    if not doc.get("sensitive"):
        return None
    return True if may_see_sensitive(user) else False


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
