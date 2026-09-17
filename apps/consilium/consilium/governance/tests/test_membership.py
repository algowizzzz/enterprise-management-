"""Membership: history, by-position seats, delegation, derived officers, quorum."""

import frappe
from frappe.utils import add_days, nowdate

from consilium.governance import membership
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_seat, make_user, seat_role,
)


class TestMembershipHistory(GovernanceTestCase):
    def test_a_seat_is_closed_not_deleted(self):
        forum = make_forum()
        seat = make_seat(forum.name, seat_role())

        membership.close_seat(seat.name, nowdate(), "Term Ended")
        seat.reload()
        self.assertEqual(str(seat.end_date), nowdate())
        self.assertTrue(frappe.db.exists("Forum Membership", seat.name))

    def test_deleting_a_seat_is_refused_and_audited(self):
        forum = make_forum()
        seat = make_seat(forum.name, seat_role())
        self.purge_on_teardown("Forum Membership", seat.name)

        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Forum Membership", seat.name, ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Forum Membership", seat.name))

    def test_who_sat_on_a_forum_at_a_past_date(self):
        """A member who joined and left before the query date is still visible."""
        forum = make_forum()
        role = seat_role()
        departed = make_seat(
            forum.name, role,
            start_date=add_days(nowdate(), -400), end_date=add_days(nowdate(), -200),
        )
        current = make_seat(forum.name, role, start_date=add_days(nowdate(), -100))

        then = [row["name"] for row in membership.members_as_at(forum.name, add_days(nowdate(), -300))]
        self.assertIn(departed.name, then)
        self.assertNotIn(current.name, then)

        now_seats = [row["name"] for row in membership.members_as_at(forum.name, nowdate())]
        self.assertNotIn(departed.name, now_seats)
        self.assertIn(current.name, now_seats)

    def test_a_seat_counts_on_its_first_and_last_day(self):
        forum = make_forum()
        seat = make_seat(
            forum.name, seat_role(),
            start_date=add_days(nowdate(), -10), end_date=add_days(nowdate(), -5),
        )
        self.assertTrue(membership.seat_held_on(seat.name, add_days(nowdate(), -10)))
        self.assertTrue(membership.seat_held_on(seat.name, add_days(nowdate(), -5)))
        self.assertFalse(membership.seat_held_on(seat.name, add_days(nowdate(), -11)))
        self.assertFalse(membership.seat_held_on(seat.name, add_days(nowdate(), -4)))

    def test_two_open_seats_for_the_same_person_are_refused(self):
        forum = make_forum()
        role = seat_role()
        person = make_user()
        make_seat(forum.name, role, person)
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, seat_role(), person)

    def test_a_forum_has_at_most_one_chair_at_a_time(self):
        forum = make_forum()
        chair_role = seat_role(is_chair_role=1, max_holders=1)
        make_seat(forum.name, chair_role)
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, chair_role)

    def test_a_chair_seat_may_follow_a_closed_one(self):
        forum = make_forum()
        chair_role = seat_role(is_chair_role=1, max_holders=1)
        first = make_seat(forum.name, chair_role, start_date=add_days(nowdate(), -100))
        membership.close_seat(first.name, add_days(nowdate(), -10), "Role Change")
        second = make_seat(forum.name, chair_role, start_date=add_days(nowdate(), -9))
        self.assertTrue(second.name)

    def test_a_seat_cannot_end_before_it_starts(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, seat_role(),
                      start_date=nowdate(), end_date=add_days(nowdate(), -1))


class TestSeatShape(GovernanceTestCase):
    def test_a_seat_may_be_held_by_a_position_and_stand_vacant(self):
        forum = make_forum()
        seat = make_seat(
            forum.name, seat_role(), seat_type="Position", member=None,
            position_title="Chief Risk Officer",
        )
        self.assertIsNone(seat.member)
        self.assertEqual(seat.position_title, "Chief Risk Officer")

    def test_the_occupant_changes_without_the_seat_losing_its_identity(self):
        forum = make_forum()
        seat = make_seat(
            forum.name, seat_role(), seat_type="Position", member=None,
            position_title="Chief Risk Officer",
        )
        first, second = make_user(), make_user()
        seat.member = first
        seat.save(ignore_permissions=True)
        seat.member = second
        seat.save(ignore_permissions=True)
        seat.reload()
        self.assertEqual(seat.member, second)
        self.assertEqual(seat.position_title, "Chief Risk Officer")

    def test_a_person_seat_may_not_be_vacant(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, seat_role(), member=None, seat_type="Person")

    def test_a_position_seat_needs_a_title(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, seat_role(), seat_type="Position", member=None)

    def test_the_seat_role_supplies_the_defaults(self):
        forum = make_forum()
        non_voting = seat_role(votes_by_default=0, counts_toward_quorum=0)
        seat = make_seat(forum.name, non_voting)
        self.assertFalse(seat.votes)
        self.assertFalse(seat.counts_toward_quorum)

        voting = make_seat(forum.name, seat_role(), make_user())
        self.assertTrue(voting.votes)


class TestDelegation(GovernanceTestCase):
    def test_a_delegate_is_recorded_with_its_own_dates(self):
        forum = make_forum()
        seat = make_seat(
            forum.name, seat_role(), delegate=make_user(),
            delegate_from=add_days(nowdate(), -5), delegate_to=add_days(nowdate(), 5),
            delegate_votes=1,
        )
        row = membership.members_as_at(forum.name, nowdate())[0]
        self.assertTrue(membership.delegate_active_on(row, nowdate()))
        self.assertFalse(membership.delegate_active_on(row, add_days(nowdate(), 30)))
        self.assertFalse(membership.delegate_active_on(row, add_days(nowdate(), -30)))

    def test_a_delegate_cannot_vote_for_a_seat_with_no_vote(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            make_seat(
                forum.name, seat_role(votes_by_default=0), delegate=make_user(),
                delegate_votes=1, votes=0,
            )

    def test_a_member_cannot_delegate_to_themselves(self):
        forum = make_forum()
        person = make_user()
        with self.assertRaises(frappe.ValidationError):
            make_seat(forum.name, seat_role(), person, delegate=person)


class TestDerivedOfficers(GovernanceTestCase):
    def test_the_officer_fields_follow_the_membership(self):
        forum = make_forum()
        chair = make_user()
        make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1), chair)
        forum.reload()
        self.assertEqual(forum.committee_chair, chair)

        secretary = make_user()
        make_seat(forum.name, seat_role(is_secretary_role=1, max_holders=1), secretary)
        owner = make_user()
        make_seat(forum.name, seat_role(is_owner_role=1, max_holders=1), owner)
        forum.reload()
        self.assertEqual(forum.secretary, secretary)
        self.assertEqual(forum.forum_owner, owner)

    def test_closing_the_chair_seat_clears_the_derived_field(self):
        forum = make_forum()
        seat = make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1))
        forum.reload()
        self.assertIsNotNone(forum.committee_chair)

        membership.close_seat(seat.name, add_days(nowdate(), -1), "Left Organisation")
        forum.reload()
        self.assertIsNone(forum.committee_chair)

    def test_an_officer_field_cannot_be_edited_directly(self):
        forum = make_forum()
        forum.committee_chair = make_user()
        with self.assertRaises(frappe.ValidationError):
            forum.save(ignore_permissions=True)

    def test_the_reconciliation_sweep_reports_drift(self):
        forum = make_forum()
        chair = make_user()
        make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1), chair)
        self.assertEqual(membership.officer_drift([forum.name]), [])

        # Force the denormalisation out of step behind the controller's back.
        frappe.db.set_value("Governance Forum", forum.name, "committee_chair", None,
                            update_modified=False)
        drift = membership.officer_drift([forum.name])
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["fieldname"], "committee_chair")
        self.assertEqual(drift[0]["derived"], chair)


class TestQuorum(GovernanceTestCase):
    def test_a_count_rule(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=2)
        role = seat_role()
        make_seat(forum.name, role, make_user())
        self.assertFalse(membership.quorum_status(forum.name)["met"])
        make_seat(forum.name, role, make_user())
        status = membership.quorum_status(forum.name)
        self.assertTrue(status["met"])
        self.assertEqual(status["required"], 2)

    def test_a_percentage_rule_rounds_up(self):
        forum = make_forum(quorum_rule_type="Percentage", quorum_value=50)
        role = seat_role()
        for _ in range(3):
            make_seat(forum.name, role, make_user())
        status = membership.quorum_status(forum.name)
        self.assertEqual(status["entitled_voters"], 3)
        self.assertEqual(status["required"], 2)
        self.assertTrue(status["met"])

    def test_quorum_is_answered_as_at_a_date(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=2)
        role = seat_role()
        make_seat(forum.name, role, make_user(), start_date=add_days(nowdate(), -300))
        make_seat(forum.name, role, make_user(), start_date=add_days(nowdate(), -10))
        self.assertTrue(membership.quorum_status(forum.name, nowdate())["met"])
        self.assertFalse(membership.quorum_status(forum.name, add_days(nowdate(), -100))["met"])

    def test_a_rule_requiring_the_chair_is_not_met_without_them(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=1, quorum_requires_chair=1)
        make_seat(forum.name, seat_role(), make_user())
        self.assertFalse(membership.quorum_status(forum.name)["met"])

        make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1), make_user())
        self.assertTrue(membership.quorum_status(forum.name)["met"])

    def test_a_vacant_by_position_seat_carries_no_vote(self):
        forum = make_forum(quorum_rule_type="Count", quorum_value=1)
        make_seat(forum.name, seat_role(), seat_type="Position", member=None,
                  position_title="Vacant Chair")
        status = membership.quorum_status(forum.name)
        self.assertEqual(status["entitled_voters"], 0)
        self.assertFalse(status["met"])
