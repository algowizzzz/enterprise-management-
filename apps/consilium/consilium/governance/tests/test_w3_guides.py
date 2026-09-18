"""Defects and gaps found while writing the illustrated guides (W3-5).

Each class is one defect, reproduced as it was found and pinned so it cannot
come back:

* a single bypass waived every other open approval step;
* the designated authority was offered a bypass of their own step;
* a role-based step went to the alphabetically first holder of the role,
  which on a site where tests had been run was a leftover test account, and
  nobody else in the role could decide it;
* a request's originator could not open the request they had raised;
* the annual forum review had no screen, so it could not be started or
  recorded;
* voting had no screen, so a member could not cast a ballot nor the secretary
  record an outcome, and nothing checked quorum before a decision stood.
"""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import attestation, inbox
from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import formation, reviews, voting
from consilium.governance.tests.test_formation import assess_all, make_request
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_seat, make_user, seat_role, unique,
)


def _steps(name: str) -> list[dict]:
    return frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Committee Formation Request", "subject_name": name},
        fields=["name", "approval_step", "assigned_to", "is_open", "decision", "required_role", "acted_by"],
        order_by="step_sequence asc, creation asc",
    )


class TestABypassWaivesOnlyItsOwnStep(GovernanceTestCase):
    def test_other_open_steps_still_block_approval_after_one_is_bypassed(self):
        head = make_user(formation.DESIGNATED_AUTHORITY)
        request = assess_all(make_request())
        raised = formation.raise_approval_steps(request)
        self.purge_on_teardown("Committee Formation Request", request.name)
        self.assertEqual(len(raised), 3)

        formation.authorise_bypass(request, raised[0], "The role is vacant this quarter.", approved_by=head)
        request.reload()
        self.assertTrue(request.exception_authorisation)
        self.assertEqual(len(formation.outstanding_steps(request)), 2, "the bypass closes one step only")

        blockers = formation.approval_blockers(request)
        self.assertTrue(any("undecided" in b for b in blockers), blockers)
        with self.assertRaises(frappe.ValidationError):
            formation.approve(request)
        self.assertTrue(any(r["control"] == "formation approval gate"
                            for r in refusals_for("Committee Formation Request", request.name)))

        # Deciding the steps the bypass did not name clears the way.
        for row in _steps(request.name):
            if row["is_open"]:
                formation.record_step_decision(request, row["name"], "Approved", acting_user=row["assigned_to"])
        request.reload()
        self.assertEqual(formation.approval_blockers(request), [])
        formation.approve(request)
        self.assertTrue(request.reload() or request.created_forum)


class TestNobodyBypassesTheirOwnStep(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.head = make_user(formation.DESIGNATED_AUTHORITY)
        self.office = make_user(formation.GOVERNANCE_OFFICE)

    def _pending(self):
        """A request pending approval whose delegating authority is the head."""
        request = make_request(delegating_authority=self.head)
        formation.submit(request)
        frappe.set_user(self.office)
        formation.start_request_evaluation(request.name)
        formation.record_request_findings(
            request.name,
            [{"criterion": c, "assessment": "Pass", "comments": "Assessed."} for c in formation.CRITERIA],
            completeness_confirmed=1,
        )
        formation.raise_request_approval_steps(request.name)
        frappe.set_user("Administrator")
        return request.name

    def test_the_head_is_not_offered_and_is_refused_a_bypass_of_their_own_step(self):
        name = self._pending()
        self.purge_on_teardown("Committee Formation Request", name)
        own = next(r["name"] for r in _steps(name) if r["assigned_to"] == self.head)
        other = next(r["name"] for r in _steps(name) if r["assigned_to"] != self.head)

        frappe.set_user(self.head)
        ctx = formation.get_request_review(name)
        offered = {row["name"]: row["can_bypass"] for row in ctx["decisions"] if row["is_open"]}
        self.assertFalse(offered[own], "their own step is not offered for a bypass")
        self.assertTrue(offered[other])
        self.assertTrue(ctx["actions"]["authorise_bypass"])

        with self.assertRaises(frappe.PermissionError):
            formation.authorise_request_bypass(name, own, "I approve of skipping my own approval.")
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Approval Decision", own, "decision"), "Pending")
        self.assertTrue(any(r["control"] == "segregation of duties"
                            for r in refusals_for("Committee Formation Request", name)))

        # Someone else's step may still be bypassed, with its justification.
        frappe.set_user(self.head)
        formation.authorise_request_bypass(name, other, "The sponsor is on leave; the timeline is regulatory.")
        frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Approval Decision", other, "decision"), "Bypassed")

    def test_with_only_their_own_step_open_the_bypass_action_is_off(self):
        name = self._pending()
        for row in _steps(name):
            if row["assigned_to"] != self.head:
                frappe.db.set_value("Approval Decision", row["name"], "is_open", 0)
        frappe.set_user(self.head)
        ctx = formation.get_request_review(name)
        self.assertFalse(ctx["actions"]["authorise_bypass"])


class TestARoleIsAQueue(GovernanceTestCase):
    def _role(self) -> str:
        return frappe.get_doc({"doctype": "Role", "role_name": unique("Queue Role"),
                               "desk_access": 1}).insert(ignore_permissions=True).name

    def test_the_queue_leaves_out_disabled_website_and_built_in_accounts(self):
        role = self._role()
        live = make_user(role)
        disabled = make_user(role)
        frappe.db.set_value("User", disabled, "enabled", 0)
        website = make_user(role)
        frappe.db.set_value("User", website, "user_type", "Website User")
        frappe.get_doc("User", "Administrator").add_roles(role)
        self.assertEqual(formation.role_queue(role), [live])

    def test_an_account_that_has_signed_in_heads_the_queue_over_one_that_never_has(self):
        """The defect: the alphabetically first holder — a leftover test account
        that had never signed in — received every role-based step."""
        role = self._role()
        never = make_user(role, email=f"a-{unique('never').lower()}@example.com")
        working = make_user(role, email=f"z-{unique('working').lower()}@example.com")
        frappe.db.set_value("User", working, "last_login", frappe.utils.now())
        self.assertEqual(formation.role_queue(role), [working, never])
        self.assertEqual(formation._role_holder(role), working)

    def test_a_holder_seated_in_the_requests_operating_group_heads_the_queue(self):
        role = self._role()
        outsider = make_user(role, email=f"a-{unique('out').lower()}@example.com")
        frappe.db.set_value("User", outsider, "last_login", frappe.utils.now())
        insider = make_user(role, email=f"z-{unique('in').lower()}@example.com")
        request = make_request()
        forum = make_forum(owning_operating_group=request.owning_operating_group)
        make_seat(forum.name, seat_role(), member=insider)
        self.assertEqual(formation.role_queue(role, request)[0], insider)

    def test_any_member_of_the_queue_may_take_and_decide_a_role_based_step(self):
        request = assess_all(make_request())
        formation.raise_approval_steps(request)
        self.purge_on_teardown("Committee Formation Request", request.name)
        step = _steps(request.name)[0]
        self.assertEqual(step["required_role"], formation.GOVERNANCE_OFFICE)
        colleague = make_user(formation.GOVERNANCE_OFFICE)
        self.assertNotEqual(step["assigned_to"], colleague)
        self.assertIn(colleague, formation.role_queue(formation.GOVERNANCE_OFFICE, request))

        # The whole queue sees it waiting, not only its head.
        waiting = [item["reference"] for item in inbox.collect(colleague)]
        self.assertIn(step["name"], waiting)

        outsider = make_user()
        frappe.set_user(outsider)
        with self.assertRaises(frappe.PermissionError):
            formation.record_request_step_decision(request.name, step["name"], "Approved")
        frappe.set_user(colleague)
        formation.record_request_step_decision(request.name, step["name"], "Approved")
        frappe.set_user("Administrator")
        row = frappe.db.get_value("Approval Decision", step["name"], ["assigned_to", "acted_by", "decision"],
                                  as_dict=True)
        self.assertEqual((row.assigned_to, row.acted_by, row.decision), (colleague, colleague, "Approved"))

    def test_a_step_named_for_a_person_is_not_a_queue(self):
        request = assess_all(make_request())
        formation.raise_approval_steps(request)
        sponsor_step = next(r for r in _steps(request.name) if r["assigned_to"] == request.forum_sponsor)
        office = make_user(formation.GOVERNANCE_OFFICE)
        self.assertFalse(formation.may_decide(request, frappe._dict(sponsor_step), office))


class TestTheOriginatorReadsTheirOwnRequest(GovernanceTestCase):
    def test_an_originator_with_no_governance_role_can_open_answer_and_withdraw(self):
        originator = make_user("Policy Owner")
        request = make_request(requester=originator)
        formation.submit(request)
        formation.start_evaluation(request)
        formation.return_to_originator(request, "Which forums already cover this?")

        frappe.set_user(originator)
        self.assertTrue(frappe.has_permission("Committee Formation Request", "read", doc=request.name))
        ctx = formation.get_request_review(request.name)
        self.assertTrue(ctx["is_originator"])
        self.assertTrue(ctx["actions"]["respond"])
        formation.respond_to_returned_request(request.name, "None of them: the gap is real.")
        frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Committee Formation Request", request.name, "originator_response"),
            "None of them: the gap is real.",
        )

    def test_somebody_else_without_a_role_still_cannot(self):
        request = make_request(requester=make_user("Policy Owner"))
        stranger = make_user("Policy Owner")
        frappe.set_user(stranger)
        self.assertFalse(frappe.has_permission("Committee Formation Request", "read", doc=request.name))

    def test_the_patch_shares_requests_raised_before_the_fix(self):
        from consilium.patches.v0_1 import share_formation_requests_with_originators as patch

        originator = make_user("Policy Owner")
        request = make_request(requester=originator)
        frappe.db.delete("DocShare", {"share_doctype": request.doctype, "share_name": request.name})
        self.assertFalse(frappe.has_permission(request.doctype, "read", doc=request.name, user=originator))
        patch.execute()
        self.assertTrue(frappe.has_permission(request.doctype, "read", doc=request.name, user=originator))


class TestAnnualReviewFromTheForum(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.owner = make_user("Forum Owner")
        self.contact = make_user("Compliance Reviewer")
        self.reviewer = make_user("Compliance Reviewer")
        self.office = make_user(formation.GOVERNANCE_OFFICE)
        self.forum = make_forum(forum_owner=self.owner, compliance_contact=self.contact).name

    def test_started_signed_and_recorded_from_the_forum(self):
        frappe.set_user(self.office)
        state = reviews.start_forum_annual_review(self.forum, add_days(nowdate(), 30))
        self.assertEqual(state["started"]["created"], 1)
        task = state["tasks"][0]
        self.assertEqual((task["assigned_to"], task["second_signatory"]), (self.owner, self.contact))
        self.assertFalse(reviews.annual_review_state(self.forum)["may_start"], "one review at a time")
        with self.assertRaises(frappe.ValidationError):
            reviews.start_forum_annual_review(self.forum, add_days(nowdate(), 30))

        frappe.set_user(self.owner)
        attestation.respond_to_task(task["name"], "Attested", "The forum met its mandate this year.")
        frappe.set_user(self.reviewer)
        with self.assertRaises(frappe.ValidationError):
            # Not yet counter-signed: half a review is not a review.
            reviews.record_forum_annual_review(self.forum, task["name"], "Compliant", "Fine.")
        frappe.set_user(self.contact)
        attestation.second_sign_task(task["name"])

        frappe.set_user(self.reviewer)
        state = reviews.forum_annual_review(self.forum)
        self.assertTrue(state["may_record"])
        state = reviews.record_forum_annual_review(self.forum, task["name"], "Compliant", "Both signed.")
        frappe.set_user("Administrator")
        review = frappe.get_doc("Forum Compliance Review", state["review"])
        self.assertEqual((review.review_type, review.attestation_task), ("Annual", task["name"]))
        self.assertTrue(frappe.db.get_value("Governance Forum", self.forum, "next_review_on"))
        self.assertFalse(state["tasks"][0]["outstanding"])

    def test_only_the_office_starts_it_and_the_refusal_is_audited(self):
        frappe.set_user(self.owner)
        self.assertFalse(reviews.forum_annual_review(self.forum)["may_start"])
        with self.assertRaises(frappe.PermissionError):
            reviews.start_forum_annual_review(self.forum, add_days(nowdate(), 30))
        frappe.set_user("Administrator")
        self.assertTrue(any(r["control"] == "forum campaign role" for r in refusals_for("Governance Forum", self.forum)))
        self.purge_on_teardown("Governance Forum", self.forum)

    def test_a_lapsed_review_can_be_started_again_in_the_same_year(self):
        """The default period label was the forum and the year, and a campaign's
        type and period are unique together: a restart was refused as a duplicate."""
        frappe.set_user(self.office)
        first = reviews.start_forum_annual_review(self.forum, add_days(nowdate(), 30))
        frappe.set_user("Administrator")
        frappe.db.set_value("Attestation Task", first["tasks"][0]["name"], "is_open", 0)  # lapsed unanswered
        frappe.set_user(self.office)
        second = reviews.start_forum_annual_review(self.forum, add_days(nowdate(), 30))
        self.assertEqual(second["started"]["created"], 1)
        self.assertEqual(len(second["tasks"]), 2)

    def test_a_forum_without_its_second_signatory_cannot_start_one(self):
        forum = make_forum(forum_owner=self.owner).name
        frappe.set_user(self.office)
        state = reviews.forum_annual_review(forum)
        self.assertFalse(state["may_start"])
        self.assertTrue(state["missing"])
        with self.assertRaises(frappe.ValidationError):
            reviews.start_forum_annual_review(forum, add_days(nowdate(), 30))


class TestVotingScreen(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.secretary = make_user("Committee Secretary")
        self.forum = make_forum(quorum_rule_type="Count", quorum_value=2).name
        role = seat_role()
        self.members = [make_user() for _ in range(3)]
        self.seats = [make_seat(self.forum, role, member=m).name for m in self.members]

    def _put(self):
        frappe.set_user(self.secretary)
        ctx = voting.propose_motion(self.forum, "MOT-" + unique("x"), "That the charter be adopted.", nowdate())
        frappe.set_user("Administrator")
        return ctx["created"]

    def test_members_vote_and_the_secretary_records_a_quorate_outcome(self):
        motion = self._put()
        self.assertEqual(len(voting.entitlement(motion)), 3)
        for member, seat in zip(self.members[:2], self.seats[:2], strict=True):
            frappe.set_user(member)
            ctx = voting.get_motion(motion)
            self.assertTrue(ctx["may_vote"])
            self.assertFalse(ctx["may_record_outcome"])
            voting.cast_my_vote(motion, seat, voting.POSITION_FOR)
        frappe.set_user(self.secretary)
        ctx = voting.record_motion_outcome(motion, "Carried")
        frappe.set_user("Administrator")
        self.assertEqual(ctx["motion"]["outcome"], "Carried")
        self.assertEqual((ctx["motion"]["votes_for"], ctx["motion"]["quorum_met"]), (2, 1))
        self.assertFalse(ctx["may_vote"], "the motion is frozen")

    def test_a_member_cannot_cast_anothers_ballot(self):
        motion = self._put()
        self.purge_on_teardown("Forum Motion", motion)
        frappe.set_user(self.members[0])
        with self.assertRaises(frappe.PermissionError):
            voting.cast_my_vote(motion, self.seats[1], voting.POSITION_AGAINST)
        frappe.set_user("Administrator")
        self.assertTrue(any(r["control"] == "voting entitlement" for r in refusals_for("Forum Motion", motion)))

    def test_a_decision_does_not_stand_on_an_inquorate_sitting(self):
        motion = self._put()
        self.purge_on_teardown("Forum Motion", motion)
        frappe.set_user(self.members[0])
        voting.cast_my_vote(motion, self.seats[0], voting.POSITION_FOR)
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.ValidationError):
            voting.record_motion_outcome(motion, "Carried")
        self.assertTrue(any(r["control"] == "quorum" for r in refusals_for("Forum Motion", motion)))
        ctx = voting.record_motion_outcome(motion, "Inquorate")
        frappe.set_user("Administrator")
        self.assertEqual(ctx["motion"]["quorum_met"], 0)

    def test_only_the_secretary_puts_a_motion_or_records_its_outcome(self):
        frappe.set_user(self.members[0])
        with self.assertRaises(frappe.PermissionError):
            voting.propose_motion(self.forum, "MOT-X", "That nothing happen.", nowdate())
        frappe.set_user("Administrator")
        motion = self._put()
        frappe.set_user(self.members[0])
        with self.assertRaises(frappe.PermissionError):
            voting.record_motion_outcome(motion, "Withdrawn")
        frappe.set_user("Administrator")
        self.purge_on_teardown("Governance Forum", self.forum)
        self.purge_on_teardown("Forum Motion", motion)

    def test_the_forum_names_its_secretary_who_may_act_without_the_role(self):
        named = make_user()
        frappe.db.set_value("Governance Forum", self.forum, "secretary", named)
        self.assertTrue(voting.may_administer(self.forum, named))
        self.assertFalse(voting.may_administer(self.forum, self.members[0]))
