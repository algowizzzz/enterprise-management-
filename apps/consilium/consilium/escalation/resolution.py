"""Resolution: service levels, closure and automatic escalation on breach.

Three things live here, and none of them reads a status label:

* **Closure (E-10, E17-S3).** A matter whose semantic flags say it is no longer
  open must carry an `Escalation Closure` with a recorded outcome, and the
  response template must be complete. A state that commits the matter to an
  external system of record must also carry the external reference that
  identifies it there.
* **Service levels (E17-S4).** Timing is Core's. A matter opens a `SLA Clock`
  against the definition its matrix rule imposed, and the clock is stopped when
  the matter stops being open. Nothing here computes a duration or a calendar.
* **Breach (E17-S4).** Core's sweep marks a clock breached. This module records
  the breach on the matter, raises the matter's severity, re-runs the matrix so
  the raised matter can reach a higher destination, and notifies — through
  Core's notification layer, so the dispatch row is the evidence.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import audit, notification, sla, state_flags
from consilium.escalation import routing

MATTER = "Escalation Matter"


# --------------------------------------------------------------------- closure

def closure_of(matter_name: str) -> str | None:
    return frappe.db.get_value("Escalation Closure", {"escalation_matter": matter_name}, "name")


def validate_closure(matter) -> None:
    """A matter at rest must carry its outcome. Reads the flags, not the label."""
    if matter.is_open:
        matter.closed_on = None
        return

    closure = closure_of(matter.name)
    summary = frappe.db.get_value("Escalation Closure", closure, "closure_summary") if closure else None
    if matter.requires_statement and not (closure and summary):
        frappe.throw(
            _(
                "This matter cannot be closed without a recorded outcome. "
                "Record an Escalation Closure with a closure type and a closure summary first."
            ),
            title=_("Outcome Required"),
        )
    if not matter.response_template_completed:
        frappe.throw(
            _("The response template must be completed before a matter is closed, including one tracked externally."),
            title=_("Response Template Incomplete"),
        )
    if matter.is_committable and not matter.external_reference:
        frappe.throw(
            _("A matter tracked outside the platform must carry the external reference that identifies it there."),
            title=_("External Reference Required"),
        )
    if not matter.closed_on:
        matter.closed_on = now()


def validate_closure_record(closure) -> None:
    """The closure's own rules: criteria that are required must be met."""
    unmet = [row.criterion for row in closure.criteria_met if row.required and not row.met]
    if unmet:
        frappe.throw(
            _("Closure criteria not met: {0}.").format(", ".join(unmet)),
            title=_("Closure Criteria"),
        )
    if closure.closure_type == "Transferred Externally" and not closure.external_reference:
        frappe.throw(
            _("A closure that transfers tracking elsewhere must record the external reference."),
            title=_("External Reference Required"),
        )


# --------------------------------------------------------------- service level

def sync_clock(matter) -> None:
    """Open a clock while the matter is open; stop it when it comes to rest."""
    if not matter.sla_definition:
        return

    if matter.is_open:
        # A clock that has breached is no longer "open", but the matter is still
        # being timed against it. Starting a fresh clock from the original open
        # date gave a clock that was already overdue, so the next sweep breached
        # the matter again, and again every day after. The breach is data
        # (`breached_on`), read here instead of the clock's label.
        breached = [
            row.name
            for row in frappe.get_all(
                "SLA Clock",
                filters={"subject_doctype": MATTER, "subject_name": matter.name,
                         "sla_definition": matter.sla_definition},
                fields=["name", "breached_on", "stopped_on"],
                order_by="creation asc",
            )
            if row.breached_on and not row.stopped_on
        ]
        if breached:
            if matter.sla_clock != breached[0]:
                frappe.db.set_value(MATTER, matter.name, "sla_clock", breached[0], update_modified=False)
                matter.sla_clock = breached[0]
            return
        clock = sla.start_clock(matter.sla_definition, MATTER, matter.name, started_on=matter.opened_on)
        if matter.sla_clock != clock.name:
            frappe.db.set_value(MATTER, matter.name, "sla_clock", clock.name, update_modified=False)
            matter.sla_clock = clock.name
        return

    # Only the matter's own clocks are stopped here. Status-driven clocks (time
    # in a status, the second-line challenge) are Core's and follow the record's
    # history; taking "any open clock" used to pick one of those at random and
    # leave the matter's total-open clock running after it had closed.
    status_driven = frappe.get_all(
        "SLA Definition", filters={"measure": ["in", list(sla.STATE_MEASURES)]}, pluck="name"
    )
    for open_clock in frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": MATTER, "subject_name": matter.name, "is_open": 1,
                 "sla_definition": ["not in", status_driven or [""]]},
        pluck="name",
    ):
        sla.stop_clock(open_clock, stopped_on=matter.closed_on or now())


# ---------------------------------------------------------------------- breach

def breached_clocks() -> list[dict]:
    """Clocks Core's sweep has marked breached. `breached_on` is data, not a label.

    The emptiness test is done in Python rather than as an ``is set`` filter:
    on PostgreSQL the framework renders that filter as ``!= ''``, which the
    server rejects for a timestamp column (`03-schema.md` §13 note 5).
    """
    rows = frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": MATTER},
        fields=["name", "subject_name", "sla_definition", "breached_on"],
        order_by="modified asc",
    )
    return sorted((row for row in rows if row.breached_on), key=lambda row: str(row.breached_on))


def sweep_breaches(as_of: str | None = None) -> list[str]:
    """Record every new breach and escalate the matter it belongs to."""
    sla.sweep(as_of)

    escalated = []
    for clock in breached_clocks():
        if not frappe.db.exists(MATTER, clock.subject_name):
            continue
        matter = frappe.get_doc(MATTER, clock.subject_name)
        if not matter.is_open:
            continue
        # Only the resolution threshold the matrix imposed raises a matter. A
        # matter can also carry status-driven clocks (a Time In State or First
        # Action definition, run by Core's own sweep), and those warn and breach
        # on their own terms; letting one of them raise the severity meant a
        # matter sitting too long in triage was escalated as if it had missed its
        # resolution deadline.
        if not matter.sla_definition or clock.sla_definition != matter.sla_definition:
            continue
        if matter.last_breach_on and str(matter.last_breach_on) >= str(clock.breached_on):
            continue
        record_breach(matter, clock.name, clock.breached_on)
        escalated.append(matter.name)
    return escalated


def record_breach(matter, clock: str, breached_on) -> None:
    """The breach is recorded on the matter, the matter is raised, and people are told."""
    matter.threshold_breached = 1
    matter.breach_count = int(matter.breach_count or 0) + 1
    matter.last_breach_on = breached_on
    matter.auto_escalated = 1
    matter.severity = routing.raised_severity(matter.severity)
    matter.sla_clock = clock
    matter.save(ignore_permissions=True)

    notify_breach(matter)


def breach_recipients(matter) -> list[str]:
    """The people a breach must reach: the named accountabilities, the groups the
    matched matrix rule names, and (E-7) the chair, secretary and attesting seats
    of every forum on the matter's pathway, resolved through forum membership as
    at today — so a seat that changed hands last week reaches its new holder."""
    recipients = [matter.accountable_executive, matter.response_owner, matter.identified_by]
    for participants in routing.pathway_participants(matter).values():
        recipients.extend(participant["user"] for participant in participants)
    if matter.escalation_matrix and matter.matched_matrix_rule:
        groups = frappe.get_all(
            "Escalation Matrix Notification",
            filters={
                "parent": matter.escalation_matrix,
                "parenttype": "Escalation Matrix",
                "rule_code": matter.matched_matrix_rule,
            },
            pluck="user_group",
        )
        for group in groups:
            recipients.extend(
                frappe.get_all("User Group Member", filters={"parent": group}, pluck="user")
            )
    seen, ordered = set(), []
    for recipient in recipients:
        if recipient and recipient not in seen:
            seen.add(recipient)
            ordered.append(recipient)
    return ordered


def notify_breach(matter) -> list[str]:
    """Raise ``escalation.matter.breached``. The template reads the matter itself
    (``doc``), so the severity and breach count it shows are the saved ones."""
    sent = notification.notify(
        "escalation.matter.breached", breach_recipients(matter), {},
        subject_doctype=MATTER, subject_name=matter.name,
    )
    _stamp_reached_forums(matter)
    return sent


def _stamp_reached_forums(matter) -> None:
    """Mark the pathway forums whose participants the notice just reached."""
    reached = [forum for forum, people in routing.pathway_participants(matter).items() if people]
    if reached:
        routing.stamp_notified(matter, reached)


def notify_material_entity_impact(matter) -> list[str]:
    """E-8: flagging material-entity impact tells the pathway's forums."""
    sent = notification.notify(
        "escalation.matter.material_entity_impact", breach_recipients(matter), {},
        subject_doctype=MATTER, subject_name=matter.name,
    )
    _stamp_reached_forums(matter)
    return sent


# ============================================================ portal actions
#
# The matter's page offers the actions that are valid now for the person looking
# at it, and nothing else. Two checks decide that, both on the server, both made
# again on the way into every entry point — so a button the page shows is one the
# server will accept, and a hand-built request for one it did not show is refused:
#
# * the **stage**, read from the matter's semantic flags — at rest, being worked,
#   or under review. Never from the status label;
# * the caller's **standing**: a role that carries the action at that stage, and
#   write access to this matter (which is also where the sensitive-matter
#   restriction bites: a matter a user may not see is a matter they cannot act on).
#
# A refusal on standing is audited through Core, as every refused modification is.

OWNER = "Escalation Owner"
REVIEWER = "Escalation Reviewer"
SUPERUSER_ROLES = ("System Manager",)

#: Who may take each action. ``move_status`` is narrowed by stage in `MOVE_ROLES`.
ACTION_ROLES = {
    "move_status": (OWNER, REVIEWER),
    "add_action_plan": (OWNER,),
    "update_action_plan": (OWNER,),
    "add_risk_acceptance": (OWNER,),
    "request_approval": (OWNER,),
    "record_review": (REVIEWER,),
    "record_closure": (OWNER,),
    "close": (OWNER,),
    "change_pathway": (OWNER,),
    # The queue half of the check (the caller belongs to the matter's queue and
    # the matter is waiting) is ``assignment.can_take``.
    "take_ownership": (OWNER,),
}

#: Moving the status belongs to whoever holds the matter at its stage: the first
#: line while it is being worked (including sending it for review), the second
#: line while it is under review (including handing it back).
MOVE_ROLES = {"working": (OWNER,), "in_review": (REVIEWER,)}

ACTION_LABELS = {
    "move_status": _("Move the status"),
    "add_action_plan": _("Add an action plan"),
    "update_action_plan": _("Update an action plan"),
    "add_risk_acceptance": _("Propose a risk acceptance"),
    "request_approval": _("Request risk-acceptance approval"),
    "decide_approval": _("Decide a risk acceptance"),
    "record_review": _("Record a review round"),
    "record_closure": _("Record the closure"),
    "close": _("Close the matter"),
    "change_pathway": _("Change the pathway"),
    "take_ownership": _("Take ownership"),
}

#: What each stage offers, whoever is asking. While the second line has the
#: matter, the first line may still report progress on its plans and an approver
#: may still decide, but the substance of the response waits for it to come back.
STAGE_ACTIONS = {
    "at_rest": (),
    "working": ("move_status", "add_action_plan", "update_action_plan", "add_risk_acceptance",
                "request_approval", "decide_approval", "record_closure", "close", "change_pathway",
                "take_ownership"),
    "in_review": ("move_status", "record_review", "update_action_plan", "decide_approval", "take_ownership"),
}

#: Starting suggestions for a new closure's criteria. The person closing edits,
#: removes and adds to them; what is required is what they leave marked required.
DEFAULT_CLOSURE_CRITERIA = (
    {"criterion": "Root cause identified and recorded", "required": 1},
    {"criterion": "Actions complete, accepted or transferred", "required": 1},
    {"criterion": "Lessons learned shared with the owning forum", "required": 0},
)


def stage_of(matter) -> str:
    """Where the matter stands, in this module's own vocabulary, from its flags."""
    if not matter.is_open:
        return "at_rest"
    if matter.requires_review:
        return "in_review"
    return "working"


def stage_actions(matter) -> set[str]:
    return set(STAGE_ACTIONS[stage_of(matter)])


def _holds(roles, user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & (set(roles) | set(SUPERUSER_ROLES)))


def roles_for(matter, action: str) -> tuple[str, ...]:
    if action == "move_status":
        return MOVE_ROLES.get(stage_of(matter), ())
    return ACTION_ROLES.get(action, ())


#: Actions that are a challenge of the matter, and so may not be taken by the
#: people accountable for it.
INDEPENDENT_ACTIONS = ("record_review",)


def is_accountable(matter, user: str) -> bool:
    return user in (matter.accountable_executive, matter.response_owner)


def may_take(matter, action: str, user: str | None = None) -> bool:
    """Whether the user's standing allows the action. Says nothing about stage."""
    user = user or frappe.session.user
    if action in INDEPENDENT_ACTIONS and is_accountable(matter, user):
        return False
    return _holds(roles_for(matter, action), user) and bool(
        frappe.has_permission(MATTER, "write", doc=matter, user=user)
    )


def authorise(matter, action: str) -> None:
    """Refuse, audited, an action the caller's standing does not carry; then one
    the matter's stage does not offer."""
    if not may_take(matter, action):
        audit.refuse(
            _("{0} may not take the action \"{1}\" on escalation {2}. At this stage it belongs to: {3}.").format(
                frappe.session.user, ACTION_LABELS[action], matter.name,
                ", ".join(roles_for(matter, action)) or _("nobody"),
            ),
            subject_doctype=MATTER,
            subject_name=matter.name,
            attempted_action="Other",
            control="escalation action role",
            context={"action": action},
        )
    if action not in stage_actions(matter):
        frappe.throw(
            _("\"{0}\" is not available while escalation {1} is {2}.").format(
                ACTION_LABELS[action], matter.name, matter.status
            ),
            title=_("Not Available At This Stage"),
        )


def load_matter(name: str, ptype: str = "read"):
    """The matter, if the caller may ``ptype`` it.

    A matter that does not exist and one the caller may not see get the same
    answer (see ``www/escalation.py``): anything else would tell a person without
    the right which references belong to sensitive matters.
    """
    if not name or not frappe.db.exists(MATTER, name):
        frappe.throw(_("Escalation {0} is not available to you.").format(name), frappe.PermissionError)
    matter = frappe.get_doc(MATTER, name)
    if not frappe.has_permission(MATTER, "read", doc=matter):
        frappe.throw(_("Escalation {0} is not available to you.").format(name), frappe.PermissionError)
    if ptype != "read" and not frappe.has_permission(MATTER, ptype, doc=matter):
        frappe.throw(_("You cannot change escalation {0}.").format(name), frappe.PermissionError)
    return matter


def _options(doctype: str, fieldname: str) -> list[str]:
    field = frappe.get_meta(doctype).get_field(fieldname)
    return [o for o in (field.options or "").split("\n") if o] if field else []


def status_targets(matter) -> list[dict]:
    """The open states the matter may move to: every configured open state but its own.

    Closing is a separate action with its own gate, so the states a matter
    rests in are not offered here.
    """
    by_value = state_flags.get_flag_map(MATTER).get("status", {})
    return [
        {"value": value, "requires_review": int(flags.get("requires_review") or 0)}
        for value in _options(MATTER, "status")
        for flags in [by_value.get(value) or {}]
        if int(flags.get("is_open") or 0) and value != matter.status
    ]


def closing_states() -> list[dict]:
    """The states a matter may come to rest in, and whether each needs an external reference."""
    by_value = state_flags.get_flag_map(MATTER).get("status", {})
    return [
        {"value": value, "is_committable": int(flags.get("is_committable") or 0)}
        for value in _options(MATTER, "status")
        for flags in [by_value.get(value) or {}]
        if flags and not int(flags.get("is_open") or 0)
    ]


def _people() -> list[dict]:
    """Enabled system users, for the pickers. ``User`` is not readable by most
    roles over the REST interface, so the list is served here, after the caller
    has been shown to hold an action on the matter."""
    return frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User", "name": ["not in", list(frappe.STANDARD_USERS)]},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )


def _truthy(value) -> bool:
    """A flag as a form sends it: a boolean, a number, or a string of either."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _clean(values, allowed: tuple[str, ...]) -> dict:
    """Only the fields a form may set. A list of forums arrives as names or rows
    and is stored as rows."""
    values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    cleaned = {key: values.get(key) for key in allowed if key in values}
    if "governance_forums" in cleaned:
        cleaned["governance_forums"] = [
            {"governance_forum": entry if isinstance(entry, str) else (entry or {}).get("governance_forum")}
            for entry in cleaned["governance_forums"] or []
            if (entry if isinstance(entry, str) else (entry or {}).get("governance_forum"))
        ]
    return cleaned


# --------------------------------------------------------------- the payload


def workbench(escalation_matter: str) -> dict:
    """Everything the matter's page needs to offer the actions valid now.

    The screen does not work out what is allowed; it is told, per action and per
    record, by the same checks the entry points make.
    """
    from consilium.escalation import approvals, assignment, templates

    matter = load_matter(escalation_matter, "read")
    user = frappe.session.user
    stage = stage_actions(matter)
    actions = {action: action in stage and may_take(matter, action, user) for action in ACTION_ROLES}

    plans = frappe.get_list(
        "Action Plan",
        filters={"escalation_matter": matter.name},
        fields=["name", "action_plan_name", "status", "start_date", "end_date", "accountable_executive",
                "owner_user", "description", "is_editable", "is_open"],
        order_by="end_date asc",
    )
    # The plans' forum rows follow the plans just read with the caller's permissions.
    plan_forums: dict[str, list[str]] = {}
    for row in frappe.get_all(
        "Escalation Forum Reference",
        filters={"parenttype": "Action Plan", "parent": ["in", [plan.name for plan in plans] or [""]]},
        fields=["parent", "governance_forum"],
    ):
        plan_forums.setdefault(row.parent, []).append(row.governance_forum)
    for plan in plans:
        plan["can_update"] = bool(actions["update_action_plan"] and plan.is_editable)
        plan["governance_forums"] = plan_forums.get(plan.name, [])
    # Offered only when there is a plan it can be taken on.
    actions["update_action_plan"] = any(plan["can_update"] for plan in plans)

    acceptances = approvals.acceptances_for(matter, stage, user)
    actions["decide_approval"] = any(row["can_decide"] for row in acceptances)
    actions["request_approval"] = actions["request_approval"] and any(row["can_request"] for row in acceptances)
    # Offered only to a member of the queue, while the matter waits in it.
    actions["take_ownership"] = actions["take_ownership"] and assignment.can_take(matter, user)

    closure = None
    closure_name = frappe.get_list(
        "Escalation Closure", filters={"escalation_matter": matter.name}, pluck="name", limit_page_length=1
    )
    if closure_name:
        closure_doc = frappe.get_doc("Escalation Closure", closure_name[0])
        closure = closure_doc.as_dict(convert_dates_to_str=True)

    acting = any(actions.values())
    severity = matter.severity
    return {
        "matter": {
            "name": matter.name, "status": matter.status, "stage": stage_of(matter),
            "is_open": matter.is_open, "requires_review": matter.requires_review,
            "is_editable": matter.is_editable, "severity": severity,
            "escalation_type": matter.escalation_type,
            "accountable_executive": matter.accountable_executive,
            "response_owner": matter.response_owner,
            "response_template_completed": matter.response_template_completed,
            "external_reference": matter.external_reference,
            "matched_matrix_rule": matter.matched_matrix_rule,
            "systemic": matter.systemic,
            "assigned_role": matter.assigned_role,
            "assigned_group": matter.assigned_group,
            "assignment_rule": matter.assignment_rule,
            "ownership_taken_on": str(matter.ownership_taken_on) if matter.ownership_taken_on else None,
            "waiting_for_owner": assignment.is_waiting(matter),
        },
        "actions": actions,
        "action_labels": ACTION_LABELS,
        "status_targets": status_targets(matter) if actions["move_status"] else [],
        "closing_states": closing_states() if actions["close"] else [],
        "plans": plans,
        "plan_statuses": _options("Action Plan", "status"),
        "acceptances": acceptances,
        "decision_choices": approvals.decision_choices(),
        "approvers": approvals.approver_candidates(matter) if actions["request_approval"] else [],
        "review_outcomes": _options("Escalation Review", "outcome"),
        "lines_of_defence": frappe.get_list(
            # A new round is recorded against a line in use: retired lines are
            # not offered (their labels still show on past rounds).
            "Line Of Defence", filters={"is_active": 1}, fields=["name", "line_of_defence_name"],
            order_by="name asc"
        ) if actions["record_review"] else [],
        "closure": closure,
        "closure_types": _options("Escalation Closure", "closure_type"),
        "default_criteria": list(DEFAULT_CLOSURE_CRITERIA),
        "external_systems": frappe.get_all(
            "External System", filters={"is_active": 1}, fields=["name", "title"], order_by="title asc"
        ) if (actions["record_closure"] or actions["close"]) else [],
        "template_requirements": {
            scope: templates.requirements_for(matter.escalation_type, scope, severity)
            for scope in (templates.SCOPE_ACTION_PLAN, templates.SCOPE_RISK_ACCEPTANCE)
        },
        "pathway": [
            {
                "name": row.name, "governance_forum": row.governance_forum,
                "role_in_escalation": row.role_in_escalation, "proposed_by_rule": row.proposed_by_rule,
                "notified_on": str(row.notified_on) if row.notified_on else None,
                "participants": participants,
            }
            for row in matter.get("governance_forums") or []
            for participants in [routing.forum_participants(row.governance_forum)]
        ],
        "pathway_roles": _options("Escalation Forum Link", "role_in_escalation"),
        "forums": routing.selectable_forums() if actions["change_pathway"] else [],
        "people": _people() if acting else [],
    }


@frappe.whitelist(methods=["GET"])
def get_matter_workbench(escalation_matter: str) -> dict:
    """The matter page's action payload. Anyone who may read the matter."""
    return workbench(escalation_matter)


# --------------------------------------------------------------- the status


@frappe.whitelist(methods=["POST"])
def move_matter_status(escalation_matter: str, status: str) -> dict:
    """Move an open matter to another open state. Escalation Owner while it is
    being worked (including sending it for review); Escalation Reviewer while it
    is under review (including handing it back). Closing is `close_matter`."""
    matter = load_matter(escalation_matter, "write")
    authorise(matter, "move_status")
    if status not in [target["value"] for target in status_targets(matter)]:
        frappe.throw(
            _("Escalation {0} cannot be moved to {1} from here. A matter comes to rest only through "
              "its closure.").format(matter.name, status),
            title=_("Not A Move"),
        )
    matter.status = status
    matter.save(ignore_permissions=True)
    return workbench(matter.name)


# ------------------------------------------------------------- action plans

PLAN_FIELDS = ("action_plan_name", "start_date", "end_date", "accountable_executive", "owner_user",
               "status", "description", "governance_forums")


@frappe.whitelist(methods=["POST"])
def add_action_plan(escalation_matter: str, values) -> dict:
    """Add an action plan to the matter (E16-S3). Escalation Owner, while it is worked.

    The plan's own controller applies the action-plan template for the matter's
    type and severity, so a field the template requires is refused here as it is
    on the desk.
    """
    matter = load_matter(escalation_matter, "write")
    authorise(matter, "add_action_plan")
    plan = frappe.get_doc({"doctype": "Action Plan", **_clean(values, PLAN_FIELDS),
                           "escalation_matter": matter.name})
    plan.insert(ignore_permissions=True)
    return workbench(matter.name)


@frappe.whitelist(methods=["POST"])
def update_action_plan(action_plan: str, values) -> dict:
    """Update one of the matter's plans, including its status. Escalation Owner.

    A plan whose state is no longer editable (completed, cancelled) is refused.
    """
    if not action_plan or not frappe.db.exists("Action Plan", action_plan):
        frappe.throw(_("Action plan {0} is not available to you.").format(action_plan), frappe.PermissionError)
    plan = frappe.get_doc("Action Plan", action_plan)
    if not frappe.has_permission("Action Plan", "read", doc=plan):
        frappe.throw(_("Action plan {0} is not available to you.").format(action_plan), frappe.PermissionError)
    matter = load_matter(plan.escalation_matter, "write")
    authorise(matter, "update_action_plan")
    if not plan.is_editable:
        frappe.throw(
            _("Action plan {0} is {1} and can no longer be changed.").format(plan.name, plan.status),
            title=_("Plan Closed"),
        )
    plan.update(_clean(values, PLAN_FIELDS))
    plan.save(ignore_permissions=True)
    return workbench(matter.name)


# ------------------------------------------------------------- review rounds


@frappe.whitelist(methods=["POST"])
def record_review_round(escalation_matter: str, outcome: str, comments: str | None = None,
                        review_line: str | None = None) -> dict:
    """Record the second line's challenge on a matter under review (E-9). Escalation Reviewer.

    Effective challenge is a control, not a courtesy, so the round carries its
    reasoning, and it may not be given by the matter's own accountable executive
    or response owner. A round already opened for this reviewer and not yet
    answered is completed; otherwise a new round is added.
    """
    matter = load_matter(escalation_matter, "write")
    user = frappe.session.user
    if is_accountable(matter, user):
        audit.refuse(
            _("{0} is accountable for escalation {1} and cannot also challenge it.").format(user, matter.name),
            subject_doctype=MATTER,
            subject_name=matter.name,
            attempted_action="Other",
            control="independent challenge",
        )
    authorise(matter, "record_review")
    if outcome not in _options("Escalation Review", "outcome"):
        frappe.throw(_("{0} is not a review outcome.").format(outcome), title=_("Unknown Outcome"))
    if not (comments or "").strip():
        frappe.throw(_("A review round is recorded with its reasoning."), title=_("Reasoning Required"))
    if review_line and not frappe.db.get_value("Line Of Defence", {"name": review_line, "is_active": 1}, "name"):
        frappe.throw(_("{0} is not a line of defence in use.").format(review_line), title=_("Retired Value"))

    stamp = now()
    pending = next(
        (row for row in matter.reviews if row.reviewer == user and not row.responded_on), None
    )
    if pending is None:
        pending = matter.append("reviews", {
            "round": max([int(row.round or 0) for row in matter.reviews] or [0]) + 1,
            "reviewer": user,
            "received_on": stamp,
        })
    pending.outcome = outcome
    pending.comments = comments.strip()
    pending.responded_on = stamp
    if review_line:
        pending.review_line = review_line
    # The round is answered against the challenge service level running on the
    # matter, if one applies to it (E-9): the clock is Core's, started when the
    # matter went to the second line.
    from consilium.escalation import timing

    challenge_clock = timing.open_challenge_clock(matter.name)
    if challenge_clock and not pending.sla_clock:
        pending.sla_clock = challenge_clock
    matter.save(ignore_permissions=True)
    return workbench(matter.name)


# ------------------------------------------------------------------- closure


def _external_reference(matter, external_system: str | None, external_key: str | None) -> str | None:
    """The External Reference naming where the matter is tracked, found or recorded."""
    if not (external_system or external_key):
        return None
    if not (external_system and external_key):
        frappe.throw(_("An external reference needs both the system and its key there."),
                     title=_("External Reference Incomplete"))
    if not frappe.db.get_value("External System", {"name": external_system, "is_active": 1}, "name"):
        frappe.throw(_("{0} is not an active external system.").format(external_system),
                     title=_("Unknown External System"))
    existing = frappe.db.get_value(
        "External Reference", {"external_system": external_system, "external_key": external_key.strip()}, "name"
    )
    if existing:
        return existing
    return frappe.get_doc({
        "doctype": "External Reference", "subject_doctype": MATTER, "subject_name": matter.name,
        "external_system": external_system, "external_key": external_key.strip(),
        "label": _("Tracking of {0}").format(matter.name),
    }).insert(ignore_permissions=True).name


@frappe.whitelist(methods=["POST"])
def record_matter_closure(escalation_matter: str, closure_type: str, closure_summary: str,
                          criteria=None, external_system: str | None = None,
                          external_key: str | None = None) -> dict:
    """Record (or revise) the matter's closure and its criteria (E-10). Escalation Owner.

    The closure's controller refuses one whose required criteria are not met,
    and a transfer elsewhere without its external reference.
    """
    matter = load_matter(escalation_matter, "write")
    authorise(matter, "record_closure")
    rows = frappe.parse_json(criteria) if isinstance(criteria, str) else (criteria or [])
    name = closure_of(matter.name)
    closure = frappe.get_doc("Escalation Closure", name) if name else frappe.get_doc(
        {"doctype": "Escalation Closure", "escalation_matter": matter.name}
    )
    closure.closure_type = closure_type
    closure.closure_summary = (closure_summary or "").strip()
    reference = _external_reference(matter, external_system, external_key)
    if reference:
        closure.external_reference = reference
    closure.set("criteria_met", [])
    for row in rows:
        if not (row.get("criterion") or "").strip():
            continue
        closure.append("criteria_met", {
            "criterion": row["criterion"].strip(),
            "required": 1 if row.get("required") else 0,
            "met": 1 if row.get("met") else 0,
            "evidence_note": row.get("evidence_note"),
        })
    if name:
        closure.save(ignore_permissions=True)
    else:
        closure.insert(ignore_permissions=True)
    return workbench(matter.name)


@frappe.whitelist(methods=["POST"])
def close_matter(escalation_matter: str, status: str, response_template_completed=None) -> dict:
    """Bring the matter to rest (E-10, E-14). Escalation Owner, while it is worked.

    The gates are the controller's, unchanged: a recorded closure with its
    summary, the response template complete, and for a state that commits the
    matter elsewhere, the external reference — taken from the closure when the
    closure recorded one. Whoever closes the matter approves its outcome.
    """
    matter = load_matter(escalation_matter, "write")
    authorise(matter, "close")
    targets = {row["value"]: row for row in closing_states()}
    if status not in targets:
        frappe.throw(_("{0} is not a state a matter comes to rest in.").format(status), title=_("Not A Closure"))
    name = closure_of(matter.name)
    if not name:
        frappe.throw(_("Record the closure — how the matter ended and against which criteria — before closing it."),
                     title=_("Outcome Required"))
    closure = frappe.get_doc("Escalation Closure", name)
    if _truthy(response_template_completed):
        matter.response_template_completed = 1
    if targets[status]["is_committable"] and not matter.external_reference:
        matter.external_reference = closure.external_reference
    matter.status = status
    matter.save(ignore_permissions=True)
    if not closure.approved_by:
        closure.approved_by = frappe.session.user
        closure.approved_on = now()
        closure.save(ignore_permissions=True)
    return workbench(matter.name)


# --------------------------------------------------------------- your queue


@frappe.whitelist(methods=["GET"])
def my_escalation_queue() -> dict:
    """What is waiting on the caller, for the register: acceptances they are
    asked to decide, matters awaiting their review, and open matters they are
    accountable for or own the response to. Every row read with the caller's
    own permissions, so a sensitive matter appears only to those cleared for it.
    """
    user = frappe.session.user
    if not frappe.has_permission(MATTER, "read"):
        return {"approvals": [], "reviews": [], "owned": []}
    decisions = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Risk Acceptance", "is_open": 1, "assigned_to": user},
        pluck="subject_name",
    )
    approvals = frappe.get_list(
        "Risk Acceptance", filters={"name": ["in", decisions or [""]]},
        fields=["name", "risk_acceptance_name", "escalation_matter", "status"],
    ) if decisions and frappe.has_permission("Risk Acceptance", "read") else []
    reviews = frappe.get_list(
        MATTER, filters={"is_open": 1, "requires_review": 1},
        fields=["name", "escalation_title", "status", "severity"], order_by="opened_on asc",
    ) if _holds((REVIEWER,), user) else []
    owned = frappe.get_list(
        MATTER, filters={"is_open": 1},
        or_filters={"accountable_executive": user, "response_owner": user},
        fields=["name", "escalation_title", "status", "severity"], order_by="opened_on asc",
    )
    return {"approvals": approvals, "reviews": reviews, "owned": owned}
