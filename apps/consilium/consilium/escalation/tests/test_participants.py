"""E-7: the forums on a pathway reach their people.

A forum is not a mailbox. Who a notice reaches is read from forum membership as
at the day: the chair, the secretary and every attesting seat, plus a standing
delegate in place that day. Ordinary members, vacant seats and seats that have
ended are not reached.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.escalation import resolution, routing
from consilium.escalation.tests.fixtures import retry_on_deadlock
from consilium.escalation.tests.utils import EscalationTestCase, make_user
from consilium.governance.tests.utils import make_seat, seat_role


class TestPathwayParticipants(EscalationTestCase):
    def setUp(self):
        super().setUp()
        # A setUp that fails never reaches tearDown; without this its aborted
        # transaction would fail every test after it.
        self.addCleanup(frappe.db.rollback)
        retry_on_deadlock(self.build)

    def build(self):
        self.reference = self.reference_data()
        self.forum = self.reference["forum"]
        self.chair = make_user()
        self.secretary = make_user()
        self.attester = make_user()
        self.member = make_user()
        self.former = make_user()
        self.delegate = make_user()
        make_seat(self.forum, seat_role(is_chair_role=1), member=self.chair,
                  delegate=self.delegate, delegate_from=add_days(nowdate(), -5), delegate_to=add_days(nowdate(), 5))
        make_seat(self.forum, seat_role(is_secretary_role=1, votes_by_default=0), member=self.secretary)
        make_seat(self.forum, seat_role(can_attest=1), member=self.attester)
        make_seat(self.forum, seat_role(), member=self.member)
        make_seat(self.forum, seat_role(is_chair_role=1), member=self.former,
                  start_date=add_days(nowdate(), -700), end_date=add_days(nowdate(), -400))
        make_seat(self.forum, seat_role(can_attest=1), member=None, seat_type="Position",
                  position_title="Head of a function")

    def test_the_officer_and_attesting_seats_are_resolved(self):
        people = {p["user"]: p for p in routing.forum_participants(self.forum)}
        self.assertEqual(set(people), {self.chair, self.secretary, self.attester, self.delegate})
        self.assertEqual(people[self.delegate]["capacity"], "delegate")
        self.assertNotIn(self.member, people)
        self.assertNotIn(self.former, people)

    def test_a_breach_reaches_the_pathway_forums_people(self):
        matter = self.make_matter(self.reference, governance_forums=[
            {"governance_forum": self.forum, "role_in_escalation": "Decision"}])
        recipients = resolution.breach_recipients(matter)
        for person in (self.chair, self.secretary, self.attester, self.delegate):
            self.assertIn(person, recipients)
        self.assertNotIn(self.member, recipients)
        self.assertEqual(len(recipients), len(set(recipients)), "each person is told once")

    def test_material_entity_impact_notifies_them_and_stamps_the_forum(self):
        matter = self.make_matter(self.reference, governance_forums=[
            {"governance_forum": self.forum, "role_in_escalation": "Oversight"}])
        matter.material_entity_impact = 1
        matter.save(ignore_permissions=True)
        told = frappe.get_all("Notification Dispatch",
                              filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
                              pluck="recipient")
        for person in (self.chair, self.secretary, self.attester):
            self.assertIn(person, told)
        self.assertNotIn(self.member, told)
        row = frappe.get_doc("Escalation Matter", matter.name).governance_forums[0]
        self.assertTrue(row.notified_on)

    def test_a_forum_with_no_filled_officer_seat_is_not_stamped(self):
        empty = self.reference_data()["forum"]
        matter = self.make_matter(self.reference, governance_forums=[
            {"governance_forum": empty, "role_in_escalation": "Informed"}])
        matter.material_entity_impact = 1
        matter.save(ignore_permissions=True)
        self.assertFalse(frappe.get_doc("Escalation Matter", matter.name).governance_forums[0].notified_on)

    def test_the_matter_page_shows_who_a_notice_reaches(self):
        matter = self.make_matter(self.reference, governance_forums=[
            {"governance_forum": self.forum, "role_in_escalation": "Decision"}])
        pathway = resolution.workbench(matter.name)["pathway"]
        self.assertIn(self.secretary, [p["user"] for p in pathway[0]["participants"]])
