"""G-14 / O-4: meeting-schedule and charter notifications.

"The system shall send configurable, templated, automated notifications for
... meeting schedules ... and charter reviews." Each event here goes through
``notification.notify`` with a seeded ``Notification Template``, so the tests
read the dispatch rows it writes — the evidence that a person was told.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from consilium.consilium_core import reminders
from consilium.consilium_core.setup import notification_templates
from consilium.governance import charters, meetings
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_seat, make_user, seat_role, unique

NEW_EVENTS = (
    "governance.meeting.scheduled",
    "governance.meeting.rescheduled",
    "governance.meeting.cancelled",
    "governance.charter.review_due",
    "governance.charter.review_overdue",
    "governance.charter.challenge_recorded",
)


def dispatches(doctype: str, name: str) -> list[dict]:
    return frappe.get_all(
        "Notification Dispatch",
        filters={"subject_doctype": doctype, "subject_name": name},
        fields=["recipient", "rendered_subject", "rendered_body"],
        order_by="creation asc",
    )


def told(doctype: str, name: str, subject_starts: str) -> set[str]:
    return {row["recipient"] for row in dispatches(doctype, name)
            if (row["rendered_subject"] or "").startswith(subject_starts)}


class TestTheEventsAreTemplated(GovernanceTestCase):
    def test_every_new_event_has_a_seeded_template(self):
        notification_templates.seed_templates()
        for event in NEW_EVENTS:
            with self.subTest(event=event):
                self.assertIn(event, notification_templates.EVENT_INDEX)
                self.assertTrue(frappe.db.exists("Notification Template", {"event_code": event}))


class TestMeetingSchedules(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.forum = make_forum()
        self.member = make_user()
        self.other_member = make_user()
        self.former = make_user()
        make_seat(self.forum.name, seat_role(), self.member)
        make_seat(self.forum.name, seat_role(), self.other_member)
        make_seat(self.forum.name, seat_role(), self.former, end_date=add_days(nowdate(), -30))
        self.secretary = make_user()

    def meeting(self, when=None, **values):
        return frappe.get_doc({
            "doctype": "Forum Meeting",
            "forum": self.forum.name,
            "meeting_reference": unique("M"),
            "scheduled_on": when or add_to_date(now_datetime(), days=14),
            "status": "Scheduled",
            "location": "Room 4",
            "secretary": self.secretary,
            **values,
        }).insert(ignore_permissions=True)

    def test_scheduling_a_meeting_tells_the_members_and_the_secretary(self):
        meeting = self.meeting()
        people = told("Forum Meeting", meeting.name, "Meeting scheduled")
        self.assertEqual(people, {self.member, self.other_member, self.secretary})
        self.assertNotIn(self.former, people)
        body = dispatches("Forum Meeting", meeting.name)[0]["rendered_body"]
        self.assertIn("Room 4", body)

    def test_moving_a_meeting_tells_them_again_with_the_old_and_new_time(self):
        meeting = self.meeting()
        meeting.scheduled_on = add_to_date(now_datetime(), days=21)
        meeting.save(ignore_permissions=True)
        people = told("Forum Meeting", meeting.name, "Meeting moved")
        self.assertEqual(people, {self.member, self.other_member, self.secretary})

    def test_moving_the_place_is_a_reschedule_too_and_an_unrelated_edit_is_not(self):
        meeting = self.meeting()
        meeting.chaired_by = self.member
        meeting.save(ignore_permissions=True)
        self.assertFalse(told("Forum Meeting", meeting.name, "Meeting moved"))
        meeting.location = "Room 9"
        meeting.save(ignore_permissions=True)
        self.assertTrue(told("Forum Meeting", meeting.name, "Meeting moved"))

    def test_cancelling_a_meeting_tells_them(self):
        meeting = self.meeting()
        meeting.status = "Cancelled"
        meeting.save(ignore_permissions=True)
        people = told("Forum Meeting", meeting.name, "Meeting cancelled")
        self.assertEqual(people, {self.member, self.other_member, self.secretary})

    def test_recording_a_past_meeting_announces_nothing(self):
        meeting = self.meeting(when=add_to_date(now_datetime(), days=-10))
        self.assertEqual(dispatches("Forum Meeting", meeting.name), [])
        meeting.status = "Held"
        meeting.held_on = meeting.scheduled_on
        meeting.save(ignore_permissions=True)
        self.assertEqual(dispatches("Forum Meeting", meeting.name), [])

    def test_the_event_is_read_from_flags(self):
        meeting = self.meeting()
        before = frappe._dict(meeting.as_dict())
        self.assertIsNone(meetings.meeting_event(meeting, before))


class TestCharterNotices(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user()
        self.secretary = make_user()
        self.forum = make_forum(forum_owner=self.owner, secretary=self.secretary)
        # make_forum's owner fields may be re-derived from seats; set them plainly.
        frappe.db.set_value("Governance Forum", self.forum.name,
                            {"forum_owner": self.owner, "secretary": self.secretary}, update_modified=False)

    def charter(self, **values):
        return frappe.get_doc({"doctype": "Committee Charter", "charter_title": unique("Charter"),
                               "forum": self.forum.name, **values}).insert(ignore_permissions=True)

    def test_a_challenge_tells_the_owner_the_secretary_and_the_office(self):
        charter = self.charter()
        charters.record_challenge(charter, charters.CHALLENGE_CHANGES_REQUESTED,
                                  comments="Clarify the escalation threshold.", by=self.rgo)
        people = told("Committee Charter", charter.name, "Charter challenged")
        self.assertIn(self.owner, people)
        self.assertIn(self.secretary, people)
        self.assertIn(self.rgo, people)
        body = dispatches("Committee Charter", charter.name)[0]["rendered_body"]
        self.assertIn("Clarify the escalation threshold.", body)

    def test_clearing_the_challenge_tells_them_it_is_cleared(self):
        charter = self.charter()
        charters.record_challenge(charter, charters.CHALLENGE_CLEARED, by=self.rgo)
        people = told("Committee Charter", charter.name, "Charter challenge cleared")
        self.assertIn(self.owner, people)
        self.assertIn(self.rgo, people)

    def test_a_review_falling_due_is_sent_once_to_the_owner_and_secretary(self):
        charter = self.charter(next_charter_review_on=add_days(nowdate(), 10))
        sent = reminders.remind_charter_reviews(charters=[charter.name])
        self.assertEqual(len(sent), 2)
        self.assertEqual(told("Committee Charter", charter.name, "Charter review due"), {self.owner, self.secretary})
        # Reminder Log: the same run again sends nothing.
        self.assertEqual(reminders.remind_charter_reviews(charters=[charter.name]), [])

    def test_an_overdue_review_is_chased(self):
        charter = self.charter(next_charter_review_on=add_days(nowdate(), -3))
        reminders.remind_charter_reviews(charters=[charter.name])
        self.assertEqual(told("Committee Charter", charter.name, "Charter review overdue"),
                         {self.owner, self.secretary})

    def test_a_review_far_off_or_on_an_ended_charter_is_not_sent(self):
        later = self.charter(next_charter_review_on=add_days(nowdate(), 90))
        ended = self.charter(next_charter_review_on=add_days(nowdate(), -3), effective_to=add_days(nowdate(), -1))
        self.assertEqual(reminders.remind_charter_reviews(charters=[later.name, ended.name]), [])

    def test_the_daily_run_includes_charter_reviews(self):
        self.assertIn("charter reviews", [label for label, _doctype, _fn in reminders.DAILY])
