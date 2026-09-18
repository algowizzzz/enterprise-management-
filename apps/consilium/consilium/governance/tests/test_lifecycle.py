"""The forum's lifecycle: compliance states, watched fields, annual review, disbandment."""

import frappe
from frappe.utils import add_days, add_years, nowdate

from consilium.consilium_core import attestation, state_flags
from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import lifecycle, membership, reviews, setup
from consilium.governance.tests import task_for
from consilium.governance.state_flag_seed import GOVERNANCE_STATE_FLAGS
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_org_unit, make_seat, make_user, seat_role, unique,
)


class TestStateFlags(GovernanceTestCase):
    def test_every_governance_state_is_configured(self):
        for doctype, state_field, state_value, *_ in GOVERNANCE_STATE_FLAGS:
            with self.subTest(state=f"{doctype}.{state_field}={state_value}"):
                self.assertIsNotNone(state_flags.flags_for(doctype, state_field, state_value))

    def test_the_flags_follow_the_state(self):
        forum = make_forum()
        self.assertTrue(forum.is_editable)
        self.assertTrue(forum.is_active)

        lifecycle.set_forum_state(forum, "Pending")
        forum.reload()
        self.assertFalse(forum.is_editable)
        self.assertTrue(forum.is_active)
        self.assertTrue(forum.requires_review)

        lifecycle.set_forum_state(forum, "Compliant")
        forum.reload()
        self.assertTrue(forum.is_editable)
        self.assertFalse(forum.requires_review)

    def test_an_unconfigured_state_is_refused_rather_than_guessed(self):
        row = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": "Governance Forum", "state_field": "compliance_status",
             "state_value": "Compliant"},
            "name",
        )
        frappe.delete_doc("Workflow State Flag", row, ignore_permissions=True, force=True)
        state_flags.clear_cache("Governance Forum")

        forum = make_forum()
        forum.compliance_status = "Compliant"
        forum.flags.consilium_lifecycle = True
        with self.assertRaises(frappe.ValidationError):
            forum.save(ignore_permissions=True)


class TestComplianceReview(GovernanceTestCase):
    def test_a_review_moves_the_forum_and_leaves_a_history(self):
        forum = make_forum()
        reviewer = make_user("Compliance Reviewer")

        first = lifecycle.record_review(forum.name, "Non-Compliant", reviewer=reviewer,
                                        comments="No charter on record.")
        forum.reload()
        self.assertEqual(forum.compliance_status, "Non-Compliant")
        self.assertEqual(first.resulting_status, "Non-Compliant")
        self.assertTrue(first.decided_on)

        lifecycle.record_review(forum.name, "Compliant", reviewer=reviewer, comments="Charter filed.")
        forum.reload()
        self.assertEqual(forum.compliance_status, "Compliant")

        history = frappe.get_all("Forum Compliance Review", filters={"forum": forum.name})
        self.assertEqual(len(history), 2)

    def test_returning_to_the_creator_is_a_transition_carrying_questions(self):
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Pending")
        review = lifecycle.record_review(
            forum.name, "Returned To Creator",
            returned_questions="Which regulation requires this forum?",
        )
        forum.reload()
        self.assertEqual(forum.compliance_status, "Draft")
        self.assertTrue(forum.is_editable)
        self.assertEqual(review.returned_questions, "Which regulation requires this forum?")

    def test_a_return_without_questions_is_refused(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_review(forum.name, "Returned To Creator")

    def test_the_status_cannot_be_edited_directly(self):
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.compliance_status = "Compliant"
        with self.assertRaises(frappe.PermissionError):
            fresh.save(ignore_permissions=True)

        audited = refusals_for("Governance Forum", forum.name)
        self.assertTrue(audited)
        self.assertEqual(audited[0]["control"], "forum lifecycle transition")

    def test_a_forum_under_review_is_locked(self):
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Pending")
        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.escalation_threshold = "Anything material."
        with self.assertRaises(frappe.ValidationError):
            fresh.save(ignore_permissions=True)


class TestWatchedFields(GovernanceTestCase):
    def test_the_watched_list_is_configuration(self):
        field_set = frappe.get_doc("Watched Field Set", "Governance Forum")
        self.assertEqual(field_set.on_change_action, "Reset Workflow State")
        self.assertEqual(field_set.reset_to_state, setup.FORUM_REVIEW_STATE)
        self.assertIn("description", [row.fieldname for row in field_set.fields])

    def test_changing_a_watched_field_sends_the_forum_back_for_review(self):
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Compliant")

        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.description = "A materially different mandate."
        fresh.save(ignore_permissions=True)

        fresh.reload()
        self.assertEqual(fresh.compliance_status, "Pending")
        self.assertFalse(fresh.is_editable)
        self.assertTrue(fresh.requires_review)

    def test_changing_an_unwatched_field_does_not(self):
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Compliant")

        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.escalation_threshold = "Anything above appetite."
        fresh.save(ignore_permissions=True)
        fresh.reload()
        self.assertEqual(fresh.compliance_status, "Compliant")

    def test_compliance_is_notified_and_a_task_is_raised(self):
        make_user("Compliance Reviewer")
        forum = make_forum()
        lifecycle.set_forum_state(forum, "Compliant")

        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.description = "Another mandate."
        fresh.save(ignore_permissions=True)

        self.assertTrue(frappe.get_all(
            "ToDo", filters={"reference_type": "Governance Forum", "reference_name": forum.name}
        ))
        self.assertTrue(frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Governance Forum", "subject_name": forum.name},
        ))

    def test_removing_a_field_from_the_list_stops_the_trigger(self):
        field_set = frappe.get_doc("Watched Field Set", "Governance Forum")
        field_set.fields = [row for row in field_set.fields if row.fieldname != "description"]
        field_set.save(ignore_permissions=True)

        forum = make_forum()
        lifecycle.set_forum_state(forum, "Compliant")
        fresh = frappe.get_doc("Governance Forum", forum.name)
        fresh.description = "Changed, but no longer watched."
        fresh.save(ignore_permissions=True)
        fresh.reload()
        self.assertEqual(fresh.compliance_status, "Compliant")


class TestAnnualReview(GovernanceTestCase):
    def _forum_with_owner_and_compliance(self):
        forum = make_forum()
        owner = make_user()
        make_seat(forum.name, seat_role(is_owner_role=1, max_holders=1, can_attest=1), owner)
        contact = make_user("Compliance Reviewer")
        forum.reload()
        forum.compliance_contact = contact
        forum.flags.consilium_lifecycle = True
        forum.save(ignore_permissions=True)
        return forum, owner, contact

    def test_the_annual_review_needs_both_the_owner_and_compliance(self):
        forum, owner, contact = self._forum_with_owner_and_compliance()
        campaign = reviews.open_annual_review(unique("period"), due_on=add_days(nowdate(), 30))
        result = reviews.generate(campaign)
        # The campaign covers every forum on the inventory, so the count is not 1.
        self.assertIn(forum.name, [frappe.db.get_value("Attestation Task", n, "subject_name")
                                   for n in result["created"]])

        task = frappe.get_doc("Attestation Task", task_for(result, forum.name))
        self.assertEqual(task.assigned_to, owner)
        self.assertEqual(task.second_signatory, contact)

        # Only one signature: not a completed review.
        with self.assertRaises(frappe.ValidationError):
            reviews.record_annual_review(task, "Compliant")

        attestation.respond(task, "Attested")
        task.reload()
        with self.assertRaises(frappe.ValidationError):
            reviews.record_annual_review(task, "Compliant")

        frappe.set_user(contact)
        try:
            attestation.second_sign(task.name)
        finally:
            frappe.set_user("Administrator")

        task.reload()
        self.assertTrue(reviews.dual_signature_complete(task))
        review = reviews.record_annual_review(task, "Compliant", comments="Reviewed and current.")
        self.assertEqual(review.review_type, "Annual")
        self.assertEqual(review.attestation_task, task.name)

        forum.reload()
        self.assertEqual(forum.compliance_status, "Compliant")
        self.assertEqual(str(forum.next_review_on), str(add_years(nowdate(), 1)))

    def test_the_inventory_attestation_goes_to_attesting_seats(self):
        forum = make_forum()
        chair = make_user()
        make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1, can_attest=1), chair)
        make_seat(forum.name, seat_role(can_attest=0), make_user())

        campaign = reviews.open_inventory_attestation(unique("period"), due_on=add_days(nowdate(), 30))
        result = reviews.generate(campaign)
        assignees = frappe.get_all(
            "Attestation Task", filters={"campaign": campaign.name, "subject_name": forum.name},
            pluck="assigned_to",
        )
        self.assertEqual(assignees, [chair])

    def test_an_overdue_review_is_visible_as_an_exception(self):
        forum = make_forum()
        frappe.db.set_value("Governance Forum", forum.name, "next_review_on",
                            add_days(nowdate(), -1), update_modified=False)
        overdue = [row for row in reviews.overdue_reviews() if row["forum"] == forum.name]
        self.assertTrue(overdue)
        self.assertEqual(overdue[0]["reason"], "review_overdue")

    def test_a_missing_second_signature_is_visible_as_an_exception(self):
        forum, owner, contact = self._forum_with_owner_and_compliance()
        campaign = reviews.open_annual_review(
            unique("period"), opens_on=add_days(nowdate(), -30), due_on=add_days(nowdate(), -1)
        )
        task_name = task_for(reviews.generate(campaign), forum.name)
        attestation.respond(task_name, "Attested")

        rows = [row for row in reviews.overdue_reviews() if row["forum"] == forum.name]
        self.assertIn("second_signature_missing", [row["reason"] for row in rows])


class TestDisbandment(GovernanceTestCase):
    def _plan(self, forum):
        plan = frappe.get_doc(
            {"doctype": "Disbandment Plan", "forum": forum.name,
             "trigger_scenario": "Mandate Complete",
             "records_disposition_note": "Retained under the forum's retention class.",
             "effective_on": nowdate()}
        )
        for role in ("Delegating Authority", "Sponsor", "Chair"):
            plan.append("approvals", {"approver_role": role, "approver": make_user(), "required": 1})
        return plan.insert(ignore_permissions=True)

    def test_my_work_says_what_a_disbandment_approver_is_deciding(self):
        """My work used to list a disbandment approval as the plan's code and the
        step ("FDIS-2026-00002 · Sponsor"). It now names the decision, the seat
        it is decided from, who raised it and when, and opens the forum's
        disbandment page rather than the workspace."""
        from consilium.consilium_core import inbox

        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        plan = self._plan(forum)
        plan.raise_approvals()
        sponsor = next(row.approver for row in plan.approvals if row.approver_role == "Sponsor")
        forum_name = frappe.db.get_value("Governance Forum", forum.name, "forum_name")

        frappe.set_user(sponsor)
        try:
            items = [item for group in inbox.my_tasks()["groups"] for item in group["items"]
                     if item["kind"] == "approval" and item.get("subject_name") == plan.name]
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["title"], f"Approve the disbandment plan for {forum_name}")
        self.assertEqual(item["as_role"], "Sponsor")
        self.assertEqual(item["raised_by"], "Administrator")
        self.assertEqual(item["raised_on"], nowdate())
        self.assertEqual(item["due_on"], nowdate(), "due by the plan's effective date")
        self.assertEqual(item["url"], f"/forum-disband?forum={forum.name}")
        self.assertNotIn(plan.name, item["title"])

    def test_approval_step_names_read_as_seats(self):
        from consilium.consilium_core import inbox

        self.assertEqual(inbox._step_words("Document Approver Approval"), "Document Approver")
        self.assertEqual(inbox._step_words("Sponsor"), "Sponsor")
        self.assertEqual(inbox._step_words("Approval"), "Approval")
        self.assertEqual(inbox._step_words(None), "")

    def test_a_forum_cannot_be_disbanded_while_an_approval_is_outstanding(self):
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        plan = self._plan(forum)
        plan.raise_approvals()

        with self.assertRaises(frappe.ValidationError):
            lifecycle.execute_disbandment(plan)
        audited = refusals_for("Governance Forum", forum.name)
        self.assertEqual(audited[0]["control"], "disbandment approvals")

    def test_an_approved_disbandment_makes_the_forum_inactive_not_deleted(self):
        forum = make_forum()
        seat = make_seat(forum.name, seat_role())
        plan = self._plan(forum)
        for decision in plan.raise_approvals():
            assigned = frappe.db.get_value("Approval Decision", decision, "assigned_to")
            frappe.get_doc("Approval Decision", decision)  # readable by its assignee
            from consilium.consilium_core import approvals
            approvals.record_decision(decision, "Approved", acting_user=assigned)

        result = lifecycle.execute_disbandment(plan)
        forum.reload()
        self.assertFalse(forum.is_active)
        self.assertFalse(forum.is_editable)
        self.assertEqual(str(forum.disbanded_on), nowdate())
        self.assertEqual(forum.disbandment_plan, plan.name)
        self.assertTrue(frappe.db.exists("Governance Forum", forum.name))

        # Every seat is closed, and none is deleted.
        self.assertIn(seat.name, result["seats_closed"])
        seat.reload()
        self.assertEqual(str(seat.end_date), nowdate())
        self.assertEqual(seat.end_reason, "Forum Disbanded")
        self.assertEqual(membership.members_as_at(forum.name, add_days(nowdate(), 1)), [])
        # And history survives: the seat is still there on a past date.
        self.assertTrue(membership.members_as_at(forum.name, add_days(nowdate(), -1)))

    def test_deleting_a_forum_is_refused_and_audited(self):
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Governance Forum", forum.name, ignore_permissions=True)
        self.assertTrue(frappe.db.exists("Governance Forum", forum.name))
        audited = refusals_for("Governance Forum", forum.name)
        self.assertEqual(audited[0]["control"], "forum disbandment, not deletion")
