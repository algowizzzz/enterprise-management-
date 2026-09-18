"""The escalation portal's write actions.

Every entry point is exercised on the path that should work and on the paths
that must not: the wrong role, the wrong stage, and a sensitive matter reached
by someone not cleared to see it. A refusal on standing is audited out of band,
so the tests that expect one purge it afterwards.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core.tests.utils import purge_refusals, refusals_for
from consilium.escalation import approvals, flags, resolution, routing, templates
from consilium.escalation.tests.fixtures import retry_on_deadlock
from consilium.escalation.tests.utils import EscalationTestCase, as_user, make_forum, make_user, unique


def ensure_role(role: str) -> None:
    if not frappe.db.exists("Role", role):
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


class PortalTestCase(EscalationTestCase):
    def setUp(self):
        super().setUp()
        # A setUp that fails never reaches tearDown; without this its aborted
        # transaction would fail every test after it.
        self.addCleanup(frappe.db.rollback)
        self._purge = []
        retry_on_deadlock(self.build)

    def build(self):
        ensure_role(approvals.APPROVER_ROLE)
        self.reference = self.reference_data()
        self.owner = self.reference["user"]
        self.reviewer = make_user("Escalation Reviewer")
        # An approver decides from the matter's page, so must be able to read it.
        self.approver = make_user(approvals.APPROVER_ROLE, "Consilium Audit")
        self.auditor = make_user("Consilium Audit")
        self.matter = self.make_matter(self.reference, response_owner=self.owner)

    def tearDown(self):
        for doctype, name in self._purge:
            purge_refusals(doctype, name)
        super().tearDown()

    def purge_on_teardown(self, doctype: str, name: str) -> None:
        self._purge.append((doctype, name))

    def fresh(self):
        return frappe.get_doc("Escalation Matter", self.matter.name)

    def open_target(self, *, review: bool):
        return next(t["value"] for t in resolution.status_targets(self.fresh())
                    if bool(t["requires_review"]) is review)

    def send_for_review(self):
        with as_user(self.owner):
            resolution.move_matter_status(self.matter.name, self.open_target(review=True))

    def plan_values(self, **extra):
        return {"action_plan_name": "Rebuild the control", "start_date": "2026-02-01", "end_date": "2026-05-01",
                "accountable_executive": self.owner, "owner_user": self.owner, **extra}

    def acceptance_values(self, **extra):
        return {"risk_acceptance_name": "Carry the residual risk", "start_date": "2026-02-01",
                "end_date": "2026-08-01", "accountable_executive": self.owner,
                "rationale": "Treatment costs more than the exposure for two quarters.", **extra}


class TestWorkbench(PortalTestCase):
    def test_the_owner_is_offered_the_first_line_actions(self):
        with as_user(self.owner):
            wb = resolution.get_matter_workbench(self.matter.name)
        on = {k for k, v in wb["actions"].items() if v}
        self.assertTrue({"move_status", "add_action_plan", "add_risk_acceptance", "record_closure", "close",
                         "change_pathway"} <= on)
        self.assertNotIn("record_review", on)
        self.assertNotIn("update_action_plan", on, "no plan exists to update")
        self.assertTrue(wb["people"])

    def test_the_reviewer_is_offered_nothing_until_the_matter_is_under_review(self):
        with as_user(self.reviewer):
            self.assertFalse(any(resolution.get_matter_workbench(self.matter.name)["actions"].values()))
        self.send_for_review()
        with as_user(self.reviewer):
            on = {k for k, v in resolution.get_matter_workbench(self.matter.name)["actions"].items() if v}
        self.assertEqual(on, {"move_status", "record_review"})

    def test_a_reader_is_offered_nothing_and_sees_no_people(self):
        with as_user(self.auditor):
            wb = resolution.get_matter_workbench(self.matter.name)
        self.assertFalse(any(wb["actions"].values()))
        self.assertEqual(wb["people"], [])


class TestStatus(PortalTestCase):
    def test_the_owner_moves_the_matter_and_sends_it_for_review(self):
        working = self.open_target(review=False)
        with as_user(self.owner):
            resolution.move_matter_status(self.matter.name, working)
        self.assertEqual(self.fresh().status, working)
        self.send_for_review()
        self.assertTrue(self.fresh().requires_review)

    def test_only_the_reviewer_hands_it_back(self):
        self.send_for_review()
        back = self.open_target(review=False)
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            resolution.move_matter_status(self.matter.name, back)
        self.assertIn("escalation action role",
                      [r.control for r in refusals_for("Escalation Matter", self.matter.name)])
        with as_user(self.reviewer):
            resolution.move_matter_status(self.matter.name, back)
        self.assertFalse(self.fresh().requires_review)

    def test_a_move_cannot_close_the_matter(self):
        closing = resolution.closing_states()[0]["value"]
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            resolution.move_matter_status(self.matter.name, closing)
        self.assertTrue(self.fresh().is_open)

    def test_a_reader_cannot_move_it(self):
        with as_user(self.auditor), self.assertRaises(frappe.PermissionError):
            resolution.move_matter_status(self.matter.name, self.open_target(review=False))


class TestSensitiveMatter(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.matter.sensitive = 1
        self.matter.save(ignore_permissions=True)

    def test_a_sensitive_matter_is_invisible_to_an_owner_without_access(self):
        # An owner the matter does not name: the people it names see it (below).
        outsider = make_user("Escalation Owner")
        with as_user(outsider):
            with self.assertRaises(frappe.PermissionError) as hidden:
                resolution.get_matter_workbench(self.matter.name)
            with self.assertRaises(frappe.PermissionError) as missing:
                resolution.get_matter_workbench("ESC-NOT-THERE")
            with self.assertRaises(frappe.PermissionError):
                resolution.move_matter_status(self.matter.name, "anything")
            with self.assertRaises(frappe.PermissionError):
                resolution.add_action_plan(self.matter.name, self.plan_values())
            self.assertNotIn(self.matter.name,
                             [row.name for row in resolution.my_escalation_queue()["owned"]])
        self.assertEqual(str(hidden.exception).replace(self.matter.name, "X"),
                         str(missing.exception).replace("ESC-NOT-THERE", "X"))
        self.assertFalse(frappe.get_all("Action Plan", filters={"escalation_matter": self.matter.name}))

    def test_the_response_owner_it_names_works_it_without_clearance(self):
        with as_user(self.owner):
            wb = resolution.add_action_plan(self.matter.name, self.plan_values())
            self.assertIn(self.matter.name, [row.name for row in resolution.my_escalation_queue()["owned"]])
        self.assertEqual(len(wb["plans"]), 1, "the plans of a matter that names you are yours to see")

    def test_a_cleared_owner_works_it(self):
        frappe.get_doc("User", self.owner).add_roles("Sensitive Escalation Access")
        with as_user(self.owner):
            wb = resolution.add_action_plan(self.matter.name, self.plan_values())
            self.assertIn(self.matter.name, [row.name for row in resolution.my_escalation_queue()["owned"]])
        self.assertEqual(len(wb["plans"]), 1)


class TestActionPlans(PortalTestCase):
    def test_the_owner_adds_and_updates_a_plan(self):
        with as_user(self.owner):
            wb = resolution.add_action_plan(self.matter.name, self.plan_values())
            plan = wb["plans"][0]
            self.assertTrue(plan["can_update"])
            resolution.update_action_plan(plan["name"], {"description": "Tested twice.", "matter": "ignored"})
        self.assertEqual(frappe.db.get_value("Action Plan", plan["name"], "description"), "Tested twice.")

    def test_the_plan_template_is_enforced(self):
        self.make_template(self.reference, templates.SCOPE_ACTION_PLAN,
                           [{"fieldname": "description", "is_required": 1, "required_when_severity": "Always"}])
        with as_user(self.owner):
            self.assertEqual([r["fieldname"] for r in resolution.get_matter_workbench(self.matter.name)
                              ["template_requirements"][templates.SCOPE_ACTION_PLAN]], ["description"])
            with self.assertRaises(frappe.ValidationError):
                resolution.add_action_plan(self.matter.name, self.plan_values())
            resolution.add_action_plan(self.matter.name, self.plan_values(description="What will be done."))

    def test_a_closed_plan_cannot_be_changed(self):
        done = flags.values_meaning("Action Plan", "status", is_open=0, is_active=1)[0]
        with as_user(self.owner):
            wb = resolution.add_action_plan(self.matter.name, self.plan_values())
            name = wb["plans"][0]["name"]
            resolution.update_action_plan(name, {"status": done})
            with self.assertRaises(frappe.ValidationError):
                resolution.update_action_plan(name, {"description": "Too late."})

    def test_the_reviewer_cannot_add_a_plan(self):
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.reviewer), self.assertRaises(frappe.PermissionError):
            resolution.add_action_plan(self.matter.name, self.plan_values())
        self.assertIn("escalation action role",
                      [r.control for r in refusals_for("Escalation Matter", self.matter.name)])


class TestRiskAcceptanceApproval(PortalTestCase):
    def propose(self):
        with as_user(self.owner):
            wb = approvals.add_risk_acceptance(self.matter.name, self.acceptance_values())
        return wb["acceptances"][0]["name"]

    def request(self, name):
        with as_user(self.owner):
            return approvals.request_risk_acceptance_approval(name, self.approver)

    def test_a_proposal_has_no_effect(self):
        name = self.propose()
        self.assertFalse(frappe.db.get_value("Risk Acceptance", name, "is_active"))

    def test_the_named_approver_approves_and_the_acceptance_takes_effect(self):
        name = self.propose()
        wb = self.request(name)
        row = wb["acceptances"][0]
        self.assertTrue(frappe.db.get_value("Risk Acceptance", name, "requires_review"))
        self.assertFalse(row["can_request"])
        with as_user(self.approver):
            self.assertTrue(resolution.get_matter_workbench(self.matter.name)["actions"]["decide_approval"])
            self.assertEqual([a.name for a in resolution.my_escalation_queue()["approvals"]], [name])
            approvals.decide_risk_acceptance(name, "Approved", "Within appetite for the period.")
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertTrue(doc.is_committable and doc.is_active)
        self.assertEqual(doc.approved_by, self.approver)
        self.assertTrue(approvals.is_approved(doc))

    def test_a_rejection_needs_its_reason_and_returns_the_acceptance(self):
        name = self.propose()
        self.request(name)
        with as_user(self.approver):
            with self.assertRaises(frappe.ValidationError):
                approvals.decide_risk_acceptance(name, "Rejected")
            approvals.decide_risk_acceptance(name, "Rejected", "The period is too long.")
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertEqual(doc.status, approvals.returned_state())
        self.assertFalse(doc.approved_by)
        with as_user(self.owner):
            self.assertTrue(resolution.get_matter_workbench(self.matter.name)["acceptances"][0]["can_request"])

    def test_someone_else_cannot_decide_it(self):
        name = self.propose()
        self.request(name)
        other = make_user(approvals.APPROVER_ROLE, "Escalation Owner")
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(other):
            self.assertFalse(resolution.get_matter_workbench(self.matter.name)["actions"]["decide_approval"])
            with self.assertRaises(frappe.PermissionError):
                approvals.decide_risk_acceptance(name, "Approved", "Taking it on myself.")
        self.assertTrue(refusals_for("Risk Acceptance", name))
        self.assertFalse(frappe.db.get_value("Risk Acceptance", name, "is_active"))

    def test_an_approver_must_be_independent(self):
        name = self.propose()
        frappe.get_doc("User", self.owner).add_roles(approvals.APPROVER_ROLE)
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            approvals.request_risk_acceptance_approval(name, self.owner)
        self.assertIn("four eyes", [r.control for r in refusals_for("Risk Acceptance", name)])

    def test_the_approver_must_hold_the_approver_role(self):
        name = self.propose()
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            approvals.request_risk_acceptance_approval(name, self.reviewer)

    def test_an_approver_who_cannot_see_the_matter_is_not_offered(self):
        blind = make_user(approvals.APPROVER_ROLE)
        name = self.propose()
        with as_user(self.owner):
            offered = [p.name for p in resolution.get_matter_workbench(self.matter.name)["approvers"]]
            self.assertIn(self.approver, offered)
            self.assertNotIn(blind, offered)
            with self.assertRaises(frappe.ValidationError):
                approvals.request_risk_acceptance_approval(name, blind)

    def test_approval_cannot_be_requested_twice(self):
        name = self.propose()
        self.request(name)
        with self.assertRaises(frappe.ValidationError):
            self.request(name)

    def test_a_sensitive_matter_is_decided_only_by_a_cleared_approver(self):
        name = self.propose()
        self.request(name)
        self.matter.reload()
        self.matter.sensitive = 1
        self.matter.save(ignore_permissions=True)
        with as_user(self.approver), self.assertRaises(frappe.PermissionError):
            approvals.decide_risk_acceptance(name, "Approved", "ok")
        frappe.get_doc("User", self.approver).add_roles("Sensitive Escalation Access")
        with as_user(self.approver):
            approvals.decide_risk_acceptance(name, "Approved", "ok")


class TestReviewRounds(PortalTestCase):
    def test_the_reviewer_records_a_round_on_a_matter_under_review(self):
        self.send_for_review()
        with as_user(self.reviewer):
            with self.assertRaises(frappe.ValidationError):
                resolution.record_review_round(self.matter.name, "Challenged", "  ")
            resolution.record_review_round(self.matter.name, "Challenged", "Show the sensitivity analysis.")
            resolution.record_review_round(self.matter.name, "Accepted", "Evidence seen.")
        rounds = [(r.round, r.reviewer, r.outcome) for r in self.fresh().reviews]
        self.assertEqual(rounds, [(1, self.reviewer, "Challenged"), (2, self.reviewer, "Accepted")])

    def test_an_open_round_is_completed_rather_than_duplicated(self):
        matter = self.fresh()
        matter.append("reviews", {"round": 1, "reviewer": self.reviewer, "received_on": "2026-01-10 09:00:00"})
        matter.save(ignore_permissions=True)
        self.send_for_review()
        with as_user(self.reviewer):
            resolution.record_review_round(self.matter.name, "Accepted", "Evidence seen.")
        rounds = self.fresh().reviews
        self.assertEqual(len(rounds), 1)
        self.assertTrue(rounds[0].responded_on)

    def test_no_round_while_the_matter_is_being_worked(self):
        with as_user(self.reviewer), self.assertRaises(frappe.ValidationError):
            resolution.record_review_round(self.matter.name, "Accepted", "Premature.")

    def test_the_accountable_executive_cannot_challenge_their_own_matter(self):
        frappe.get_doc("User", self.owner).add_roles("Escalation Reviewer")
        self.send_for_review()
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            resolution.record_review_round(self.matter.name, "Accepted", "Marking my own work.")
        self.assertIn("independent challenge",
                      [r.control for r in refusals_for("Escalation Matter", self.matter.name)])

    def test_the_owner_cannot_record_a_round(self):
        self.send_for_review()
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            resolution.record_review_round(self.matter.name, "Accepted", "Mine.")


class TestClosure(PortalTestCase):
    def criteria(self, met=1):
        return [{"criterion": "Root cause recorded", "required": 1, "met": met},
                {"criterion": "Lessons shared", "required": 0, "met": 0}]

    def test_the_owner_records_the_closure_and_closes(self):
        closing = next(c["value"] for c in resolution.closing_states() if not c["is_committable"])
        with as_user(self.owner):
            with self.assertRaises(frappe.ValidationError):
                resolution.close_matter(self.matter.name, closing, 1)          # no closure yet
            with self.assertRaises(frappe.ValidationError):
                resolution.record_matter_closure(self.matter.name, "Resolved", "Done.", self.criteria(met=0))
            resolution.record_matter_closure(self.matter.name, "Resolved", "Done.", self.criteria())
            with self.assertRaises(frappe.ValidationError):
                resolution.close_matter(self.matter.name, closing, 0)          # template incomplete
            wb = resolution.close_matter(self.matter.name, closing, "true")
        matter = self.fresh()
        self.assertFalse(matter.is_open)
        self.assertEqual(wb["matter"]["stage"], "at_rest")
        self.assertFalse(any(wb["actions"].values()))
        closure = frappe.get_doc("Escalation Closure", resolution.closure_of(matter.name))
        self.assertEqual(closure.approved_by, self.owner)
        self.assertEqual(len(closure.criteria_met), 2)

    def test_a_closure_is_revised_not_duplicated(self):
        with as_user(self.owner):
            resolution.record_matter_closure(self.matter.name, "Resolved", "First.", self.criteria())
            resolution.record_matter_closure(self.matter.name, "Resolved", "Second.", self.criteria())
        rows = frappe.get_all("Escalation Closure", filters={"escalation_matter": self.matter.name},
                              pluck="closure_summary")
        self.assertEqual(rows, ["Second."])

    def test_closing_as_tracked_elsewhere_takes_the_closures_reference(self):
        committable = next(c["value"] for c in resolution.closing_states() if c["is_committable"])
        system = frappe.get_doc({"doctype": "External System", "system_code": unique("SYS").upper(),
                                 "title": "An issue tracker", "is_active": 1}).insert(ignore_permissions=True)
        with as_user(self.owner):
            resolution.record_matter_closure(self.matter.name, "Transferred Externally", "Moved.",
                                             self.criteria(), external_system=system.name, external_key="ISS-1")
            resolution.close_matter(self.matter.name, committable, 1)
        matter = self.fresh()
        self.assertEqual(frappe.db.get_value("External Reference", matter.external_reference, "external_key"), "ISS-1")

    def test_a_matter_under_review_cannot_be_closed(self):
        with as_user(self.owner):
            resolution.record_matter_closure(self.matter.name, "Resolved", "Done.", self.criteria())
        self.send_for_review()
        closing = resolution.closing_states()[0]["value"]
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            resolution.close_matter(self.matter.name, closing, 1)
        with as_user(self.reviewer), self.assertRaises(frappe.PermissionError):
            resolution.close_matter(self.matter.name, closing, 1)


class TestPathway(PortalTestCase):
    def test_the_owner_adds_a_forum_and_keeps_the_rest(self):
        extra = make_forum()
        with as_user(self.owner):
            wb = routing.set_pathway(self.matter.name, [{"governance_forum": self.reference["forum"],
                                                         "role_in_escalation": "Oversight"},
                                                        {"governance_forum": extra}])
        self.assertEqual(sorted(p["governance_forum"] for p in wb["pathway"]),
                         sorted([self.reference["forum"], extra]))

    def test_an_inactive_forum_is_refused(self):
        inactive = make_forum()
        # The forum's standing is the Governance module's; from here it is simply
        # a forum that is no longer active (as in test_routing).
        frappe.db.set_value("Governance Forum", inactive, "is_active", 0)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            routing.set_pathway(self.matter.name, [{"governance_forum": inactive}])

    def test_a_forum_the_matrix_routes_to_cannot_be_removed(self):
        self.make_matrix(self.reference,
                         rules=[{"rule_code": "R1", "priority": 10, "is_active": 1, "resulting_severity": "High",
                                 "condition": {"escalation_type": self.reference["escalation_type"]}}],
                         routes=[{"rule_code": "R1", "governance_forum": self.reference["forum"],
                                  "role_in_escalation": "Decision"}])
        matter = self.make_matter(self.reference, severity_source="Matrix")
        self.assertIn(self.reference["forum"], [r.governance_forum for r in matter.governance_forums])
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            routing.set_pathway(matter.name, [])
        with as_user(self.owner):
            wb = routing.set_pathway(matter.name, [{"governance_forum": self.reference["forum"],
                                                    "role_in_escalation": "Informed"}])
        self.assertEqual(wb["pathway"][0]["role_in_escalation"], "Informed")
        self.assertEqual(wb["pathway"][0]["proposed_by_rule"], "R1")

    def test_the_reviewer_cannot_change_it(self):
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.reviewer), self.assertRaises(frappe.PermissionError):
            routing.set_pathway(self.matter.name, [])


class TestRaise(PortalTestCase):
    def values(self, **extra):
        return {
            "escalation_title": "Raised from the portal",
            "escalation_type": self.reference["escalation_type"],
            "escalation_identification_date": "2026-03-01",
            "description": "A control failed in production.",
            "escalation_trigger": "Two failures in one quarter.",
            "tier_1_risk_type": self.reference["risk_type"],
            "organizational_level": self.reference["organizational_level"],
            "accountable_executive": self.owner,
            "impacted_entities": [{"entity_type": "Legal Entity", "entity_value": self.reference["legal_entity"]}],
            **extra,
        }

    def test_a_chosen_severity_is_recorded_as_an_override(self):
        with as_user(self.owner):
            result = templates.raise_escalation(self.values(severity="Low"))
        matter = frappe.get_doc("Escalation Matter", result["name"])
        self.assertEqual((matter.severity, matter.severity_source), ("Low", "Manual Override"))
        self.assertEqual(matter.identified_by, self.owner)
        self.assertEqual(matter.owner, self.owner)

    def test_the_matrix_sets_the_severity_when_none_is_chosen(self):
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            templates.raise_escalation(self.values())
        self.make_matrix(self.reference,
                         rules=[{"rule_code": "R1", "priority": 10, "is_active": 1, "resulting_severity": "High",
                                 "condition": {"escalation_type": self.reference["escalation_type"]}}])
        with as_user(self.owner):
            result = templates.raise_escalation(self.values())
        matter = frappe.get_doc("Escalation Matter", result["name"])
        self.assertEqual((matter.severity, matter.severity_source, matter.matched_matrix_rule),
                         ("High", "Matrix", "R1"))

    def test_the_escalation_template_is_enforced(self):
        self.make_template(self.reference, templates.SCOPE_ESCALATION,
                           [{"fieldname": "response_owner", "is_required": 1, "required_when_severity": "High"}])
        with as_user(self.owner):
            self.assertEqual(templates.template_requirements(self.reference["escalation_type"], "Low")["required"], [])
            self.assertEqual([r["fieldname"] for r in templates.template_requirements(
                self.reference["escalation_type"], "High")["required"]], ["response_owner"])
            with self.assertRaises(frappe.ValidationError):
                templates.raise_escalation(self.values(severity="High"))
            templates.raise_escalation(self.values(severity="High", response_owner=self.owner))

    def test_only_a_cleared_person_raises_a_sensitive_matter(self):
        title = "A restricted matter"
        self.purge_on_teardown("Escalation Matter", title)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            templates.raise_escalation(self.values(severity="Low", sensitive=1, escalation_title=title))
        self.assertIn("sensitive escalation access",
                      [r.control for r in refusals_for("Escalation Matter", title)])
        cleared = make_user("Escalation Owner", "Sensitive Escalation Access")
        with as_user(cleared):
            result = templates.raise_escalation(self.values(severity="Low", sensitive=1))
        self.assertEqual(frappe.db.get_value("Escalation Matter", result["name"], "sensitive"), 1)

    def test_someone_who_cannot_create_a_matter_cannot_raise_one(self):
        with as_user(self.reviewer):
            with self.assertRaises(frappe.PermissionError):
                templates.raise_escalation(self.values(severity="Low"))
            with self.assertRaises(frappe.PermissionError):
                templates.intake_options()

    def test_the_form_is_offered_the_configuration(self):
        with as_user(self.owner):
            options = templates.intake_options()
        self.assertIn(self.reference["escalation_type"], [o["value"] for o in options["escalation_types"]])
        self.assertIn(self.reference["forum"], [o["value"] for o in options["forums"]])
        self.assertFalse(options["may_restrict"])
