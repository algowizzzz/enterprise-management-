"""Assignment of escalation matters by role or by group (E-5, E-8, E33-S6).

A matter used to reach a person only if someone named them. The escalation
matrix now also says *who works it*: the rule that fires may name a role, a
user group, or both, and the matter is placed in that queue. Everyone in the
queue sees the matter in their inbox until one of them takes ownership, which
makes them its response owner. Assignment is therefore configuration per type
and severity in exactly the way routing is — a rule's condition already tests
the escalation type and the severity — and it follows the matter when the
route changes: a matter flagged systemic, or raised by a breach, moves to the
queue of the rule that now fires.

**What "waiting" means.** A matter is waiting in its queue while it is open,
has a queue, and has no response owner *from that queue*. A response owner
named when the matter was raised who belongs to the queue has, in effect,
already taken it, so nobody else is asked. One who does not belong to it — a
matter re-routed to a higher owner on the systemic route, say — leaves the
matter waiting, so the new queue is told and one of its members can take it
over. The previous owner stays in the matter's change log.

**Who may take a matter.** Three things, all checked on the server: the
caller holds the role that carries the response (``Escalation Owner``) and may
write this matter — which is also where the sensitive-matter restriction bites
— and belongs to the queue. A refusal on standing is audited through Core, as
every refused modification is. Two people taking the same matter at once is
settled by a row lock: the second is told who has it.

Nothing here reads a status label: "open" is the matter's semantic flag.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

MATTER = "Escalation Matter"
ACTION = "take_ownership"

#: The event raised when a matter enters a queue. Its wording is a
#: ``Notification Template`` an administrator may edit.
QUEUED_EVENT = "escalation.matter.queued"


# ------------------------------------------------------------ the queue


def apply_assignment(matter, matched: dict) -> None:
    """Set the matter's queue from the rule that fired. Called by routing.

    A rule that names no queue clears it: the queue records the route the
    matter is on now, not one it was on once.
    """
    matter.assigned_role = matched.get("route_to_role") or None
    matter.assigned_group = matched.get("route_to_group") or None
    matter.assignment_rule = matched.get("rule_code") if (matter.assigned_role or matter.assigned_group) else None


def _enabled(users) -> list[str]:
    users = [u for u in users if u and u not in frappe.STANDARD_USERS]
    if not users:
        return []
    enabled = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
    seen, out = set(), []
    for user in users:
        if user in enabled and user not in seen:
            seen.add(user)
            out.append(user)
    return out


def role_holders(role: str | None) -> list[str]:
    if not role:
        return []
    return _enabled(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))


def group_members(group: str | None) -> list[str]:
    if not group:
        return []
    return _enabled(
        frappe.get_all("User Group Member", filters={"parent": group, "parenttype": "User Group"}, pluck="user")
    )


def queue_members(matter) -> list[str]:
    """Everyone in the matter's queue: holders of its role and members of its group."""
    return _enabled([*role_holders(matter.get("assigned_role")), *group_members(matter.get("assigned_group"))])


def in_queue(matter, user: str) -> bool:
    role, group = matter.get("assigned_role"), matter.get("assigned_group")
    if role and role in frappe.get_roles(user):
        return True
    if group and frappe.db.exists("User Group Member", {"parent": group, "parenttype": "User Group", "user": user}):
        return True
    return False


def has_queue(matter) -> bool:
    return bool(matter.get("assigned_role") or matter.get("assigned_group"))


def is_waiting(matter) -> bool:
    """Open, queued, and not yet owned by a member of the queue. See the module note."""
    if not (int(matter.get("is_open") or 0) and has_queue(matter)):
        return False
    owner = matter.get("response_owner")
    return not owner or not in_queue(matter, owner)


def queue_label(matter) -> str:
    parts = []
    if matter.get("assigned_role"):
        parts.append(_("role {0}").format(matter.get("assigned_role")))
    if matter.get("assigned_group"):
        parts.append(_("group {0}").format(matter.get("assigned_group")))
    return _(" or ").join(parts)


def can_take(matter, user: str | None = None) -> bool:
    """Whether the queue half of the check passes. The role and stage half is
    ``resolution.may_take`` and ``resolution.stage_actions``."""
    user = user or frappe.session.user
    return is_waiting(matter) and matter.get("response_owner") != user and in_queue(matter, user)


# ---------------------------------------------------------------- inbox


def waiting_for(user: str) -> list[dict]:
    """Matters waiting in a queue ``user`` belongs to, read with their permissions.

    Read through the permission engine, so a sensitive matter is listed only to
    someone cleared to see it — an inbox entry that opens onto a refusal is
    worse than none.
    """
    if not frappe.has_permission(MATTER, "read", user=user):
        return []
    roles = [r for r in frappe.get_roles(user) if r not in ("All", "Guest")]
    groups = frappe.get_all("User Group Member", filters={"user": user, "parenttype": "User Group"}, pluck="parent")
    rows = frappe.get_list(
        MATTER,
        filters={"is_open": 1},
        or_filters=[["assigned_role", "in", roles or [""]], ["assigned_group", "in", groups or [""]]],
        fields=["name", "escalation_title", "severity", "response_owner", "assigned_role", "assigned_group",
                "assignment_rule", "is_open", "opened_on", "systemic"],
        order_by="opened_on asc",
        limit_page_length=500,
        user=user,
    )
    return [row for row in rows if is_waiting(row) and row.response_owner != user]


# -------------------------------------------------------- notification


def on_update(matter) -> None:
    """Tell the queue when a matter enters it. Wired from the matter's controller.

    Only people who may read the matter are told: a notice naming a sensitive
    matter to someone not cleared for it would leak exactly what the
    restriction withholds.
    """
    if not (matter.has_value_changed("assigned_role") or matter.has_value_changed("assigned_group")):
        return
    if not is_waiting(matter):
        return
    notify_queue(matter)


def notify_queue(matter) -> list[str]:
    from consilium.consilium_core import notification

    recipients = [
        user for user in queue_members(matter)
        if user != matter.response_owner and frappe.has_permission(MATTER, "read", doc=matter, user=user)
    ]
    if not recipients:
        return []
    try:
        return notification.notify(
            QUEUED_EVENT,
            recipients,
            {"queue": queue_label(matter), "rule_code": matter.assignment_rule},
            MATTER,
            matter.name,
        )
    except Exception:
        # The routing is what matters; a notice that cannot be sent is logged
        # where an administrator will see it and the save goes on.
        frappe.log_error(title=_("Queue notice for {0} failed").format(matter.name),
                         message=frappe.get_traceback())
        return []


# ---------------------------------------------------------- the action


@frappe.whitelist(methods=["POST"])
def take_ownership(escalation_matter: str) -> dict:
    """Take a queued matter and become its response owner (E-5, E-8).

    Escalation Owner, in the matter's queue, while the matter is open. Returns
    the matter's workbench, as every portal action does.
    """
    from consilium.consilium_core import audit
    from consilium.escalation import resolution

    matter = resolution.load_matter(escalation_matter, "write")
    resolution.authorise(matter, ACTION)
    user = frappe.session.user
    if not in_queue(matter, user):
        audit.refuse(
            _("{0} is not in the queue escalation {1} is assigned to ({2}), so cannot take it.").format(
                user, matter.name, queue_label(matter) or _("no queue")),
            subject_doctype=MATTER,
            subject_name=matter.name,
            attempted_action="Other",
            control="escalation queue",
            context={"assigned_role": matter.assigned_role, "assigned_group": matter.assigned_group},
        )

    # Two members taking the same matter at once: the row lock makes the
    # second wait, and the fresh read then shows who has it.
    frappe.db.get_value(MATTER, matter.name, "name", for_update=True)
    matter = frappe.get_doc(MATTER, matter.name)
    if not is_waiting(matter):
        frappe.throw(
            _("Escalation {0} is no longer waiting for an owner; {1} owns the response.").format(
                matter.name, matter.response_owner or _("nobody")),
            title=_("Already Taken"),
        )
    matter.response_owner = user
    matter.ownership_taken_on = now()
    matter.save(ignore_permissions=True)
    return resolution.workbench(matter.name)
