"""Forum Vote — controller.

One row per entitled voter. The row *is* the entitlement, so the check that
matters happens here: the seat must have been open on the motion's decision
date, not today. A vote for someone who was not a member then is refused and the
refusal is audited.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from consilium.consilium_core import audit
from consilium.governance import membership as membership_api
from consilium.governance import voting


class ForumVote(Document):
    def validate(self):
        motion = frappe.db.get_value(
            "Forum Motion", self.motion, ["forum", "decision_date", "is_editable"], as_dict=True
        )
        if not motion:
            frappe.throw(_("Motion {0} does not exist.").format(self.motion))

        self._validate_seat(motion)
        self._validate_entitlement(motion)
        self._validate_voter(motion)
        self._validate_frozen(motion)

        if self.position != voting.POSITION_NOT_CAST and not self.cast_on:
            self.cast_on = now()

    def on_trash(self):
        audit.refuse(
            _("Entitlement row {0} cannot be deleted; who was entitled is part of the decision.").format(
                self.name
            ),
            subject_doctype=self.doctype,
            subject_name=self.name,
            attempted_action="Delete",
            control="voting entitlement record",
        )

    # ---------------------------------------------------------------------

    def _validate_seat(self, motion):
        seat = frappe.db.get_value(
            "Forum Membership", self.membership, ["forum", "member", "votes", "delegate",
                                                 "delegate_votes"], as_dict=True
        )
        if not seat:
            frappe.throw(_("Seat {0} does not exist.").format(self.membership))
        if seat.forum != motion.forum:
            frappe.throw(
                _("Seat {0} is on another forum.").format(self.membership), title=_("Wrong Forum")
            )
        if not seat.votes:
            frappe.throw(
                _("Seat {0} carries no vote.").format(self.membership), title=_("Not Entitled")
            )
        self._seat = seat

    def _validate_entitlement(self, motion):
        if membership_api.seat_held_on(self.membership, motion.decision_date):
            return
        audit.refuse(
            _(
                "Seat {0} was not open on {1}, the decision date of motion {2}. Entitlement to vote is "
                "drawn from membership as at the decision date, not as at today."
            ).format(self.membership, motion.decision_date, self.motion),
            subject_doctype="Forum Motion",
            subject_name=self.motion,
            attempted_action="Other",
            control="voting entitlement as at decision date",
            context={"membership": self.membership, "decision_date": str(motion.decision_date)},
            exc=frappe.ValidationError,
        )

    def _validate_voter(self, motion):
        seat = self._seat
        if self.voted_as == "Delegate":
            if not seat.delegate_votes:
                frappe.throw(
                    _("Seat {0} does not permit its delegate to vote.").format(self.membership),
                    title=_("Delegate May Not Vote"),
                )
            seat_row = frappe.db.get_value(
                "Forum Membership", self.membership,
                ["delegate", "delegate_from", "delegate_to"], as_dict=True
            )
            if not membership_api.delegate_active_on(dict(seat_row), motion.decision_date):
                frappe.throw(
                    _("No delegation was in place on {0} for seat {1}.").format(
                        motion.decision_date, self.membership
                    ),
                    title=_("Delegation Not In Force"),
                )
            if self.voter != seat_row.delegate:
                frappe.throw(
                    _("{0} is not the delegate of seat {1}.").format(self.voter, self.membership),
                    title=_("Wrong Delegate"),
                )
            self.acting_for = seat.member
        elif seat.member and self.voter != seat.member:
            frappe.throw(
                _("{0} does not hold seat {1}.").format(self.voter, self.membership),
                title=_("Wrong Voter"),
            )

    def _validate_frozen(self, motion):
        if self.is_new():
            if not motion.is_editable:
                frappe.throw(
                    _("Motion {0} has a recorded outcome; entitlement cannot be added to it.").format(
                        self.motion
                    ),
                    title=_("Motion Closed"),
                )
            return
        if motion.is_editable:
            return
        before = self.get_doc_before_save()
        if before and (before.get("position") or None) != (self.position or None):
            audit.refuse(
                _("Motion {0} has a recorded outcome; its votes can no longer change.").format(self.motion),
                subject_doctype="Forum Motion",
                subject_name=self.motion,
                attempted_action="Modify",
                control="recorded decision immutability",
                context={"vote": self.name},
            )
