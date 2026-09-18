"""Forum Meeting — controller.

Attendance is snapshotted: each row records whether that seat counted toward
quorum at the time, so a later seat-role change cannot rewrite whether the
meeting was quorate. Quorum is evaluated and stored when attendance is recorded.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.governance import meetings
from consilium.governance import membership as membership_api
from consilium.governance import setup


class ForumMeeting(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        self._snapshot_attendance()
        self._evaluate_quorum()

    def on_update(self):
        # G-14: the forum's members are told when a meeting is scheduled, moved
        # or cancelled. Read from the meeting's flags; see meetings.announce.
        meetings.announce(self)

    def _snapshot_attendance(self):
        for row in self.get("attendance") or []:
            if not row.membership:
                row.counts_toward_quorum = 0
                continue
            seat = frappe.db.get_value(
                "Forum Membership", row.membership, ["forum", "member", "counts_toward_quorum"],
                as_dict=True,
            )
            if not seat:
                frappe.throw(_("Seat {0} does not exist.").format(row.membership))
            if seat.forum != self.forum:
                frappe.throw(
                    _("Seat {0} is on another forum.").format(row.membership), title=_("Wrong Forum")
                )
            row.counts_toward_quorum = 1 if (seat.counts_toward_quorum and row.present) else 0

    def _evaluate_quorum(self):
        """Only where the meeting actually sat, which the semantic flag says."""
        if not self.is_committable:
            return
        as_at = getdate(self.held_on or self.scheduled_on)
        present = [row.membership for row in self.get("attendance") or [] if row.membership and row.present]
        status = membership_api.quorum_status(self.forum, as_at, present)
        self.quorum_met = 1 if status["met"] else 0
        self.quorum_evaluated_note = _("Evaluated as at {0}. {1}.").format(status["as_at"], status["basis"])
