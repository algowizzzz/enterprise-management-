"""Forum membership: who sat on a forum, when, and what that entitled them to.

Membership is a standalone dated record (structural decision M-1), so every
question about the past is a date-range filter rather than a replay of version
diffs. Three things are built on that:

* **Membership as at a date.** The only query the rest of the module uses. It
  never asks who sits on a forum *now* unless now is the date in question.
* **The officer fields on the forum.** ``committee_chair``, ``secretary`` and
  ``forum_owner`` are denormalised for query performance and are therefore
  derived, by one code path, on every membership change — with a reconciliation
  sweep that reports drift, because a denormalisation without a reconciliation
  check is a defect waiting to happen (07-assumptions-and-gaps.md C-4).
* **Quorum.** Configurable per forum as a count or a percentage, and always
  evaluated as at a date.
"""

from __future__ import annotations

import math

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

#: Seat-role flag -> the forum field derived from it. The single derivation path.
OFFICER_FIELDS = (
    ("is_chair_role", "committee_chair"),
    ("is_secretary_role", "secretary"),
    ("is_owner_role", "forum_owner"),
)

_SEAT_FIELDS = """"name", "forum", "member", "seat_type", "position_title", "forum_role",
    "votes", "counts_toward_quorum", "is_voting_chair", "delegate", "delegate_from",
    "delegate_to", "delegate_votes", "start_date", "end_date" """


def members_as_at(forum: str, on_date=None) -> list[dict]:
    """Every seat that was open on ``on_date``, vacant seats included.

    A seat counts on its start date and on its end date; a seat closed yesterday
    does not count today.
    """
    on_date = getdate(on_date or nowdate())
    return frappe.db.sql(
        f"""SELECT {_SEAT_FIELDS}
            FROM "tabForum Membership"
            WHERE "forum" = %(forum)s
              AND "docstatus" < 2
              AND "start_date" <= %(on_date)s
              AND ("end_date" IS NULL OR "end_date" >= %(on_date)s)
            ORDER BY "start_date", "name" """,
        {"forum": forum, "on_date": on_date},
        as_dict=True,
    )


def seat_held_on(membership: str, on_date) -> bool:
    """Was this seat open on that date? The entitlement question, asked directly."""
    row = frappe.db.get_value(
        "Forum Membership", membership, ["start_date", "end_date", "docstatus"], as_dict=True
    )
    if not row or int(row.docstatus or 0) > 1:
        return False
    on_date = getdate(on_date)
    if getdate(row.start_date) > on_date:
        return False
    return row.end_date is None or getdate(row.end_date) >= on_date


def entitled_voters_as_at(forum: str, on_date) -> list[dict]:
    """Seats entitled to vote on a date: the seat votes, and it is occupied.

    A vacant by-position seat carries no vote, because nobody holds it.
    """
    return [seat for seat in members_as_at(forum, on_date) if seat["votes"] and seat["member"]]


def quorum_counting_seats_as_at(forum: str, on_date) -> list[dict]:
    return [seat for seat in members_as_at(forum, on_date) if seat["counts_toward_quorum"]]


def role_defaults(forum_role: str) -> dict:
    return (
        frappe.db.get_value(
            "Governance Forum Role",
            forum_role,
            ["counts_toward_quorum", "votes_by_default", "can_attest", "is_chair_role",
             "is_secretary_role", "is_owner_role", "max_holders"],
            as_dict=True,
        )
        or {}
    )


def delegate_active_on(seat: dict, on_date) -> bool:
    """Whether a seat's standing delegate was in place on a date."""
    if not seat.get("delegate"):
        return False
    on_date = getdate(on_date)
    if seat.get("delegate_from") and getdate(seat["delegate_from"]) > on_date:
        return False
    if seat.get("delegate_to") and getdate(seat["delegate_to"]) < on_date:
        return False
    return True


# ---------------------------------------------------------------- officers


def derive_officers(forum: str, on_date=None) -> dict:
    """What the forum's officer fields should say, read from the seats."""
    seats = members_as_at(forum, on_date)
    derived = {fieldname: None for _flag, fieldname in OFFICER_FIELDS}
    for seat in seats:
        if not seat["member"]:
            continue
        flags = role_defaults(seat["forum_role"])
        for flag, fieldname in OFFICER_FIELDS:
            if flags.get(flag) and not derived[fieldname]:
                derived[fieldname] = seat["member"]
    return derived


def sync_officers(forum: str) -> dict:
    """Write the derived officer fields. **The single derivation path.**"""
    if not frappe.db.exists("Governance Forum", forum):
        return {}
    derived = derive_officers(forum)
    doc = frappe.get_doc("Governance Forum", forum)
    changed = {}
    for fieldname, value in derived.items():
        if (doc.get(fieldname) or None) != value:
            doc.db_set(fieldname, value, update_modified=False)
            changed[fieldname] = value
    return changed


def officer_drift(forums: list[str] | None = None) -> list[dict]:
    """Reconciliation sweep: where the stored officer fields disagree with the seats.

    An empty result is the healthy state. Anything here is a defect, not a
    difference of opinion.
    """
    names = forums or frappe.get_all("Governance Forum", pluck="name")
    drift = []
    for name in names:
        stored = frappe.db.get_value(
            "Governance Forum", name, [f for _flag, f in OFFICER_FIELDS], as_dict=True
        )
        derived = derive_officers(name)
        for fieldname, value in derived.items():
            if (stored.get(fieldname) or None) != value:
                drift.append(
                    {"forum": name, "fieldname": fieldname, "stored": stored.get(fieldname), "derived": value}
                )
    return drift


# ------------------------------------------------------------------ quorum


def quorum_requirement(forum_doc, counting_seats: list[dict], voting_seats: list[dict]) -> tuple[float, str]:
    """How many seats the forum's configured rule requires, and why.

    The rule type is forum configuration, not a workflow state.
    """
    rule = forum_doc.quorum_rule_type
    value = float(forum_doc.quorum_value or 0)
    if rule == "Percentage":
        required = math.ceil(len(voting_seats) * value / 100.0)
        return float(required), _(
            "{0}% of {1} entitled voters = {2}"
        ).format(value, len(voting_seats), required)
    if rule == "All Voting Members":
        return float(len(voting_seats)), _("all {0} entitled voters").format(len(voting_seats))
    if rule == "Chair Plus Count":
        return value, _("the chair plus {0} counting seats").format(value)
    return value, _("a fixed count of {0} counting seats").format(value)


def quorum_status(forum: str, on_date=None, present_memberships: list[str] | None = None) -> dict:
    """Whether quorum is met for a forum on a date.

    ``present_memberships`` narrows the count to the seats actually present —
    that is a meeting. Without it the answer is whether the forum *could* be
    quorate, which is what a secretary asks before calling one.
    """
    on_date = getdate(on_date or nowdate())
    forum_doc = frappe.get_doc("Governance Forum", forum)
    counting = quorum_counting_seats_as_at(forum, on_date)
    voting = entitled_voters_as_at(forum, on_date)

    if present_memberships is not None:
        present = set(present_memberships)
    else:
        # No attendance given: every occupied counting seat is treated as available.
        present = {seat["name"] for seat in counting if seat["member"]}
    counted = [seat for seat in counting if seat["name"] in present]

    required, basis = quorum_requirement(forum_doc, counting, voting)
    met = len(counted) >= required

    chair_present = any(role_defaults(seat["forum_role"]).get("is_chair_role") for seat in counted)
    requires_chair = bool(forum_doc.quorum_requires_chair) or forum_doc.quorum_rule_type == "Chair Plus Count"
    if requires_chair and not chair_present:
        met = False
        basis = f"{basis}; the chair must be present"

    return {
        "forum": forum,
        "as_at": str(on_date),
        "rule": forum_doc.quorum_rule_type,
        "counting_seats": len(counting),
        "entitled_voters": len(voting),
        "counted": len(counted),
        "required": required,
        "met": bool(met),
        "chair_present": bool(chair_present),
        "basis": _("{0}; {1} of {2} counting seats present").format(basis, len(counted), len(counting)),
    }


def close_seat(membership: str, end_date=None, end_reason: str | None = None):
    """End a seat. Never deletes the row — that is the point of M-1."""
    doc = frappe.get_doc("Forum Membership", membership)
    doc.end_date = getdate(end_date or nowdate())
    if end_reason:
        doc.end_reason = end_reason
    doc.save(ignore_permissions=True)
    return doc
