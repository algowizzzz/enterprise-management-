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


# ---------------------------------------------------------------------------
# The voting screen (`/forum-motion`).
#
# Everything above had no caller outside the tests and the demonstration
# loader: a motion could be put, and a vote recorded, only from a Python shell
# or the desk. What follows are the portal's doors onto it:
#
# * the secretary puts a motion to the forum, which records who is entitled to
#   vote on its decision date (``open_motion``);
# * each entitled member — or the seat's standing delegate, where the seat lets
#   the delegate vote — casts their own ballot, and only their own;
# * the secretary records the outcome, which evaluates quorum once and freezes
#   the motion (``record_outcome``). An outcome that would stand as the
#   forum's decision is refused while the sitting is inquorate.
#
# "Secretary" is standing, not a state: whoever may write motions (the
# Committee Secretary role), or the person the forum names as its secretary.
# Whether a motion still takes votes is its ``is_editable`` flag, and whether an
# outcome is a standing decision is read from that outcome's flags, never from
# its label.
# ---------------------------------------------------------------------------

#: The ballots a voter may cast. "Not Cast" is where a ballot starts, not a choice.
CASTABLE_POSITIONS = (POSITION_FOR, POSITION_AGAINST, POSITION_ABSTAIN, POSITION_RECUSED)


def may_administer(forum: str, user: str | None = None) -> bool:
    """Whether ``user`` acts as the forum's secretary for its motions."""
    user = user or frappe.session.user
    if frappe.has_permission("Forum Motion", "write", user=user):
        return True
    return bool(forum) and frappe.db.get_value("Governance Forum", forum, "secretary") == user


def _is_standing_decision(outcome: str) -> bool:
    """An outcome that closes the motion as the forum's decision: it leaves the
    motion active, not editable and not needing review (carried, not carried).
    Read from the outcome's flags; an inquorate, deferred or withdrawn motion
    is none of these."""
    from consilium.consilium_core import state_flags

    flags = state_flags.flags_for("Forum Motion", "outcome", outcome) or {}
    return bool(flags.get("is_active") and not flags.get("is_editable") and not flags.get("requires_review"))


def _my_seats(motion, user: str) -> list[dict]:
    """The ballots on this motion ``user`` may cast: their own seat's, and any
    seat whose standing delegate they were on the decision date, where the seat
    lets its delegate vote."""
    out = []
    for row in entitlement(motion.name):
        seat = frappe.db.get_value(
            "Forum Membership", row["membership"],
            ["name", "member", "delegate", "delegate_from", "delegate_to", "delegate_votes"], as_dict=True,
        ) or frappe._dict()
        if seat.member == user:
            out.append({"membership": row["membership"], "as_delegate": False, "for": user})
        elif (seat.delegate == user and seat.delegate_votes
              and membership_api.delegate_active_on(seat, motion.decision_date)):
            out.append({"membership": row["membership"], "as_delegate": True, "for": seat.member})
    return out


def _may_read_motion(motion, user: str) -> bool:
    if frappe.has_permission("Forum Motion", "read", doc=motion, user=user):
        return True
    return bool(_my_seats(motion, user))


def motion_context(motion: str) -> dict:
    """Everything the voting screen shows, and what the viewer may do."""
    user = frappe.session.user
    doc = frappe.get_doc("Forum Motion", motion)
    if not _may_read_motion(doc, user):
        frappe.throw(_("Motion {0} is not open to you.").format(motion), frappe.PermissionError)
    seats = {row["membership"]: row for row in _my_seats(doc, user)}
    ballots = []
    for row in entitlement(doc.name):
        member = frappe.db.get_value("Forum Membership", row["membership"], "member")
        mine = seats.get(row["membership"])
        ballots.append({
            **row,
            "member": member,
            "cast_on": str(row["cast_on"]) if row["cast_on"] else None,
            "cast": row["position"] != POSITION_NOT_CAST,
            "mine": bool(mine),
            "as_delegate": bool(mine and mine["as_delegate"]),
        })
    administer = may_administer(doc.forum, user)
    open_for_votes = bool(doc.is_editable)
    present = [b["membership"] for b in ballots if b["cast"]]
    quorum = membership_api.quorum_status(doc.forum, doc.decision_date, present)
    outcome_field = frappe.get_meta("Forum Motion").get_field("outcome")
    return {
        "motion": {
            key: (str(doc.get(key)) if doc.get(key) is not None and key.endswith(("_on", "_date")) else doc.get(key))
            for key in ("name", "forum", "meeting", "motion_reference", "motion_text", "decision_date",
                        "voting_mode", "proposed_by", "seconded_by", "opened_on", "closed_on", "outcome",
                        "is_open", "is_editable", "eligible_voter_count", "votes_cast", "votes_for",
                        "votes_against", "abstentions", "quorum_required", "quorum_met", "quorum_basis",
                        "outcome_recorded_by", "chair_casting_vote_used")
        },
        "forum_name": frappe.db.get_value("Governance Forum", doc.forum, "forum_name"),
        "ballots": ballots,
        "tally": tally(doc.name),
        "quorum": quorum,
        "may_vote": open_for_votes and bool(seats),
        "positions": list(CASTABLE_POSITIONS),
        "may_record_outcome": open_for_votes and administer,
        "outcomes": [
            {"outcome": option, "standing_decision": _is_standing_decision(option)}
            for option in (outcome_field.options or "").split("\n") if option
        ] if open_for_votes and administer else [],
    }


@frappe.whitelist(methods=["GET"])
def get_motion(motion: str) -> dict:
    return motion_context(motion)


@frappe.whitelist(methods=["POST"])
def propose_motion(forum: str, motion_reference: str, motion_text: str, decision_date: str,
                   meeting: str | None = None, voting_mode: str = "In Meeting",
                   proposed_by: str | None = None, seconded_by: str | None = None) -> dict:
    """Put a motion to the forum and record who may vote on it."""
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not may_administer(forum):
        audit.refuse(
            _("{0} may not put a motion to forum {1}. Motions are put by the forum's secretary.").format(
                frappe.session.user, forum),
            subject_doctype="Governance Forum",
            subject_name=forum,
            attempted_action="Create",
            control="motion secretary",
        )
    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        frappe.throw(_("Forum {0} is closed and takes no further decisions.").format(forum),
                     title=_("Forum Inactive"))
    if not (motion_reference or "").strip() or not (motion_text or "").strip() or not decision_date:
        frappe.throw(_("A motion needs its reference, its wording and its decision date."),
                     title=_("Motion Incomplete"))
    doc = frappe.get_doc({
        "doctype": "Forum Motion",
        "forum": forum,
        "meeting": meeting or None,
        "motion_reference": motion_reference.strip(),
        "motion_text": motion_text.strip(),
        "decision_date": getdate(decision_date),
        "voting_mode": voting_mode or "In Meeting",
        "proposed_by": proposed_by or None,
        "seconded_by": seconded_by or None,
    }).insert(ignore_permissions=True)
    open_motion(doc)
    return {**motion_context(doc.name), "created": doc.name}


@frappe.whitelist(methods=["POST"])
def cast_my_vote(motion: str, membership: str, position: str, rationale: str | None = None) -> dict:
    """Cast the caller's own ballot — for their seat, or as its standing delegate."""
    doc = frappe.get_doc("Forum Motion", motion)
    mine = {row["membership"]: row for row in _my_seats(doc, frappe.session.user)}
    seat = mine.get(membership)
    if not seat:
        audit.refuse(
            _("{0} holds no vote for seat {1} on motion {2}: a ballot is cast by the seat's member, or by "
              "its standing delegate where the seat allows it.").format(frappe.session.user, membership, motion),
            subject_doctype="Forum Motion",
            subject_name=motion,
            attempted_action="Other",
            control="voting entitlement",
            context={"membership": membership},
        )
    if position not in CASTABLE_POSITIONS:
        frappe.throw(_("{0} is not a ballot that can be cast.").format(position), title=_("Unknown Ballot"))
    cast_vote(doc, membership, position, voter=frappe.session.user, rationale=(rationale or "").strip() or None,
              as_delegate=seat["as_delegate"])
    return motion_context(motion)


@frappe.whitelist(methods=["POST"])
def record_motion_outcome(motion: str, outcome: str, chair_casting_vote_used=0) -> dict:
    """The secretary records the outcome. Quorum is evaluated once, here."""
    doc = frappe.get_doc("Forum Motion", motion)
    if not may_administer(doc.forum):
        audit.refuse(
            _("{0} may not record the outcome of motion {1}. The forum's secretary records it.").format(
                frappe.session.user, motion),
            subject_doctype="Forum Motion",
            subject_name=motion,
            attempted_action="Other",
            control="motion secretary",
        )
    options = [o for o in (frappe.get_meta("Forum Motion").get_field("outcome").options or "").split("\n") if o]
    if outcome not in options:
        frappe.throw(_("{0} is not an outcome a motion can record.").format(outcome), title=_("Unknown Outcome"))
    present = [row["membership"] for row in entitlement(doc.name) if row["position"] != POSITION_NOT_CAST]
    quorum = membership_api.quorum_status(doc.forum, doc.decision_date, present)
    if _is_standing_decision(outcome) and not quorum["met"]:
        audit.refuse(
            _("Motion {0} cannot be recorded as {1}: the sitting is not quorate ({2}). Record it as "
              "inquorate or deferred instead.").format(motion, outcome, quorum["basis"]),
            subject_doctype="Forum Motion",
            subject_name=motion,
            attempted_action="Other",
            control="quorum",
            context={"quorum": quorum},
            exc=frappe.ValidationError,
        )
    record_outcome(doc, outcome, chair_casting_vote_used=bool(int(chair_casting_vote_used or 0)),
                   present_memberships=present)
    return motion_context(motion)
