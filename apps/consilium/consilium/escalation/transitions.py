"""Which moves an escalation matter may make, by matter type and severity (E-8).

Until this existed, the escalation workflow was the same for every matter: the
role holding the matter at its stage could move it from any open state to any
other, and close it from any state it was worked in. The requirement is that the
workflow is configurable *by matter type and severity* — a High-severity matter
may have to pass through second-line review before it can be closed, while a
Low one may not.

The configuration is a table of allowed moves, `Escalation Transition Rule`:
from-state, to-state, type, severity and the role that may make the move. A
blank column means "any". The framework's own Workflow was the alternative; it
was not used because a Workflow is one per DocType and would own the status
field, where the matter's states, stages and flags are already this module's
(and a Workflow keyed on type and severity needs one transition row per
combination, which is exactly the explosion a blank-means-any table avoids).

**Which rules apply to a matter.** Every active rule whose type and severity are
the matter's or blank matches. Only the most specific *set* of them applies:
rules naming both type and severity, else those naming the type, else those
naming the severity, else the rules naming neither. That is what lets an
administrator narrow the workflow for one type or severity without restating
it for every other: adding rules for High severity replaces, for High matters
only, the catch-all rule that everything else still follows. The trade-off is
that a narrower set must be complete — a state it gives no way out of is a state
a matter of that kind cannot leave from the portal — which is why rules are
deactivated rather than deleted and why the seed ships the stricter set
inactive.

**No rules at all means no restriction.** A site whose rules have not been
seeded, or where every rule is inactive, behaves as it did before this table
existed. The seeded catch-all reproduces that behaviour explicitly, so nothing
changes until an administrator narrows it.

Nothing here reads a status label as a condition: the states in a rule are
configuration compared with the matter's own value, and "open" and "at rest"
come from the semantic flags.
"""

from __future__ import annotations

import frappe
from frappe import _

RULE = "Escalation Transition Rule"
MATTER = "Escalation Matter"

RULE_FIELDS = ["name", "escalation_type", "severity", "from_status", "to_status", "allowed_role"]


def _specificity(rule: dict) -> int:
    """Type outranks severity: a rule for one kind of matter is a narrower statement
    than a rule for one severity across every kind."""
    return (2 if rule.get("escalation_type") else 0) + (1 if rule.get("severity") else 0)


def active_rules() -> list[dict]:
    if not frappe.db.table_exists(RULE):
        return []
    return frappe.get_all(RULE, filters={"is_active": 1}, fields=RULE_FIELDS, order_by="rule_code asc")


def applicable_rules(matter) -> list[dict]:
    """The rules that govern this matter: the most specific matching set, or none."""
    matching = [
        rule for rule in active_rules()
        if rule.escalation_type in (None, "", matter.get("escalation_type"))
        and rule.severity in (None, "", matter.get("severity"))
    ]
    if not matching:
        return []
    best = max(_specificity(rule) for rule in matching)
    return [rule for rule in matching if _specificity(rule) == best]


def _holds(role: str | None, user: str) -> bool:
    if not role:
        return True
    from consilium.escalation import resolution

    return resolution._holds((role,), user)


def rules_for_move(matter, from_status: str | None, to_status: str) -> list[dict]:
    """The applicable rules that allow ``from_status`` to ``to_status``."""
    return [
        rule for rule in applicable_rules(matter)
        if rule.from_status in (None, "", from_status) and rule.to_status in (None, "", to_status)
    ]


def is_configured(matter) -> bool:
    """Whether any rule governs this matter. Without one, every move is allowed."""
    return bool(applicable_rules(matter))


def permits(matter, to_status: str, user: str | None = None, *, from_status: str | None = None) -> bool:
    """Whether the configuration lets ``user`` move this matter to ``to_status``.

    Says nothing about the stage or the caller's standing on the matter: those
    are `resolution.authorise`'s, checked first on every entry point.
    """
    user = user or frappe.session.user
    rules = applicable_rules(matter)
    if not rules:
        return True
    current = from_status if from_status is not None else matter.get("status")
    return any(
        _holds(rule.allowed_role, user)
        for rule in rules
        if rule.from_status in (None, "", current) and rule.to_status in (None, "", to_status)
    )


def refusal_reason(matter, to_status: str, user: str | None = None) -> str:
    """Why a move is refused, in words a person can act on."""
    user = user or frappe.session.user
    allowing = rules_for_move(matter, matter.get("status"), to_status)
    if allowing:
        roles = sorted({rule.allowed_role for rule in allowing if rule.allowed_role})
        return _(
            "Escalation {0} may move from {1} to {2} only by someone holding: {3}."
        ).format(matter.name, matter.get("status"), to_status, ", ".join(roles))
    return _(
        "The workflow configured for {0} matters of {1} severity does not allow a move from {2} to {3}."
    ).format(matter.get("escalation_type") or _("any type"), matter.get("severity") or _("any"),
             matter.get("status"), to_status)


def describe(matter) -> list[dict]:
    """The applicable rules, for the matter's page and for an administrator asking why."""
    return [
        {"rule": rule.name, "from_status": rule.from_status or None, "to_status": rule.to_status or None,
         "allowed_role": rule.allowed_role or None}
        for rule in applicable_rules(matter)
    ]


def validate_rule(rule) -> None:
    """A rule names states the matter really has, and moves out of a state it can be worked in."""
    from consilium.consilium_core import state_flags
    from consilium.escalation import resolution

    options = resolution._options(MATTER, "status")
    for fieldname in ("from_status", "to_status"):
        value = rule.get(fieldname)
        if value and value not in options:
            frappe.throw(
                _("{0} is not a state an escalation matter has.").format(value), title=_("Unknown State")
            )
    if rule.from_status:
        flags = state_flags.flags_for(MATTER, "status", rule.from_status) or {}
        if not int(flags.get("is_open") or 0):
            frappe.throw(
                _("A matter at rest does not move; a rule can only start from a state a matter is worked in."),
                title=_("Not A Starting State"),
            )
    if rule.from_status and rule.to_status and rule.from_status == rule.to_status:
        frappe.throw(_("A move goes somewhere: the from and to states are the same."), title=_("Not A Move"))


def validate_status_change(matter) -> None:
    """A status change made by a person outside the portal follows the same rules.

    The desk form and the REST interface can set the status directly. Code paths
    (imports, the breach sweep, demo and test fixtures) save with
    ``ignore_permissions`` and are left alone: they are not a person choosing a
    move, and several of them set a state on a matter that is being loaded
    rather than worked.
    """
    if matter.is_new() or matter.flags.ignore_permissions:
        return
    before = matter.get_doc_before_save()
    if not before or before.status == matter.status:
        return
    if permits(matter, matter.status, from_status=before.status):
        return
    from consilium.consilium_core import audit

    probe = frappe._dict(matter.as_dict())
    probe.status = before.status
    audit.refuse(
        refusal_reason(probe, matter.status),
        subject_doctype=MATTER,
        subject_name=matter.name,
        attempted_action="Other",
        control="escalation transition rule",
        context={"from_status": before.status, "to_status": matter.status},
        exc=frappe.ValidationError,
    )
