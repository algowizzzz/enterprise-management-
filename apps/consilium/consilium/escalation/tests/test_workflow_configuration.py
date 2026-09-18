"""E-8 and E-9: the escalation workflow and the risk-acceptance approval chain
are configuration, keyed by matter type and severity.

E-8: `Escalation Transition Rule` decides which moves a matter may make — the
page offers only those, and `move_matter_status` / `close_matter` refuse (and
audit) any other. Two types, and two severities, are shown to get different
moves; the seeded catch-all is shown to change nothing; the seeded High-severity
set is shown to force second-line review before closure.

E-9: `Risk Acceptance Approval Route` raises several Core decisions, sequential
or parallel. The acceptance is approved only when the chain completes, any
objection returns it, steps reach My work only when they are due, a delegate can
decide a step, and nobody who owns or raised the matter can approve.

Each test starts from a known rule set: every rule on the site is switched off
inside the test's own transaction (rolled back afterwards), and the rules the
test needs are written or switched on.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import inbox
from consilium.consilium_core.tests.utils import refusals_for
from consilium.escalation import approvals, resolution, transitions
from consilium.escalation.setup import install
from consilium.escalation.tests.test_portal_actions import PortalTestCase
from consilium.escalation.tests.utils import as_user, make_taxonomy, make_user, unique

RULE = "Escalation Transition Rule"
ROUTE = "Risk Acceptance Approval Route"


def seeded_rows(prefix: str) -> list[tuple]:
    return [row for row in install.TRANSITION_RULES if row[0].startswith(prefix)]


class WorkflowTestCase(PortalTestCase):
    def build(self):
        super().build()
        install.ensure_transition_rules()
        frappe.db.sql(f'UPDATE "tab{RULE}" SET "is_active" = 0')
        frappe.db.sql(f'UPDATE "tab{ROUTE}" SET "is_active" = 0')

    def switch_on(self, prefix: str) -> None:
        for row in seeded_rows(prefix):
            frappe.db.set_value(RULE, row[0], "is_active", 1)

    def rule(self, **values) -> str:
        return frappe.get_doc({"doctype": RULE, "rule_code": unique("RULE").upper(), "is_active": 1,
                               **values}).insert(ignore_permissions=True).name

    def targets(self, matter, user=None) -> list[str]:
        return [t["value"] for t in resolution.status_targets(matter, user or self.owner)]

    def all_open(self, matter) -> list[str]:
        return [t["value"] for t in resolution.open_states(matter)]

    def other_matter(self, **overrides):
        return self.make_matter(self.reference, response_owner=self.owner, **overrides)


# ======================================================================= E-8


class TestTransitionRules(WorkflowTestCase):
    def test_no_rule_and_the_seeded_catch_all_both_leave_every_move_open(self):
        matter = self.fresh()
        self.assertEqual(self.targets(matter), self.all_open(matter))
        self.switch_on("ESC-ANY")
        self.assertTrue(transitions.is_configured(matter))
        self.assertEqual(self.targets(matter), self.all_open(matter))
        self.assertEqual([c["value"] for c in resolution.closing_states(matter, self.owner)],
                         [c["value"] for c in resolution.closing_states()])

    def test_two_types_get_different_moves(self):
        self.switch_on("ESC-ANY")
        strict_type = make_taxonomy("Escalation Type", "escalation_type_code", "escalation_type_name")
        review = self.open_target(review=True)
        self.rule(escalation_type=strict_type, from_status=self.matter.status, to_status=review)
        strict = self.other_matter(escalation_type=strict_type)
        ordinary = self.fresh()

        self.assertEqual(self.targets(strict), [review])
        self.assertEqual(resolution.closing_states(strict, self.owner), [])
        self.assertEqual(self.targets(ordinary), self.all_open(ordinary))
        self.assertNotEqual(self.targets(strict), self.targets(ordinary))

        with as_user(self.owner):
            wb = resolution.get_matter_workbench(strict.name)
        self.assertEqual([t["value"] for t in wb["status_targets"]], [review])
        self.assertTrue(wb["transition_rules"])

    def test_two_severities_get_different_moves(self):
        self.switch_on("ESC-ANY")
        self.switch_on("ESC-HIGH-")
        high = self.other_matter(severity="High")
        medium = self.fresh()

        high_targets = self.targets(high)
        self.assertTrue(high_targets)
        for value in high_targets:
            self.assertTrue(frappe.get_all("Workflow State Flag", filters={
                "target_doctype": "Escalation Matter", "state_value": value, "requires_review": 1}),
                msg="a new High matter may only be sent for review")
        self.assertEqual(resolution.closing_states(high, self.owner), [])
        self.assertEqual(self.targets(medium), self.all_open(medium))
        self.assertTrue(resolution.closing_states(medium, self.owner))

    def test_a_move_the_configuration_does_not_allow_is_refused_and_audited(self):
        self.switch_on("ESC-ANY")
        self.switch_on("ESC-HIGH-")
        high = self.other_matter(severity="High")
        working = next(t["value"] for t in resolution.open_states(high) if not t["requires_review"])
        self.purge_on_teardown("Escalation Matter", high.name)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            resolution.move_matter_status(high.name, working)
        self.assertIn("escalation transition rule",
                      [r.control for r in refusals_for("Escalation Matter", high.name)])
        self.assertEqual(frappe.db.get_value("Escalation Matter", high.name, "status"), high.status)

    def test_a_high_matter_passes_through_second_line_review_before_closure(self):
        self.switch_on("ESC-ANY")
        self.switch_on("ESC-HIGH-")
        high = self.other_matter(severity="High")
        self.make_closure(high)
        closing = next(c["value"] for c in resolution.closing_states() if not c["is_committable"])
        self.purge_on_teardown("Escalation Matter", high.name)

        with as_user(self.owner):
            self.assertFalse(resolution.get_matter_workbench(high.name)["actions"]["close"])
            with self.assertRaises(frappe.ValidationError):
                resolution.close_matter(high.name, closing, response_template_completed=1)
            resolution.move_matter_status(high.name, self.targets(high)[0])
        self.assertTrue(frappe.db.get_value("Escalation Matter", high.name, "requires_review"))

        under_review = frappe.get_doc("Escalation Matter", high.name)
        back = self.targets(under_review, self.reviewer)
        self.assertEqual(len(back), 1)
        with as_user(self.reviewer):
            resolution.move_matter_status(high.name, back[0])

        with as_user(self.owner):
            wb = resolution.get_matter_workbench(high.name)
            self.assertTrue(wb["actions"]["close"])
            self.assertIn(closing, [c["value"] for c in wb["closing_states"]])
            resolution.close_matter(high.name, closing, response_template_completed=1)
        self.assertFalse(frappe.db.get_value("Escalation Matter", high.name, "is_open"))

    def test_a_rule_can_name_the_role_that_makes_the_move(self):
        working = self.open_target(review=False)
        self.rule(from_status=self.matter.status, to_status=working, allowed_role="Consilium Administrator")
        matter = self.fresh()
        self.assertEqual(self.targets(matter), [])
        with as_user(self.owner):
            self.assertFalse(resolution.get_matter_workbench(matter.name)["actions"]["move_status"])
        self.purge_on_teardown("Escalation Matter", matter.name)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            resolution.move_matter_status(matter.name, working)

        frappe.get_doc("User", self.owner).add_roles("Consilium Administrator")
        self.assertEqual(self.targets(frappe.get_doc("Escalation Matter", matter.name)), [working])
        with as_user(self.owner):
            resolution.move_matter_status(matter.name, working)
        self.assertEqual(frappe.db.get_value("Escalation Matter", matter.name, "status"), working)

    def test_a_status_changed_on_the_desk_follows_the_same_rules(self):
        self.switch_on("ESC-ANY")
        self.switch_on("ESC-HIGH-")
        high = self.other_matter(severity="High")
        working = next(t["value"] for t in resolution.open_states(high) if not t["requires_review"])
        self.purge_on_teardown("Escalation Matter", high.name)
        with as_user(self.owner):
            doc = frappe.get_doc("Escalation Matter", high.name)
            doc.status = working
            with self.assertRaises(frappe.ValidationError):
                doc.save()

    def test_a_rule_must_name_real_states_and_start_from_one_that_is_worked(self):
        closing = resolution.closing_states()[0]["value"]
        with self.assertRaises(frappe.ValidationError):
            self.rule(from_status=closing, to_status=self.open_target(review=False))
        with self.assertRaises(frappe.ValidationError):
            self.rule(from_status=self.matter.status, to_status=self.matter.status)


# ======================================================================= E-9


class ChainTestCase(WorkflowTestCase):
    def build(self):
        super().build()
        self.first = make_user(approvals.APPROVER_ROLE, "Consilium Audit")
        self.second = make_user(approvals.APPROVER_ROLE, "Consilium Audit")
        self.third = make_user(approvals.APPROVER_ROLE, "Consilium Audit")

    def route(self, steps: list[dict], **values) -> str:
        return frappe.get_doc({
            "doctype": ROUTE, "route_code": unique("RAR").upper(), "route_title": unique("Route"),
            "priority": 100, "is_active": 1, "steps": steps, **values,
        }).insert(ignore_permissions=True).name

    def sequential_route(self, **values) -> str:
        return self.route([
            {"step_sequence": 1, "approval_step": "Second-line review", "mode": "Sequential",
             "assignee_source": approvals.CHOSEN_AT_REQUEST},
            {"step_sequence": 2, "approval_step": "Executive sign-off", "mode": "Sequential",
             "assignee_source": approvals.NAMED_USER, "assignee": self.second},
        ], **values)

    def propose(self) -> str:
        with as_user(self.owner):
            wb = approvals.add_risk_acceptance(self.matter.name, self.acceptance_values())
        return wb["acceptances"][0]["name"]

    def acceptance_row(self, name: str, user: str) -> dict:
        with as_user(user):
            rows = resolution.get_matter_workbench(self.matter.name)["acceptances"]
        return next(row for row in rows if row["name"] == name)

    def decide(self, user: str, name: str, decision: str = "Approved", comments: str = "Within appetite."):
        with as_user(user):
            return approvals.decide_risk_acceptance(name, decision, comments)

    def chain(self, name: str) -> list[dict]:
        return approvals.cycle_steps(frappe.get_doc("Risk Acceptance", name))

    def inbox_subjects(self, user: str) -> list[str]:
        return [item["subject_name"] for item in inbox.collect(user) if item["kind"] == "approval"]


class TestRouteSelection(ChainTestCase):
    def test_no_route_keeps_the_single_independent_approver(self):
        name = self.propose()
        self.assertIsNone(self.acceptance_row(name, self.owner)["route"])
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, self.approver)
        self.assertEqual(len(self.chain(name)), 1)
        self.assertFalse(frappe.db.get_value("Risk Acceptance", name, "approval_route"))
        self.decide(self.approver, name)
        self.assertTrue(frappe.db.get_value("Risk Acceptance", name, "is_active"))

    def test_the_route_is_chosen_by_type_and_severity(self):
        other_type = make_taxonomy("Escalation Type", "escalation_type_code", "escalation_type_name")
        by_type = self.sequential_route(escalation_type=self.matter.escalation_type)
        by_severity = self.sequential_route(severity="High")
        high_other = self.other_matter(escalation_type=other_type, severity="High")
        medium_other = self.other_matter(escalation_type=other_type, severity="Medium")

        self.assertEqual(approvals.select_route(self.fresh()).name, by_type)
        self.assertEqual(approvals.select_route(high_other).name, by_severity)
        self.assertIsNone(approvals.select_route(medium_other))

        both = self.sequential_route(escalation_type=other_type, severity="High")
        self.assertEqual(approvals.select_route(high_other).name, both, "the more specific route wins a tie")

    def test_the_planned_chain_is_shown_before_it_is_requested(self):
        self.sequential_route()
        name = self.propose()
        plan = self.acceptance_row(name, self.owner)["route"]
        self.assertEqual([s["approval_step"] for s in plan["steps"]], ["Second-line review", "Executive sign-off"])
        chosen = plan["steps"][0]
        self.assertTrue(chosen["chosen"])
        offered = [p.name for p in chosen["candidates"]]
        self.assertIn(self.first, offered)
        self.assertNotIn(self.owner, offered, "the matter's owner is never offered as its approver")
        self.assertEqual(plan["steps"][1]["assignee"], self.second)

    def test_a_route_needs_steps_and_a_named_step_its_person(self):
        with self.assertRaises(frappe.ValidationError):
            self.route([])
        with self.assertRaises(frappe.ValidationError):
            self.route([{"step_sequence": 1, "approval_step": "Sign-off",
                         "assignee_source": approvals.NAMED_USER}])


class TestSequentialChain(ChainTestCase):
    def test_steps_are_decided_in_order_and_the_last_approval_gives_effect(self):
        self.sequential_route()
        name = self.propose()
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={"1": self.first})
        steps = self.chain(name)
        self.assertEqual([(s.approval_step, s.assigned_to) for s in steps],
                         [("Second-line review", self.first), ("Executive sign-off", self.second)])
        self.assertEqual(frappe.db.get_value("Risk Acceptance", name, "approval_route"),
                         approvals.select_route(self.fresh()).name)

        # The second step is not due: not decidable, not in My work.
        self.assertFalse(self.acceptance_row(name, self.second)["can_decide"])
        self.assertNotIn(name, self.inbox_subjects(self.second))
        self.assertIn(name, self.inbox_subjects(self.first))
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.second), self.assertRaises(frappe.ValidationError):
            approvals.decide_risk_acceptance(name, "Approved", "Early.")
        self.assertIn("sequential approval order", [r.control for r in refusals_for("Risk Acceptance", name)])

        self.decide(self.first, name)
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertFalse(doc.is_active, "one approval of two is not an approval")
        self.assertTrue(doc.requires_review)
        self.assertFalse(doc.approved_by)
        self.assertIn(name, self.inbox_subjects(self.second))
        self.assertTrue(self.acceptance_row(name, self.second)["can_decide"])

        self.decide(self.second, name)
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertTrue(doc.is_active and doc.is_committable)
        self.assertEqual(doc.approved_by, self.second)
        self.assertTrue(approvals.is_approved(doc))

    def test_a_rejection_at_any_step_returns_the_acceptance(self):
        self.sequential_route()
        name = self.propose()
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={"1": self.first})
        self.decide(self.first, name)
        self.decide(self.second, name, "Rejected", "The period is too long.")
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertEqual(doc.status, approvals.returned_state())
        self.assertFalse(doc.approved_by)
        self.assertFalse(approvals.is_approved(doc))

        # Asked again, a fresh chain is raised; the old one neither counts nor blocks.
        self.assertTrue(self.acceptance_row(name, self.owner)["can_request"])
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={"1": self.third})
        fresh = self.chain(name)
        self.assertEqual(len(fresh), 2)
        self.assertTrue(all(step.is_open for step in fresh))
        self.assertIn(name, self.inbox_subjects(self.third))


class TestParallelChain(ChainTestCase):
    def parallel_route(self) -> str:
        return self.route([
            {"step_sequence": 1, "approval_step": "Risk sign-off", "mode": "Parallel",
             "assignee_source": approvals.CHOSEN_AT_REQUEST},
            {"step_sequence": 1, "approval_step": "Finance sign-off", "mode": "Parallel",
             "assignee_source": approvals.CHOSEN_AT_REQUEST},
        ])

    def request(self, name: str) -> None:
        plan = self.acceptance_row(name, self.owner)["route"]
        keys = [s["key"] for s in plan["steps"]]
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={keys[0]: self.first, keys[1]: self.second})

    def test_parallel_steps_are_decided_in_any_order_and_both_are_needed(self):
        self.parallel_route()
        name = self.propose()
        self.request(name)
        self.assertIn(name, self.inbox_subjects(self.first))
        self.assertIn(name, self.inbox_subjects(self.second))

        self.decide(self.second, name)
        self.assertFalse(frappe.db.get_value("Risk Acceptance", name, "is_active"))
        self.decide(self.first, name)
        doc = frappe.get_doc("Risk Acceptance", name)
        self.assertTrue(doc.is_active)
        self.assertEqual(doc.approved_by, self.first)

    def test_one_rejection_rejects_and_settles_the_other_step(self):
        self.parallel_route()
        name = self.propose()
        self.request(name)
        self.decide(self.first, name, "Rejected", "Not within appetite.")
        self.assertEqual(frappe.db.get_value("Risk Acceptance", name, "status"), approvals.returned_state())
        self.assertFalse([step for step in self.chain(name) if step.is_open])
        self.assertNotIn(name, self.inbox_subjects(self.second))

    def test_one_person_cannot_take_two_steps(self):
        self.parallel_route()
        name = self.propose()
        plan = self.acceptance_row(name, self.owner)["route"]
        keys = [s["key"] for s in plan["steps"]]
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            approvals.request_risk_acceptance_approval(name, approvers={keys[0]: self.first, keys[1]: self.first})
        self.assertFalse(self.chain(name))


class TestChainControls(ChainTestCase):
    def delegate_approval(self, delegator: str, delegate: str) -> str:
        return frappe.get_doc({
            "doctype": "Authority Delegation", "delegator": delegator, "delegate": delegate,
            "scope_type": "DocType", "scope_doctype": "Risk Acceptance",
            "valid_from": frappe.utils.nowdate(), "delegated_actions": [{"delegable_action": "APPROVE"}],
        }).insert(ignore_permissions=True).name

    def test_a_delegate_decides_a_step(self):
        self.sequential_route()
        name = self.propose()
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={"1": self.first})
        self.decide(self.first, name)
        stand_in = make_user("Consilium Audit")
        delegation = self.delegate_approval(self.second, stand_in)
        self.assertIn(name, self.inbox_subjects(stand_in))
        self.assertTrue(self.acceptance_row(name, stand_in)["can_decide"])
        self.decide(stand_in, name)
        last = self.chain(name)[-1]
        self.assertEqual((last.acted_by, last.acting_delegation), (stand_in, delegation))
        self.assertTrue(frappe.db.get_value("Risk Acceptance", name, "is_active"))

    def test_the_matters_owner_cannot_be_named_on_a_step(self):
        self.route([{"step_sequence": 1, "approval_step": "Owner sign-off",
                     "assignee_source": approvals.NAMED_USER, "assignee": self.owner}])
        name = self.propose()
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            approvals.request_risk_acceptance_approval(name)
        self.assertIn("four eyes", [r.control for r in refusals_for("Risk Acceptance", name)])
        self.assertFalse(self.chain(name))

    def test_the_matters_raiser_cannot_be_chosen(self):
        raiser = make_user(approvals.APPROVER_ROLE, "Consilium Audit")
        self.matter = self.other_matter(identified_by=raiser)
        self.sequential_route()
        name = self.propose()
        self.assertNotIn(raiser, [p.name for p in self.acceptance_row(name, self.owner)["route"]["steps"][0]["candidates"]])
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            approvals.request_risk_acceptance_approval(name, approvers={"1": raiser})

    def test_the_matters_owner_cannot_decide_even_as_a_delegate(self):
        self.sequential_route()
        name = self.propose()
        with as_user(self.owner):
            approvals.request_risk_acceptance_approval(name, approvers={"1": self.first})
        self.delegate_approval(self.first, self.owner)
        self.assertFalse(self.acceptance_row(name, self.owner)["can_decide"])
        self.purge_on_teardown("Risk Acceptance", name)
        with as_user(self.owner), self.assertRaises(frappe.PermissionError):
            approvals.decide_risk_acceptance(name, "Approved", "Mine to approve.")
        self.assertIn("separation of duties", [r.control for r in refusals_for("Risk Acceptance", name)])
        self.assertTrue(self.chain(name)[0].is_open)
