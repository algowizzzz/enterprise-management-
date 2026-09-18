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


def _approval_items(user: str, today) -> list[dict]:
    people = _acting_as(user, delegation.ACTION_APPROVE)
    rows = frappe.get_all(
        "Approval Decision",
        filters={"assigned_to": ["in", people], "is_open": 1},
        fields=["name", "subject_doctype", "subject_name", "approval_step", "assigned_to", "creation"],
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
        # A risk acceptance is decided on its escalation's screen.
        if subject_doctype == "Risk Acceptance":
            matter = frappe.db.get_value("Risk Acceptance", subject_name, "escalation_matter")
            url = _screen("Escalation Matter", matter) if matter else _screen(subject_doctype, subject_name)
        else:
            url = _screen(subject_doctype, subject_name)
        kind = "formation_step" if subject_doctype == "Committee Formation Request" else "approval"
        items.append(_item(
            kind,
            reference=row.name,
            doctype="Approval Decision",
            title=_label(subject_doctype, subject_name),
            url=url,
            context=_("{0} — {1} {2}, raised {3}").format(
                row.approval_step, _(subject_doctype), subject_name, str(getdate(row.creation))
            ),
            today=today,
            acting_for=acting_for,
            raised_on=str(getdate(row.creation)),
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
