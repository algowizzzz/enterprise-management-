"""Forum Membership — controller.

The invariants 02-data-model.md §6.3 lists, enforced here because the database
cannot express them (03-schema.md §9.2):

1. No two open seats for the same person on the same forum.
2. At most one open chair seat per forum.
3. ``end_date >= start_date``.
4. A by-position seat may stand vacant; a person seat may not.
5. Closing a seat never deletes the row.

Saving a seat also refreshes the forum's derived officer fields, through the one
derivation path that exists.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.consilium_core import audit
from consilium.governance import membership as membership_api


class ForumMembership(Document):
    def validate(self):
        self._apply_role_defaults()
        self._validate_occupancy()
        self._validate_dates()
        self._validate_delegation()
        self._validate_no_overlap()
        self._validate_single_chair()
        self._validate_seat_cap()

    def on_update(self):
        membership_api.sync_officers(self.forum)

    def after_insert(self):
        membership_api.sync_officers(self.forum)

    def on_trash(self):
        audit.refuse(
            _(
                "Seat {0} cannot be deleted. A seat is closed by setting an end date, so that the "
                "composition of forum {1} at any past date remains answerable."
            ).format(self.name, self.forum),
            subject_doctype=self.doctype,
            subject_name=self.name,
            attempted_action="Delete",
            control="membership history",
        )

    # ---------------------------------------------------------------------

    def _apply_role_defaults(self):
        """The seat role carries the defaults; the seat may override them."""
        if not self.forum_role:
            return
        defaults = membership_api.role_defaults(self.forum_role)
        if self.is_new():
            if self.votes is None or self.votes == 0:
                self.votes = defaults.get("votes_by_default") or 0
            if self.counts_toward_quorum is None or self.counts_toward_quorum == 0:
                self.counts_toward_quorum = defaults.get("counts_toward_quorum") or 0

    def _validate_occupancy(self):
        if self.seat_type == "Position":
            if not self.position_title:
                frappe.throw(
                    _("A seat held by position needs the position's title; that is the seat's identity."),
                    title=_("Position Required"),
                )
        elif not self.member:
            frappe.throw(
                _("A seat held by a person needs the person. Only a by-position seat may stand vacant."),
                title=_("Member Required"),
            )

    def _validate_dates(self):
        if self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("A seat cannot end before it starts."), title=_("Invalid Dates"))

    def _validate_delegation(self):
        if not self.delegate:
            return
        if self.delegate == self.member:
            frappe.throw(_("A member cannot be their own delegate."), title=_("Invalid Delegation"))
        if self.delegate_from and self.delegate_to and getdate(self.delegate_to) < getdate(self.delegate_from):
            frappe.throw(_("A delegation cannot end before it starts."), title=_("Invalid Dates"))
        if self.delegate_votes and not self.votes:
            frappe.throw(
                _("A delegate cannot vote for a seat that holds no vote."),
                title=_("Invalid Delegation"),
            )

    def _overlapping(self, extra_filters: dict) -> list[str]:
        """Open seats on this forum that overlap this one's date range."""
        conditions = {"forum": self.forum, "name": ["!=", self.name or ""], **extra_filters}
        candidates = frappe.get_all(
            "Forum Membership", filters=conditions, fields=["name", "start_date", "end_date"]
        )
        start, end = getdate(self.start_date), getdate(self.end_date) if self.end_date else None
        clashes = []
        for row in candidates:
            other_start = getdate(row["start_date"])
            other_end = getdate(row["end_date"]) if row["end_date"] else None
            if (end is None or other_start <= end) and (other_end is None or other_end >= start):
                clashes.append(row["name"])
        return clashes

    def _validate_no_overlap(self):
        if not self.member:
            return
        clashes = self._overlapping({"member": self.member})
        if clashes:
            frappe.throw(
                _("{0} already holds seat {1} on this forum over the same period.").format(
                    self.member, clashes[0]
                ),
                title=_("Duplicate Seat"),
            )

    def _validate_single_chair(self):
        defaults = membership_api.role_defaults(self.forum_role)
        if not defaults.get("is_chair_role"):
            return
        chair_roles = frappe.get_all(
            "Governance Forum Role", filters={"is_chair_role": 1}, pluck="name"
        )
        clashes = self._overlapping({"forum_role": ["in", chair_roles]})
        if clashes:
            frappe.throw(
                _("Forum {0} already has a chair seat ({1}) over the same period.").format(
                    self.forum, clashes[0]
                ),
                title=_("Chair Already Seated"),
            )

    def _validate_seat_cap(self):
        cap = int(membership_api.role_defaults(self.forum_role).get("max_holders") or 0)
        if cap <= 0:
            return
        held = len(self._overlapping({"forum_role": self.forum_role}))
        if held + 1 > cap:
            frappe.throw(
                _("Seat role {0} allows at most {1} concurrent holder(s) on a forum.").format(
                    self.forum_role, cap
                ),
                title=_("Seat Cap Reached"),
            )
