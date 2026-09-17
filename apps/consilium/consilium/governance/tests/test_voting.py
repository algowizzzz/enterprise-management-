"""Meetings, motions and votes.

The two properties this module exists for:

* entitlement is derived from membership **as at the decision date**;
* a recorded decision's quorum verdict is stored, and nothing later rewrites it.
"""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import membership, voting
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_seat, make_user, seat_role,
)


def make_motion(forum, decision_date=None, **values):
    defaults = {
        "doctype": "Forum Motion",
        "forum": forum,
        "motion_reference": "MOT-1",
        "motion_text": "That the mandate be adopted.",
        "decision_date": decision_date or nowdate(),
        "voting_mode": "In Meeting",
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class TestEntitlement(GovernanceTestCase):
    def test_entitlement_is_drawn_from_membership_as_at_the_decision_date(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=1)
        role = seat_role()
        past = make_seat(forum.name, role, start_date=add_days(nowdate(), -400),
                         end_date=add_days(nowdate(), -100))
        present = make_seat(forum.name, role, start_date=add_days(nowdate(), -50))

        motion = make_motion(forum.name, add_days(nowdate(), -200))
        voting.open_motion(motion)

        entitled = {row["membership"] for row in voting.entitlement(motion.name)}
        self.assertIn(past.name, entitled)
        self.assertNotIn(present.name, entitled)

    def test_a_vote_for_someone_who_was_not_a_member_then_is_refused(self):
        """The failure path that matters most in this module."""
        forum = make_forum()
        role = seat_role()
        make_seat(forum.name, role, start_date=add_days(nowdate(), -400),
                  end_date=add_days(nowdate(), -100))
        latecomer = make_seat(forum.name, role, start_date=add_days(nowdate(), -50))

        motion = make_motion(forum.name, add_days(nowdate(), -200))
        voting.open_motion(motion)
        self.purge_on_teardown("Forum Motion", motion.name)

        with self.assertRaises(frappe.ValidationError):
            voting.cast_vote(motion, latecomer.name, voting.POSITION_FOR)

        # And it cannot be smuggled in by writing the entitlement row directly.
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Forum Vote", "motion": motion.name, "membership": latecomer.name,
                 "voter": latecomer.member, "position": voting.POSITION_FOR}
            ).insert(ignore_permissions=True)

        audited = refusals_for("Forum Motion", motion.name)
        self.assertTrue(audited)
        self.assertEqual(audited[0]["control"], "voting entitlement as at decision date")

    def test_a_seat_with_no_vote_is_not_entitled(self):
        forum = make_forum()
        silent = make_seat(forum.name, seat_role(votes_by_default=0))
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        self.assertEqual(voting.entitlement(motion.name), [])

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Forum Vote", "motion": motion.name, "membership": silent.name,
                 "voter": silent.member, "position": voting.POSITION_FOR}
            ).insert(ignore_permissions=True)

    def test_entitlement_is_recorded_whether_or_not_a_vote_is_cast(self):
        forum = make_forum()
        role = seat_role()
        for _ in range(3):
            make_seat(forum.name, role, make_user())
        motion = make_motion(forum.name)
        voting.open_motion(motion)

        rows = voting.entitlement(motion.name)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["position"] == voting.POSITION_NOT_CAST for row in rows))

    def test_a_seat_on_another_forum_cannot_vote(self):
        forum, other = make_forum(), make_forum()
        outsider = make_seat(other.name, seat_role())
        motion = make_motion(forum.name)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Forum Vote", "motion": motion.name, "membership": outsider.name,
                 "voter": outsider.member, "position": voting.POSITION_FOR}
            ).insert(ignore_permissions=True)


class TestDelegatedVoting(GovernanceTestCase):
    def test_a_delegate_votes_only_where_the_seat_permits_it(self):
        forum = make_forum()
        delegate = make_user()
        seat = make_seat(
            forum.name, seat_role(), delegate=delegate, delegate_votes=1,
            delegate_from=add_days(nowdate(), -30), delegate_to=add_days(nowdate(), 30),
        )
        motion = make_motion(forum.name)
        voting.open_motion(motion)

        vote = voting.cast_vote(motion, seat.name, voting.POSITION_FOR,
                                voter=delegate, as_delegate=True)
        self.assertEqual(vote.voted_as, "Delegate")
        self.assertEqual(vote.acting_for, seat.member)

    def test_a_delegate_outside_the_delegation_window_is_refused(self):
        forum = make_forum()
        delegate = make_user()
        seat = make_seat(
            forum.name, seat_role(), delegate=delegate, delegate_votes=1,
            delegate_from=add_days(nowdate(), -300), delegate_to=add_days(nowdate(), -200),
        )
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        with self.assertRaises(frappe.ValidationError):
            voting.cast_vote(motion, seat.name, voting.POSITION_FOR,
                             voter=delegate, as_delegate=True)

    def test_a_seat_without_delegate_voting_rights_is_refused(self):
        forum = make_forum()
        delegate = make_user()
        seat = make_seat(forum.name, seat_role(), delegate=delegate, delegate_votes=0)
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        with self.assertRaises(frappe.ValidationError):
            voting.cast_vote(motion, seat.name, voting.POSITION_FOR,
                             voter=delegate, as_delegate=True)


class TestRecordedDecisions(GovernanceTestCase):
    def _forum_with_three_voters(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=2)
        role = seat_role()
        seats = [make_seat(forum.name, role, make_user()) for _ in range(3)]
        return forum, seats

    def test_the_tally_counts_for_against_and_abstentions(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        voting.cast_vote(motion, seats[0].name, voting.POSITION_FOR)
        voting.cast_vote(motion, seats[1].name, voting.POSITION_AGAINST)
        voting.cast_vote(motion, seats[2].name, voting.POSITION_ABSTAIN)

        motion = voting.record_outcome(motion, "Carried")
        self.assertEqual(motion.eligible_voter_count, 3)
        self.assertEqual(motion.votes_for, 1)
        self.assertEqual(motion.votes_against, 1)
        self.assertEqual(motion.abstentions, 1)
        self.assertEqual(motion.votes_cast, 3)

    def test_quorum_is_stored_on_the_decision_when_it_is_recorded(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        for seat in seats[:2]:
            voting.cast_vote(motion, seat.name, voting.POSITION_FOR)

        motion = voting.record_outcome(motion, "Carried")
        self.assertTrue(motion.quorum_met)
        self.assertEqual(motion.quorum_required, 2)
        self.assertIn("counting seats present", motion.quorum_basis)

    def test_a_later_membership_change_does_not_rewrite_a_past_quorum(self):
        """The second property this module exists for."""
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        for seat in seats[:2]:
            voting.cast_vote(motion, seat.name, voting.POSITION_FOR)
        motion = voting.record_outcome(motion, "Carried")
        self.assertTrue(motion.quorum_met)

        # Everyone leaves, and the forum's quorum rule is raised afterwards.
        for seat in seats:
            membership.close_seat(seat.name, nowdate(), "Term Ended")
        forum.reload()
        forum.quorum_value = 10
        forum.save(ignore_permissions=True)

        motion.reload()
        self.assertTrue(motion.quorum_met)
        self.assertEqual(motion.quorum_required, 2)
        self.assertEqual(motion.eligible_voter_count, 3)

        # Re-evaluating today would give a different answer, which is the point.
        self.assertFalse(membership.quorum_status(forum.name, nowdate())["met"])

    def test_a_recorded_decision_cannot_be_edited(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        for seat in seats[:2]:
            voting.cast_vote(motion, seat.name, voting.POSITION_FOR)
        motion = voting.record_outcome(motion, "Carried")
        self.purge_on_teardown("Forum Motion", motion.name)
        self.assertTrue(motion.quorum_met)

        reopened = frappe.get_doc("Forum Motion", motion.name)
        reopened.quorum_met = 0
        reopened.votes_for = 99
        with self.assertRaises(frappe.PermissionError):
            reopened.save(ignore_permissions=True)

    def test_votes_cannot_change_after_the_outcome_is_recorded(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        vote = voting.cast_vote(motion, seats[0].name, voting.POSITION_FOR)
        voting.record_outcome(motion, "Carried")
        self.purge_on_teardown("Forum Motion", motion.name)

        vote.reload()
        vote.position = voting.POSITION_AGAINST
        with self.assertRaises(frappe.PermissionError):
            vote.save(ignore_permissions=True)

        with self.assertRaises(frappe.ValidationError):
            voting.cast_vote(motion, seats[1].name, voting.POSITION_FOR)

    def test_an_outcome_is_recorded_only_once(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        voting.record_outcome(motion, "Carried")
        motion.reload()
        with self.assertRaises(frappe.ValidationError):
            voting.record_outcome(motion, "Not Carried")

    def test_an_inquorate_decision_is_recorded_as_such(self):
        forum, seats = self._forum_with_three_voters()
        motion = make_motion(forum.name)
        voting.open_motion(motion)
        voting.cast_vote(motion, seats[0].name, voting.POSITION_FOR)
        motion = voting.record_outcome(motion, "Inquorate")
        self.assertFalse(motion.quorum_met)
        self.assertFalse(motion.is_editable)

    def test_a_forum_s_decisions_are_listable_and_filterable(self):
        forum, seats = self._forum_with_three_voters()
        first = make_motion(forum.name, add_days(nowdate(), -30), motion_reference="MOT-A")
        second = make_motion(forum.name, nowdate(), motion_reference="MOT-B")
        voting.open_motion(first)
        voting.open_motion(second)
        voting.record_outcome(first, "Carried")
        voting.record_outcome(second, "Not Carried")

        rows = voting.decisions_for(forum.name)
        self.assertEqual(len(rows), 2)
        carried = voting.decisions_for(forum.name, outcome="Carried")
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["motion_reference"], "MOT-A")


class TestMeetings(GovernanceTestCase):
    def test_a_meeting_snapshots_attendance_and_stores_its_quorum(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=2)
        role = seat_role()
        seats = [make_seat(forum.name, role, make_user()) for _ in range(3)]

        meeting = frappe.get_doc(
            {"doctype": "Forum Meeting", "forum": forum.name, "meeting_reference": "M-1",
             "scheduled_on": nowdate(), "held_on": nowdate(), "status": "Held"}
        )
        for seat in seats[:2]:
            meeting.append("attendance", {"membership": seat.name, "attendee": seat.member,
                                          "attended_as": "Member", "present": 1})
        meeting.append("attendance", {"membership": seats[2].name, "attendee": seats[2].member,
                                      "attended_as": "Member", "present": 0})
        meeting.insert(ignore_permissions=True)

        self.assertTrue(meeting.quorum_met)
        self.assertEqual([row.counts_toward_quorum for row in meeting.attendance], [1, 1, 0])

        # The seat's quorum flag changing afterwards does not touch the snapshot.
        seat = frappe.get_doc("Forum Membership", seats[0].name)
        seat.counts_toward_quorum = 0
        seat.save(ignore_permissions=True)
        meeting.reload()
        self.assertEqual(meeting.attendance[0].counts_toward_quorum, 1)

    def test_a_meeting_that_did_not_sit_has_no_quorum_verdict(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=1)
        make_seat(forum.name, seat_role())
        meeting = frappe.get_doc(
            {"doctype": "Forum Meeting", "forum": forum.name, "meeting_reference": "M-2",
             "scheduled_on": nowdate(), "status": "Scheduled"}
        ).insert(ignore_permissions=True)
        self.assertFalse(meeting.quorum_met)
        self.assertFalse(meeting.is_committable)
