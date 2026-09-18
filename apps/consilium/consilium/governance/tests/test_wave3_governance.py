"""Governance behaviour closed in wave 3.

* E7-S4 — the formation route's sequential steps are decided in order; a
  parallel step is not held back, and the screen offers only what Core accepts.
* Formation and forum notices are raised as templated events, so their wording
  is an administrator's ``Notification Template``, not a string in code.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core.setup import notification_templates
from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import formation, lifecycle
from consilium.governance.tests.test_formation import assess_all, make_request
from consilium.governance.tests.utils import GovernanceTestCase, make_forum


def _steps(request) -> dict[str, dict]:
    return {
        row.approval_step: row
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": request.doctype, "subject_name": request.name},
            fields=["name", "approval_step", "step_sequence", "mode", "assigned_to"],
        )
    }


class TestFormationStepOrder(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.request = assess_all(make_request())
        formation.raise_approval_steps(self.request)
        self.steps = _steps(self.request)
        self.purge_on_teardown(self.request.doctype, self.request.name)

    def test_the_second_sequential_step_waits_for_the_first(self):
        evaluation = self.steps["Risk Governance Office Evaluation"]
        authority = self.steps["Delegating Authority Approval"]
        with self.assertRaises(frappe.ValidationError):
            formation.record_step_decision(
                self.request, authority.name, "Approved", acting_user=authority.assigned_to
            )
        self.assertEqual(
            refusals_for(self.request.doctype, self.request.name)[-1]["control"], "sequential approval order"
        )
        formation.record_step_decision(
            self.request, evaluation.name, "Approved", acting_user=evaluation.assigned_to
        )
        formation.record_step_decision(
            self.request, authority.name, "Approved", acting_user=authority.assigned_to
        )
        self.assertFalse(frappe.db.get_value("Approval Decision", authority.name, "is_open"))

    def test_the_parallel_sponsor_step_is_not_held_back(self):
        sponsor = self.steps["Sponsor Endorsement"]
        self.assertEqual(sponsor.mode, "Parallel")
        formation.record_step_decision(self.request, sponsor.name, "Approved", acting_user=sponsor.assigned_to)
        self.assertFalse(frappe.db.get_value("Approval Decision", sponsor.name, "is_open"))

    def test_the_review_screen_offers_a_step_only_in_its_turn(self):
        authority = self.steps["Delegating Authority Approval"]
        frappe.set_user(authority.assigned_to)
        try:
            context = formation.review_context(frappe.get_doc(self.request.doctype, self.request.name))
        finally:
            frappe.set_user("Administrator")
        row = next(d for d in context["decisions"] if d["name"] == authority.name)
        self.assertFalse(row["can_decide"])

    def test_the_exception_step_is_not_held_behind_the_route(self):
        from consilium.governance.tests.utils import make_user

        make_user("Head of Risk Governance")
        decision = formation.raise_exception(self.request, "The sponsor disputes the scope.")
        self.assertEqual(frappe.db.get_value("Approval Decision", decision.name, "mode"), "Parallel")
        formation.resolve_exception(self.request, "Scope agreed.", approval_decision=decision.name)
        self.assertFalse(frappe.db.get_value("Approval Decision", decision.name, "is_open"))


class TestTemplatedNotices(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        frappe.flags.mute_emails = True
        notification_templates.seed_all()

    def tearDown(self):
        frappe.flags.mute_emails = False
        super().tearDown()

    def _dispatches(self, doctype, name):
        return frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": doctype, "subject_name": name},
            fields=["recipient", "rendered_subject", "rendered_body"],
        )

    def test_a_returned_request_is_told_through_its_template(self):
        request = make_request()
        formation.submit(request)
        formation.return_to_originator(request, "Which forum overlaps?")
        rows = self._dispatches(request.doctype, request.name)
        told = [row for row in rows if row.recipient == request.requester]
        self.assertTrue(told)
        self.assertEqual(told[0].rendered_subject, "Formation request returned with questions")
        self.assertIn("Which forum overlaps?", told[0].rendered_body)

    def test_the_approver_is_told_their_step_through_its_template(self):
        request = assess_all(make_request())
        formation.raise_approval_steps(request)
        subjects = {row.rendered_subject for row in self._dispatches(request.doctype, request.name)}
        self.assertIn("Formation approval requested", subjects)

    def test_compliance_is_told_of_a_review_through_its_template(self):
        from consilium.governance.tests.utils import make_user

        reviewer = make_user("Compliance Reviewer")
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Compliant")
        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.description = "A changed mandate."
        fresh.save(ignore_permissions=True)
        rows = [row for row in self._dispatches("Governance Forum", forum.name) if row.recipient == reviewer]
        self.assertTrue(rows)
        self.assertTrue(all(row.rendered_subject for row in rows))


class TestCharterChallengeOnTheRequest(GovernanceTestCase):
    """E33-S1: the charter challenge is recordable from /formation-request."""

    def setUp(self):
        super().setUp()
        from consilium.governance.tests.test_governance_gaps import make_charter, with_version

        self.request = make_request()
        self.charter = with_version(make_charter(request=self.request.name))

    def _context(self, user):
        frappe.set_user(user)
        try:
            return formation.review_context(frappe.get_doc(self.request.doctype, self.request.name))
        finally:
            frappe.set_user("Administrator")

    def test_the_office_is_offered_the_challenge_and_its_outcome_shows(self):
        from consilium.governance import charters

        context = self._context(self.rgo)["charter_challenge"]
        self.assertTrue(context["may_record"])
        row = next(c for c in context["charters"] if c["name"] == self.charter.name)
        self.assertTrue(row["can_record"])
        self.assertTrue(row["challenge_outstanding"])
        self.assertTrue(context["options"])

        frappe.set_user(self.rgo)
        try:
            charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CLEARED, "Fit to approve.")
        finally:
            frappe.set_user("Administrator")
        row = next(c for c in self._context(self.rgo)["charter_challenge"]["charters"]
                   if c["name"] == self.charter.name)
        self.assertFalse(row["challenge_outstanding"])
        self.assertEqual(row["rgo_challenge_comments"], "Fit to approve.")

    def test_the_originator_sees_the_challenge_but_is_not_offered_it(self):
        context = self._context(self.request.requester)["charter_challenge"]
        self.assertFalse(context["may_record"])
        self.assertIn(self.charter.name, [c["name"] for c in context["charters"]])
        self.assertFalse(any(c["can_record"] for c in context["charters"]))
