"""The forum's own lifecycle: compliance standing, review triggers, disbandment.

Draft to Pending to Compliant, Non-Compliant or Not Applicable, driven by
compliance — and the state a controlled disbandment leaves behind.

The mechanics are deliberately narrow:

* A forum's compliance state changes only through a ``Forum Compliance Review``,
  a watched-field trigger, or a completed disbandment. Editing the field
  directly is refused, which is how "only compliance roles may set the outcome
  states" is enforced server-side rather than by convention.
* Which forum state a review decision produces is a **mapping**, read by key.
  Nothing compares a state label.
* Disbandment makes the forum inactive. Nothing is deleted, ever, and Core's
  retention guard continues to apply to the record.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_years, getdate, now, nowdate

from consilium.consilium_core import audit, notification, state_flags, watched_fields
from consilium.governance import membership as membership_api
from consilium.governance import setup

#: Review decision -> the forum status it produces. Configuration read by key.
#: The only place the two vocabularies meet, and no comparison happens here.
REVIEW_OUTCOME_STATUS = {
    "Compliant": "Compliant",
    "Non-Compliant": "Non-Compliant",
    "Not Applicable": "Not Applicable",
    "Returned To Creator": "Draft",
}

#: The state a completed disbandment leaves behind.
DISBANDED_STATUS = "Disbanded"

#: The channel compliance notifications go out on. Core seeds it.
DEFAULT_CHANNEL = "RECORD"

REVIEW_INTERVAL_YEARS = 1


def set_forum_state(forum, status: str, **extra):
    """Write a forum's state and the flags that go with it. The only writer.

    ``status`` is configuration handed in by a caller that read it from a map or
    from a watched-field set. It is written as given and never compared.
    """
    if isinstance(forum, str):
        forum = frappe.get_doc("Governance Forum", forum)
    forum.compliance_status = status
    for fieldname, value in extra.items():
        forum.set(fieldname, value)
    forum.flags.consilium_lifecycle = True
    forum.save(ignore_permissions=True)
    return forum


# ------------------------------------------------------- compliance review


def record_review(
    forum: str,
    decision: str,
    *,
    review_type: str = "Initial",
    reviewer: str | None = None,
    comments: str | None = None,
    returned_questions: str | None = None,
    triggered_by_fields: list | None = None,
    attestation_task: str | None = None,
):
    """Record a compliance decision, and let it move the forum."""
    review = frappe.get_doc(
        {
            "doctype": "Forum Compliance Review",
            "forum": forum,
            "review_type": review_type,
            "reviewer": reviewer or frappe.session.user,
            "decision": decision,
            "comments": comments,
            "returned_questions": returned_questions,
            "triggered_by_fields": json.dumps(triggered_by_fields) if triggered_by_fields else None,
            "attestation_task": attestation_task,
        }
    ).insert()
    return review


def apply_review(review) -> None:
    """Move the forum to the state this decision produces. Called on insert."""
    status = REVIEW_OUTCOME_STATUS.get(review.decision)
    if not status:
        frappe.throw(
            _("No forum status is configured for the review decision {0}.").format(review.decision),
            title=_("Review Outcome Not Configured"),
        )
    review.db_set("resulting_status", status, update_modified=False)
    review.db_set("decided_on", now(), update_modified=False)

    extra = {}
    if review.review_type == "Annual":
        extra["next_review_on"] = add_years(getdate(nowdate()), REVIEW_INTERVAL_YEARS)
    set_forum_state(review.forum, status, **extra)
    _notify(review.forum, _("Compliance review recorded"),
            _("{0} recorded {1} on forum {2}.").format(review.reviewer, review.decision, review.forum))


# ---------------------------------------------------------- watched fields


def compliance_users() -> list[str]:
    """Who is notified when a forum needs re-review. An access role, not a field."""
    return frappe.get_all(
        "Has Role",
        filters={"role": "Compliance Reviewer", "parenttype": "User"},
        pluck="parent",
    )


def _notify(forum: str, subject: str, body: str) -> list[str]:
    if not frappe.db.exists("Notification Channel", DEFAULT_CHANNEL):
        return []
    recipients = compliance_users()
    if not recipients:
        return []
    return notification.notify_many(
        DEFAULT_CHANNEL, recipients, subject=subject, body=body,
        subject_doctype="Governance Forum", subject_name=forum,
    )


def on_watched_change(doc) -> list[dict]:
    """A change to a configured watched field sends the forum back for review.

    The list of fields, the action and the state it returns to are all data on
    the ``Watched Field Set``. Core's generic handler applies the reset to a
    ``workflow_state`` field; the forum's state field is ``compliance_status``,
    so the reset is applied here — reading the same configuration, comparing
    nothing.
    """
    hits = watched_fields.changed_watched_fields(doc)
    if not hits:
        return []

    field_set = frappe.get_doc("Watched Field Set", doc.doctype)
    if field_set.on_change_action != "Reset Workflow State" or not field_set.reset_to_state:
        return hits

    target = field_set.reset_to_state
    if doc.compliance_status == target:
        return hits

    doc.db_set("compliance_status", target, update_modified=False)
    for flag, value in (state_flags.flags_for(doc.doctype, "compliance_status", target) or {}).items():
        if doc.meta.has_field(flag):
            doc.db_set(flag, value, update_modified=False)

    summary = ", ".join(hit["label"] or hit["fieldname"] for hit in hits)
    frappe.get_doc(
        {
            "doctype": "ToDo",
            "reference_type": doc.doctype,
            "reference_name": doc.name,
            "description": _("Forum {0} needs compliance re-review: {1} changed.").format(doc.name, summary),
            "allocated_to": doc.modified_by,
        }
    ).insert(ignore_permissions=True)
    _notify(doc.name, _("Forum returned for compliance review"),
            _("Watched field(s) changed on forum {0}: {1}.").format(doc.name, summary))
    return hits


# ------------------------------------------------------------ disbandment


def disbandment_outstanding(plan) -> list[str]:
    """Required approvals that have not yet been decided. Reads the open flag."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)
    names = [row.approval_decision for row in plan.approvals if row.required and row.approval_decision]
    if not names:
        return [row.approver_role for row in plan.approvals if row.required]
    return frappe.get_all(
        "Approval Decision", filters={"name": ["in", names], "is_open": 1}, pluck="name"
    )


def execute_disbandment(plan, *, effective_on=None):
    """Make the forum inactive. It is never deleted, and retention still applies."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)

    outstanding = disbandment_outstanding(plan)
    if outstanding:
        audit.refuse(
            _(
                "Forum {0} cannot be disbanded: {1} required approval(s) are outstanding. "
                "G-11 names the approvals, and a disbandment without them is not a disbandment."
            ).format(plan.forum, len(outstanding)),
            subject_doctype="Governance Forum",
            subject_name=plan.forum,
            attempted_action="Other",
            control="disbandment approvals",
            context={"plan": plan.name, "outstanding": outstanding},
            exc=frappe.ValidationError,
        )

    effective = getdate(effective_on or plan.effective_on or nowdate())
    forum = set_forum_state(
        plan.forum, DISBANDED_STATUS, disbanded_on=effective, disbandment_plan=plan.name
    )

    ended = []
    for seat in membership_api.members_as_at(plan.forum, effective):
        membership_api.close_seat(seat["name"], effective, "Forum Disbanded")
        ended.append(seat["name"])

    plan.db_set("executed_on", now(), update_modified=False)
    _notify(plan.forum, _("Forum disbanded"),
            _("Forum {0} was disbanded with effect from {1}. The record remains, inactive.").format(
                plan.forum, effective))
    return {"forum": forum.name, "seats_closed": ended, "effective_on": str(effective)}


def refuse_deletion(doc) -> None:
    """A forum is disbanded, never deleted. G-11 and the retention obligation."""
    audit.refuse(
        _(
            "Forum {0} cannot be deleted. A forum leaves service through a disbandment plan and "
            "becomes inactive; its history and documents remain subject to retention."
        ).format(doc.name),
        subject_doctype=doc.doctype,
        subject_name=doc.name,
        attempted_action="Delete",
        control="forum disbandment, not deletion",
    )


def ensure_configuration() -> dict:
    return setup.ensure_configuration()
