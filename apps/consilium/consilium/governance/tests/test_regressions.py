"""Regressions found while loading a realistic demonstration organisation.

Each test here failed before its fix; the docstring names the bug.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.governance import formation, meetings, reviews
from consilium.governance.tests.utils import (
    GovernanceTestCase,
    make_forum,
    make_seat,
    make_user,
    seat_role,
    unique,
)


class TestSeatVotingRights(GovernanceTestCase):
    def test_a_seat_can_be_made_non_voting_when_its_role_votes_by_default(self):
        """An unticked box looked like "not given", so the role's default always won."""
        forum = make_forum()
        role = seat_role(votes_by_default=1, counts_toward_quorum=1)
        seat = make_seat(forum.name, role, votes=0, counts_toward_quorum=0, set_voting_rights_manually=1)
        seat.reload()
        self.assertFalse(seat.votes)
        self.assertFalse(seat.counts_toward_quorum)

    def test_without_the_override_the_role_default_still_applies(self):
        forum = make_forum()
        role = seat_role(votes_by_default=1, counts_toward_quorum=1)
        seat = make_seat(forum.name, role)
        seat.reload()
        self.assertTrue(seat.votes)
        self.assertTrue(seat.counts_toward_quorum)


class TestOverdueReviews(GovernanceTestCase):
    def test_a_forum_with_no_review_date_is_not_reported_overdue(self):
        """An empty date compares as the earliest possible day."""
        undated = make_forum(next_review_on=None)
        late = make_forum(next_review_on=add_days(nowdate(), -10))
        reported = {row["forum"] for row in reviews.overdue_reviews() if row["reason"] == "review_overdue"}
        self.assertIn(late.name, reported)
        self.assertNotIn(undated.name, reported)


class TestMinutes(GovernanceTestCase):
    def meeting(self):
        forum = make_forum()
        return frappe.get_doc(
            {"doctype": "Forum Meeting", "forum": forum.name, "meeting_reference": unique("M"),
             "scheduled_on": nowdate(), "held_on": nowdate(), "status": "Held"}
        ).insert(ignore_permissions=True)

    def test_minutes_are_recorded_as_a_version_the_meeting_points_at(self):
        """Nothing wrote the meeting's minutes link, so minutes could not be kept."""
        meeting = self.meeting()
        first = meetings.record_minutes(meeting, "Quorate. The risk appetite was approved.")
        meeting.reload()
        self.assertEqual(meeting.minutes_version, first.name)

        corrected = meetings.record_minutes(meeting, "Quorate. Approved, with one abstention.",
                                            change_summary="The abstention was omitted.")
        meeting.reload()
        self.assertEqual(meeting.minutes_version, corrected.name)
        self.assertGreater(corrected.version_number, first.version_number)

    def test_empty_minutes_are_refused(self):
        meeting = self.meeting()
        with self.assertRaises(frappe.ValidationError):
            meetings.record_minutes(meeting, "   ")

    def test_someone_who_cannot_edit_the_meeting_cannot_minute_it(self):
        meeting = self.meeting()
        viewer = make_user("Governance Viewer")
        frappe.set_user(viewer)
        try:
            with self.assertRaises(frappe.PermissionError):
                meetings.record_meeting_minutes(meeting.name, "Minutes.")
        finally:
            frappe.set_user("Administrator")


class TestRoleBasedAssignment(GovernanceTestCase):
    def test_a_role_based_step_goes_to_an_enabled_person_and_never_the_built_in_administrator(self):
        """The first row the database returned won, even a disabled account."""
        role = frappe.get_doc({"doctype": "Role", "role_name": unique("Approver Role"),
                               "desk_access": 1}).insert(ignore_permissions=True).name
        disabled = make_user(role, email=f"a-{unique('disabled').lower()}@example.com")
        frappe.db.set_value("User", disabled, "enabled", 0)
        enabled = make_user(role, email=f"b-{unique('enabled').lower()}@example.com")
        frappe.get_doc("User", "Administrator").add_roles(role)
        self.assertEqual(formation._role_holder(role), enabled)

    def test_no_enabled_holder_means_no_assignee(self):
        role = frappe.get_doc({"doctype": "Role", "role_name": unique("Empty Role"),
                               "desk_access": 1}).insert(ignore_permissions=True).name
        self.assertIsNone(formation._role_holder(role))
