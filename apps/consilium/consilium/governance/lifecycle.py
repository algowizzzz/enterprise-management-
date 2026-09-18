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

from consilium.consilium_core import approvals, audit, delegation, notification, state_flags, watched_fields
from consilium.governance import charters
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
    # Asked before the review is written, so a refusal leaves nothing behind;
    # `apply_review` asks again for a review inserted any other way.
    refuse_standing_over_open_challenge(forum, decision)
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
    refuse_standing_over_open_challenge(review.forum, review.decision)
    review.db_set("resulting_status", status, update_modified=False)
    review.db_set("decided_on", now(), update_modified=False)

    extra = {}
    if review.review_type == "Annual":
        extra["next_review_on"] = add_years(getdate(nowdate()), REVIEW_INTERVAL_YEARS)
    set_forum_state(review.forum, status, **extra)
    _notify("governance.forum.review_recorded", review.forum,
            reviewer=review.reviewer, decision=review.decision)


# ---------------------------------------------------------- watched fields


def compliance_users() -> list[str]:
    """Who is notified when a forum needs re-review. An access role, not a field."""
    return frappe.get_all(
        "Has Role",
        filters={"role": "Compliance Reviewer", "parenttype": "User"},
        pluck="parent",
    )


def _notify(event_code: str, forum: str, **context) -> list[str]:
    """Tell compliance about a forum, through Core's event API.

    The wording and channel are the event's ``Notification Template``; with no
    active template Core records the built-in wording on the record channel, so
    the evidence that compliance was told survives a template being switched off.
    """
    recipients = compliance_users()
    if not recipients:
        return []
    return notification.notify(
        event_code, recipients, context, subject_doctype="Governance Forum", subject_name=forum,
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
    _notify("governance.forum.returned_for_review", doc.name, summary=summary)
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


def disbandment_refused(plan) -> list[dict]:
    """Required approvals decided against the plan, and not bypassed by a recorded
    exception. Read from the decision's flags (closed and needing review), as the
    formation gate reads them."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)
    names = [row.approval_decision for row in plan.approvals if row.required and row.approval_decision]
    if not names:
        return []
    return [
        row for row in frappe.get_all(
            "Approval Decision",
            filters={"name": ["in", names], "is_open": 0, "requires_review": 1},
            fields=["name", "approval_step", "exception_authorisation"],
        )
        if not row["exception_authorisation"]
    ]


def execute_disbandment(plan, *, effective_on=None):
    """Make the forum inactive. It is never deleted, and retention still applies."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)

    if plan.executed_on:
        frappe.throw(
            _("Disbandment plan {0} was executed on {1}.").format(plan.name, plan.executed_on),
            title=_("Already Executed"),
        )
    if not frappe.db.get_value("Governance Forum", plan.forum, "is_active"):
        frappe.throw(_("Forum {0} is already inactive.").format(plan.forum), title=_("Forum Inactive"))

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
    # A refusal closes its decision, so it drops out of "outstanding" above; on
    # that check alone a forum could be disbanded over an approver's "no".
    refused = disbandment_refused(plan)
    if refused:
        audit.refuse(
            _(
                "Forum {0} cannot be disbanded: the disbandment was refused by {1}."
            ).format(plan.forum, ", ".join(row["approval_step"] for row in refused)),
            subject_doctype="Governance Forum",
            subject_name=plan.forum,
            attempted_action="Other",
            control="disbandment approvals",
            context={"plan": plan.name, "refused": [row["name"] for row in refused]},
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
    _notify("governance.forum.disbanded", plan.forum, effective_on=str(effective))
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


# ------------------------------------------------------- portal entry point
#
# A forum could sit "awaiting review" indefinitely: `record_review` was only
# reachable from tests. This is the door the compliance screen uses. It records
# a review — which is what moves the forum — and never writes the forum's state
# itself, for the reason the module docstring gives.

#: The role a compliance decision belongs to. The Forum Compliance Review
#: DocType grants create to it (and to System Manager) and to nobody else; the
#: governance office may read reviews but not record them. Checked explicitly as
#: well as through the DocType, so the refusal is audited and says who may act.
COMPLIANCE_ROLE = "Compliance Reviewer"
SUPERUSER_ROLES = ("System Manager",)

#: The review kinds the portal records. An annual review is deliberately absent:
#: it is a dually-signed attestation turned into a review by
#: ``reviews.record_annual_review``, and recording one here would skip the second
#: signature it exists to require.
PORTAL_REVIEW_TYPES = ("Initial", "Triggered By Change")


def may_record_review(user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & ({COMPLIANCE_ROLE} | set(SUPERUSER_ROLES)))


def review_decisions() -> list[dict]:
    """Each decision a review may record, what it moves the forum to, and whether
    it must carry written questions or comments (its ``requires_statement`` flag)."""
    field = frappe.get_meta("Forum Compliance Review").get_field("decision")
    out = []
    for decision in [option for option in (field.options or "").split("\n") if option]:
        flags = state_flags.flags_for("Forum Compliance Review", "decision", decision) or {}
        out.append({
            "decision": decision,
            "resulting_status": REVIEW_OUTCOME_STATUS.get(decision),
            "requires_statement": bool(flags.get("requires_statement")),
        })
    return out


@frappe.whitelist(methods=["POST"])
def record_compliance_review(forum: str, decision: str, review_type: str = "Initial",
                             comments: str | None = None, returned_questions: str | None = None) -> dict:
    """Record a compliance decision on a forum from the portal."""
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not may_record_review():
        audit.refuse(
            _("{0} may not record a compliance review on forum {1}. Compliance decisions belong to the {2} role.").format(
                frappe.session.user, forum, COMPLIANCE_ROLE
            ),
            subject_doctype="Governance Forum",
            subject_name=forum,
            attempted_action="Other",
            control="compliance review role",
        )
    frappe.has_permission("Forum Compliance Review", "create", throw=True)

    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        frappe.throw(
            _("Forum {0} is disbanded. Its standing is final and is not reviewed again.").format(forum),
            title=_("Forum Inactive"),
        )
    if review_type not in PORTAL_REVIEW_TYPES:
        frappe.throw(
            _("A {0} review is recorded from its dually-signed attestation, not from here.").format(review_type),
            title=_("Review Type Not Available"),
        )

    review = record_review(
        forum, decision, review_type=review_type, comments=comments, returned_questions=returned_questions,
    )
    standing = frappe.db.get_value(
        "Governance Forum", forum, ["compliance_status", "requires_review", "is_editable", "is_active"],
        as_dict=True,
    )
    return {"review": review.name, "decision": review.decision, "forum": forum, **standing}


# ------------------------------------------- charter challenge and standing
#
# G-7's charter challenge also bears on the forum's own standing: a forum found
# compliant (or out of scope) while the risk governance office still disputes
# its charter would carry a clean standing over an open second-line objection.
# So a decision that would leave the forum in good standing is refused while a
# charter in force on it has an uncleared challenge. "Good standing" is read
# from the flags of the state the decision produces — active and not needing
# review — so no decision or state label is compared, and a decision that
# sends the forum back (non-compliant, returned) is never blocked by this.


def _leaves_good_standing(decision: str) -> bool:
    status = REVIEW_OUTCOME_STATUS.get(decision)
    flags = state_flags.flags_for("Governance Forum", "compliance_status", status) if status else None
    return bool(flags and flags.get("is_active") and not flags.get("requires_review"))


def standing_blockers(forum: str, decision: str) -> list[str]:
    """Why this decision may not be recorded on this forum now. Empty when it may."""
    if not _leaves_good_standing(decision):
        return []
    text = charters.challenge_blocker_text(charters.uncleared_challenges(forum=forum))
    return [text] if text else []


def refuse_standing_over_open_challenge(forum: str, decision: str) -> None:
    blockers = standing_blockers(forum, decision)
    if blockers:
        audit.refuse(
            _("Forum {0} cannot be recorded as {1}: {2}. Clear or resolve the challenge first.").format(
                forum, decision, "; ".join(blockers)
            ),
            subject_doctype="Governance Forum",
            subject_name=forum,
            attempted_action="Other",
            control="charter challenge",
            exc=frappe.ValidationError,
        )


# ------------------------------------------------ disbandment from a screen
#
# `execute_disbandment` had no caller (E8-S5). What follows is the door the
# `/forum-disband` page uses: raise a plan naming G-11's approvals, let each
# approver (or their delegate) decide through Core, and execute once nothing is
# outstanding. Every step checks the document permission, then the role the
# step belongs to, and audits a refusal.

#: Who raises and executes a disbandment: the governance office, whose DocType
#: permission on `Disbandment Plan` is the only non-administrator write grant.
DISBANDMENT_ROLE = "Risk Governance Office"

#: G-11 names these approvers on every disbandment. The jurisdictional chief
#: risk officer is required "where applicable", so it is offered, not demanded.
REQUIRED_DISBANDMENT_APPROVERS = ("Delegating Authority", "Sponsor", "Chair")

#: What an approver may record. `Pending` is where a decision starts and a
#: bypass is only reachable through an exception authorisation, so neither is
#: offered. Values handed to Core, never compared.
DISBANDMENT_DECISIONS = ("Approved", "Rejected")


def may_administer_disbandment(user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & ({DISBANDMENT_ROLE} | set(SUPERUSER_ROLES)))


def _refuse_disbandment(message: str, forum: str, control: str, exc=frappe.PermissionError):
    audit.refuse(message, subject_doctype="Governance Forum", subject_name=forum,
                 attempted_action="Other", control=control, exc=exc)


def disbandment_blockers(plan) -> list[str]:
    """Everything standing between this plan and its execution. Facts, not labels."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)
    blockers = []
    if plan.executed_on:
        blockers.append(_("the plan has already been executed"))
        return blockers
    if not frappe.db.get_value("Governance Forum", plan.forum, "is_active"):
        blockers.append(_("the forum is already inactive"))
    outstanding = disbandment_outstanding(plan)
    if outstanding:
        blockers.append(_("{0} required approval(s) are undecided").format(len(outstanding)))
    refused = disbandment_refused(plan)
    if refused:
        blockers.append(_("the disbandment was refused by: {0}").format(
            ", ".join(row["approval_step"] for row in refused)))
    return blockers


def _plan_is_live(plan_row) -> bool:
    """A plan still in play: not executed and not refused. A refused plan stays on
    record, and a fresh plan may be raised in its place."""
    return not plan_row.executed_on and not disbandment_refused(plan_row.name)


def live_plan(forum: str) -> str | None:
    for row in frappe.get_all("Disbandment Plan", filters={"forum": forum},
                              fields=["name", "executed_on"], order_by="creation desc"):
        if _plan_is_live(frappe._dict(row)):
            return row["name"]
    return None


def default_disbandment_approvers(forum: str) -> dict:
    """Who G-11's approvals would go to, as the forum's own record names them.

    A suggestion for the form, not a rule: the governance office confirms or
    changes each one. The delegating authority is the one named on the request
    that formed the forum; a forum formed before the platform has none recorded.
    """
    doc = frappe.db.get_value("Governance Forum", forum, ["sponsor", "committee_chair", "formation_request"],
                              as_dict=True) or {}
    authority = None
    if doc.get("formation_request"):
        authority = frappe.db.get_value("Committee Formation Request", doc["formation_request"],
                                        "delegating_authority")
    return {"Delegating Authority": authority, "Sponsor": doc.get("sponsor"), "Chair": doc.get("committee_chair")}


def _real_user(user: str | None) -> bool:
    """An enabled person, not one of the framework's pseudo-users.

    The account type is deliberately not asked: a sponsor or delegating
    authority often holds no governance role, and the framework files an account
    with no desk role as a website user. They still decide their approval here."""
    return bool(user) and user not in frappe.STANDARD_USERS and bool(
        frappe.db.get_value("User", {"name": user, "enabled": 1}, "name")
    )


def raise_disbandment(forum: str, *, trigger_scenario: str, records_disposition_note: str,
                      approvals_rows: list, successor_forum: str | None = None,
                      effective_on=None, notify: bool = True):
    """Raise a plan and its Core approval decisions in one step.

    G-11's three named approvals must each have a named, real approver; a
    jurisdictional CRO row is accepted where the plan needs one. The Core
    decisions are raised at once, so an approver has something to decide the
    moment the plan exists.
    """
    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        frappe.throw(_("Forum {0} is already inactive.").format(forum), title=_("Forum Inactive"))
    existing = live_plan(forum)
    if existing:
        frappe.throw(
            _("Forum {0} already has disbandment plan {1} in progress.").format(forum, existing),
            title=_("Plan In Progress"),
        )
    if successor_forum and not frappe.db.get_value("Governance Forum", successor_forum, "is_active"):
        frappe.throw(_("The successor forum {0} is not an active forum.").format(successor_forum),
                     title=_("Invalid Successor"))
    if not (records_disposition_note or "").strip():
        frappe.throw(_("A disbandment plan records what happens to the forum's records."),
                     title=_("Records Disposition Required"))

    role_options = [o for o in (frappe.get_meta("Disbandment Approval").get_field("approver_role").options or "")
                    .split("\n") if o]
    rows, named = [], set()
    for item in approvals_rows or []:
        role = (item.get("approver_role") or "").strip()
        approver = (item.get("approver") or "").strip()
        if not role and not approver:
            continue
        if role not in role_options:
            frappe.throw(_("{0} is not a disbandment approver role.").format(role), title=_("Unknown Role"))
        if role in named:
            frappe.throw(_("{0} is named twice.").format(role), title=_("Duplicate Approver"))
        if not _real_user(approver):
            frappe.throw(_("The {0} approval needs a named, enabled person.").format(role),
                         title=_("Approver Required"))
        named.add(role)
        rows.append({"approver_role": role, "approver": approver, "required": 1})
    missing = [role for role in REQUIRED_DISBANDMENT_APPROVERS if role not in named]
    if missing:
        frappe.throw(
            _("G-11 requires approval from the delegating authority, the sponsor and the chair. Missing: {0}.")
            .format(", ".join(missing)),
            title=_("Approvals Required"),
        )

    plan = frappe.get_doc({
        "doctype": "Disbandment Plan",
        "forum": forum,
        "trigger_scenario": trigger_scenario,
        "records_disposition_note": records_disposition_note.strip(),
        "successor_forum": successor_forum or None,
        "effective_on": effective_on or None,
        "approvals": rows,
    }).insert(ignore_permissions=True)
    plan.raise_approvals()
    if notify:
        notification.notify(
            "governance.disbandment.approval_requested", sorted({row["approver"] for row in rows}),
            {"forum": forum}, subject_doctype="Disbandment Plan", subject_name=plan.name,
        )
    return frappe.get_doc("Disbandment Plan", plan.name)


def decidable_disbandment_approvals(plan, user: str | None = None) -> list[str]:
    """Open decisions on this plan the user may take: as the approver, or as the
    holder of a live delegation from them. Core answers the delegation question."""
    user = user or frappe.session.user
    name = plan if isinstance(plan, str) else plan.name
    out = []
    for row in frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Disbandment Plan", "subject_name": name, "is_open": 1},
        fields=["name", "assigned_to"], order_by="step_sequence asc, creation asc",
    ):
        resolution = delegation.resolve_actor(row["assigned_to"], delegation.ACTION_APPROVE, acting_user=user,
                                              doctype="Disbandment Plan", name=name)
        if resolution["permitted"]:
            out.append(row["name"])
    return out


def _decision_choice(decision: str) -> dict:
    flags = state_flags.flags_for("Approval Decision", "decision", decision) or {}
    return {"decision": decision, "needs_reason": bool(flags.get("requires_review"))}


def plan_view(plan, user: str | None = None) -> dict:
    """One plan as the screen shows it, with what the viewer may do to it."""
    if isinstance(plan, str):
        plan = frappe.get_doc("Disbandment Plan", plan)
    user = user or frappe.session.user
    decisions = {
        row["name"]: row for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": "Disbandment Plan", "subject_name": plan.name},
            fields=["name", "approval_step", "assigned_to", "acted_by", "acting_delegation", "decision",
                    "is_open", "requires_review", "decided_on", "comments", "exception_authorisation"],
        )
    }
    decidable = set(decidable_disbandment_approvals(plan, user)) if not plan.executed_on else set()
    approvals_out = []
    for row in plan.approvals:
        decided = decisions.get(row.approval_decision) or {}
        approvals_out.append({
            "approver_role": row.approver_role,
            "approver": row.approver,
            "required": row.required,
            "approval_decision": row.approval_decision,
            "decision": decided.get("decision"),
            "is_open": decided.get("is_open"),
            "refused": bool(decided and not decided.get("is_open") and decided.get("requires_review")
                            and not decided.get("exception_authorisation")),
            "acted_by": decided.get("acted_by"),
            "acting_delegation": decided.get("acting_delegation"),
            "decided_on": str(decided["decided_on"]) if decided.get("decided_on") else None,
            "comments": decided.get("comments"),
            "can_decide": row.approval_decision in decidable,
        })
    blockers = disbandment_blockers(plan)
    administer = may_administer_disbandment(user) and bool(
        frappe.has_permission("Disbandment Plan", "write", doc=plan, user=user))
    return {
        "name": plan.name,
        "forum": plan.forum,
        "trigger_scenario": plan.trigger_scenario,
        "successor_forum": plan.successor_forum,
        "successor_forum_name": frappe.db.get_value("Governance Forum", plan.successor_forum, "forum_name")
        if plan.successor_forum else None,
        "records_disposition_note": plan.records_disposition_note,
        "plan_file": plan.plan_file,
        "effective_on": str(plan.effective_on) if plan.effective_on else None,
        "executed_on": str(plan.executed_on) if plan.executed_on else None,
        "creation": str(plan.creation),
        "owner": plan.owner,
        "approvals": approvals_out,
        "blockers": blockers,
        "live": not plan.executed_on and not disbandment_refused(plan),
        "can_execute": administer and not blockers,
        "can_attach": administer and not plan.executed_on,
    }


def _takes_part(plan: str, user: str) -> bool:
    """Named as an approver on the plan, acted on it (as a delegate, say), or may
    decide one of its approvals now. An approver keeps sight of the plan after
    deciding, so they can see where it went."""
    return bool(
        frappe.db.exists("Disbandment Approval", {"parenttype": "Disbandment Plan", "parent": plan, "approver": user})
        or frappe.db.exists("Approval Decision", {"subject_doctype": "Disbandment Plan", "subject_name": plan,
                                                  "acted_by": user})
        or decidable_disbandment_approvals(plan, user)
    )


def _viewable_plans(forum: str, user: str) -> list[str]:
    """Plans on this forum the user may see: all of them with read access to plans,
    otherwise only those the user takes part in."""
    names = frappe.get_all("Disbandment Plan", filters={"forum": forum}, pluck="name", order_by="creation desc")
    if frappe.has_permission("Disbandment Plan", "read", user=user):
        return names
    return [name for name in names if _takes_part(name, user)]


def disbandment_context(forum: str, user: str | None = None) -> dict:
    user = user or frappe.session.user
    forum_row = frappe.db.get_value(
        "Governance Forum", forum,
        ["name", "forum_name", "forum_type", "compliance_status", "is_active", "disbanded_on",
         "disbandment_plan", "sponsor", "committee_chair", "parent_forum"],
        as_dict=True,
    )
    plans = [plan_view(name, user) for name in _viewable_plans(forum, user)]
    may_raise = (
        bool(forum_row.is_active) and may_administer_disbandment(user)
        and bool(frappe.has_permission("Disbandment Plan", "create", user=user))
        and not live_plan(forum)
    )
    trigger_field = frappe.get_meta("Disbandment Plan").get_field("trigger_scenario")
    role_field = frappe.get_meta("Disbandment Approval").get_field("approver_role")
    return {
        "forum": {**forum_row, "disbanded_on": str(forum_row.disbanded_on) if forum_row.disbanded_on else None},
        "plans": plans,
        "may_raise": may_raise,
        "trigger_options": [o for o in (trigger_field.options or "").split("\n") if o],
        "approver_roles": [o for o in (role_field.options or "").split("\n") if o],
        "required_roles": list(REQUIRED_DISBANDMENT_APPROVERS),
        "default_approvers": default_disbandment_approvers(forum) if may_raise else {},
        "decisions": [_decision_choice(d) for d in DISBANDMENT_DECISIONS],
    }


def may_view_disbandment(forum: str, user: str | None = None) -> bool:
    user = user or frappe.session.user
    if frappe.has_permission("Governance Forum", "read", doc=forum, user=user) and frappe.has_permission(
        "Disbandment Plan", "read", user=user
    ):
        return True
    return bool(_viewable_plans(forum, user))


@frappe.whitelist(methods=["GET"])
def get_disbandment(forum: str) -> dict:
    """The disbandment screen's payload.

    Readable by anyone who may read the forum and its plans, and by anyone asked
    to decide one of its approvals — a sponsor or delegating authority often
    holds no governance role at all, and still has to see what they approve.
    """
    if not frappe.db.exists("Governance Forum", forum):
        frappe.throw(_("Forum {0} does not exist.").format(forum), frappe.DoesNotExistError)
    if not may_view_disbandment(forum):
        frappe.throw(_("You do not have access to the disbandment of forum {0}.").format(forum),
                     frappe.PermissionError)
    return disbandment_context(forum)


@frappe.whitelist(methods=["GET"])
def disbandment_people() -> list[dict]:
    """The people a plan may name as approvers: enabled accounts, pseudo-users excluded.

    A server method because the ``User`` list is readable only by administrators
    over the REST interface, and unfiltered it would offer pseudo-users. Accounts
    of every type are offered, for the reason ``_real_user`` gives.
    """
    if not may_administer_disbandment():
        frappe.throw(_("You cannot raise a disbandment plan."), frappe.PermissionError)
    return frappe.get_all(
        "User",
        filters={"enabled": 1, "name": ["not in", list(frappe.STANDARD_USERS)]},
        fields=["name", "full_name"],
        order_by="full_name asc",
    )


@frappe.whitelist(methods=["POST"])
def raise_disbandment_plan(forum: str, trigger_scenario: str, records_disposition_note: str,
                           approvals=None, successor_forum: str | None = None,
                           effective_on: str | None = None) -> dict:
    """The governance office raises a disbandment plan and its approvals."""
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not may_administer_disbandment():
        _refuse_disbandment(
            _("{0} may not raise a disbandment plan for forum {1}. It belongs to the {2}.").format(
                frappe.session.user, forum, DISBANDMENT_ROLE),
            forum, "disbandment role",
        )
    frappe.has_permission("Disbandment Plan", "create", throw=True)
    rows = frappe.parse_json(approvals) if isinstance(approvals, str) else (approvals or [])
    raise_disbandment(
        forum, trigger_scenario=trigger_scenario, records_disposition_note=records_disposition_note,
        approvals_rows=rows, successor_forum=successor_forum, effective_on=effective_on,
    )
    return disbandment_context(forum)


@frappe.whitelist(methods=["POST"])
def attach_disbandment_file(plan: str, file_url: str) -> dict:
    """Record the uploaded plan document (G-11's "uploaded, tracked artefact").

    Only a file the framework's upload attached to *this* plan is accepted."""
    doc = frappe.get_doc("Disbandment Plan", plan)
    if not may_administer_disbandment():
        _refuse_disbandment(
            _("{0} may not change disbandment plan {1}.").format(frappe.session.user, plan),
            doc.forum, "disbandment role",
        )
    doc.check_permission("write")
    if doc.executed_on:
        frappe.throw(_("Plan {0} has been executed and is kept as it stood.").format(plan),
                     title=_("Already Executed"))
    if not frappe.db.exists("File", {"file_url": file_url, "attached_to_doctype": "Disbandment Plan",
                                     "attached_to_name": doc.name}):
        frappe.throw(_("{0} is not a file attached to plan {1}.").format(file_url, plan), title=_("Unknown File"))
    doc.plan_file = file_url
    doc.save(ignore_permissions=True)
    return disbandment_context(doc.forum)


@frappe.whitelist(methods=["POST"])
def record_disbandment_decision(plan: str, approval_decision: str, decision: str,
                                comments: str | None = None) -> dict:
    """An approver — or their delegate — decides their approval on a plan.

    No governance role and no document permission is asked for: the right to
    decide comes from being named, and Core refuses, and audits, anyone who is
    neither the approver nor holding a live delegation from them.
    """
    doc = frappe.get_doc("Disbandment Plan", plan)
    if doc.executed_on:
        frappe.throw(_("Plan {0} has been executed.").format(plan), title=_("Already Executed"))
    row = frappe.db.get_value(
        "Approval Decision", approval_decision,
        ["name", "subject_doctype", "subject_name", "is_open", "approval_step"], as_dict=True,
    )
    if not row or row.subject_doctype != doc.doctype or row.subject_name != doc.name:
        frappe.throw(_("Approval {0} does not belong to plan {1}.").format(approval_decision, plan),
                     title=_("Wrong Approval"))
    if not row.is_open:
        frappe.throw(_("The {0} approval has already been decided.").format(row.approval_step),
                     title=_("Already Decided"))
    if decision not in DISBANDMENT_DECISIONS:
        frappe.throw(_("{0} is not a decision a disbandment approval can record.").format(decision),
                     title=_("Unknown Decision"))
    if _decision_choice(decision)["needs_reason"] and not (comments or "").strip():
        frappe.throw(_("A decision of \"{0}\" is recorded with its reason.").format(decision),
                     title=_("Reason Required"))
    approvals.record_decision(approval_decision, decision, comments=(comments or "").strip() or None,
                              acting_user=frappe.session.user)
    # Mirror the Core decision onto the plan's row for display (the controller
    # does it on save). Saved as the system: the approver need not hold write
    # access to the plan to have decided on it.
    doc.reload()
    doc.save(ignore_permissions=True)
    return disbandment_context(doc.forum)


@frappe.whitelist(methods=["POST"])
def execute_forum_disbandment(plan: str) -> dict:
    """The governance office executes an approved plan. The forum goes inactive."""
    doc = frappe.get_doc("Disbandment Plan", plan)
    if not may_administer_disbandment():
        _refuse_disbandment(
            _("{0} may not execute disbandment plan {1}. It belongs to the {2}.").format(
                frappe.session.user, plan, DISBANDMENT_ROLE),
            doc.forum, "disbandment role",
        )
    doc.check_permission("write")
    result = execute_disbandment(doc)
    return {**disbandment_context(doc.forum), "executed": result}


@frappe.whitelist(methods=["GET"])
def forum_page_actions(forum: str) -> dict:
    """What the forum page may offer beyond reading, decided by the server.

    The page's own context is not this module's to change, so the page asks.
    """
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    user = frappe.session.user
    active = bool(frappe.db.get_value("Governance Forum", forum, "is_active"))
    plan = live_plan(forum)
    viewable = _viewable_plans(forum, user)
    may_raise = active and may_administer_disbandment() and bool(
        frappe.has_permission("Disbandment Plan", "create")) and not plan
    return {
        "forum": forum,
        "disbandment": {
            # Offered when there is something to do or to follow: a plan to raise,
            # or a plan the viewer may see. A reader of plans on a forum with none
            # is not sent to an empty page.
            "visible": bool(may_raise or viewable),
            "may_raise": may_raise,
            "live_plan": plan if plan in viewable else None,
            "awaiting_my_decision": bool(plan and decidable_disbandment_approvals(plan)),
        },
    }
