"""The explicit approval a risk acceptance requires (E16-S4).

A risk acceptance is a decision to carry a risk rather than fix it, so it may
not take effect on one person's say-so: the approval is a separate, recorded act.
Core owns the approval engine — delegation resolution, the bypass rule, the
version the decision was given against — so this module only asks it for a
decision and then stamps the outcome onto the acceptance.

The approval fields on `Risk Acceptance` are read-only in the schema precisely so
that this is the only path that can set them.

**Approval chains (E-9).** An acceptance's approval may be a chain rather than
one person: a `Risk Acceptance Approval Route` keyed by the matter's escalation
type and severity names its steps, each sequential or parallel, and each raised
as its own Core `Approval Decision` — the same mode Core already enforces for
policy routes (`consilium.policy.routing`). The acceptance is approved only
when every step of the chain has approved; any objection returns it to its
author, and the steps the chain never reached are settled so they stop waiting
on anyone. With no matching route the acceptance goes, as before, to one
independent approver (or is approved by a forum motion).

Separation of duties holds on both ends: nobody who owns, raised or answers
for the matter, and nobody who proposed or is accountable for the acceptance,
may be asked to approve it or decide a step of it — including as someone
else's delegate.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import approvals as core_approvals
from consilium.consilium_core import audit, state_flags
from consilium.escalation import flags

APPROVAL_STEP = "Risk Acceptance"


def request_approval(risk_acceptance: str, approver: str, required_role: str | None = None):
    """Open a decision for the named approver. The acceptance stays without effect."""
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    decision = core_approvals.request_decision(
        subject_doctype="Risk Acceptance",
        subject_name=acceptance.name,
        approval_step=APPROVAL_STEP,
        assigned_to=approver,
        required_role=required_role,
    )
    frappe.db.set_value("Risk Acceptance", acceptance.name, "approval_decision", decision.name)
    return decision


def record_approval(risk_acceptance: str, decision_value: str, *, comments: str | None = None,
                    acting_user: str | None = None):
    """Record the approver's decision on the (first) step and settle the acceptance.

    ``decision_value`` is a configured `Approval Decision` value, passed through
    to Core as data. Whether it *means* approval is read from the flag map, not
    from the string. For an acceptance with one approver this is the whole
    approval; on a chain it decides the first step (see `record_step`).
    """
    acceptance = frappe.get_doc("Risk Acceptance", risk_acceptance)
    if not acceptance.approval_decision:
        frappe.throw(
            _("No approval has been requested for {0}.").format(acceptance.name),
            title=_("Nothing To Decide"),
        )
    return record_step(acceptance, acceptance.approval_decision, decision_value,
                       comments=comments, acting_user=acting_user)


def is_approved(acceptance) -> bool:
    """An acceptance is approved when its whole approval chain approved it.

    One approver is a chain of one. A forum motion is the other accepted route:
    an approval taken in a meeting is evidenced by the motion, not by an
    in-system decision.
    """
    if acceptance.approval_motion:
        return True
    if not (acceptance.approved_by and acceptance.approved_on):
        return False
    if not acceptance.approval_decision:
        return False
    return chain_status(acceptance)["complete"]


# ============================================================ approval chains
#
# E-9: approvals aligned to type and severity, sequential or parallel. The
# route is configuration; the steps are Core decisions; ordering is Core's
# (`approvals.waiting_on`), so a sequential step decided out of turn is refused
# and audited there, exactly as on a policy route.

ROUTE = "Risk Acceptance Approval Route"
ROUTE_STEP = "Risk Acceptance Approval Step"

#: Where a step's approver comes from. Configuration vocabulary for the
#: ``assignee_source`` column, not a workflow state.
CHOSEN_AT_REQUEST = "Chosen At Request"
NAMED_USER = "Named User"

#: The value a step the chain never reached is settled with once another step
#: has decided against the acceptance. It is Core's "no position taken", which
#: is the truth about a step nobody was asked to decide: leaving it open kept it
#: in its approver's work list for an acceptance that was already back with its
#: author. The comment on the row says why it was settled; the objection that
#: ended the chain is what `chain_status` reads.
UNREACHED_DECISION = "Abstained"

CHAIN_FIELDS = ["name", "approval_step", "step_sequence", "mode", "required_role", "assigned_to", "acted_by",
                "acting_delegation", "decision", "is_open", "decided_on", "comments", "exception_authorisation",
                "owner", "creation"]


def validate_route(route) -> None:
    """A route that could not be raised is refused when it is saved, not when it is used."""
    if not route.get("steps"):
        frappe.throw(_("An approval route needs at least one step."), title=_("No Steps"))
    labels = set()
    for row in route.steps:
        if int(row.step_sequence or 0) < 1:
            frappe.throw(_("Step {0} needs a sequence of 1 or more.").format(row.approval_step),
                         title=_("Sequence Required"))
        if row.assignee_source == NAMED_USER and not row.assignee:
            frappe.throw(_("Step {0} names its approver: choose the person.").format(row.approval_step),
                         title=_("Approver Required"))
        if row.approval_step in labels:
            frappe.throw(_("Two steps are called {0}; each step needs its own name.").format(row.approval_step),
                         title=_("Duplicate Step"))
        labels.add(row.approval_step)


def _route_specificity(route: dict) -> int:
    return (1 if route.get("escalation_type") else 0) + (1 if route.get("severity") else 0)


def select_route(matter) -> dict | None:
    """The approval route for acceptances on this matter: the first active route
    whose type and severity are the matter's or blank, lowest priority first,
    the more specific winning a tie. None means the default single approver."""
    if not frappe.db.table_exists(ROUTE):
        return None
    routes = frappe.get_all(
        ROUTE,
        filters={"is_active": 1},
        fields=["name", "route_title", "escalation_type", "severity", "priority"],
        order_by="priority asc, modified asc",
    )
    candidates = [
        route for route in routes
        if route.escalation_type in (None, "", matter.get("escalation_type"))
        and route.severity in (None, "", matter.get("severity"))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda route: (int(route.priority or 0), -_route_specificity(route)))
    return candidates[0]


def route_steps(route: str) -> list[dict]:
    return frappe.get_all(
        ROUTE_STEP,
        filters={"parent": route, "parenttype": ROUTE},
        fields=["idx", "step_sequence", "approval_step", "mode", "required_role", "assignee_source", "assignee"],
        order_by="step_sequence asc, idx asc",
    )


def conflicted(matter, acceptance, requester: str | None = None) -> set[str]:
    """The people who may not approve this acceptance (separation of duties).

    The matter's owner and raiser — its response owner, accountable executive,
    the person who identified it and the account that recorded it — and the
    acceptance's proposer and accountable executive, and whoever asked for the
    approval. An acceptance approved by someone who answers for the risk has
    not been independently approved.
    """
    people = {
        matter.get("response_owner"), matter.get("accountable_executive"), matter.get("identified_by"),
        matter.get("owner"), acceptance.get("accountable_executive"), acceptance.get("owner"), requester,
    }
    return {person for person in people if person}


def _step_role(step) -> str:
    return step.get("required_role") or APPROVER_ROLE


def step_candidates(matter, acceptance, step, requester: str | None = None) -> list[dict]:
    """Who may be chosen for a step: enabled holders of its role who can see the
    matter and are independent of it."""
    holders = frappe.get_all("Has Role", filters={"role": _step_role(step), "parenttype": "User"}, pluck="parent")
    if not holders:
        return []
    excluded = conflicted(matter, acceptance, requester)
    people = frappe.get_all(
        "User",
        filters={"name": ["in", holders], "enabled": 1, "user_type": "System User"},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )
    return [p for p in people if p.name not in excluded
            and frappe.has_permission("Escalation Matter", "read", doc=matter, user=p.name)]


def planned_chain(matter, acceptance, requester: str | None = None) -> dict | None:
    """The route an approval request would raise now, resolved but not written.

    Shown before the request is made, so the person asking sees who will be
    asked and in what order — and picks the people a step leaves to them.
    """
    route = select_route(matter)
    if not route:
        return None
    steps = []
    for row in route_steps(route.name):
        chosen = row.assignee_source != NAMED_USER
        steps.append({
            "key": str(row.idx),
            "step_sequence": int(row.step_sequence or 0),
            "approval_step": row.approval_step,
            "mode": row.mode or core_approvals.SEQUENTIAL,
            "required_role": _step_role(row),
            "chosen": chosen,
            "assignee": None if chosen else row.assignee,
            "candidates": step_candidates(matter, acceptance, row, requester) if chosen else [],
        })
    return {"route": route.name, "title": route.route_title, "steps": steps}


def cycle_steps(acceptance) -> list[dict]:
    """The steps of the approval now in progress, in order.

    The acceptance points at the first step of its latest request; that step and
    everything raised with or after it is the current cycle. Steps from a request
    that ended in a rejection are history, and must not count towards (or block)
    the next one.
    """
    first = acceptance.get("approval_decision")
    if not first:
        return []
    started = frappe.db.get_value("Approval Decision", first, "creation")
    if not started:
        return []
    return frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Risk Acceptance", "subject_name": acceptance.get("name"),
                 "creation": [">=", started], "docstatus": ["<", 2]},
        fields=CHAIN_FIELDS,
        order_by="step_sequence asc, creation asc",
    )


def _objects(row) -> bool:
    """Whether a settled or open decision stands against the acceptance: its value's
    flags ask for review (a rejection, a request for changes) and no exception
    authorisation excuses it. Read from the flag map, never from the label."""
    value_flags = state_flags.flags_for("Approval Decision", "decision", row.get("decision")) or {}
    return bool(int(value_flags.get("requires_review") or 0)) and not row.get("exception_authorisation")


def chain_status(acceptance) -> dict:
    """Where the current approval stands: complete, objected to, or still waiting."""
    rows = cycle_steps(acceptance)
    approving = set(flags.approving_decisions())
    objected = [row.approval_step for row in rows if _objects(row)]
    waiting = [row.approval_step for row in rows if int(row.is_open or 0)]
    complete = bool(rows) and not objected and not waiting and all(row.decision in approving for row in rows)
    return {"complete": complete, "objected": objected, "waiting": waiting, "steps": len(rows)}


def _close_unreached(acceptance, ended_by) -> None:
    for row in cycle_steps(acceptance):
        if not int(row.is_open or 0):
            continue
        doc = frappe.get_doc("Approval Decision", row.name)
        doc.decision = UNREACHED_DECISION
        doc.decided_on = now()
        doc.comments = _("Not reached: the approval ended when \"{0}\" was decided against the acceptance.").format(
            ended_by.approval_step)
        doc.save(ignore_permissions=True)


def record_step(acceptance, approval_decision: str, decision_value: str, *, comments: str | None = None,
                acting_user: str | None = None):
    """Record one step's decision through Core, then settle the acceptance.

    Core resolves delegation and refuses — audited — someone who is neither the
    assignee nor their live delegate, and a sequential step decided out of turn.
    What the acceptance carries afterwards follows the chain as a whole: an
    approval is stamped only once the last step approves; an objection anywhere
    clears it and settles the steps left unreached.
    """
    if isinstance(acceptance, str):
        acceptance = frappe.get_doc("Risk Acceptance", acceptance)
    decision = core_approvals.record_decision(
        approval_decision, decision_value, comments=comments, acting_user=acting_user
    )
    status = chain_status(acceptance)
    if status["objected"]:
        _close_unreached(acceptance, decision)
        stamp = {"approved_by": None, "approved_on": None}
    elif status["complete"]:
        stamp = {"approved_by": decision.acted_by, "approved_on": decision.decided_on}
    else:
        stamp = {"approved_by": None, "approved_on": None}
    frappe.db.set_value("Risk Acceptance", acceptance.name, stamp)
    return decision


def raise_chain(acceptance, plan: dict, assignees: dict[str, str]) -> list[str]:
    """Write the planned route as Core decisions, first step first."""
    written = []
    for step in sorted(plan["steps"], key=lambda step: (step["step_sequence"], int(step["key"]))):
        decision = core_approvals.request_decision(
            subject_doctype="Risk Acceptance",
            subject_name=acceptance.name,
            approval_step=step["approval_step"],
            step_sequence=step["step_sequence"],
            mode=step["mode"],
            required_role=step["required_role"],
            assigned_to=assignees[step["key"]],
        )
        written.append(decision.name)
    frappe.db.set_value("Risk Acceptance", acceptance.name,
                        {"approval_decision": written[0], "approval_route": plan["route"]})
    return written


# ============================================================ portal actions
#
# The acceptance is proposed and its approval requested by the first line, and
# decided by the person the request names — or by someone holding a live
# delegation from them, which is Core's question to answer, so Core is asked
# and Core audits a refusal. Which state an acceptance moves to at each step is
# read from the flag map, never named.

#: The role an approver is drawn from, and that the decision records as required.
APPROVER_ROLE = "Head of Risk Governance"

#: The decisions an approver may record. Values handed to Core; what each one
#: *means* is read from its flags (`flags.approving_decisions`), never compared.
DECISION_CHOICES = ("Approved", "Rejected")

ACCEPTANCE_FIELDS = ("risk_acceptance_name", "external_acceptance_id", "start_date", "end_date",
                     "accountable_executive", "rationale", "reassessment_frequency_months",
                     "next_reassessment_on", "governance_forums")


def _state(**wanted) -> str:
    """The one Risk Acceptance state whose flags are ``wanted``. Configuration, found by meaning."""
    values = flags.values_meaning("Risk Acceptance", "status", **wanted)
    if not values:
        frappe.throw(
            _("No Risk Acceptance state is configured with the flags {0}.").format(wanted),
            title=_("State Flags Not Configured"),
        )
    return values[0]


def pending_state() -> str:
    """Awaiting its approver: still open, and asking for review."""
    return _state(is_open=1, requires_review=1)


def approved_state() -> str:
    """In effect: committed and active."""
    return _state(is_committable=1, is_active=1)


def returned_state() -> str:
    """Back with its author: open and editable, asking for nothing, not in effect."""
    return _state(is_open=1, is_editable=1, requires_review=0, is_active=0)


def decision_choices() -> list[dict]:
    """The decisions the screen may offer, and whether each must carry its reason."""
    from consilium.consilium_core import state_flags

    return [
        {"decision": value,
         "needs_reason": bool((state_flags.flags_for("Approval Decision", "decision", value) or {}).get("requires_review"))}
        for value in DECISION_CHOICES
    ]


def approver_candidates(matter=None) -> list[dict]:
    """Enabled people holding the approver role — and, given the matter, able to read it.

    An approver decides from the matter's own page and has to see what they are
    approving, so someone who cannot read the matter is not offered. For a
    sensitive matter that is also what keeps the choice to people cleared for it.
    """
    holders = frappe.get_all("Has Role", filters={"role": APPROVER_ROLE, "parenttype": "User"}, pluck="parent")
    if not holders:
        return []
    people = frappe.get_all(
        "User",
        filters={"name": ["in", holders], "enabled": 1, "user_type": "System User"},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )
    if matter is None:
        return people
    return [p for p in people if frappe.has_permission("Escalation Matter", "read", doc=matter, user=p.name)]


def _open_decision(acceptance) -> dict | None:
    if not acceptance.get("approval_decision"):
        return None
    row = frappe.db.get_value(
        "Approval Decision", acceptance.approval_decision,
        ["name", "assigned_to", "is_open", "decision", "decided_on", "acted_by", "comments"], as_dict=True,
    )
    return row


def _may_decide(decision: dict | None, acceptance: str, user: str) -> bool:
    if not decision or not decision.is_open:
        return False
    from consilium.consilium_core import delegation

    return bool(delegation.resolve_actor(
        decision.assigned_to, delegation.ACTION_APPROVE, acting_user=user,
        doctype="Risk Acceptance", name=acceptance,
    )["permitted"])


def acceptances_for(matter, stage: set[str], user: str) -> list[dict]:
    """The matter's acceptances the caller may read, with what they may do to each."""
    from consilium.escalation import resolution

    can_request = "request_approval" in stage and resolution.may_take(matter, "request_approval", user)
    decide_stage = "decide_approval" in stage
    rows = frappe.get_list(
        "Risk Acceptance",
        filters={"escalation_matter": matter.name},
        fields=["name", "risk_acceptance_name", "status", "is_editable", "requires_review", "is_open",
                "is_active", "approval_decision", "approval_motion", "approval_route", "approved_by", "approved_on",
                "accountable_executive", "start_date", "end_date", "rationale", "owner"],
        order_by="start_date desc",
    )
    for row in rows:
        chain = cycle_steps(row)
        requester = chain[0].owner if chain else None
        independent = user not in conflicted(matter, row, requester)
        for step in chain:
            step["in_turn"] = bool(int(step.is_open or 0) and core_approvals.is_turn(step.name))
            step["can_decide"] = bool(decide_stage and independent and step["in_turn"]
                                      and _may_decide(step, row.name, user))
        open_steps = [step for step in chain if int(step.is_open or 0)]
        current = next((step for step in open_steps if step["in_turn"]), None)
        row["chain"] = chain
        # One decision, for the screens that show one: the step waiting now, or
        # the last one taken.
        row["decision"] = current or (open_steps[0] if open_steps else (chain[-1] if chain else _open_decision(row)))
        row["waiting_on"] = [step.assigned_to for step in open_steps if step["in_turn"]]
        row["decidable_steps"] = [step.name for step in chain if step["can_decide"]]
        row["can_request"] = bool(can_request and row.is_editable and not row.requires_review and not open_steps)
        row["can_decide"] = bool(row["decidable_steps"])
        row["route"] = planned_chain(matter, row, user) if row["can_request"] else None
    return rows


def _load_acceptance(name: str):
    if not name or not frappe.db.exists("Risk Acceptance", name):
        frappe.throw(_("Risk acceptance {0} is not available to you.").format(name), frappe.PermissionError)
    doc = frappe.get_doc("Risk Acceptance", name)
    if not frappe.has_permission("Risk Acceptance", "read", doc=doc):
        frappe.throw(_("Risk acceptance {0} is not available to you.").format(name), frappe.PermissionError)
    return doc


@frappe.whitelist(methods=["POST"])
def add_risk_acceptance(escalation_matter: str, values) -> dict:
    """Propose a risk acceptance on the matter (E16-S4). Escalation Owner, while it is worked.

    It starts without effect; the template for the matter's type and severity is
    applied by the acceptance's own controller.
    """
    from consilium.escalation import resolution

    matter = resolution.load_matter(escalation_matter, "write")
    resolution.authorise(matter, "add_risk_acceptance")
    doc = frappe.get_doc({"doctype": "Risk Acceptance", **resolution._clean(values, ACCEPTANCE_FIELDS),
                          "escalation_matter": matter.name, "status": returned_state()})
    doc.insert(ignore_permissions=True)
    return resolution.workbench(matter.name)


def _refuse_conflicted(person: str, acceptance, step_label: str | None = None) -> None:
    audit.refuse(
        _("{0} cannot approve risk acceptance {1}{2}: an approver must be independent of the matter's owner "
          "and raiser, of the person asking, and of the acceptance's proposer and accountable executive.").format(
            person, acceptance.name, _(" at the step \"{0}\"").format(step_label) if step_label else ""),
        subject_doctype="Risk Acceptance",
        subject_name=acceptance.name,
        attempted_action="Other",
        control="four eyes",
    )


@frappe.whitelist(methods=["POST"])
def request_risk_acceptance_approval(risk_acceptance: str, approver: str | None = None, approvers=None) -> dict:
    """Ask for an acceptance to be decided. Escalation Owner.

    Where an approval route matches the matter's type and severity (E-9), every
    step of it is raised, in order, as a Core decision: ``approvers`` maps each
    step whose approver is chosen at request (by the step's ``key``) to the
    person chosen; a route with one such step also takes ``approver``. With no
    matching route, ``approver`` is the one independent approver, as before.

    Four eyes, on every step: nobody who owns, raised or answers for the matter,
    or proposed or is accountable for the acceptance, or is asking, may be asked
    to approve — because an acceptance approved by its own author has not been
    approved at all. Nor may one person take two steps of the same chain.
    """
    from consilium.escalation import resolution

    acceptance = _load_acceptance(risk_acceptance)
    matter = resolution.load_matter(acceptance.escalation_matter, "write")
    resolution.authorise(matter, "request_approval")
    if not acceptance.is_editable or acceptance.requires_review or chain_status(acceptance)["waiting"]:
        frappe.throw(
            _("Risk acceptance {0} is {1}; approval can be requested only while it is with its author.").format(
                acceptance.name, acceptance.status),
            title=_("Not Available At This Stage"),
        )
    requester = frappe.session.user
    excluded = conflicted(matter, acceptance, requester)
    plan = planned_chain(matter, acceptance, requester)

    if plan is None:
        if not approver:
            frappe.throw(_("Choose the approver."), title=_("Approver Required"))
        if approver in excluded:
            _refuse_conflicted(approver, acceptance)
        if approver not in [row.name for row in approver_candidates(matter)]:
            frappe.throw(
                _("{0} cannot be asked to approve: an approver holds the {1} role and can see the matter.").format(
                    approver, APPROVER_ROLE),
                title=_("Not An Approver"),
            )
        request_approval(acceptance.name, approver, required_role=APPROVER_ROLE)
        frappe.db.set_value("Risk Acceptance", acceptance.name, "approval_route", None)
    else:
        chosen = frappe.parse_json(approvers) if isinstance(approvers, str) else dict(approvers or {})
        chosen = {str(key): value for key, value in (chosen or {}).items() if value}
        to_choose = [step for step in plan["steps"] if step["chosen"]]
        if approver and not chosen and len(to_choose) == 1:
            chosen = {to_choose[0]["key"]: approver}
        assignees: dict[str, str] = {}
        for step in plan["steps"]:
            person = chosen.get(step["key"]) if step["chosen"] else step["assignee"]
            if not person:
                frappe.throw(_("Choose who approves the step \"{0}\".").format(step["approval_step"]),
                             title=_("Approver Required"))
            if person in excluded:
                _refuse_conflicted(person, acceptance, step["approval_step"])
            if step["chosen"] and person not in [row.name for row in step["candidates"]]:
                frappe.throw(
                    _("{0} cannot be asked to approve the step \"{1}\": its approver holds the {2} role and "
                      "can see the matter.").format(person, step["approval_step"], step["required_role"]),
                    title=_("Not An Approver"),
                )
            if not step["chosen"] and not frappe.has_permission("Escalation Matter", "read", doc=matter,
                                                                 user=person):
                frappe.throw(
                    _("{0}, named on the step \"{1}\", cannot see escalation {2} and so cannot decide it. "
                      "Ask an administrator to correct the route.").format(person, step["approval_step"], matter.name),
                    title=_("Approver Cannot See The Matter"),
                )
            assignees[step["key"]] = person
        people = list(assignees.values())
        if len(set(people)) != len(people):
            audit.refuse(
                _("One person cannot take two steps of the approval of risk acceptance {0}: a chain is several "
                  "independent approvals, not one approval counted twice.").format(acceptance.name),
                subject_doctype="Risk Acceptance",
                subject_name=acceptance.name,
                attempted_action="Other",
                control="four eyes",
                exc=frappe.ValidationError,
            )
        raise_chain(acceptance, plan, assignees)

    acceptance.reload()
    acceptance.status = pending_state()
    acceptance.save(ignore_permissions=True)
    return resolution.workbench(matter.name)


@frappe.whitelist(methods=["POST"])
def decide_risk_acceptance(risk_acceptance: str, decision: str, comments: str | None = None,
                           approval_decision: str | None = None) -> dict:
    """An approver (or their live delegate) decides their step of the acceptance.

    No escalation role is asked for: the right to decide comes from being asked,
    and Core refuses — audited — anyone who is neither the assignee nor holding
    a delegation from them, and a sequential step taken before the steps ahead
    of it. The approver must still be able to see the matter, so a sensitive
    matter can be decided only by someone cleared for it, and must be
    independent of it: the matter's owner or raiser cannot decide an acceptance
    on it even as someone's delegate.

    ``approval_decision`` names the step when the caller holds more than one;
    otherwise the caller's step that is due now is decided. The acceptance takes
    effect when the last step approves; an objection at any step returns it to
    its author.
    """
    from consilium.escalation import resolution

    acceptance = _load_acceptance(risk_acceptance)
    matter = resolution.load_matter(acceptance.escalation_matter, "read")
    if "decide_approval" not in resolution.stage_actions(matter):
        frappe.throw(
            _("Escalation {0} is {1}; its acceptances cannot be decided now.").format(matter.name, matter.status),
            title=_("Not Available At This Stage"),
        )
    if decision not in DECISION_CHOICES:
        frappe.throw(_("{0} is not a decision an approver can record.").format(decision), title=_("Unknown Decision"))
    chain = cycle_steps(acceptance)
    open_steps = [step for step in chain if int(step.is_open or 0)]
    if not open_steps:
        frappe.throw(_("No approval is waiting on risk acceptance {0}.").format(acceptance.name),
                     title=_("Nothing To Decide"))
    if (state_flags.flags_for("Approval Decision", "decision", decision) or {}).get("requires_review") \
            and not (comments or "").strip():
        frappe.throw(_("A decision of {0} is recorded with its reason.").format(decision), title=_("Reason Required"))

    user = frappe.session.user
    if user in conflicted(matter, acceptance, chain[0].owner):
        audit.refuse(
            _("{0} owns, raised or answers for escalation {1}, or proposed or asked for this acceptance, and so "
              "cannot decide risk acceptance {2}.").format(user, matter.name, acceptance.name),
            subject_doctype="Risk Acceptance",
            subject_name=acceptance.name,
            attempted_action="Other",
            control="separation of duties",
        )
    if approval_decision:
        step = next((row for row in open_steps if row.name == approval_decision), None)
        if not step:
            frappe.throw(_("{0} is not an open step of risk acceptance {1}.").format(approval_decision,
                                                                                     acceptance.name),
                         title=_("Wrong Step"))
    else:
        mine = [row for row in open_steps if _may_decide(row, acceptance.name, user)]
        due = [row for row in mine if core_approvals.is_turn(row.name)]
        # Nothing of the caller's: Core is still asked, so its refusal is the
        # audited one; a step of theirs not yet due: Core refuses it in order.
        step = (due or mine or open_steps)[0]

    record_step(acceptance, step.name, decision, comments=comments, acting_user=user)
    acceptance.reload()
    outcome = chain_status(acceptance)
    if outcome["objected"]:
        acceptance.status = returned_state()
        acceptance.save(ignore_permissions=True)
    elif outcome["complete"]:
        acceptance.status = approved_state()
        acceptance.save(ignore_permissions=True)
    return resolution.workbench(matter.name)
