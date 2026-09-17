"""Forum Motion — controller.

A motion's counters and its quorum verdict are written once, by
``voting.record_outcome``. Afterwards the record is closed: the semantic flag
says it is no longer editable, and that is what stops a later membership change
from rewriting whether a past decision was quorate.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import audit
from consilium.governance import setup

#: Written only when the outcome is recorded.
FROZEN_FIELDS = (
    "eligible_voter_count", "votes_cast", "votes_for", "votes_against", "abstentions",
    "quorum_required", "quorum_met", "quorum_basis", "outcome", "closed_on",
    "outcome_recorded_by", "chair_casting_vote_used", "decision_date",
)


class ForumMotion(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        self._guard_frozen()
        if self.meeting:
            meeting = frappe.db.get_value(
                "Forum Meeting", self.meeting, ["forum", "is_committable"], as_dict=True
            )
            if meeting and meeting.forum != self.forum:
                frappe.throw(
                    _("Meeting {0} belongs to another forum.").format(self.meeting),
                    title=_("Wrong Forum"),
                )

    def _guard_frozen(self):
        if self.flags.consilium_outcome or self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or before.get("is_editable"):
            return
        changed = [f for f in FROZEN_FIELDS if (before.get(f) or None) != (self.get(f) or None)]
        if changed:
            audit.refuse(
                _(
                    "Motion {0} carries a recorded outcome. Its counters and its quorum verdict were "
                    "evaluated as at {1} and stored then; they are the answer for good."
                ).format(self.name, self.decision_date),
                subject_doctype=self.doctype,
                subject_name=self.name,
                attempted_action="Modify",
                control="recorded decision immutability",
                context={"fields": changed},
            )
