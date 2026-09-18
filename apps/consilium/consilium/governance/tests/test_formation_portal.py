"""The portal's doors into formation and compliance review.

Every entry point here is exercised as someone who may use it and as someone
who may not, because an entry point that only proves the good case tells you
nothing about the control it exists to enforce. The stage gate is tested too:
the transitions themselves do not check where a request stands, so the entry
points are the only thing stopping "start evaluation" from reopening an
approved request.
"""

import frappe

from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import formation, lifecycle
from consilium.governance.tests.test_formation import make_request
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_user


def findings(assessment="Pass", comments="Assessed against the criterion."):
    return [{"criterion": c, "assessment": assessment, "comments": comments} for c in formation.CRITERIA]


class PortalCase(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.office = make_user(formation.GOVERNANCE_OFFICE)
        self.head = make_user(formation.DESIGNATED_AUTHORITY)
        # Write access to formation requests, but not the office's role: the
        # user the role check exists to refuse.
        self.secretary = make_user("Committee Secretary")
        self.viewer = make_user("Governance Viewer")
        # An originator who can raise and answer their own request.
        self.originator = make_user("Committee Secretary")

    def submitted(self, **values):
        request = make_request(requester=self.originator, **values)
        formation.submit(request)
        return request.name

    def as_user(self, user):
        frappe.set_user(user)

    def evaluated(self):
        """A request with every finding recorded and completeness confirmed."""
        name = self.submitted()
        self.as_user(self.office)
        formation.start_request_evaluation(name)
        formation.record_request_findings(name, findings(), completeness_confirmed=1)
        return name

    def decide_all(self, name, decision="Approved", comments=None):
        frappe.set_user("Administrator")
        for row in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": "Committee Formation Request", "subject_name": name, "is_open": 1},
            fields=["name", "assigned_to"],
            # In route order: Core refuses a sequential step decided before the
            # steps ahead of it (E7-S4).
            order_by="step_sequence asc, creation asc",
        ):
            self.as_user(row["assigned_to"])
            formation.record_request_step_decision(name, row["name"], decision, comments=comments)
        frappe.set_user("Administrator")


class TestStage(PortalCase):
    def test_the_stage_follows_the_flags_through_the_flow(self):
        request = make_request(requester=self.originator)
        self.assertEqual(formation.stage_of(request), "draft")
        self.assertEqual(formation.stage_actions(request), {"submit", "withdraw"})

        formation.submit(request)
        self.assertEqual(formation.stage_of(request), "awaiting_evaluation")
        formation.start_evaluation(request)
        self.assertEqual(formation.stage_of(request), "evaluation")
        formation.return_to_originator(request, "Why?")
        self.assertEqual(formation.stage_of(request), "with_originator")
        formation.respond_to_return(request, "Because.")
        self.assertEqual(formation.stage_of(request), "evaluation")

    def test_submitted_and_pending_approval_share_flags_and_are_told_apart_by_fact(self):
        name = self.evaluated()
        request = frappe.get_doc("Committee Formation Request", name)
        self.assertEqual(formation.stage_of(request), "evaluation")
        formation.raise_request_approval_steps(name)
        request.reload()
        self.assertEqual(formation.stage_of(request), "approval")
        self.assertIn("approve", formation.stage_actions(request))
        self.assertNotIn("start_evaluation", formation.stage_actions(request))


class TestRoleRefusals(PortalCase):
    def test_an_office_action_is_refused_to_a_writer_without_the_role_and_audited(self):
        name = self.submitted()
        self.purge_on_teardown("Committee Formation Request", name)
        self.as_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            formation.start_request_evaluation(name)
        audited = refusals_for("Committee Formation Request", name)
        self.assertTrue(any(row["control"] == "formation action role" for row in audited))

        frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Committee Formation Request", name, "workflow_state"),
            formation.STATE_SUBMITTED,
        )

    def test_a_reader_without_write_access_is_refused_before_anything_else(self):
        name = self.submitted()
        self.as_user(self.viewer)
        for call, args in (
            (formation.start_request_evaluation, ()),
            (formation.return_request_to_originator, ("Why?",)),
            (formation.approve_request, ()),
            (formation.reject_request, ("No.",)),
        ):
            with self.subTest(call=call.__name__):
                with self.assertRaises(frappe.PermissionError):
                    call(name, *args)

    def test_the_bypass_belongs_to_the_designated_authority_not_the_office(self):
        name = self.evaluated()
        self.purge_on_teardown("Committee Formation Request", name)
        formation.raise_request_approval_steps(name)
        step = formation.outstanding_steps(name)[0]

        with self.assertRaises(frappe.PermissionError):
            formation.authorise_request_bypass(name, step, "Vacant role.")

        self.as_user(self.head)
        with self.assertRaises(frappe.ValidationError):
            formation.authorise_request_bypass(name, step, "   ")
        formation.authorise_request_bypass(name, step, "The role is vacant and the timeline is regulatory.")
        frappe.set_user("Administrator")
        self.assertTrue(frappe.db.get_value("Committee Formation Request", name, "exception_authorisation"))
        self.assertEqual(frappe.db.get_value("Approval Decision", step, "decision"), "Bypassed")

    def test_the_review_payload_offers_the_office_its_actions_and_a_reader_none(self):
        name = self.submitted()
        self.as_user(self.office)
        office = formation.get_request_review(name)
        self.assertTrue(office["actions"]["start_evaluation"])
        self.assertFalse(office["actions"]["approve"])
        self.assertEqual(office["stage"], "awaiting_evaluation")

        self.as_user(self.viewer)
        reader = formation.get_request_review(name)
        self.assertFalse(any(reader["actions"].values()))

    def test_the_review_payload_is_refused_to_someone_with_no_part_in_the_request(self):
        name = self.submitted()
        self.as_user(make_user())
        with self.assertRaises(frappe.PermissionError):
            formation.get_request_review(name)


class TestStageRefusals(PortalCase):
    def test_an_action_the_stage_does_not_offer_is_refused(self):
        name = self.submitted()
        self.as_user(self.office)
        formation.start_request_evaluation(name)
        with self.assertRaises(frappe.ValidationError):
            formation.start_request_evaluation(name)
        with self.assertRaises(frappe.ValidationError):
            formation.approve_request(name)

    def test_a_request_is_not_submitted_twice(self):
        name = self.submitted()
        self.as_user(self.originator)
        with self.assertRaises(frappe.ValidationError):
            formation.submit_request(name)

    def test_nothing_reopens_a_decided_request(self):
        name = self.submitted()
        self.as_user(self.office)
        formation.reject_request(name, "Duplicates an existing forum.")
        for call, args in (
            (formation.start_request_evaluation, ()),
            (formation.return_request_to_originator, ("Why?",)),
            (formation.withdraw_request, ("Changed.",)),
        ):
            with self.subTest(call=call.__name__):
                with self.assertRaises(frappe.ValidationError):
                    call(name, *args)


class TestReturnAndRespond(PortalCase):
    def test_the_exchange_runs_through_the_entry_points(self):
        name = self.submitted()
        self.as_user(self.office)
        formation.start_request_evaluation(name)
        with self.assertRaises(frappe.ValidationError):
            formation.return_request_to_originator(name, "  ")
        context = formation.return_request_to_originator(name, "Which forum covers this now?")
        self.assertEqual(context["stage"], "with_originator")
        # The office may enter a reply it received some other way.
        self.assertTrue(context["actions"]["respond"])

        self.as_user(self.originator)
        formation.respond_to_returned_request(name, "None does.")
        frappe.set_user("Administrator")
        request = frappe.get_doc("Committee Formation Request", name)
        self.assertEqual(request.originator_response, "None does.")
        self.assertEqual(formation.stage_of(request), "evaluation")

    def test_an_originator_who_cannot_raise_requests_can_answer_theirs(self):
        """A business executive named as originator, with no governance role,
        was sent to the answer screen and told "You cannot raise a formation
        request". They are shown the questions and answer them; the request
        form itself stays with those who may raise one."""
        from consilium.consilium_core.tests.test_portal_pages import render

        executive = make_user()
        frappe.set_user("Administrator")
        request = make_request(requester=executive)
        formation.submit(request)
        self.as_user(self.office)
        formation.start_request_evaluation(request.name)
        formation.return_request_to_originator(request.name, "Which <b>forum</b> covers this now?")

        self.as_user(executive)
        self.assertFalse(frappe.has_permission("Committee Formation Request", "create"))
        status, body = render("create-forum", executive, {"request": request.name})
        self.assertEqual(status, 200)
        self.assertNotIn("You cannot raise a formation request", body)
        self.assertIn("The governance office has questions", body)
        self.assertIn("Which &lt;b&gt;forum&lt;/b&gt; covers this now?", body, "the questions are escaped")
        self.assertNotIn('id="formation-form"', body, "the raising form is not offered")

        self.as_user(executive)
        formation.respond_to_returned_request(request.name, "None does.")
        frappe.set_user("Administrator")
        self.assertEqual(formation.stage_of(frappe.get_doc("Committee Formation Request", request.name)),
                         "evaluation")

        # Someone else without a role still gets the refusal, not the questions.
        stranger = make_user()
        status, body = render("create-forum", stranger, {"request": request.name})
        self.assertIn("You cannot raise a formation request", body)
        self.assertNotIn("covers this now", body)

    def test_a_reply_to_a_request_that_was_never_returned_is_refused(self):
        name = self.submitted()
        self.as_user(self.originator)
        with self.assertRaises(frappe.ValidationError):
            formation.respond_to_returned_request(name, "Unasked.")

    def test_only_the_originator_or_the_office_may_answer(self):
        name = self.submitted()
        self.purge_on_teardown("Committee Formation Request", name)
        self.as_user(self.office)
        formation.return_request_to_originator(name, "Clarify the mandate.")
        self.as_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            formation.respond_to_returned_request(name, "Not mine to answer.")


class TestFindings(PortalCase):
    def test_findings_are_recorded_with_their_reviewer(self):
        name = self.evaluated()
        frappe.set_user("Administrator")
        request = frappe.get_doc("Committee Formation Request", name)
        self.assertEqual(formation.unassessed_criteria(request), [])
        self.assertTrue(request.completeness_confirmed)
        self.assertTrue(all(row.reviewed_by == self.office for row in request.evaluations))

    def test_a_finding_without_a_note_is_refused(self):
        name = self.submitted()
        self.as_user(self.office)
        formation.start_request_evaluation(name)
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_findings(name, findings(comments=""))

    def test_an_unknown_criterion_or_finding_is_refused(self):
        name = self.submitted()
        self.as_user(self.office)
        formation.start_request_evaluation(name)
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_findings(
                name, [{"criterion": "Not A Criterion", "assessment": "Pass", "comments": "x"}]
            )
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_findings(
                name, [{"criterion": formation.CRITERIA[0], "assessment": "Excellent", "comments": "x"}]
            )

    def test_findings_are_only_recorded_during_evaluation(self):
        name = self.submitted()
        self.as_user(self.office)
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_findings(name, findings())


class TestApprovalThroughThePortal(PortalCase):
    def test_the_whole_route_creates_the_forum(self):
        name = self.evaluated()
        context = formation.raise_request_approval_steps(name)
        self.assertEqual(context["stage"], "approval")
        self.assertTrue(context["blockers"])
        self.decide_all(name, comments="Agreed.")

        self.as_user(self.office)
        context = formation.approve_request(name)
        self.assertEqual(context["stage"], "approved")
        self.assertTrue(context["created_forum"])
        forum = frappe.get_doc("Governance Forum", context["created_forum"]["name"])
        self.assertEqual(forum.formation_request, name)
        self.assertFalse(any(context["actions"].values()))

    def test_a_step_is_decided_only_by_its_assignee(self):
        name = self.evaluated()
        self.purge_on_teardown("Committee Formation Request", name)
        formation.raise_request_approval_steps(name)
        step = formation.outstanding_steps(name)[0]
        self.as_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            formation.record_request_step_decision(name, step, "Approved")

    def test_a_refusal_carries_its_reason(self):
        name = self.evaluated()
        formation.raise_request_approval_steps(name)
        frappe.set_user("Administrator")
        step = formation.outstanding_steps(name)[0]
        self.as_user(frappe.db.get_value("Approval Decision", step, "assigned_to"))
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_step_decision(name, step, "Rejected")
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_step_decision(name, step, "Bypassed", comments="Not this way.")

    def test_a_refused_step_blocks_approval(self):
        name = self.evaluated()
        self.purge_on_teardown("Committee Formation Request", name)
        formation.raise_request_approval_steps(name)
        self.decide_all(name, decision="Rejected", comments="The mandate overlaps ours.")
        request = frappe.get_doc("Committee Formation Request", name)
        self.assertEqual(formation.outstanding_steps(request), [])
        self.assertTrue(any("refused" in blocker for blocker in formation.approval_blockers(request)))

        self.as_user(self.office)
        with self.assertRaises(frappe.ValidationError):
            formation.approve_request(name)

    def test_a_decided_step_is_not_decided_again(self):
        name = self.evaluated()
        formation.raise_request_approval_steps(name)
        frappe.set_user("Administrator")
        step = formation.outstanding_steps(name)[0]
        assignee = frappe.db.get_value("Approval Decision", step, "assigned_to")
        self.as_user(assignee)
        formation.record_request_step_decision(name, step, "Approved")
        with self.assertRaises(frappe.ValidationError):
            formation.record_request_step_decision(name, step, "Approved")


class TestExceptionThroughThePortal(PortalCase):
    def test_the_office_raises_and_the_authority_resolves(self):
        name = self.evaluated()
        self.purge_on_teardown("Committee Formation Request", name)
        context = formation.raise_request_exception(name, "The delegating authority disputes the scope.")
        self.assertEqual(context["stage"], "exception")

        # The office may not resolve its own exception.
        with self.assertRaises(frappe.PermissionError):
            formation.resolve_request_exception(name, "Settled.")

        frappe.set_user("Administrator")
        authority = frappe.db.get_value(
            "Approval Decision",
            {"subject_doctype": "Committee Formation Request", "subject_name": name, "is_open": 1},
            "assigned_to",
        )
        self.as_user(authority)
        with self.assertRaises(frappe.ValidationError):
            formation.resolve_request_exception(name, "  ")
        context = formation.resolve_request_exception(name, "Scope narrowed and agreed.")
        self.assertEqual(context["stage"], "approval")
        self.assertEqual(context["request"]["exception_resolution"], "Scope narrowed and agreed.")


class TestClosing(PortalCase):
    def test_a_rejection_needs_its_reason(self):
        name = self.submitted()
        self.as_user(self.office)
        with self.assertRaises(frappe.ValidationError):
            formation.reject_request(name, "")
        context = formation.reject_request(name, "Duplicates an existing forum.")
        self.assertEqual(context["stage"], "closed")

    def test_the_originator_may_withdraw_their_own_request_with_a_reason(self):
        name = self.submitted()
        self.as_user(self.originator)
        with self.assertRaises(frappe.ValidationError):
            formation.withdraw_request(name, " ")
        context = formation.withdraw_request(name, "No longer needed.")
        self.assertEqual(context["stage"], "closed")

    def test_someone_else_may_not_withdraw_it(self):
        name = self.submitted()
        self.purge_on_teardown("Committee Formation Request", name)
        self.as_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            formation.withdraw_request(name, "Not mine.")


class TestNamedPeople(PortalCase):
    def test_only_enabled_signed_in_people_are_offered(self):
        disabled = make_user("Committee Secretary")
        frappe.db.set_value("User", disabled, "enabled", 0)
        website = make_user()
        frappe.db.set_value("User", website, "user_type", "Website User")

        self.as_user(self.originator)
        offered = {row["name"] for row in formation.named_people()}
        self.assertIn(self.office, offered)
        for absent in ("Guest", "Administrator", disabled, website):
            with self.subTest(user=absent):
                self.assertNotIn(absent, offered)

    def test_the_list_is_refused_to_someone_who_cannot_raise_a_request(self):
        self.as_user(make_user())
        with self.assertRaises(frappe.PermissionError):
            formation.named_people()


class TestComplianceReviewThroughThePortal(PortalCase):
    def setUp(self):
        super().setUp()
        self.reviewer = make_user(lifecycle.COMPLIANCE_ROLE)

    def test_a_compliance_reviewer_moves_the_forum(self):
        forum = make_forum()
        self.as_user(self.reviewer)
        result = lifecycle.record_compliance_review(forum.name, "Compliant", comments="All on record.")
        self.assertEqual(result["compliance_status"], "Compliant")
        self.assertFalse(result["requires_review"])
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Forum Compliance Review", result["review"], "reviewer"), self.reviewer)

    def test_the_governance_office_may_not_record_one_and_is_audited(self):
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        self.as_user(self.office)
        with self.assertRaises(frappe.PermissionError):
            lifecycle.record_compliance_review(forum.name, "Compliant", comments="Looks fine.")
        audited = refusals_for("Governance Forum", forum.name)
        self.assertTrue(any(row["control"] == "compliance review role" for row in audited))
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Governance Forum", forum.name, "compliance_status"), "Draft")

    def test_an_annual_review_is_not_recorded_from_the_portal(self):
        forum = make_forum()
        self.as_user(self.reviewer)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_compliance_review(forum.name, "Compliant", review_type="Annual", comments="x")

    def test_a_decision_that_needs_a_statement_is_refused_without_one(self):
        forum = make_forum()
        self.as_user(self.reviewer)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_compliance_review(forum.name, "Returned To Creator")

    def test_a_disbanded_forum_is_not_reviewed_again(self):
        forum = make_forum()
        lifecycle.set_forum_state(forum, lifecycle.DISBANDED_STATUS)
        self.as_user(self.reviewer)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_compliance_review(forum.name, "Compliant", comments="x")

    def test_the_decisions_offered_say_what_they_do(self):
        choices = {row["decision"]: row for row in lifecycle.review_decisions()}
        self.assertEqual(choices["Returned To Creator"]["resulting_status"], "Draft")
        self.assertTrue(choices["Returned To Creator"]["requires_statement"])
        self.assertFalse(choices["Compliant"]["requires_statement"])
