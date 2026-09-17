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
  machinery the rest of the platform uses.
* **No step is skipped without a recorded exception.** The gate is "no open
  approval decisions, unless a Core ``Exception Authorisation`` says otherwise",
  which is a fact about records rather than a comparison against a label.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now, nowdate

from consilium.consilium_core import approvals, audit, notification
from consilium.governance import lifecycle

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


def _notify(user: str, subject: str, body: str, request: str) -> None:
    if not user or not frappe.db.exists("Notification Channel", lifecycle.DEFAULT_CHANNEL):
        return
    notification.dispatch(
        lifecycle.DEFAULT_CHANNEL, user, subject=subject, body=body,
        subject_doctype="Committee Formation Request", subject_name=request,
    )


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


def submit(request):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
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
    _notify(request.requester, _("Formation request returned with questions"),
            _("Request {0} was returned to you: {1}").format(request.name, questions), request.name)
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


def resolve_route(request):
    """The configured route for this request. Most specific active route wins."""
    for filters in ({"request_type": request.request_type, "is_active": 1},
                    {"request_type": "Any", "is_active": 1}):
        names = frappe.get_all(
            "Formation Approval Route", filters=filters, pluck="name", order_by="modified desc", limit=1
        )
        if names:
            return frappe.get_doc("Formation Approval Route", names[0])
    return None


def _assignee(request, step) -> str | None:
    if step.assign_to_user:
        return step.assign_to_user
    if step.assign_to_field and request.meta.has_field(step.assign_to_field):
        return request.get(step.assign_to_field)
    if step.required_role:
        holders = frappe.get_all(
            "Has Role", filters={"role": step.required_role, "parenttype": "User"}, pluck="parent", limit=1
        )
        return holders[0] if holders else None
    return None


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
        _notify(assignee, _("Formation approval requested"),
                _("Request {0} awaits your decision at step {1}.").format(request.name, step.step_title),
                request.name)

    request.approval_route = route.name
    _set_state(request, STATE_PENDING_APPROVAL)
    return raised


def outstanding_steps(request) -> list[str]:
    name = request if isinstance(request, str) else request.name
    return approvals.outstanding("Committee Formation Request", name)


def record_step_decision(request, approval_decision: str, decision: str, *, comments: str | None = None,
                         acting_user: str | None = None):
    """Record one step's decision through Core, which resolves any delegation."""
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
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
        assigned_to=authority,
        required_role="Head of Risk Governance" if frappe.db.exists("Role", "Head of Risk Governance") else None,
    )
    _notify(authority, _("Formation exception raised"),
            _("Request {0} was routed to you as an exception: {1}").format(request.name, rationale),
            request.name)
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


def _role_holder(role: str) -> str | None:
    holders = frappe.get_all(
        "Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent", limit=1
    )
    return holders[0] if holders else None


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
    open_steps = outstanding_steps(request)
    if open_steps and not request.exception_authorisation:
        blockers.append(
            _("{0} approval step(s) are undecided and no exception authorisation is recorded").format(
                len(open_steps)
            )
        )
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
    _notify(request.requester, _("Formation request approved"),
            _("Request {0} was approved.").format(request.name), request.name)
    return request


def reject(request, reason: str):
    if isinstance(request, str):
        request = frappe.get_doc("Committee Formation Request", request)
    if not (reason or "").strip():
        frappe.throw(_("A rejection is recorded with its reason."), title=_("Reason Required"))
    request.exception_resolution = reason
    request.decided_on = nowdate()
    _set_state(request, STATE_REJECTED)
    _notify(request.requester, _("Formation request rejected"),
            _("Request {0} was rejected: {1}").format(request.name, reason), request.name)
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
