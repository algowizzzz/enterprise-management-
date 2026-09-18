"""Committee formation: intake, evaluation, approval, and the forum it creates.

One intake artefact covers create, modify and retire (decision D-1). It carries
the nine-state formation flow; the forum it produces carries the five-state
compliance flow (decision D-3). The two never share a state machine.

Four things here are worth reading closely:

* **The five G-5 criteria are rows, not code.** A request cannot be approved
  while any criterion is without a finding, and the criteria set can grow.
* **Return to originator is a transition, not a comment.** The questions and the
  reply live on the record, and the originator is notified.
* **The approval steps are configuration.** A ``Formation Approval Route`` holds
  them: role-based, sequenced, sequential or parallel. Each step becomes a Core
  ``Approval Decision``, so delegation and exception authorisation are the same
  machinery the rest of the platform uses. Which route applies is configuration
  too (G-8): a route may name a request type, a forum type and a materiality of
  change, and the most specific active route that fits wins (``resolve_route``).
* **No step is skipped without a recorded exception.** The gate is "no open
  approval decisions, unless a Core ``Exception Authorisation`` says otherwise",
  which is a fact about records rather than a comparison against a label.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now, nowdate

from consilium.consilium_core import approvals, audit, delegation, notification, state_flags
from consilium.governance import charters, lifecycle

#: The state labels the flow writes. Configuration handed to the state map; the
#: flags are what any logic then reads.
STATE_DRAFT = "Draft"
STATE_SUBMITTED = "Submitted"
STATE_UNDER_EVALUATION = "Under Evaluation"
STATE_RETURNED = "Returned To Originator"
STATE_PENDING_APPROVAL = "Pending Approval"
STATE_EXCEPTION = "Exception Review"
STATE_APPROVED = "Approved"
STATE_REJECTED = "Rejected"
STATE_WITHDRAWN = "Withdrawn"

#: The G-5 criteria. Seeded onto a new request so the five are always present.
CRITERIA = (
    "Gap In Coverage",
    "Duplication",
    "Escalation Pathway",
    "Framework Alignment",
    "Resource Feasibility",
)

UNASSESSED = "Not Assessed"

#: The forum state an approved request creates the forum in.
NEW_FORUM_STATUS = "Draft"

REQUEST_CREATE = "Create"


def _set_state(request, state: str):
    request.workflow_state = state
    request.flags.consilium_formation = True
    request.save(ignore_permissions=True)
    return request


def _notify(event_code: str, user: str, request: str, **context) -> list[str]:
    """Raise a formation event through Core's event API.

    The wording is the ``Notification Template`` seeded for the event, so an
    administrator can change it without a release; with no active template Core
    records the built-in wording on the record channel, so the evidence that the
    person was told survives a template being switched off.
    """
    if not user:
        return []
    return notification.notify(
        event_code, [user], context,
        subject_doctype="Committee Formation Request", subject_name=request,
    )


def share_with_originator(request) -> str | None:
    """Give the request's originator read and write on their own request.

    Anyone may be named as a request's originator — a business executive with
    no governance role at all is the usual case — but the DocType's permissions
    are by role, so an originator without one could not open what they had
    raised, answer its questions or withdraw it: the respond and withdraw doors
    exist for them and they could not reach either. A document share is the
    framework's own per-record grant, so every read path — the review page, the
    REST interface, lists — honours it without a permission hook.

    Write is part of the grant because answering and withdrawing need it; it
    is not a way round the flow: the controller refuses edits whenever the
    state's ``is_editable`` flag is off, and every action still asks the
    formation stage rules.
    """
    user = request.get("requester")
    if not user or user in frappe.STANDARD_USERS or not frappe.db.exists("User", user):
        return None
    existing = frappe.db.get_value(
        "DocShare", {"share_doctype": request.doctype, "share_name": request.name, "user": user},
        ["name", "read", "write"], as_dict=True,
    )
    if existing and existing.read and existing.write:
        return existing.name
    from frappe.share import add_docshare

    share = add_docshare(
        request.doctype, request.name, user, read=1, write=1, notify=0,
        flags={"ignore_share_permission": True},
    )
    return share.name if share else None


def seed_criteria(request) -> None:
    """Every G-5 criterion present, each awaiting a finding."""
    present = {row.criterion for row in request.get("evaluations") or []}
    for criterion in CRITERIA:
        if criterion not in present:
            request.append("evaluations", {"criterion": criterion, "assessment": UNASSESSED})


def unassessed_criteria(request) -> list[str]:
    return [row.criterion for row in request.evaluations if row.assessment == UNASSESSED]


def duplicate_check(request) -> str:
    """The G-7 overlap check: forums that already cover this ground."""
    filters = {"is_active": 1}
    if request.forum_type:
        filters["forum_type"] = request.forum_type
    if request.primary_risk_category:
        filters["primary_risk_category"] = request.primary_risk_category
    candidates = frappe.get_all(
        "Governance Forum", filters=filters, fields=["name", "forum_name"], limit=25
    )
    if not candidates:
        return _("No existing forum shares this forum type and primary risk category.")
    listed = "; ".join(f"{row['name']} {row['forum_name']}" for row in candidates)
    return _("{0} existing forum(s) share this forum type and primary risk category: {1}").format(
        len(candidates), listed
    )


# ------------------------------------------------------------ transitions
#
# `submit` and `respond_to_return` are whitelisted because the portal has to be
# able to call them. Without that, a screen can only move the request by writing
# its state over the REST interface — which sets the state and the semantic flags
# correctly, and silently skips everything the transition does around them. For
# submission that means the duplicate check never runs, so two identical forums
# can be requested and nobody is told. A transition that can be bypassed by
# writing a field is not a transition.


@frappe.whitelist(methods=["POST"])
def submit_request(request: str):
    """Submit a formation request. The portal's entry point."""
    doc = frappe.get_doc("Committee Formation Request", request)
    doc.check_permission("write")
    # Only a draft is submitted. Unguarded, a second submission of a request
    # already in evaluation or pending approval would drop it back to the start.
    if "submit" not in stage_actions(doc):
        frappe.throw(
            _("Request {0} has already been sent; it is {1}.").format(doc.name, doc.workflow_state),
            title=_("Already Submitted"),
        )
    return submit(doc)


@frappe.whitelist(methods=["POST"])
def respond_to_returned_request(request: str, response: str):
    """The originator's reply to a returned request. The portal's entry point."""
    doc = frappe.get_doc("Committee Formation Request", request)
    doc.check_permission("write")
    # Without this, a reply could be posted to a request that was never
    # returned, and it would be moved straight back into evaluation from
    # wherever it was — including out of a pending approval.
    _authorise(doc, "respond")
    return respond_to_return(doc, response)


def submit(request):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    require_materiality(request, _("submitted"))
    request.duplicate_check_result = duplicate_check(request)
    return _set_state(request, STATE_SUBMITTED)


def start_evaluation(request):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    return _set_state(request, STATE_UNDER_EVALUATION)


def return_to_originator(request, questions: str, *, by: str | None = None):
    """A transition, not a comment. The exchange stays on the record."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (questions or "").strip():
        frappe.throw(
            _("Returning a request needs the questions the originator must answer."),
            title=_("Questions Required"),
        )
    request.return_questions = questions
    request.returned_on = now()
    request.returned_by = by or frappe.session.user
    _set_state(request, STATE_RETURNED)
    _notify("governance.formation.returned", request.requester, request.name, questions=questions)
    return request


def respond_to_return(request, response: str):
    """The originator's half of the exchange, then back into evaluation."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (response or "").strip():
        frappe.throw(_("A response is needed before the request goes back."), title=_("Response Required"))
    request.originator_response = response
    return _set_state(request, STATE_UNDER_EVALUATION)


# --------------------------------------------------------------- approval


#: A route's value for "this route does not narrow on that dimension". A
#: configuration option label, never a state.
ROUTE_ANY = "Any"


def _route_fit(route: dict, request) -> tuple | None:
    """How specifically ``route`` fits ``request``, or None when it does not.

    G-8 lets the approval path differ by the kind of request, the forum type and
    the materiality of the change. A route narrows on any of the three: each it
    names must equal the request's, and each it leaves open (``Any``, or no
    forum type) fits every request. The fit is ordered so that the route naming
    the most dimensions wins; between routes naming as many, one written for a
    forum type is preferred to one written for a materiality, and that to one
    written for a request type — the forum type is the most deliberate choice an
    administrator makes, because it settles how much authority the forum holds.
    The final tie-break, most recently modified, is the caller's.
    """
    named_type = bool(route.get("request_type") and route["request_type"] != ROUTE_ANY)
    named_forum = bool(route.get("forum_type"))
    named_materiality = bool(route.get("change_materiality") and route["change_materiality"] != ROUTE_ANY)
    if named_type and route["request_type"] != request.get("request_type"):
        return None
    if named_forum and route["forum_type"] != request.get("forum_type"):
        return None
    if named_materiality and route["change_materiality"] != request.get("change_materiality"):
        return None
    return (named_type + named_forum + named_materiality, named_forum, named_materiality, named_type)


def matching_routes(request) -> list[dict]:
    """Every active route that fits the request, the one that applies first."""
    routes = frappe.get_all(
        "Formation Approval Route",
        filters={"is_active": 1},
        fields=["name", "request_type", "forum_type", "change_materiality", "modified"],
        order_by="modified desc",
    )
    fitting = [(fit, route) for route in routes if (fit := _route_fit(route, request)) is not None]
    # Stable sort: among equal fits the most recently modified stays first.
    fitting.sort(key=lambda pair: pair[0], reverse=True)
    return [route for _fit, route in fitting]


def resolve_route(request):
    """The configured route for this request: the most specific active match.

    Selection reads configuration only (see ``_route_fit``). A request whose
    route names neither its forum type nor its materiality still falls back to a
    route for its request type, and then to one for any request, exactly as
    before those two dimensions existed.
    """
    routes = matching_routes(request)
    return frappe.get_doc("Formation Approval Route", routes[0]["name"]) if routes else None


#: The request type whose intake must say how material the change is (G-8).
#: A configuration option of ``request_type``, never a workflow state.
REQUEST_MODIFY = "Modify"


def require_materiality(request, attempted: str) -> None:
    """A change to an existing forum states its materiality before it moves on.

    The materiality chooses the approval path (``resolve_route``), so a change
    request without one would be routed as if nobody had assessed it. Drafts
    may be saved without it; submitting and seeking approval may not, and the
    refusal is audited like every other control on the request.
    """
    if request.get("request_type") != REQUEST_MODIFY or request.get("change_materiality"):
        return
    audit.refuse(
        _("Request {0} changes an existing forum, so it must say how material the change is (Minor, "
          "Significant or Material) before it can be {1}. The materiality chooses the approval path.").format(
            request.name, attempted),
        subject_doctype=request.doctype,
        subject_name=request.name,
        attempted_action="Other",
        control="formation change materiality",
        exc=frappe.ValidationError,
    )


def _assignee(request, step) -> str | None:
    if step.assign_to_user:
        return step.assign_to_user
    if step.assign_to_field and request.meta.has_field(step.assign_to_field):
        return request.get(step.assign_to_field)
    if step.required_role:
        # A role-based step goes to the role's queue (see `role_queue`). The
        # decision row still names one accountable person — Core needs one —
        # and that is the queue's first member; any other member may take the
        # step by deciding it (see `_claim_queued_step`).
        return _role_holder(step.required_role, request)
    return None


def _is_role_based(step) -> bool:
    """A route step that names a role and nobody in particular."""
    return bool(step.required_role and not step.assign_to_user and not step.assign_to_field)


def raise_approval_steps(request) -> list[str]:
    """Turn the configured route into Core approval decisions."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)

    unassessed = unassessed_criteria(request)
    if unassessed:
        frappe.throw(
            _("Every evaluation criterion needs a finding before approval is sought. Outstanding: {0}.").format(
                ", ".join(unassessed)
            ),
            title=_("Evaluation Incomplete"),
        )
    if not request.completeness_confirmed:
        frappe.throw(
            _("The G-7 completeness confirmation gates progression. Confirm it first."),
            title=_("Completeness Not Confirmed"),
        )
    require_materiality(request, _("sent for approval"))

    route = resolve_route(request)
    if not route:
        frappe.throw(
            _("No active formation approval route is configured. Approval steps are configuration."),
            title=_("No Approval Route"),
        )

    raised = []
    for step in sorted(route.steps, key=lambda row: (row.step_sequence, row.idx)):
        if not step.is_active:
            continue
        assignee = _assignee(request, step)
        if not assignee:
            frappe.throw(
                _("Approval step {0} has nobody to decide it.").format(step.step_title),
                title=_("Step Unassigned"),
            )
        existing = frappe.db.exists(
            "Approval Decision",
            {"subject_doctype": request.doctype, "subject_name": request.name,
             "approval_step": step.step_title},
        )
        if existing:
            raised.append(existing)
            continue
        decision = approvals.request_decision(
            subject_doctype=request.doctype,
            subject_name=request.name,
            approval_step=step.step_title,
            step_sequence=step.step_sequence,
            mode=step.mode,
            required_role=step.required_role,
            assigned_to=assignee,
        )
        raised.append(decision.name)
        # A role-based step is announced to its whole queue, as an escalation
        # routed to a role is (E-5, E-8): whoever of them is free takes it.
        for person in (role_queue(step.required_role, request) if _is_role_based(step) else [assignee]):
            _notify("governance.formation.approval_requested", person, request.name,
                    step_title=step.step_title)

    request.approval_route = route.name
    _set_state(request, STATE_PENDING_APPROVAL)
    return raised


def outstanding_steps(request) -> list[str]:
    name = request if isinstance(request, str) else request.name
    return approvals.outstanding("Committee Formation Request", name)


def record_step_decision(request, approval_decision: str, decision: str, *, comments: str | None = None,
                         acting_user: str | None = None):
    """Record one step's decision through Core, which resolves any delegation.

    A member of a role-based step's queue takes the step first (see
    `_claim_queued_step`); anyone else is Core's to accept or refuse.
    """
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    _claim_queued_step(request, approval_decision, acting_user or frappe.session.user)
    return approvals.record_decision(
        approval_decision, decision, comments=comments, acting_user=acting_user
    )


def authorise_bypass(request, approval_decision: str, justification: str, *, approved_by: str | None = None,
                     exception_type: str = "Approval Bypass"):
    """Skip a step — only with a Core Exception Authorisation recording why.

    P-25's rule, applied here: a bypass without a documented authorisation is not
    available at all, so there is no path that produces an unexplained skip.
    """
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (justification or "").strip():
        audit.refuse(
            _("A step cannot be bypassed without a documented exception authorisation."),
            subject_doctype=request.doctype,
            subject_name=request.name,
            attempted_action="Other",
            control="approval bypass authorisation",
            exc=frappe.ValidationError,
        )
    # Segregation of duties: a bypass is one person excusing another's check,
    # so nobody excuses a check that is theirs to make — as its assignee, as a
    # delegate of the assignee, or as a member of the step's role queue.
    # Without this the designated authority, named on a step, could skip their
    # own approval and record it as an exception.
    step_row = frappe.db.get_value(
        "Approval Decision", approval_decision,
        ["name", "approval_step", "assigned_to", "required_role"], as_dict=True,
    ) or frappe._dict()
    for person in {frappe.session.user, approved_by or frappe.session.user}:
        if step_row and may_decide(request, step_row, person):
            audit.refuse(
                _("{0} may not bypass approval step {1} on {2}: it is theirs to decide, and nobody "
                  "excuses their own approval.").format(person, step_row.approval_step, request.name),
                subject_doctype=request.doctype,
                subject_name=request.name,
                attempted_action="Other",
                control="segregation of duties",
                context={"approval_decision": approval_decision, "user": person},
            )
    authorisation = frappe.get_doc(
        {
            "doctype": "Exception Authorisation",
            "subject_doctype": request.doctype,
            "subject_name": request.name,
            "exception_type": exception_type,
            "justification": justification,
            "requested_by": frappe.session.user,
            "approved_by": approved_by or frappe.session.user,
            "approved_on": now(),
        }
    ).insert(ignore_permissions=True)
    # The step is marked bypassed against its own assignee, because the step is
    # not being decided by someone else — it is being skipped. Who authorised the
    # skip, and why, is on the Exception Authorisation, which is the record P-25
    # requires.
    approvals.record_decision(
        approval_decision, "Bypassed", comments=justification,
        acting_user=frappe.db.get_value("Approval Decision", approval_decision, "assigned_to"),
        exception_authorisation=authorisation.name,
    )
    request.db_set("exception_authorisation", authorisation.name, update_modified=False)
    return authorisation


# -------------------------------------------------------- exception route


def raise_exception(request, rationale: str, *, authority: str | None = None):
    """The G-17 dispute path: route to the designated authority, with a rationale."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (rationale or "").strip():
        frappe.throw(
            _("An exception needs a recorded rationale before it is routed."),
            title=_("Rationale Required"),
        )
    authority = authority or _role_holder("Head of Risk Governance")
    if not authority:
        frappe.throw(
            _("No Head of Risk Governance is available to resolve the exception."),
            title=_("No Designated Authority"),
        )
    request.exception_raised = 1
    request.exception_rationale = rationale
    _set_state(request, STATE_EXCEPTION)
    decision = approvals.request_decision(
        subject_doctype=request.doctype,
        subject_name=request.name,
        approval_step="Exception Resolution",
        step_sequence=99,
        # The dispute path is not a step of the route: it is raised because the
        # route is stuck, so it cannot wait for the route's open steps to clear
        # (which sequential ordering would otherwise demand of a step at 99).
        mode="Parallel",
        assigned_to=authority,
        required_role="Head of Risk Governance" if frappe.db.exists("Role", "Head of Risk Governance") else None,
    )
    _notify("governance.formation.exception_raised", authority, request.name, rationale=rationale)
    return decision


def resolve_exception(request, resolution: str, *, approval_decision: str | None = None,
                      decision: str = "Approved", acting_user: str | None = None):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (resolution or "").strip():
        frappe.throw(_("An exception is closed with a recorded resolution."), title=_("Resolution Required"))
    if approval_decision:
        # The designated authority decides it; anyone else needs a live delegation,
        # which Core resolves and records.
        acting_user = acting_user or frappe.db.get_value(
            "Approval Decision", approval_decision, "assigned_to"
        )
        approvals.record_decision(
            approval_decision, decision, comments=resolution, acting_user=acting_user
        )
    request.exception_resolution = resolution
    return _set_state(request, STATE_PENDING_APPROVAL)


def role_queue(role: str | None, request=None) -> list[str]:
    """Everyone a role-based step may go to, most suitable first.

    A role is a queue, not a person — the same reading escalation assignment
    gives it (E-5, E-8). Its members are the role's holders who are enabled,
    desk users (a website-only account cannot open the review screen), and not
    the framework's built-in accounts.

    The order matters only for the one name Core's decision row must carry,
    and it used to be the alphabet. On a site where tests had ever been run
    that put a throwaway account at the head of the queue, and every role-based
    step went to it. The order is now, most suitable first:

    1. holders who sit on a live forum of the request's owning operating group
       — the nearest thing to "in scope" the data model records about a
       person, since accounts carry no organisation of their own;
    2. holders who have ever signed in — an account that never has is not
       staffing anything, whether it is a leftover test account or someone who
       has not started yet;
    3. the account name, so the choice is the same on every run.

    Nobody is excluded for failing 1 or 2: a queue whose members have not yet
    signed in (a fresh installation) still has members.
    """
    if not role:
        return []
    holders = set(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
    holders -= set(frappe.STANDARD_USERS)
    if not holders:
        return []
    people = frappe.get_all(
        "User",
        filters={"name": ["in", sorted(holders)], "enabled": 1, "user_type": "System User"},
        fields=["name", "last_login"],
    )
    in_scope = _seated_in_group(
        [row.name for row in people], request.get("owning_operating_group") if request else None
    )
    people.sort(key=lambda row: (row.name not in in_scope, not row.last_login, row.name))
    return [row.name for row in people]


def _seated_in_group(users: list[str], operating_group: str | None) -> set[str]:
    """Which of ``users`` hold an open seat on a live forum of the group."""
    if not users or not operating_group:
        return set()
    forums = frappe.get_all(
        "Governance Forum", filters={"owning_operating_group": operating_group, "is_active": 1}, pluck="name"
    )
    if not forums:
        return set()
    membership = frappe.qb.DocType("Forum Membership")
    rows = (
        frappe.qb.from_(membership)
        .select(membership.member)
        .where(
            membership.forum.isin(forums)
            & membership.member.isin(users)
            & (membership.end_date.isnull() | (membership.end_date >= nowdate()))
        )
        .run(pluck=True)
    )
    return set(rows)


def _role_holder(role: str, request=None) -> str | None:
    """The one person a role-based step's decision row names: the head of the
    role's queue (see `role_queue`), or nobody if the queue is empty."""
    queue = role_queue(role, request)
    return queue[0] if queue else None


def _route_step(request, approval_step: str):
    """The configured route step a decision was raised from, if any."""
    if not request.approval_route:
        return None
    for step in frappe.get_doc("Formation Approval Route", request.approval_route).steps:
        if step.step_title == approval_step:
            return step
    return None


def queued_role(request, decision_row) -> str | None:
    """The role whose queue may decide this step, when it was raised from a
    role-based route step; None for a step raised against a named person.

    Read from the route rather than from the decision's ``required_role``: the
    exception step also names a role, but it is routed to one designated
    authority, and another holder of that role acts for them only under a
    delegation.
    """
    role = decision_row.get("required_role")
    if not role:
        return None
    step = _route_step(request, decision_row.get("approval_step"))
    return role if step is not None and _is_role_based(step) else None


def may_decide(request, decision_row, user: str | None = None) -> bool:
    """Whether ``user`` may decide this step: its assignee, a live delegate of
    the assignee (Core's answer), or a member of the step's role queue."""
    user = user or frappe.session.user
    resolution = delegation.resolve_actor(
        decision_row.get("assigned_to"), delegation.ACTION_APPROVE, acting_user=user,
        doctype=request.doctype, name=request.name,
    )
    if resolution["permitted"]:
        return True
    role = queued_role(request, decision_row)
    return bool(role and user in role_queue(role, request))


def queued_steps_for(user: str) -> list[dict]:
    """Open role-based formation steps waiting in a queue ``user`` belongs to,
    and assigned to somebody else. The inbox lists them next to the steps
    assigned to the user, so the whole queue sees the work, not only its head."""
    roles = set(frappe.get_roles(user))
    rows = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Committee Formation Request", "is_open": 1,
                 "required_role": ["in", sorted(roles) or [""]], "assigned_to": ["!=", user]},
        fields=["name", "subject_doctype", "subject_name", "approval_step", "assigned_to", "required_role",
                "creation"],
        order_by="creation asc",
    )
    out = []
    for row in rows:
        request = frappe.get_doc("Committee Formation Request", row.subject_name)
        role = queued_role(request, row)
        if role and user in role_queue(role, request):
            out.append(row)
    return out


def _claim_queued_step(request, approval_decision: str, user: str) -> None:
    """A queue member deciding a role-based step takes it first.

    The step is re-pointed at them, through the document so the change is in
    the decision's tracked history, and Core then records the decision as
    theirs — which keeps Core the single place that decides who may act: it
    sees the assignee acting for themselves. Nothing happens when the caller
    already is the assignee or acts under a delegation from them.
    """
    row = frappe.get_doc("Approval Decision", approval_decision)
    if row.assigned_to == user:
        return
    if delegation.resolve_actor(row.assigned_to, delegation.ACTION_APPROVE, acting_user=user,
                                doctype=request.doctype, name=request.name)["permitted"]:
        return
    role = queued_role(request, row)
    if role and user in role_queue(role, request):
        row.assigned_to = user
        row.save(ignore_permissions=True)


# ------------------------------------------------------------ the outcome


def approval_blockers(request) -> list[str]:
    """Everything standing between this request and approval. Facts, not labels."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    blockers = []
    unassessed = unassessed_criteria(request)
    if unassessed:
        blockers.append(_("evaluation criteria without a finding: {0}").format(", ".join(unassessed)))
    if not request.completeness_confirmed:
        blockers.append(_("the completeness confirmation is not given"))
    # Every open step blocks. A bypass closes the one step it names — Core marks
    # that decision bypassed against its own exception authorisation — so it
    # drops out of this list by itself. This used to be waived wholesale by the
    # request carrying *an* exception authorisation, which meant one bypass of
    # one step excused every other undecided step on the route.
    open_steps = outstanding_steps(request)
    if open_steps:
        blockers.append(
            _("{0} approval step(s) are undecided: {1}").format(
                len(open_steps),
                ", ".join(frappe.get_all("Approval Decision", filters={"name": ["in", open_steps]},
                                         pluck="approval_step", order_by="step_sequence asc")),
            )
        )
    # A step decided *against* the request is closed, so it drops out of the
    # outstanding list above — which, on its own, let a request be approved over
    # an approver's rejection. A closed decision whose flags say it needs review
    # (a rejection) blocks, unless the decision itself carries an exception
    # authorisation (a recorded bypass). Flags, not the decision's label.
    refused_steps = [
        row["approval_step"]
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": request.doctype, "subject_name": request.name,
                     "is_open": 0, "requires_review": 1},
            fields=["approval_step", "exception_authorisation"],
        )
        if not row["exception_authorisation"]
    ]
    if refused_steps:
        blockers.append(
            _("approval was refused at: {0}").format(", ".join(refused_steps))
        )
    # G-7: the risk governance office challenges the draft charter before final
    # approval, and an unresolved challenge blocks it (E33-S1). Read from each
    # charter's `requires_review` flag, never its challenge label. A request with
    # no charter drafted against it is not blocked here: G-7 requires that a
    # drafted charter can be challenged, not that every request carries one.
    challenged = charters.challenge_blocker_text(charters.uncleared_challenges(formation_request=request.name))
    if challenged:
        blockers.append(challenged)
    return blockers


def approve(request):
    """Approve the request, and create the forum it asked for."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)

    blockers = approval_blockers(request)
    if blockers:
        audit.refuse(
            _("Request {0} cannot be approved: {1}.").format(request.name, "; ".join(blockers)),
            subject_doctype=request.doctype,
            subject_name=request.name,
            attempted_action="Other",
            control="formation approval gate",
            context={"blockers": blockers},
            exc=frappe.ValidationError,
        )

    request.decided_on = nowdate()
    _set_state(request, STATE_APPROVED)
    forum = create_forum(request)
    if forum:
        request.db_set("created_forum", forum.name, update_modified=False)
    _notify("governance.formation.approved", request.requester, request.name)
    return request


def reject(request, reason: str):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (reason or "").strip():
        frappe.throw(_("A rejection is recorded with its reason."), title=_("Reason Required"))
    request.exception_resolution = reason
    request.decided_on = nowdate()
    _set_state(request, STATE_REJECTED)
    _notify("governance.formation.rejected", request.requester, request.name, reason=reason)
    return request


def withdraw(request, reason: str):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    request.exception_resolution = reason
    return _set_state(request, STATE_WITHDRAWN)


def create_forum(request):
    """An approved create request produces a forum in draft, linked both ways.

    Only from the state whose semantic flag says the request is committable. A
    modify or retire request has no forum to create; it marks its subject for
    review instead.
    """
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not request.is_committable:
        frappe.throw(
            _("Request {0} is not in a state from which a forum may be created.").format(request.name),
            title=_("Not Approved"),
        )
    if request.created_forum:
        return frappe.get_doc("Governance Forum", request.created_forum)

    if request.request_type != REQUEST_CREATE:
        if request.subject_forum:
            lifecycle.set_forum_state(request.subject_forum, lifecycle.setup.FORUM_REVIEW_STATE)
        return None

    forum = frappe.get_doc(
        {
            "doctype": "Governance Forum",
            "forum_name": request.forum_name,
            "forum_type": request.forum_type,
            "description": request.purpose_scope,
            "cadence": request.cadence or "Quarterly",
            "sponsor": request.forum_sponsor,
            "primary_risk_category": request.primary_risk_category,
            "owning_operating_group": request.owning_operating_group,
            "owning_line_of_business": request.owning_line_of_business,
            "parent_forum": request.parent_forum,
            "escalation_protocol": request.proposed_responsibilities,
            "quorum_rule_type": "Count",
            "quorum_value": 1,
            "compliance_status": NEW_FORUM_STATUS,
            "formation_request": request.name,
            "established_on": request.proposed_timeline,
        }
    )
    for row in request.get("jurisdictions") or []:
        forum.append("jurisdictions", {"jurisdiction": row.jurisdiction})
    for row in request.get("owning_business_units") or []:
        forum.append("business_units", {"business_unit": row.business_unit})
    forum.flags.consilium_lifecycle = True
    forum.insert(ignore_permissions=True)
    return forum


# ------------------------------------------------------- portal entry points
#
# The governance office's screens call what follows. Each entry point is thin:
# load the request, check the framework's document permission, check the caller
# holds the role the action belongs to, check the request is at a stage where
# the action exists, then hand over to the transition above. None of them takes
# a state from the client — the comment above `submit_request` says why.
#
# The transitions themselves do not check the stage (the tests drive them
# straight through, and other modules may too), so the stage gate lives here, at
# the only door the browser can reach. Without it, "start evaluation" posted
# against an approved request would quietly reopen it.
#
# Which stage a request is at is read from its semantic flags plus one fact —
# whether approval has been sought — and never from its state label. Two states
# carry identical flags (submitted, and pending approval); the fact tells them
# apart, because a request pending approval has approval decisions raised
# against it. A renamed or inserted state stays an afternoon's configuration.

#: Roles are access configuration, not workflow states. The office evaluates and
#: administers a request; the designated authority settles a dispute and
#: authorises a skipped step. Whoever a step is assigned to decides that step,
#: whatever roles they hold — Core resolves the assignee and any delegation, so
#: step decisions are deliberately absent from this map.
GOVERNANCE_OFFICE = "Risk Governance Office"
DESIGNATED_AUTHORITY = "Head of Risk Governance"

#: The DocType already grants this role every right over the record, so refusing
#: it here would only move the same work to the desk, without the stage gate.
SUPERUSER_ROLES = ("System Manager",)

ACTION_ROLES = {
    "start_evaluation": (GOVERNANCE_OFFICE,),
    "return_to_originator": (GOVERNANCE_OFFICE,),
    "record_findings": (GOVERNANCE_OFFICE,),
    "raise_approval_steps": (GOVERNANCE_OFFICE,),
    "raise_exception": (GOVERNANCE_OFFICE, DESIGNATED_AUTHORITY),
    "resolve_exception": (DESIGNATED_AUTHORITY,),
    "authorise_bypass": (DESIGNATED_AUTHORITY,),
    "approve": (GOVERNANCE_OFFICE, DESIGNATED_AUTHORITY),
    "reject": (GOVERNANCE_OFFICE, DESIGNATED_AUTHORITY),
    "withdraw": (GOVERNANCE_OFFICE,),
    "respond": (GOVERNANCE_OFFICE,),
}

#: The originator may withdraw their own request and answer its questions
#: without holding a governance role. The office may also enter a reply it
#: received some other way, which is why `respond` is in both places.
ORIGINATOR_ACTIONS = ("withdraw", "respond")

ACTION_LABELS = {
    "submit": _("Submit"),
    "start_evaluation": _("Start evaluation"),
    "return_to_originator": _("Return to originator"),
    "record_findings": _("Record criterion findings"),
    "raise_approval_steps": _("Raise approval steps"),
    "record_step_decision": _("Record step decision"),
    "raise_exception": _("Raise an exception"),
    "resolve_exception": _("Resolve the exception"),
    "authorise_bypass": _("Authorise a bypass"),
    "approve": _("Approve"),
    "reject": _("Reject"),
    "withdraw": _("Withdraw"),
    "respond": _("Respond to the questions"),
}

#: The decisions a step's assignee may record. `Pending` is where a step starts
#: and `Bypassed` is only reachable through an exception authorisation, so
#: neither is offered. These are values handed to Core, never compared.
STEP_DECISIONS = ("Approved", "Rejected", "Changes Requested", "Abstained")

#: What an exception's resolution may record against the authority's step.
EXCEPTION_DECISIONS = ("Approved", "Rejected")


def approval_sought(request) -> bool:
    """A fact, not a label: approval decisions have been raised on this request."""
    return bool(
        frappe.db.exists(
            "Approval Decision", {"subject_doctype": request.doctype, "subject_name": request.name}
        )
    )


def stage_of(request) -> str:
    """Where the request stands, as this module's own vocabulary, from its flags.

    Read from the semantic flags (see ``state_flag_seed.py``) and one fact:

    * inactive — closed (rejected or withdrawn);
    * committable — approved;
    * editable and needing a statement — back with the originator for answers;
    * editable otherwise — the originator's draft;
    * needing review and a statement — an exception awaiting its authority;
    * needing review otherwise — being evaluated;
    * otherwise open — awaiting approval once approval has been sought, and
      awaiting evaluation before that.

    The keys are not state labels and are never written to the record; they
    exist so a screen can say where a request is without reading its label.
    """
    if not request.is_active:
        return "closed"
    if request.is_committable:
        return "approved"
    if request.is_editable:
        return "with_originator" if request.requires_statement else "draft"
    if request.requires_review:
        return "exception" if request.requires_statement else "evaluation"
    if approval_sought(request):
        return "approval"
    return "awaiting_evaluation"


_CLOSING = ("reject", "withdraw")

#: What each stage offers, whoever is asking. Who may take each is `ACTION_ROLES`.
STAGE_ACTIONS = {
    "closed": (),
    "approved": (),
    "draft": ("submit", "withdraw"),
    "with_originator": ("respond", *_CLOSING),
    "awaiting_evaluation": ("start_evaluation", "return_to_originator", *_CLOSING),
    "evaluation": ("record_findings", "return_to_originator", "raise_approval_steps", "raise_exception",
                   *_CLOSING),
    "exception": ("resolve_exception", *_CLOSING),
    "approval": ("record_step_decision", "authorise_bypass", "raise_exception", "approve", *_CLOSING),
}


def stage_actions(request) -> set[str]:
    """The actions the request's stage allows, whoever is asking."""
    stage = stage_of(request)
    actions = set(STAGE_ACTIONS[stage])
    if stage == "approval" and not request.approval_route:
        # Approval was reached through an exception before the configured route
        # was raised; the route can still be raised from here.
        actions.add("raise_approval_steps")
    return actions


def _holds(roles, user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & (set(roles) | set(SUPERUSER_ROLES)))


def may_take(request, action: str, user: str | None = None) -> bool:
    """Whether the user's standing allows the action. Says nothing about stage."""
    user = user or frappe.session.user
    if action in ORIGINATOR_ACTIONS and user == request.requester:
        return True
    return _holds(ACTION_ROLES.get(action, ()), user)


def _authorise(request, action: str) -> None:
    """Refuse, with an audit record, an action the caller's role does not carry;
    then refuse one the request's stage does not offer."""
    if not may_take(request, action):
        holders = list(ACTION_ROLES.get(action, ()))
        if action in ORIGINATOR_ACTIONS:
            holders.insert(0, _("the request's originator"))
        audit.refuse(
            _("{0} may not take the action \"{1}\" on formation request {2}. It belongs to: {3}.").format(
                frappe.session.user, ACTION_LABELS[action], request.name, ", ".join(holders)
            ),
            subject_doctype=request.doctype,
            subject_name=request.name,
            attempted_action="Other",
            control="formation action role",
            context={"action": action},
        )
    if action not in stage_actions(request):
        frappe.throw(
            _("\"{0}\" is not available while request {1} is {2}.").format(
                ACTION_LABELS[action], request.name, request.workflow_state
            ),
            title=_("Not Available At This Stage"),
        )


def decidable_steps(request, user: str | None = None) -> list[str]:
    """Open approval decisions on this request that the user may decide.

    The assignee acts for themselves; anyone else needs a live delegation, which
    is Core's question to answer, so it is asked of Core — or, on a role-based
    step, membership of the role's queue (see `may_decide`).
    """
    user = user or frappe.session.user
    return [
        row["name"]
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": request.doctype, "subject_name": request.name, "is_open": 1},
            fields=["name", "assigned_to", "approval_step", "required_role"],
            order_by="step_sequence asc, creation asc",
        )
        if may_decide(request, row, user)
    ]


def bypassable_steps(request, user: str | None = None) -> list[str]:
    """Open steps the user could authorise a bypass of: every open step except
    those that are theirs to decide (segregation of duties, see
    `authorise_bypass`)."""
    user = user or frappe.session.user
    return [
        row["name"]
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": request.doctype, "subject_name": request.name, "is_open": 1},
            fields=["name", "assigned_to", "approval_step", "required_role"],
            order_by="step_sequence asc, creation asc",
        )
        if not may_decide(request, row, user)
    ]


def _open_decision_on(request, approval_decision: str):
    """The decision row, if it is an open step of this request. Refused otherwise."""
    row = frappe.db.get_value(
        "Approval Decision", approval_decision,
        ["name", "subject_doctype", "subject_name", "is_open", "approval_step", "assigned_to"],
        as_dict=True,
    )
    if not row or row.subject_doctype != request.doctype or row.subject_name != request.name:
        frappe.throw(
            _("Approval step {0} does not belong to request {1}.").format(approval_decision, request.name),
            title=_("Wrong Step"),
        )
    if not row.is_open:
        frappe.throw(
            _("Approval step {0} has already been decided.").format(row.approval_step),
            title=_("Step Already Decided"),
        )
    return row


def _needs_reason(decision: str, comments: str | None, what: str) -> None:
    """A decision that sends the request back for review carries its reason.

    Read from ``requires_review`` rather than ``is_affirmative``: the seed rows
    carry the latter, but Core's flag map does not yet load it, so it reads as
    false for every decision and would demand a reason for an approval too.
    """
    flags = state_flags.flags_for("Approval Decision", "decision", decision) or {}
    if flags.get("requires_review") and not (comments or "").strip():
        frappe.throw(
            _("{0} of \"{1}\" is recorded with its reason.").format(what, decision),
            title=_("Reason Required"),
        )


def record_findings(request, findings, *, completeness_confirmed=None, by: str | None = None):
    """The evaluator's findings against the G-5 criteria, and the G-7 confirmation.

    Only the criterion rows and the confirmation are touched. The request is
    locked to its originator while it is evaluated, so this writes through the
    transition flag rather than as an ordinary edit — the same way every other
    transition here does — and the controller still refuses a finding without a
    comment.
    """
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    findings = frappe.parse_json(findings) if isinstance(findings, str) else (findings or [])
    options = [
        option
        for option in (frappe.get_meta("Formation Evaluation").get_field("assessment").options or "").split("\n")
        if option
    ]
    rows = {row.criterion: row for row in request.evaluations}
    by = by or frappe.session.user
    for item in findings:
        criterion = item.get("criterion")
        assessment = item.get("assessment")
        comments = (item.get("comments") or "").strip()
        row = rows.get(criterion)
        if row is None:
            frappe.throw(
                _("{0} is not one of this request's evaluation criteria.").format(criterion),
                title=_("Unknown Criterion"),
            )
        if assessment not in options:
            frappe.throw(
                _("{0} is not a finding that can be recorded for {1}.").format(assessment, criterion),
                title=_("Unknown Finding"),
            )
        if row.assessment == assessment and (row.comments or "").strip() == comments:
            continue
        row.assessment = assessment
        row.comments = comments
        row.reviewed_by = by
        row.reviewed_on = now()
    if completeness_confirmed is not None:
        request.completeness_confirmed = cint(completeness_confirmed)
    request.flags.consilium_formation = True
    request.save(ignore_permissions=True)
    return request


def _decision_choice(decision: str) -> dict:
    """A decision the screen may offer, and whether it must carry a reason."""
    flags = state_flags.flags_for("Approval Decision", "decision", decision) or {}
    return {"decision": decision, "needs_reason": bool(flags.get("requires_review"))}


def review_context(request) -> dict:
    """Everything the review screen shows, and which actions it may offer.

    The screen does not work out what is allowed; it is told. Each action is on
    only when the stage offers it **and** the viewer's standing carries it — the
    same two checks the entry points make on the way in, so a button the screen
    shows is one the server will accept.
    """
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    user = frappe.session.user
    stage = stage_actions(request)
    decidable = set(decidable_steps(request, user)) if stage else set()
    # A sequential step whose predecessors are still open is the viewer's, but
    # not yet: Core would refuse it (E7-S4), so the screen does not offer it.
    decidable = {name for name in decidable if approvals.is_turn(name)}

    actions = {action: action in stage and may_take(request, action, user) for action in ACTION_ROLES}
    actions["record_step_decision"] = "record_step_decision" in stage and bool(decidable)
    # Segregation of duties: the steps offered for a bypass leave out the
    # viewer's own (see `authorise_bypass`), and with none left the action is off.
    bypassable = set(bypassable_steps(request, user)) if actions.get("authorise_bypass") else set()
    actions["authorise_bypass"] = bool(actions.get("authorise_bypass") and bypassable)

    decisions = frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": request.doctype, "subject_name": request.name},
        fields=["name", "approval_step", "step_sequence", "mode", "required_role", "assigned_to",
                "acted_by", "acting_delegation", "decision", "is_open", "requires_review", "decided_on", "comments", "exception_authorisation", "creation"],
        order_by="step_sequence asc, creation asc",
    )
    for row in decisions:
        row["can_decide"] = row["name"] in decidable
        row["can_bypass"] = row["name"] in bypassable

    exception = None
    if request.exception_authorisation:
        exception = frappe.db.get_value(
            "Exception Authorisation", request.exception_authorisation,
            ["name", "exception_type", "justification", "requested_by", "approved_by", "approved_on"],
            as_dict=True,
        )

    created_forum = None
    if request.created_forum:
        created_forum = {
            "name": request.created_forum,
            "forum_name": frappe.db.get_value("Governance Forum", request.created_forum, "forum_name"),
        }

    open_request = bool(request.is_active and not request.is_committable)
    assessment_field = frappe.get_meta("Formation Evaluation").get_field("assessment")
    return {
        "request": request.as_dict(convert_dates_to_str=True),
        "decisions": decisions,
        "blockers": approval_blockers(request) if open_request else [],
        "unassessed": unassessed_criteria(request),
        "actions": actions,
        "action_labels": ACTION_LABELS,
        "exception_authorisation": exception,
        "created_forum": created_forum,
        "assessment_options": [o for o in (assessment_field.options or "").split("\n") if o],
        "unassessed_value": UNASSESSED,
        "step_decisions": [_decision_choice(d) for d in STEP_DECISIONS],
        "exception_decisions": [_decision_choice(d) for d in EXCEPTION_DECISIONS],
        "stage": stage_of(request),
        "is_originator": user == request.requester,
        "is_open": open_request,
        "charter_challenge": _charter_challenge_context(request, open_request),
        "route": _route_summary(request),
    }


def _route_summary(request) -> dict | None:
    """The approval route this request follows, or would follow, and what chose it (G-8).

    Once steps are raised the request records its route; before that the route
    is the one ``resolve_route`` would pick now, so the path is visible before
    anyone is asked to decide.
    """
    name = request.get("approval_route")
    if not name:
        routes = matching_routes(request)
        name = routes[0]["name"] if routes else None
    if not name:
        return None
    row = frappe.db.get_value(
        "Formation Approval Route", name, ["name", "request_type", "forum_type", "change_materiality"], as_dict=True
    )
    if not row:
        return None
    chosen_by = []
    if row.forum_type:
        chosen_by.append(_("forum type {0}").format(
            frappe.db.get_value("Governance Forum Type", row.forum_type, "forum_type_name") or row.forum_type))
    if row.change_materiality and row.change_materiality != ROUTE_ANY:
        chosen_by.append(_("{0} change").format(row.change_materiality.lower()))
    if row.request_type and row.request_type != ROUTE_ANY:
        chosen_by.append(_("{0} request").format(row.request_type.lower()))
    return {"name": row.name, "raised": bool(request.get("approval_route")), "chosen_by": chosen_by}


def _charter_challenge_context(request, open_request: bool) -> dict:
    """The G-7 charter challenge as the review screen shows it (E33-S1).

    The charters drafted against the request, each with its challenge outcome,
    and whether this viewer may record one — the risk governance office, as
    ``charters.may_challenge`` says, and only while the request is undecided and
    the charter has a version to challenge. ``charters.record_charter_challenge``
    asks the same questions again on the way in and audits a refusal.
    """
    rows = frappe.get_all(
        "Committee Charter",
        filters={"formation_request": request.name},
        fields=["name", "charter_title", "rgo_challenge_status", "rgo_challenge_comments",
                "rgo_reviewed_by", "rgo_reviewed_on", "requires_review", "current_version"],
        order_by="name asc",
    )
    may = bool(open_request and charters.may_challenge())
    for row in rows:
        row["challenge_outstanding"] = bool(row.pop("requires_review"))
        row["rgo_reviewed_on"] = str(row["rgo_reviewed_on"]) if row["rgo_reviewed_on"] else None
        row["can_record"] = may and bool(row["current_version"])
    return {
        "charters": rows,
        "may_record": may,
        "options": charters.challenge_options() if may else [],
    }


def _load(request: str, ptype: str = "write"):
    doc = frappe.get_doc("Committee Formation Request", request)
    doc.check_permission(ptype)
    return doc


def _fresh(doc) -> dict:
    return review_context(frappe.get_doc(doc.doctype, doc.name))


@frappe.whitelist(methods=["GET"])
def get_request_review(request: str) -> dict:
    """The review screen's payload.

    Readable by anyone who may read the request, and by anyone asked to decide
    one of its steps — a sponsor or delegating authority often holds no
    governance role at all, and still has to see what they are approving.
    """
    doc = frappe.get_doc("Committee Formation Request", request)
    if not frappe.has_permission(doc.doctype, "read", doc=doc) and not decidable_steps(doc):
        frappe.throw(
            _("You do not have access to formation request {0}.").format(request),
            frappe.PermissionError,
        )
    return review_context(doc)


@frappe.whitelist(methods=["GET"])
def named_people() -> list[dict]:
    """The people a formation request may name as delegating authority or sponsor.

    A server method, for two reasons. The ``User`` list is readable only by
    system managers, so read over the REST interface it came back empty — or
    refused — for everyone else who raises a request. And read unfiltered it
    offered the framework's pseudo-users, who cannot delegate authority or
    sponsor anything, alongside disabled accounts and website-only users.
    """
    if not (
        frappe.has_permission("Committee Formation Request", "create")
        or frappe.has_permission("Committee Formation Request", "write")
    ):
        frappe.throw(_("You cannot raise or edit a formation request."), frappe.PermissionError)
    return frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User", "name": ["not in", list(frappe.STANDARD_USERS)]},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )


@frappe.whitelist(methods=["POST"])
def start_request_evaluation(request: str) -> dict:
    doc = _load(request)
    _authorise(doc, "start_evaluation")
    start_evaluation(doc)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def return_request_to_originator(request: str, questions: str) -> dict:
    doc = _load(request)
    _authorise(doc, "return_to_originator")
    return_to_originator(doc, questions)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def record_request_findings(request: str, findings, completeness_confirmed=None) -> dict:
    doc = _load(request)
    _authorise(doc, "record_findings")
    record_findings(doc, findings, completeness_confirmed=completeness_confirmed)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def raise_request_approval_steps(request: str) -> dict:
    doc = _load(request)
    _authorise(doc, "raise_approval_steps")
    raise_approval_steps(doc)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def record_request_step_decision(request: str, approval_decision: str, decision: str,
                                 comments: str | None = None) -> dict:
    """A step's assignee (or their delegate) decides it.

    No governance role is asked for and no document permission either: the
    right to decide a step comes from being assigned it, and Core refuses — and
    audits — anyone who is neither the assignee nor holding a live delegation.
    """
    doc = frappe.get_doc("Committee Formation Request", request)
    if "record_step_decision" not in stage_actions(doc):
        frappe.throw(
            _("\"{0}\" is not available while request {1} is {2}.").format(
                ACTION_LABELS["record_step_decision"], doc.name, doc.workflow_state
            ),
            title=_("Not Available At This Stage"),
        )
    _open_decision_on(doc, approval_decision)
    if decision not in STEP_DECISIONS:
        frappe.throw(_("{0} is not a decision a step can record.").format(decision), title=_("Unknown Decision"))
    _needs_reason(decision, comments, _("A decision"))
    record_step_decision(doc, approval_decision, decision, comments=comments, acting_user=frappe.session.user)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def authorise_request_bypass(request: str, approval_decision: str, justification: str) -> dict:
    doc = _load(request)
    _authorise(doc, "authorise_bypass")
    _open_decision_on(doc, approval_decision)
    authorise_bypass(doc, approval_decision, justification, approved_by=frappe.session.user)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def raise_request_exception(request: str, rationale: str) -> dict:
    doc = _load(request)
    _authorise(doc, "raise_exception")
    raise_exception(doc, rationale)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def resolve_request_exception(request: str, resolution: str, approval_decision: str | None = None,
                              decision: str = "Approved") -> dict:
    """The designated authority settles the exception.

    The authority's own step is decided as the caller, not as its assignee, so
    Core's delegation check applies: another holder of the role needs a live
    delegation from the assignee, as they would for any other step.
    """
    doc = _load(request)
    _authorise(doc, "resolve_exception")
    if decision not in EXCEPTION_DECISIONS:
        frappe.throw(_("{0} is not a decision an exception can record.").format(decision),
                     title=_("Unknown Decision"))
    if not approval_decision:
        # The authority's step is the latest open one they may decide.
        candidates = decidable_steps(doc)
        approval_decision = candidates[-1] if candidates else None
    if approval_decision:
        _open_decision_on(doc, approval_decision)
    resolve_exception(doc, resolution, approval_decision=approval_decision, decision=decision,
                      acting_user=frappe.session.user)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def approve_request(request: str) -> dict:
    doc = _load(request)
    _authorise(doc, "approve")
    approve(doc)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def reject_request(request: str, reason: str) -> dict:
    doc = _load(request)
    _authorise(doc, "reject")
    reject(doc, reason)
    return _fresh(doc)


@frappe.whitelist(methods=["POST"])
def withdraw_request(request: str, reason: str) -> dict:
    """Withdrawal is recorded with its reason, even though the transition allows none:
    a request that simply disappears from the queue leaves nobody able to say why."""
    doc = _load(request, "read")
    _authorise(doc, "withdraw")
    if not (reason or "").strip():
        frappe.throw(_("A withdrawal is recorded with its reason."), title=_("Reason Required"))
    withdraw(doc, reason)
    return _fresh(doc)
