"""Motions and votes.

Two properties are the reason this module exists, and both are tested:

* **Entitlement is as at the decision date, not as at today.** Opening a motion
  writes one ``Forum Vote`` row per seat that was entitled *on that date*, and a
  vote for a seat that was not open on that date is refused and audited.
* **Quorum is calculated once and stored on the motion when the outcome is
  recorded.** It is never recomputed, so a membership change made afterwards
  cannot rewrite whether a past decision was quorate. Recording the outcome also
  takes the motion out of editability, which is what freezes the votes.

Nothing here reads a state label. Whether a motion still accepts votes is the
``is_editable`` flag; whether it is still running is ``is_open``.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, now

from consilium.consilium_core import audit
from consilium.governance import membership as membership_api

#: Ballot values. These are data on the vote row, not a workflow state: they are
#: counted, and the counts are what get stored on the motion.
POSITION_NOT_CAST = "Not Cast"
POSITION_FOR = "For"
POSITION_AGAINST = "Against"
POSITION_ABSTAIN = "Abstain"
POSITION_RECUSED = "Recused"


def open_motion(motion, on_date=None):
    """Record who was entitled to vote, by writing a row for each of them.

    Entitlement is recorded whether or not a vote is ever cast, which is what
    makes 'who was entitled' answerable years later.
    """
    if isinstance(motion, str):
        motion = frappe.get_doc("Forum Motion", motion)
    if not motion.is_editable:
        frappe.throw(
            _("Motion {0} has a recorded outcome; its entitlement cannot be reopened.").format(motion.name),
            title=_("Motion Closed"),
        )

    decision_date = getdate(on_date or motion.decision_date)
    created = []
    for seat in membership_api.entitled_voters_as_at(motion.forum, decision_date):
        if frappe.db.exists("Forum Vote", {"motion": motion.name, "membership": seat["name"]}):
            continue
        vote = frappe.get_doc(
            {
                "doctype": "Forum Vote",
                "motion": motion.name,
                "membership": seat["name"],
                "voter": seat["member"],
                "voted_as": "Member",
                "position": POSITION_NOT_CAST,
                "weight": 1,
            }
        ).insert(ignore_permissions=True)
        created.append(vote.name)

    if not motion.opened_on:
        motion.db_set("opened_on", now())
    return created


def entitlement(motion: str) -> list[dict]:
    return frappe.get_all(
        "Forum Vote",
        filters={"motion": motion},
        fields=["name", "membership", "voter", "voted_as", "acting_for", "position", "weight", "cast_on"],
        order_by="creation",
    )


def cast_vote(motion, membership: str, position: str, *, voter: str | None = None,
              rationale: str | None = None, as_delegate: bool = False):
    """Record one ballot. The entitlement row must already exist."""
    if isinstance(motion, str):
        motion = frappe.get_doc("Forum Motion", motion)
    if not motion.is_editable:
        audit.refuse(
            _("Motion {0} has a recorded outcome; its votes can no longer change.").format(motion.name),
            subject_doctype="Forum Motion",
            subject_name=motion.name,
            attempted_action="Other",
            control="motion outcome recorded",
            exc=frappe.ValidationError,
        )

    name = frappe.db.get_value("Forum Vote", {"motion": motion.name, "membership": membership}, "name")
    if not name:
        audit.refuse(
            _(
                "Seat {0} holds no entitlement on motion {1}. Entitlement is drawn from membership "
                "as at the decision date {2}, and a vote cannot be added to it afterwards."
            ).format(membership, motion.name, motion.decision_date),
            subject_doctype="Forum Motion",
            subject_name=motion.name,
            attempted_action="Other",
            control="voting entitlement as at decision date",
            context={"membership": membership},
            exc=frappe.ValidationError,
        )

    vote = frappe.get_doc("Forum Vote", name)
    vote.position = position
    vote.rationale = rationale
    if as_delegate:
        seat = frappe.db.get_value(
            "Forum Membership", membership,
            ["member", "delegate", "delegate_from", "delegate_to", "delegate_votes"], as_dict=True,
        )
        vote.voted_as = "Delegate"
        vote.acting_for = seat.member
        vote.voter = voter or seat.delegate
    elif voter:
        vote.voter = voter
    vote.save(ignore_permissions=True)
    return vote


def tally(motion: str) -> dict:
    rows = entitlement(motion)
    counts = {
        "eligible_voter_count": len(rows),
        "votes_cast": 0,
        "votes_for": 0,
        "votes_against": 0,
        "abstentions": 0,
        "recusals": 0,
    }
    bucket = {
        POSITION_FOR: "votes_for",
        POSITION_AGAINST: "votes_against",
        POSITION_ABSTAIN: "abstentions",
        POSITION_RECUSED: "recusals",
    }
    for row in rows:
        key = bucket.get(row["position"])
        if not key:
            continue
        counts[key] += int(row["weight"] or 1) if key in ("votes_for", "votes_against") else 1
        if key != "recusals":
            counts["votes_cast"] += 1
    return counts


def record_outcome(motion, outcome: str, *, recorded_by: str | None = None,
                   chair_casting_vote_used: bool = False, present_memberships: list[str] | None = None):
    """Freeze the motion: tally the votes, evaluate quorum **once**, and store both.

    After this, the motion is no longer editable and its stored quorum is the
    answer for good. A membership change tomorrow cannot reach back into it.
    """
    if isinstance(motion, str):
        motion = frappe.get_doc("Forum Motion", motion)
    if not motion.is_editable:
        frappe.throw(
            _("Motion {0} already carries a recorded outcome.").format(motion.name),
            title=_("Outcome Already Recorded"),
        )

    if present_memberships is None:
        present_memberships = [
            row["membership"] for row in entitlement(motion.name) if row["position"] != POSITION_NOT_CAST
        ]
    status = membership_api.quorum_status(motion.forum, motion.decision_date, present_memberships)
    counts = tally(motion.name)

    motion.update(counts)
    motion.quorum_required = status["required"]
    motion.quorum_met = 1 if status["met"] else 0
    motion.quorum_basis = _("Evaluated as at {0}. {1}.").format(status["as_at"], status["basis"])
    motion.outcome = outcome
    motion.outcome_recorded_by = recorded_by or frappe.session.user
    motion.chair_casting_vote_used = 1 if chair_casting_vote_used else 0
    motion.closed_on = now()
    motion.flags.consilium_outcome = True
    motion.save(ignore_permissions=True)
    # The permission to write the frozen fields lasts exactly one save.
    motion.flags.consilium_outcome = False
    return motion


def decisions_for(forum: str, *, from_date=None, to_date=None, outcome: str | None = None) -> list[dict]:
    """Every decision a forum has taken. The list E10-S4 asks for."""
    filters = {"forum": forum}
    if from_date:
        filters["decision_date"] = [">=", getdate(from_date)]
    if to_date:
        filters["decision_date"] = ["<=", getdate(to_date)] if not from_date else [
            "between", [getdate(from_date), getdate(to_date)]
        ]
    if outcome:
        filters["outcome"] = outcome
    return frappe.get_all(
        "Forum Motion",
        filters=filters,
        fields=["name", "motion_reference", "motion_text", "decision_date", "outcome",
                "quorum_met", "votes_for", "votes_against", "abstentions", "eligible_voter_count"],
        order_by="decision_date desc, creation desc",
    )
