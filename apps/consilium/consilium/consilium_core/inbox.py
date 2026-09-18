"""The personal inbox (CS-10): everything waiting on one person, across modules.

Before this existed, work waiting on someone was scattered over six record
types, and for two of them — attestation tasks and approval decisions — only an
administrator could even list it, because those DocTypes grant nobody else a
right. The people asked to attest or decide had no way to find out that they
had been asked.

How each kind is read, and why it is not all one query:

* **Attestation tasks and approval decisions** are read directly, filtered to
  the caller. Their DocTypes are closed to ordinary users on purpose — the
  right to act on one comes from being named on it, not from a role — so the
  permission engine would return nothing. Being the assignee (or holding a
  live delegation from the assignee, judged by Core's delegation engine) is the
  entitlement, and it is exactly what the filter asks.
* **Everything else** — documents, forums, escalations, action plans,
  remediation tasks, formation requests — is read through the permission
  engine (`frappe.get_list`), so the restricted-record rules apply. A record the
  caller may not read is not shown, even if they are named on it, because the
  screen it links to would refuse them; an inbox entry that opens onto a
  refusal is worse than none.

Nothing here reads a workflow state label. "Waiting" is read from the semantic
flags (`is_open`, `requires_review`, `is_editable`, `requires_statement`) and
from dates.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import approvals, delegation

#: How far ahead a review date counts as "due" rather than merely scheduled.
DUE_SOON_DAYS = 30

#: The portal screen each record type opens on. A type with no portal screen
#: falls back to its desk form.
SCREENS = {
    "Committee Formation Request": "/formation-request?name={}",
    "Governing Document": "/policy?name={}",
    "Escalation Matter": "/escalation?name={}",
    "Governance Forum": "/forum?name={}",
}

#: The groups, in the order the page shows them, with the words it uses.
#: Translated when the inbox is read, not when this module is imported, so the
#: reader's language applies.
GROUPS = (
    ("attestation", "Attestations to give",
     "Confirm the record is accurate, or say where it is not. Answer here."),
    ("second_signature", "Second signatures",
     "Answers that need your counter-signature before they count."),
    ("approval", "Approval decisions",
     "Steps assigned to you, or to someone who has delegated approval to you."),
    ("formation_step", "Formation approval steps",
     "Requests to create, change or retire a forum that need your decision."),
    ("formation_returned", "Formation requests returned to you",
     "The governance office has questions about a request you raised."),
    ("forum_compliance", "Forums awaiting your compliance review",
     "Forums you are the compliance contact for, whose standing needs a decision."),
    ("forum_review", "Your forums awaiting review",
     "Forums you own that are awaiting a compliance decision or whose review falls due."),
    ("document_review", "Policy reviews due",
     "Documents you own whose periodic review is due, and review cycles assigned to you."),
    ("escalation_queue", "Escalations waiting for an owner",
     "Matters routed to a role or group you belong to. Take one to become its response owner."),
    ("escalation_review", "Escalations under review",
     "Matters you are accountable for or respond to, awaiting review."),
    ("action_plan", "Action plans",
     "Open action plans you own."),
    ("remediation", "Metadata to correct",
     "Records left pointing at something retired, disbanded or deactivated."),
)


# ----------------------------------------------------------------- helpers

def _screen(doctype: str, name: str) -> str:
    pattern = SCREENS.get(doctype)
    if pattern:
        return pattern.format(frappe.utils.quote(name, safe=""))
    return f"/app/{frappe.scrub(doctype).replace('_', '-')}/{frappe.utils.quote(name, safe='')}"


_label_cache: dict = {}


def _label(doctype: str, name: str) -> str:
    """A record's readable title, for records the caller is named on."""
    if not name:
        return ""
    key = (doctype, name)
    if key not in _label_cache:
        title_field = frappe.get_meta(doctype).get_title_field()
        value = None
        if title_field and title_field != "name":
            value = frappe.db.get_value(doctype, name, title_field)
        _label_cache[key] = value or name
    return _label_cache[key]


def _readable(doctype: str, **kwargs) -> list[dict]:
    """``frappe.get_list`` for a type the caller may read; nothing otherwise.

    `get_list` raises rather than returning nothing when the caller may not read
    the type at all, and a person with no policy role simply has no policy work.
    """
    if not frappe.has_permission(doctype, "read"):
        return []
    kwargs.setdefault("limit_page_length", 500)
    return frappe.get_list(doctype, **kwargs)


def _item(kind: str, *, reference: str, doctype: str, title: str, url: str, due_on=None,
          context: str | None = None, today=None, **extra) -> dict:
    due = getdate(due_on) if due_on else None
    today = today or getdate(nowdate())
    return {
        "kind": kind,
        "reference": reference,
        "doctype": doctype,
        "title": title,
        "url": url,
        "context": context,
        "due_on": str(due) if due else None,
        "overdue": bool(due and due < today),
        "due_soon": bool(due and today <= due <= add_days(today, 7)),
        **extra,
    }


def _delegators(user: str, action: str) -> list[str]:
    """People who have delegated ``action`` to ``user`` with a delegation live today.

    Only a candidate list: whether a delegation covers a particular record is
    asked of Core's `resolve_actor` for each record.
    """
    names = frappe.get_all(
        "Authority Delegation", filters={"delegate": user, "is_active": 1}, pluck="name"
    )
    out = []
    for name in names:
        doc = frappe.get_doc("Authority Delegation", name)
        if not delegation.is_within_dates(doc):
            continue
        if action in [row.delegable_action for row in doc.delegated_actions] and doc.delegator not in out:
            out.append(doc.delegator)
    return out


def _acting_as(user: str, action: str) -> list[str]:
    """The caller and everyone who has delegated ``action`` to them."""
    return [user, *[d for d in _delegators(user, action) if d != user]]


# ------------------------------------------------------------- the sources

def _attestation_items(user: str, today) -> list[dict]:
    from consilium.consilium_core import attestation

    people = _acting_as(user, attestation.ATTEST_ACTION)
    rows = frappe.get_all(
        "Attestation Task",
        filters={"assigned_to": ["in", people], "is_open": 1},
        fields=["name", "campaign", "subject_doctype", "subject_name", "assigned_to", "due_on",
                "second_signatory", "status"],
        order_by="due_on asc, name asc",
    )
    campaigns: dict[str, dict] = {}
    items = []
    for row in rows:
        acting_for = None
        if row.assigned_to != user:
            task = frappe._dict(row)
            if not attestation.acting_resolution(task, user)["permitted"]:
                continue
            acting_for = row.assigned_to
        if row.campaign not in campaigns:
            campaigns[row.campaign] = frappe.db.get_value(
                "Attestation Campaign", row.campaign, ["campaign_title", "campaign_type"], as_dict=True
            ) or {}
        campaign = campaigns[row.campaign]
        items.append(_item(
            "attestation",
            reference=row.name,
            doctype="Attestation Task",
            title=_label(row.subject_doctype, row.subject_name),
            url=_screen(row.subject_doctype, row.subject_name),
            due_on=row.due_on,
            context=campaign.get("campaign_title"),
            today=today,
            action="respond",
            acting_for=acting_for,
            subject_doctype=row.subject_doctype,
            subject_name=row.subject_name,
            second_signatory=row.second_signatory,
        ))
    return items


def _second_signature_items(user: str, today) -> list[dict]:
    rows = frappe.get_all(
        "Attestation Task",
        # "Not yet signed" is tested here rather than in the filter: an emptiness
        # filter on a Datetime column renders as a comparison with '' and
        # PostgreSQL refuses it (see attestation._open_seat_names).
        filters={"second_signatory": user, "is_open": 0},
        fields=["name", "campaign", "subject_doctype", "subject_name", "assigned_to", "due_on", "status",
                "responded_on", "response_statement", "acting_delegation", "second_signed_on"],
        order_by="due_on asc, name asc",
    )
    items = []
    for row in rows:
        # Closed without an answer means the task lapsed: nothing to counter-sign.
        if not row.responded_on or row.second_signed_on:
            continue
        items.append(_item(
            "second_signature",
            reference=row.name,
            doctype="Attestation Task",
            title=_label(row.subject_doctype, row.subject_name),
            url=_screen(row.subject_doctype, row.subject_name),
            due_on=row.due_on,
            context=frappe.db.get_value("Attestation Campaign", row.campaign, "campaign_title"),
            today=today,
            action="second_sign",
            first_signatory=row.assigned_to,
            response_status=row.status,
            response_statement=row.response_statement,
            responded_on=str(row.responded_on),
        ))
    return items


def _step_words(approval_step: str | None) -> str:
    """The seat an approval step is decided from, as a person would say it.

    Steps are configured with names such as "Sponsor", "Document Approver
    Approval" or "Delegating Authority Approval". Read as "as Document Approver
    Approval" the last word is noise, so a trailing "Approval" is dropped:
    "as Document Approver". Display only; the step name is never compared.
    """
    words = (approval_step or "").strip()
    suffix = " approval"
    if words.lower().endswith(suffix) and len(words) > len(suffix):
        words = words[: -len(suffix)].strip()
    return words


def _earliest_clock(doctype: str, name: str):
    """The nearest target of a running service-level clock on the record, if any.

    Where the record's type carries no date of its own for the decision, the
    time limit the organisation has configured for the stage it is in is the
    due date a person should work to.
    """
    targets = frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": doctype, "subject_name": name, "is_open": 1},
        pluck="target_on",
        order_by="target_on asc",
        limit=1,
    ) if frappe.db.exists("DocType", "SLA Clock") else []
    return getdate(targets[0]) if targets and targets[0] else None


def decision_summary(subject_doctype: str, subject_name: str, approval_step: str | None) -> dict:
    """What an approval step asks of the person, in words (My work).

    The inbox used to show an approval as the record's code and the step name —
    "FDIS-2026-00002 · Sponsor" — which tells the person nothing about what they
    are being asked to decide. This names the decision the way a person asks for
    it ("Approve the disbandment plan for the Model Risk Committee"), the seat it
    is decided from ("Sponsor"), and the date it is due by where the record type
    has one.

    Returns ``title``, ``as_role`` (empty when the step is not a seat) and
    ``due_on`` (or None). Reads only the fields it words; the caller is named on
    the decision, which is the entitlement to see what it concerns (see the
    module docstring), so nothing here widens what the inbox shows.
    """
    step = _step_words(approval_step)
    title, due_on, noun = None, None, ""
    if subject_doctype == "Disbandment Plan":
        plan = frappe.db.get_value(subject_doctype, subject_name, ["forum", "effective_on"], as_dict=True) or {}
        forum = _label("Governance Forum", plan.get("forum")) if plan.get("forum") else subject_name
        title = _("Approve the disbandment plan for {0}").format(forum)
        due_on = plan.get("effective_on")
    elif subject_doctype == "Committee Formation Request":
        request = frappe.db.get_value(
            subject_doctype, subject_name, ["forum_name", "request_type", "proposed_timeline"], as_dict=True
        ) or {}
        forum = request.get("forum_name") or subject_name
        # request_type is a configuration choice (Create / Modify / Retire), read
        # to choose words only.
        wording = {
            "Modify": _("Approve the requested change to {0}"),
            "Retire": _("Approve the request to retire {0}"),
        }.get(request.get("request_type"), _("Approve the request to form {0}"))
        title = wording.format(forum)
        due_on = request.get("proposed_timeline")
    elif subject_doctype == "Governing Document":
        document = frappe.db.get_value(
            subject_doctype, subject_name, ["document_name", "version_label"], as_dict=True
        ) or {}
        name = document.get("document_name") or subject_name
        title = (_("Approve {0}, version {1}").format(name, document.get("version_label"))
                 if document.get("version_label") else _("Approve {0}").format(name))
    elif subject_doctype == "Risk Acceptance":
        acceptance = frappe.db.get_value(
            subject_doctype, subject_name, ["risk_acceptance_name", "escalation_matter", "start_date"], as_dict=True
        ) or {}
        what = acceptance.get("risk_acceptance_name") or subject_name
        title = _("Approve accepting the risk: {0}").format(what)
        due_on = acceptance.get("start_date")
        noun = _("Risk Acceptance")
    else:
        title = _("Decide on {0}").format(_label(subject_doctype, subject_name))
    if not due_on:
        due_on = _earliest_clock(subject_doctype, subject_name)
    # A step named after the decision itself ("Risk Acceptance") is not a seat.
    as_role = "" if not step or step.lower() == str(noun).lower() else step
    return {"title": title, "as_role": as_role, "due_on": due_on}


def _approval_items(user: str, today) -> list[dict]:
    people = _acting_as(user, delegation.ACTION_APPROVE)
    rows = frappe.get_all(
        "Approval Decision",
        filters={"assigned_to": ["in", people], "is_open": 1},
        fields=["name", "subject_doctype", "subject_name", "approval_step", "assigned_to", "creation", "owner"],
        order_by="creation asc",
    )
    # A role-based formation step waits in its role's queue, like an escalation
    # routed to a role (E-5, E-8): every member sees it until one decides it.
    # Which steps are queued, and who is in the queue, is the formation
    # module's rule, so it is asked rather than restated here.
    queued = set()
    if frappe.db.exists("DocType", "Committee Formation Request"):
        from consilium.governance import formation

        seen = {row.name for row in rows}
        for row in formation.queued_steps_for(user):
            if row.name not in seen:
                rows.append(row)
                queued.add(row.name)
    items = []
    for row in rows:
        # A sequential step behind an undecided one is not yet anyone's task:
        # Core refuses it until the steps ahead are decided (E7-S4).
        if not approvals.is_turn(row.name):
            continue
        acting_for = None
        if row.assigned_to != user and row.name not in queued:
            resolution = delegation.resolve_actor(
                row.assigned_to, delegation.ACTION_APPROVE, acting_user=user,
                doctype=row.subject_doctype, name=row.subject_name,
            )
            if not resolution["permitted"]:
                continue
            acting_for = row.assigned_to
        subject_doctype, subject_name = row.subject_doctype, row.subject_name
        # A risk acceptance is decided on its escalation's screen, and a
        # disbandment plan on its forum's disbandment page — never the desk.
        if subject_doctype == "Risk Acceptance":
            matter = frappe.db.get_value("Risk Acceptance", subject_name, "escalation_matter")
            url = _screen("Escalation Matter", matter) if matter else _screen(subject_doctype, subject_name)
        elif subject_doctype == "Disbandment Plan":
            forum = frappe.db.get_value("Disbandment Plan", subject_name, "forum")
            url = (f"/forum-disband?forum={frappe.utils.quote(forum, safe='')}" if forum
                   else _screen(subject_doctype, subject_name))
        else:
            url = _screen(subject_doctype, subject_name)
        kind = "formation_step" if subject_doctype == "Committee Formation Request" else "approval"
        summary = decision_summary(subject_doctype, subject_name, row.approval_step)
        raised_by = row.get("owner") or frappe.db.get_value("Approval Decision", row.name, "owner")
        items.append(_item(
            kind,
            reference=row.name,
            doctype="Approval Decision",
            title=summary["title"],
            url=url,
            due_on=summary["due_on"],
            # Kept for readers that show one line (the assistant, exports): the
            # same facts the page draws from the fields below.
            context=_("As {0}").format(summary["as_role"]) if summary["as_role"] else None,
            today=today,
            acting_for=acting_for,
            as_role=summary["as_role"],
            raised_by=raised_by,
            raised_on=str(getdate(row.creation)),
            subject_doctype=subject_doctype,
            subject_name=subject_name,
        ))
    return items


def _formation_returned_items(user: str, today) -> list[dict]:
    rows = _readable(
        "Committee Formation Request",
        filters={"requester": user, "is_active": 1, "is_editable": 1, "requires_statement": 1},
        fields=["name", "forum_name", "returned_on", "proposed_timeline"],
        order_by="returned_on asc",
    )
    return [
        _item(
            "formation_returned",
            reference=row.name,
            doctype="Committee Formation Request",
            title=row.forum_name or row.name,
            url=_screen("Committee Formation Request", row.name),
            due_on=row.proposed_timeline,
            context=_("Returned {0}").format(str(getdate(row.returned_on))) if row.returned_on else None,
            today=today,
        )
        for row in rows
    ]


def _forum_items(user: str, today, horizon) -> list[dict]:
    from consilium.governance import lifecycle

    items = []
    may_review = lifecycle.may_record_review(user)
    for row in _readable(
        "Governance Forum",
        filters={"compliance_contact": user, "is_active": 1, "requires_review": 1},
        fields=["name", "forum_name", "compliance_status", "next_review_on"],
    ):
        items.append(_item(
            "forum_compliance",
            reference=row.name,
            doctype="Governance Forum",
            title=row.forum_name or row.name,
            url=(f"/forum-review?forum={frappe.utils.quote(row.name, safe='')}" if may_review
                 else _screen("Governance Forum", row.name)),
            context=_("Standing: {0}").format(row.compliance_status) if row.compliance_status else None,
            today=today,
        ))

    seen = set()
    owned = _readable(
        "Governance Forum",
        filters={"forum_owner": user, "is_active": 1},
        or_filters=[
            ["requires_review", "=", 1],
            # The lower bound keeps forums with no review date out: an empty
            # date compares as the earliest possible day.
            ["next_review_on", "between", ["1900-01-02", str(horizon)]],
        ],
        fields=["name", "forum_name", "compliance_status", "next_review_on", "requires_review"],
    )
    for row in owned:
        if row.name in seen:
            continue
        seen.add(row.name)
        reason = (_("Awaiting a compliance decision") if row.requires_review
                  else _("Periodic review falls due"))
        items.append(_item(
            "forum_review",
            reference=row.name,
            doctype="Governance Forum",
            title=row.forum_name or row.name,
            url=_screen("Governance Forum", row.name),
            due_on=row.next_review_on if row.next_review_on and getdate(row.next_review_on) <= horizon else None,
            context=reason,
            today=today,
        ))
    return items


def _document_items(user: str, today, horizon) -> list[dict]:
    items = []
    for row in _readable(
        "Governing Document",
        filters={
            "document_owner": user,
            "is_active": 1,
            "next_review_on": ["between", ["1900-01-02", str(horizon)]],
        },
        fields=["name", "document_name", "next_review_on"],
        order_by="next_review_on asc",
    ):
        items.append(_item(
            "document_review",
            reference=row.name,
            doctype="Governing Document",
            title=row.document_name or row.name,
            url=_screen("Governing Document", row.name),
            due_on=row.next_review_on,
            context=_("Periodic review of a document you own"),
            today=today,
        ))
    for row in _readable(
        "Document Review Cycle",
        filters={"reviewer": user, "is_open": 1},
        fields=["name", "document", "due_on", "cycle_year"],
        order_by="due_on asc",
    ):
        items.append(_item(
            "document_review",
            reference=row.name,
            doctype="Document Review Cycle",
            title=_label("Governing Document", row.document),
            url=_screen("Governing Document", row.document),
            due_on=row.due_on,
            context=_("Review cycle {0} assigned to you").format(row.cycle_year or row.name),
            today=today,
        ))
    return items


def _escalation_items(user: str, today) -> list[dict]:
    items = []
    for row in _readable(
        "Escalation Matter",
        filters={"is_open": 1, "requires_review": 1},
        or_filters=[["accountable_executive", "=", user], ["response_owner", "=", user]],
        fields=["name", "escalation_title", "severity", "accountable_executive", "response_owner"],
        order_by="modified asc",
    ):
        role = _("Accountable executive") if row.accountable_executive == user else _("Response owner")
        items.append(_item(
            "escalation_review",
            reference=row.name,
            doctype="Escalation Matter",
            title=row.escalation_title or row.name,
            url=_screen("Escalation Matter", row.name),
            context=_("{0} · severity {1}").format(role, row.severity or _("not set")),
            today=today,
        ))
    for row in _readable(
        "Action Plan",
        filters={"owner_user": user, "is_open": 1},
        fields=["name", "action_plan_name", "escalation_matter", "end_date"],
        order_by="end_date asc",
    ):
        items.append(_item(
            "action_plan",
            reference=row.name,
            doctype="Action Plan",
            title=row.action_plan_name or row.name,
            url=(_screen("Escalation Matter", row.escalation_matter) if row.escalation_matter
                 else _screen("Action Plan", row.name)),
            due_on=row.end_date,
            context=_("For {0}").format(row.escalation_matter) if row.escalation_matter else None,
            today=today,
        ))
    return items


def _escalation_queue_items(user: str, today) -> list[dict]:
    """Matters waiting in a role or group queue the caller belongs to (E-5, E-8).

    The queue rule — what "waiting" means, who belongs — is the escalation
    module's (``escalation.assignment``); it reads with the caller's own
    permissions, so a sensitive matter is listed only to those cleared for it.
    """
    if not frappe.db.exists("DocType", "Escalation Matter"):
        return []
    from consilium.escalation import assignment

    items = []
    for row in assignment.waiting_for(user):
        items.append(_item(
            "escalation_queue",
            reference=row.name,
            doctype="Escalation Matter",
            title=row.escalation_title or row.name,
            url=_screen("Escalation Matter", row.name),
            context=_("Routed to {0} · severity {1}{2}").format(
                assignment.queue_label(row), row.severity or _("not set"),
                _(" · systemic") if row.systemic else ""),
            today=today,
            action="take_ownership",
            current_owner=row.response_owner,
        ))
    return items


def _remediation_items(user: str, today) -> list[dict]:
    items = []
    for row in _readable(
        "Metadata Remediation Task",
        filters={"assigned_to": user, "is_open": 1},
        fields=["name", "subject_doctype", "subject_name", "invalid_fieldname", "trigger_event", "due_on"],
        order_by="due_on asc",
    ):
        label = row.invalid_fieldname
        if row.subject_doctype and row.invalid_fieldname:
            field = frappe.get_meta(row.subject_doctype).get_field(row.invalid_fieldname)
            label = field.label if field else row.invalid_fieldname
        items.append(_item(
            "remediation",
            reference=row.name,
            doctype="Metadata Remediation Task",
            title=_label(row.subject_doctype, row.subject_name) if row.subject_doctype else row.name,
            url=_screen(row.subject_doctype, row.subject_name) if row.subject_doctype else _screen(
                "Metadata Remediation Task", row.name),
            due_on=row.due_on,
            context=_("{0}: {1}").format(row.trigger_event or _("Needs correcting"), label or ""),
            today=today,
        ))
    return items


# ---------------------------------------------------------------- assembly

def collect(user: str | None = None) -> list[dict]:
    """Every item waiting on ``user``, flat, most urgent first."""
    user = user or frappe.session.user
    _label_cache.clear()
    today = getdate(nowdate())
    horizon = add_days(today, DUE_SOON_DAYS)
    items = [
        *_attestation_items(user, today),
        *_second_signature_items(user, today),
        *_approval_items(user, today),
        *_formation_returned_items(user, today),
        *_forum_items(user, today, horizon),
        *_document_items(user, today, horizon),
        *_escalation_queue_items(user, today),
        *_escalation_items(user, today),
        *_remediation_items(user, today),
    ]
    items.sort(key=lambda item: (not item["overdue"], item["due_on"] or "9999-12-31", item["reference"]))
    return items


def grouped(items: list[dict]) -> list[dict]:
    out = []
    for kind, label, description in GROUPS:
        members = [item for item in items if item["kind"] == kind]
        if members:
            out.append({
                "kind": kind,
                "label": _(label),
                "description": _(description),
                "items": members,
                "overdue": sum(1 for item in members if item["overdue"]),
            })
    return out


def _require_signed_in() -> str:
    if frappe.session.user == "Guest":
        frappe.throw(_("Sign in to see what is waiting on you."), frappe.PermissionError)
    return frappe.session.user


@frappe.whitelist(methods=["GET"])
def my_tasks() -> dict:
    """The inbox page's payload: what is waiting on the caller, grouped by kind."""
    from consilium.consilium_core import attestation

    user = _require_signed_in()
    items = collect(user)
    return {
        "user": user,
        "today": nowdate(),
        "groups": grouped(items),
        "count": len(items),
        "overdue": sum(1 for item in items if item["overdue"]),
        "response_choices": attestation.response_choices(),
    }


@frappe.whitelist(methods=["GET"])
def my_task_count() -> dict:
    """The navigation badge: how many things wait on the caller, and how many are late."""
    user = _require_signed_in()
    items = collect(user)
    return {"count": len(items), "overdue": sum(1 for item in items if item["overdue"])}
