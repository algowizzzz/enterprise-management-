"""Committee formation: intake, evaluation, return, approval, exception, creation."""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import approvals
from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import formation
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_forum_type, make_jurisdiction, make_org_unit,
    make_risk_category, make_user, unique,
)


def make_request(**values):
    defaults = {
        "doctype": "Committee Formation Request",
        "requester": make_user(),
        "request_type": "Create",
        "is_new_committee": 1,
        "rationale": "A gap in oversight.",
        "purpose_scope": "Oversight of model risk.",
        "proposed_responsibilities": "Review and challenge.",
        "delegating_authority": make_user(),
        "proposed_timeline": add_days(nowdate(), 30),
        "forum_name": unique("Proposed Forum"),
        "forum_type": make_forum_type(),
        "primary_risk_category": make_risk_category(),
        "owning_operating_group": make_org_unit(),
        "forum_sponsor": make_user(),
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


def assess_all(request, assessment="Pass"):
    request.reload()
    for row in request.evaluations:
        row.assessment = assessment
        row.comments = "Assessed against the criterion."
    request.completeness_confirmed = 1
    request.flags.consilium_formation = True
    request.save(ignore_permissions=True)
    return request


class TestIntake(GovernanceTestCase):
    def test_one_intake_covers_create_modify_and_retire(self):
        create = make_request()
        self.assertEqual(create.workflow_state, "Draft")
        self.assertTrue(create.is_editable)

        forum = make_forum()
        for request_type in ("Modify", "Retire"):
            with self.subTest(request_type=request_type):
                request = make_request(request_type=request_type, subject_forum=forum.name)
                self.assertEqual(request.request_type, request_type)

    def test_a_modify_request_must_name_its_subject(self):
        with self.assertRaises(frappe.ValidationError):
            make_request(request_type="Modify")

    def test_required_fields_are_enforced_before_submission(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Committee Formation Request", "request_type": "Create",
                 "forum_name": unique("Forum")}
            ).insert(ignore_permissions=True)

    def test_the_five_criteria_are_present_on_every_request(self):
        request = make_request()
        self.assertEqual(
            sorted(row.criterion for row in request.evaluations), sorted(formation.CRITERIA)
        )
        self.assertEqual(formation.unassessed_criteria(request), list(formation.CRITERIA))

    def test_submission_runs_the_overlap_check(self):
        forum_type = make_forum_type()
        category = make_risk_category()
        make_forum(forum_type=forum_type, primary_risk_category=category)
        request = make_request(forum_type=forum_type, primary_risk_category=category)
        formation.submit(request)
        request.reload()
        self.assertIn("share this forum type", request.duplicate_check_result)
        self.assertEqual(request.workflow_state, "Submitted")


class TestEvaluation(GovernanceTestCase):
    def test_a_finding_needs_a_comment(self):
        request = make_request()
        request.evaluations[0].assessment = "Pass"
        with self.assertRaises(frappe.ValidationError):
            request.save(ignore_permissions=True)

    def test_a_finding_stamps_its_reviewer(self):
        request = assess_all(make_request())
        self.assertTrue(all(row.reviewed_by and row.reviewed_on for row in request.evaluations))

    def test_approval_cannot_be_sought_while_a_criterion_is_unassessed(self):
        request = make_request()
        formation.submit(request)
        with self.assertRaises(frappe.ValidationError):
            formation.raise_approval_steps(request)

    def test_approval_cannot_be_sought_without_the_completeness_confirmation(self):
        request = make_request()
        request.reload()
        for row in request.evaluations:
            row.assessment = "Pass"
            row.comments = "Fine."
        request.save(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            formation.raise_approval_steps(request)


class TestReturnToOriginator(GovernanceTestCase):
    def test_returning_is_a_transition_and_the_exchange_is_preserved(self):
        request = make_request()
        formation.submit(request)
        formation.start_evaluation(request)

        formation.return_to_originator(request, "Which forum already covers this?")
        request.reload()
        self.assertEqual(request.workflow_state, "Returned To Originator")
        self.assertEqual(request.return_questions, "Which forum already covers this?")
        self.assertTrue(request.returned_by)
        self.assertTrue(request.is_editable)
        self.assertTrue(request.requires_review)

        formation.respond_to_return(request, "None; the nearest is out of scope.")
        request.reload()
        self.assertEqual(request.originator_response, "None; the nearest is out of scope.")
        self.assertEqual(request.workflow_state, "Under Evaluation")

    def test_the_originator_is_notified(self):
        request = make_request()
        formation.submit(request)
        formation.return_to_originator(request, "Please clarify the mandate.")
        dispatched = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Committee Formation Request", "subject_name": request.name},
            pluck="recipient",
        )
        self.assertIn(request.requester, dispatched)

    def test_returning_without_questions_is_refused(self):
        request = make_request()
        with self.assertRaises(frappe.ValidationError):
            formation.return_to_originator(request, "   ")

    def test_a_request_is_not_editable_while_it_is_under_evaluation(self):
        request = make_request()
        formation.submit(request)
        formation.start_evaluation(request)
        fresh = frappe.get_doc("Committee Formation Request", request.name)
        fresh.rationale = "Changed my mind."
        with self.assertRaises(frappe.ValidationError):
            fresh.save(ignore_permissions=True)


class TestApprovalRoute(GovernanceTestCase):
    def test_the_steps_are_configuration(self):
        request = assess_all(make_request())
        raised = formation.raise_approval_steps(request)
        self.assertEqual(len(raised), 3)
        request.reload()
        self.assertEqual(request.workflow_state, "Pending Approval")
        self.assertEqual(request.approval_route, "Standard Formation Approval")

        steps = frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": "Committee Formation Request", "subject_name": request.name},
            fields=["approval_step", "step_sequence", "mode"],
            order_by="step_sequence",
        )
        self.assertEqual([row["step_sequence"] for row in steps], [1, 2, 2])
        self.assertIn("Parallel", [row["mode"] for row in steps])

    def test_a_route_change_changes_the_steps_without_a_deployment(self):
        route = frappe.get_doc("Formation Approval Route", "Standard Formation Approval")
        route.append("steps", {"step_title": "Second Line Challenge", "step_sequence": 3,
                               "mode": "Sequential", "assign_to_field": "forum_sponsor",
                               "is_active": 1})
        route.save(ignore_permissions=True)

        request = assess_all(make_request())
        raised = formation.raise_approval_steps(request)
        self.assertEqual(len(raised), 4)

    def test_approval_is_refused_while_a_step_is_undecided(self):
        request = assess_all(make_request())
        formation.raise_approval_steps(request)
        self.purge_on_teardown("Committee Formation Request", request.name)

        with self.assertRaises(frappe.ValidationError):
            formation.approve(request)
        audited = refusals_for("Committee Formation Request", request.name)
        self.assertTrue(audited)
        self.assertEqual(audited[0]["control"], "formation approval gate")

    def test_a_step_cannot_be_bypassed_without_a_recorded_exception(self):
        request = assess_all(make_request())
        raised = formation.raise_approval_steps(request)
        self.purge_on_teardown("Committee Formation Request", request.name)

        with self.assertRaises(frappe.ValidationError):
            formation.authorise_bypass(request, raised[0], "  ")

        authorisation = formation.authorise_bypass(
            request, raised[0], "The role is vacant and the timeline is regulatory."
        )
        self.assertTrue(authorisation.name)
        request.reload()
        self.assertEqual(request.exception_authorisation, authorisation.name)

    def test_a_decided_step_leaves_the_outstanding_list(self):
        request = assess_all(make_request())
        raised = formation.raise_approval_steps(request)
        self.assertEqual(len(formation.outstanding_steps(request)), 3)
        for decision in raised:
            assigned = frappe.db.get_value("Approval Decision", decision, "assigned_to")
            formation.record_step_decision(request, decision, "Approved", acting_user=assigned)
        self.assertEqual(formation.outstanding_steps(request), [])


class TestExceptionRoute(GovernanceTestCase):
    def test_an_exception_routes_to_the_designated_authority_with_a_rationale(self):
        authority = make_user("Head of Risk Governance")
        request = assess_all(make_request())
        decision = formation.raise_exception(request, "The delegating authority disputes the scope.")

        request.reload()
        self.assertTrue(request.exception_raised)
        self.assertEqual(request.workflow_state, "Exception Review")
        self.assertEqual(
            frappe.db.get_value("Approval Decision", decision.name, "assigned_to"), authority
        )

    def test_an_exception_without_a_rationale_is_refused(self):
        make_user("Head of Risk Governance")
        request = assess_all(make_request())
        with self.assertRaises(frappe.ValidationError):
            formation.raise_exception(request, "")

    def test_resolving_an_exception_returns_the_request_to_approval(self):
        authority = make_user("Head of Risk Governance")
        request = assess_all(make_request())
        decision = formation.raise_exception(request, "Disputed scope.")
        formation.resolve_exception(
            request, "Scope narrowed and agreed.", approval_decision=decision.name
        )
        request.reload()
        self.assertEqual(request.workflow_state, "Pending Approval")
        self.assertEqual(request.exception_resolution, "Scope narrowed and agreed.")


class TestApprovalCreatesTheForum(GovernanceTestCase):
    def _approved_request(self, **values):
        request = assess_all(make_request(**values))
        raised = formation.raise_approval_steps(request)
        for decision in raised:
            assigned = frappe.db.get_value("Approval Decision", decision, "assigned_to")
            formation.record_step_decision(request, decision, "Approved", acting_user=assigned)
        return formation.approve(request)

    def test_an_approved_request_creates_a_forum_in_draft(self):
        jurisdiction = make_jurisdiction()
        request = make_request()
        request.append("jurisdictions", {"jurisdiction": jurisdiction})
        request.save(ignore_permissions=True)
        request = self._approved_request_from(request)

        self.assertEqual(request.workflow_state, "Approved")
        self.assertTrue(request.created_forum)

        forum = frappe.get_doc("Governance Forum", request.created_forum)
        self.assertEqual(forum.compliance_status, "Draft")
        self.assertEqual(forum.forum_name, request.forum_name)
        self.assertEqual(forum.forum_type, request.forum_type)
        self.assertEqual(forum.sponsor, request.forum_sponsor)
        self.assertEqual(forum.description, request.purpose_scope)
        self.assertEqual([row.jurisdiction for row in forum.jurisdictions], [jurisdiction])

    def _approved_request_from(self, request):
        assess_all(request)
        raised = formation.raise_approval_steps(request)
        for decision in raised:
            assigned = frappe.db.get_value("Approval Decision", decision, "assigned_to")
            formation.record_step_decision(request, decision, "Approved", acting_user=assigned)
        return formation.approve(request)

    def test_the_link_is_navigable_in_both_directions(self):
        request = self._approved_request()
        forum = frappe.get_doc("Governance Forum", request.created_forum)
        self.assertEqual(forum.formation_request, request.name)
        self.assertEqual(
            frappe.db.get_value("Committee Formation Request", request.name, "created_forum"),
            forum.name,
        )

    def test_a_forum_is_created_once(self):
        request = self._approved_request()
        first = request.created_forum
        request.reload()
        again = formation.create_forum(request)
        self.assertEqual(again.name, first)

    def test_a_forum_cannot_be_created_from_an_unapproved_request(self):
        request = assess_all(make_request())
        self.assertFalse(request.is_committable)
        with self.assertRaises(frappe.ValidationError):
            formation.create_forum(request)

    def test_a_retire_request_creates_no_forum_and_marks_its_subject(self):
        forum = make_forum(compliance_status="Draft")
        request = self._approved_request(request_type="Retire", subject_forum=forum.name)
        self.assertIsNone(request.created_forum)
        forum.reload()
        self.assertEqual(forum.compliance_status, "Pending")

    def test_a_rejection_records_its_reason(self):
        request = assess_all(make_request())
        formation.reject(request, "The mandate duplicates an existing forum.")
        request.reload()
        self.assertEqual(request.workflow_state, "Rejected")
        self.assertFalse(request.is_active)
        with self.assertRaises(frappe.ValidationError):
            formation.reject(request, "")
