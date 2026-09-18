"""DEMONSTRATION data for the governance and policy gaps closed on 18 September:
G-8 (approval path by forum type and materiality), G-10 (the first-quarter
inventory attestation), G-14 / O-4 (meeting and charter notifications) and P-8
(policy approval steps in role and group queues, chased when left pending).

    from deploy.demo_additions import gaps_governance
    gaps_governance.run(frappe)   # inside a connected site; the caller commits

Builds on the records ``deploy/demo_data.py`` has already made (found by name,
not by reference, so a fresh site's numbering does not matter). Idempotent:
every step looks for what it would create and skips it when it is there. Steps
are taken **as the persona who would take them**, through the same entry points
the portal calls, so ownership, the checks and the audit trail are the ones a
real user leaves.

* **G-8.** The shipped routes by materiality and forum type are in place. The
  Head of Model Risk asks for a *material* change to the Model Risk Committee
  (climate scenario models, and approval authority over model use); the risk
  governance office evaluates it and raises its steps, so ``/formation-request``
  shows "Materiality of change: Material", the route *Material Change Approval*
  and four steps ending with the head of risk governance's sign-off. The
  Treasurer asks for a *minor* change to the Asset-Liability Committee, which is
  submitted and shows the lighter *Minor Change Approval* route it will follow.
* **G-10.** This year's inventory attestation was opened in August, outside the
  first quarter; the reason is recorded on it, and ``/attestation-campaigns``
  lists it as off-cycle beside the first-quarter standing of each year. The
  daily job opens next year's campaign on the first day of the quarter.
* **G-14 / O-4.** An extraordinary Model Risk Committee session is scheduled and
  then moved, and an Asset-Liability Committee session is scheduled and then
  cancelled: the members were told each time. The risk governance office sends
  the Data Governance Council's terms of reference back with changes requested,
  which tells the forum owner, the secretary and the office. Charter reviews
  falling due (the Audit Committee's) or overdue (the Model Risk Committee's)
  are sent to each forum's owner and secretary.
* **P-8.** A "Climate Risk Management Standard" is in review on its own route:
  a second-line review by the *Risk Management Function* group, then the
  *Policy Reviewer* role queue, then the approver. The Risk Governance Analyst,
  a group member, took and approved the first step nine days ago; the second has
  waited since and is four days past due, so every policy reviewer sees it in
  *My work*, was chased, and the Chief Risk Officer (the approver) was told.

Everything is fictitious, and every record is owned by an ``@demo.example``
persona like the rest of the demonstration data.
"""

from __future__ import annotations

DOMAIN = "demo.example"

MATERIAL_FORUM = "Model Risk Committee"
MINOR_FORUM = "Asset-Liability Committee"
CHALLENGED_CHARTER = "Data Governance Council Terms of Reference"

MOVED_MEETING = "MRC-2026-XS1"
CANCELLED_MEETING = "ALCO-2026-XS1"

CLIMATE_STANDARD = "Climate Risk Management Standard"
CLIMATE_ROUTE = "Climate Risk Standard Route"
CLIMATE_CATEGORY = "CLIMATE"


def U(key: str) -> str:
    return f"{key}@{DOMAIN}"


class _As:
    """Act as a persona for the length of a block, then restore the caller."""

    def __init__(self, frappe, user: str):
        self.frappe, self.user = frappe, user

    def __enter__(self):
        self.previous = self.frappe.session.user
        self.frappe.set_user(self.user if self.frappe.db.exists("User", self.user) else "Administrator")

    def __exit__(self, *exc):
        self.frappe.set_user(self.previous)


def _forum(frappe, forum_name: str):
    name = frappe.db.get_value("Governance Forum", {"forum_name": forum_name}, "name")
    return frappe.get_doc("Governance Forum", name) if name else None


# ------------------------------------------------------------------- G-8


def _change_request(frappe, notes: list, forum_name: str, materiality: str, requester: str, texts: dict,
                    raise_steps: bool) -> None:
    from frappe.utils import add_days, nowdate

    from consilium.governance import formation, setup

    forum = _forum(frappe, forum_name)
    if not forum:
        notes.append(f"skipped: no forum named {forum_name!r}")
        return
    existing = frappe.db.get_value(
        "Committee Formation Request",
        {"subject_forum": forum.name, "request_type": "Modify", "change_materiality": materiality}, "name",
    )
    if existing:
        notes.append(f"exists: {existing} ({materiality.lower()} change to {forum_name})")
        return
    setup.ensure_routed_paths()
    with _As(frappe, U(requester)):
        request = frappe.get_doc({
            "doctype": "Committee Formation Request",
            "requester": U(requester),
            "request_type": "Modify",
            "subject_forum": forum.name,
            "change_materiality": materiality,
            "forum_name": forum.forum_name,
            "forum_type": forum.forum_type,
            "owning_operating_group": forum.owning_operating_group,
            "primary_risk_category": forum.primary_risk_category,
            "delegating_authority": forum.sponsor or U("chief.risk.officer"),
            "forum_sponsor": forum.forum_owner or U("chief.financial.officer"),
            "proposed_timeline": add_days(nowdate(), 60),
            **texts,
        }).insert(ignore_permissions=True)
        formation.submit_request(request.name)
    note = f"created: {request.name}, a {materiality.lower()} change to {forum_name}, submitted"
    if raise_steps:
        with _As(frappe, U("risk.governance.lead")):
            formation.start_request_evaluation(request.name)
            formation.record_request_findings(request.name, [
                {"criterion": criterion, "assessment": "Pass",
                 "comments": "Assessed against the governance standard; no gap or overlap found."}
                for criterion in formation.CRITERIA
            ], completeness_confirmed=1)
            formation.raise_request_approval_steps(request.name)
        route = frappe.db.get_value("Committee Formation Request", request.name, "approval_route")
        note += f"; evaluated and its steps raised on route {route}"
    notes.append(note)


def formation_paths(frappe, notes: list) -> None:
    _change_request(
        frappe, notes, MATERIAL_FORUM, "Material", "head.model.risk",
        {
            "rationale": "Climate scenario models now feed capital planning and nothing oversees them as models. "
                         "The committee should take them in and approve model use, not only validate it.",
            "purpose_scope": "Extend the mandate to climate scenario and stress models, and give the committee "
                             "authority to approve or restrict the use of any model in scope.",
            "proposed_responsibilities": "Approve model use; set restrictions and overlays; oversee the climate "
                                         "model inventory; escalate model-risk appetite breaches to the Executive "
                                         "Risk Committee.",
        },
        raise_steps=True,
    )
    _change_request(
        frappe, notes, MINOR_FORUM, "Minor", "treasurer",
        {
            "rationale": "The quarterly liquidity pack has been renamed and its appendix order changed; the "
                         "terms of reference still use the old names.",
            "purpose_scope": "Update the names of the committee's standing papers. No change to authority, "
                             "membership or reporting line.",
            "proposed_responsibilities": "Unchanged: the committee's responsibilities stay as chartered; only the "
                                         "names of its standing papers change.",
        },
        raise_steps=False,
    )


# ------------------------------------------------------------------ G-10


def first_quarter(frappe, notes: list) -> None:
    from consilium.governance import reviews

    standing = reviews.inventory_q1_standing()
    for row in standing["off_cycle"]:
        if frappe.db.exists("Comment", {"reference_doctype": "Attestation Campaign", "reference_name": row["name"],
                                        "content": ["like", "%Off-cycle%"]}):
            continue
        campaign = frappe.get_doc("Attestation Campaign", row["name"])
        with _As(frappe, U("risk.governance.lead")):
            campaign.add_comment(
                "Info",
                f"Off-cycle inventory attestation (due {row['due_on']}, outside the first quarter). Reason: a "
                "catch-up for the forums formed and restructured after the first-quarter attestation.",
            )
        notes.append(f"recorded: off-cycle reason on {row['name']}")
    held = ", ".join(f"{r['year']} {r['standing']}" for r in standing["years"])
    notes.append(f"first-quarter standing: {held or 'none'}; next due {standing['next_due_on']}")


# ------------------------------------------------------------------ G-14


def _meeting(frappe, forum, reference: str, days: int, location: str):
    from frappe.utils import add_to_date, get_datetime, getdate

    when = get_datetime(f"{getdate(add_to_date(None, days=days))} 14:00:00")
    return frappe.get_doc({
        "doctype": "Forum Meeting",
        "forum": forum.name,
        "meeting_reference": reference,
        "scheduled_on": when,
        "location": location,
        "chaired_by": forum.committee_chair,
        "secretary": forum.secretary,
        "status": "Scheduled",
    }).insert(ignore_permissions=True)


def meeting_notices(frappe, notes: list) -> None:
    from frappe.utils import add_to_date

    model_risk = _forum(frappe, MATERIAL_FORUM)
    alco = _forum(frappe, MINOR_FORUM)
    if model_risk and not frappe.db.exists("Forum Meeting", {"meeting_reference": MOVED_MEETING}):
        with _As(frappe, model_risk.secretary or U("committee.secretary")):
            meeting = _meeting(frappe, model_risk, MOVED_MEETING, 12, "Risk Committee Room")
            meeting.reload()
            meeting.scheduled_on = add_to_date(meeting.scheduled_on, days=2)
            meeting.location = "Board Room 2"
            meeting.save(ignore_permissions=True)
        notes.append(f"created: {meeting.name} ({MOVED_MEETING}) scheduled, then moved; members told twice")
    if alco and not frappe.db.exists("Forum Meeting", {"meeting_reference": CANCELLED_MEETING}):
        with _As(frappe, alco.secretary or U("committee.secretary")):
            meeting = _meeting(frappe, alco, CANCELLED_MEETING, 20, "Treasury Floor Meeting Room")
            meeting.reload()
            meeting.status = "Cancelled"
            meeting.save(ignore_permissions=True)
        notes.append(f"created: {meeting.name} ({CANCELLED_MEETING}) scheduled, then cancelled; members told")


def charter_notices(frappe, notes: list) -> None:
    from consilium.consilium_core import reminders
    from consilium.governance import charters

    name = frappe.db.get_value("Committee Charter", {"charter_title": CHALLENGED_CHARTER}, "name")
    if name:
        doc = frappe.get_doc("Committee Charter", name)
        if doc.requires_review and doc.current_version and not doc.rgo_reviewed_by:
            with _As(frappe, U("risk.governance.lead")):
                charters.record_challenge(
                    doc, charters.CHALLENGE_CHANGES_REQUESTED,
                    comments="Name the decisions the council takes itself and those it only recommends, and "
                             "say which forum it escalates data-quality breaches to.",
                    by=U("risk.governance.lead"),
                )
            notes.append(f"recorded: changes requested on {name}; owner, secretary and office told")
        else:
            notes.append(f"exists: challenge already recorded on {name}")
    sent = reminders.remind_charter_reviews()
    notes.append(f"charter review reminders sent: {len(sent)}")


# ------------------------------------------------------------------- P-8


def _climate_route(frappe) -> str | None:
    if frappe.db.exists("Approval Route", CLIMATE_ROUTE):
        return CLIMATE_ROUTE
    if not frappe.db.exists("Risk Category", CLIMATE_CATEGORY):
        return None
    return frappe.get_doc({
        "doctype": "Approval Route",
        "route_title": CLIMATE_ROUTE,
        "target_doctype": "Governing Document",
        "primary_risk_category": CLIMATE_CATEGORY,
        "priority": 5,
        "is_active": 1,
        "description": "Climate risk documents: a second-line review by the risk management function, then any "
                       "policy reviewer, then the document's approver.",
        "steps": [
            {"step_sequence": 1, "approval_step": "Second-Line Risk Review", "assignee_source": "User Group",
             "user_group": "Risk Management Function", "mode": "Sequential", "is_mandatory": 1},
            {"step_sequence": 2, "approval_step": "Policy Review", "assignee_source": "Role Queue",
             "required_role": "Policy Reviewer", "mode": "Sequential", "is_mandatory": 1},
            {"step_sequence": 3, "approval_step": "Approver Sign-off", "assignee_source": "Document Approver",
             "mode": "Sequential", "is_mandatory": 1},
        ],
    }).insert(ignore_permissions=True).name


def queued_policy_steps(frappe, notes: list) -> None:
    from frappe.utils import add_to_date, now_datetime

    from consilium.consilium_core import reminders, versioning
    from consilium.policy import lifecycle, routing

    if not frappe.db.exists("User Group", "Risk Management Function"):
        notes.append("skipped: no Risk Management Function group")
        return
    route = _climate_route(frappe)
    if not route:
        notes.append(f"skipped: no {CLIMATE_CATEGORY} risk category")
        return
    name = frappe.db.get_value("Governing Document", {"document_name": CLIMATE_STANDARD}, "name")
    if name:
        notes.append(f"exists: {name} {CLIMATE_STANDARD}")
        return
    template = frappe.db.get_value("Governing Document", {"document_name": "Operational Risk Management Policy"},
                                   ["owning_operating_group"], as_dict=True) or {}
    owner, approver = U("head.operational.risk"), U("chief.risk.officer")
    with _As(frappe, owner):
        doc = frappe.get_doc({
            "doctype": "Governing Document",
            "document_name": CLIMATE_STANDARD,
            "document_type": "STANDARD",
            "document_owner": owner,
            "document_approver": approver,
            "document_sponsor": U("chief.financial.officer"),
            "owning_operating_group": template.get("owning_operating_group") or "ENTERPRISE",
            "primary_risk_category": CLIMATE_CATEGORY,
            "handling_classification": "Internal",
            "applicability": [{"scope_type": "Organization Unit", "scope_value": "ENTERPRISE",
                               "notification_group": "Risk Management Function"}],
        }).insert(ignore_permissions=True)
        version = versioning.create_version(
            doc, change_summary="First draft for review.", origin="Uploaded", version_label="1.0",
            body_text="DEMONSTRATION DOCUMENT: fictitious content.\n\n1. Purpose\nHow climate risk is identified, "
                      "measured and managed across the risk categories it drives.",
        )
        frappe.db.set_value("Governing Document", doc.name, {"current_version": version.name, "version_label": "1.0"})
        lifecycle.take_action(doc.name, "Submit for Review")
    with _As(frappe, U("policy.office.lead")):
        routing.raise_steps(doc.name)

    doc = frappe.get_doc("Governing Document", doc.name)
    first = frappe.db.get_value("Approval Decision", {"subject_name": doc.name, "approval_step": "Second-Line Risk Review"},
                                "name")
    second = frappe.db.get_value("Approval Decision", {"subject_name": doc.name, "approval_step": "Policy Review"},
                                 "name")
    with _As(frappe, U("risk.governance.analyst")):
        routing.decide_step(doc.name, first, "Approved",
                            "Scenario coverage and the link to the risk appetite statement are adequate.")
    # Dated back so the second step has been waiting: raised ten days ago, the
    # first step decided nine days ago, so the second fell due four days ago.
    for step in frappe.get_all("Approval Decision", filters={"subject_name": doc.name}, pluck="name"):
        frappe.db.set_value("Approval Decision", step, "creation", add_to_date(now_datetime(), days=-10),
                            update_modified=False)
    frappe.db.set_value("Approval Decision", first, "decided_on", add_to_date(now_datetime(), days=-9),
                        update_modified=False)
    sent = reminders.remind_approval_steps(decisions=[second])
    notes.append(f"created: {doc.name} {CLIMATE_STANDARD} in review on route {route}; first step decided by the "
                 f"Risk Governance Analyst from the group queue; the Policy Reviewer queue step is overdue "
                 f"({len(sent)} reminder(s) and escalation sent)")


def run(frappe) -> list[str]:
    """Apply the additions. Returns what was done; the caller commits."""
    notes: list[str] = []
    if not frappe.db.exists("Governance Forum", {"forum_name": MATERIAL_FORUM}):
        return ["skipped: the demonstration forums are missing; run deploy/demo_data.py first"]
    for label, step in (("formation paths", formation_paths), ("first quarter", first_quarter),
                        ("meeting notices", meeting_notices), ("charter notices", charter_notices),
                        ("queued policy steps", queued_policy_steps)):
        frappe.db.savepoint("gaps_governance")
        try:
            step(frappe, notes)
        except Exception as exc:  # one step failing must not undo the others
            frappe.db.rollback(save_point="gaps_governance")
            notes.append(f"failed: {label}: {exc}")
    return notes
