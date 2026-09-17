"""Routing: the matrix proposes severity and destination (E17-S1, E17-S2)."""

from __future__ import annotations

import json

import frappe

from consilium.escalation import routing
from consilium.escalation.tests.utils import EscalationTestCase, make_forum


class TestRouting(EscalationTestCase):
    def matrix_for(self, reference, forum, **rule_overrides):
        rule = {
            "rule_code": "R-HIGH",
            "priority": 10,
            "condition": {"escalation_type": reference["escalation_type"]},
            "resulting_severity": "High",
        }
        rule.update(rule_overrides)
        return self.make_matrix(
            reference,
            rules=[rule],
            routes=[{"rule_code": rule["rule_code"], "governance_forum": forum, "role_in_escalation": "Decision"}],
        )

    def test_a_matter_of_a_given_type_proposes_its_destination(self):
        reference = self.reference_data()
        matrix = self.matrix_for(reference, reference["forum"])

        matter = self.make_matter(reference, severity_source="Matrix")
        self.assertEqual(matter.escalation_matrix, matrix.name)
        self.assertEqual(matter.matched_matrix_rule, "R-HIGH")
        self.assertEqual(matter.severity, "High", msg="severity comes from the matrix")
        self.assertEqual(len(matter.governance_forums), 1)
        self.assertEqual(matter.governance_forums[0].governance_forum, reference["forum"])
        self.assertEqual(matter.governance_forums[0].proposed_by_rule, "R-HIGH")

    def test_the_forums_protocol_and_threshold_are_shown(self):
        reference = self.reference_data()
        self.matrix_for(reference, reference["forum"])
        matter = self.make_matter(reference, severity_source="Matrix")
        row = matter.governance_forums[0]
        self.assertTrue(row.escalation_protocol)
        self.assertTrue(row.escalation_threshold)

        proposal = routing.propose_pathway(matter.name)
        self.assertTrue(proposal["matched"])
        self.assertEqual(proposal["forums"][0]["escalation_protocol"], row.escalation_protocol)

    def test_a_manual_override_keeps_the_persons_severity(self):
        reference = self.reference_data()
        self.matrix_for(reference, reference["forum"])
        matter = self.make_matter(reference, severity="Low", severity_source="Manual Override")
        self.assertEqual(matter.severity, "Low")
        self.assertEqual(matter.matched_matrix_rule, "R-HIGH", msg="the trace is kept either way")

    def test_rules_fire_in_priority_order(self):
        reference = self.reference_data()
        forum_a = reference["forum"]
        forum_b = make_forum()
        self.make_matrix(
            reference,
            rules=[
                {
                    "rule_code": "R-LATE",
                    "priority": 90,
                    "condition": json.dumps({}),
                    "resulting_severity": "Low",
                },
                {
                    "rule_code": "R-EARLY",
                    "priority": 10,
                    "condition": json.dumps({"risk_appetite_breach": True}),
                    "resulting_severity": "High",
                },
            ],
            routes=[
                {"rule_code": "R-LATE", "governance_forum": forum_a},
                {"rule_code": "R-EARLY", "governance_forum": forum_b},
            ],
        )

        ordinary = self.make_matter(reference, severity_source="Matrix")
        self.assertEqual(ordinary.matched_matrix_rule, "R-LATE")

        breach = self.make_matter(reference, severity_source="Matrix", risk_appetite_breach=1)
        self.assertEqual(breach.matched_matrix_rule, "R-EARLY")
        self.assertEqual(breach.severity, "High")
        self.assertEqual(breach.governance_forums[0].governance_forum, forum_b)

    def test_severity_is_a_routable_attribute(self):
        reference = self.reference_data()
        forum_b = make_forum()
        self.make_matrix(
            reference,
            rules=[
                {
                    "rule_code": "R-SEV",
                    "priority": 10,
                    "condition": json.dumps({"severity": "High"}),
                    "resulting_severity": "High",
                }
            ],
            routes=[{"rule_code": "R-SEV", "governance_forum": forum_b}],
        )
        low = self.make_matter(reference, severity="Low", severity_source="Manual Override")
        self.assertIsNone(low.matched_matrix_rule)

        high = self.make_matter(reference, severity="High", severity_source="Manual Override")
        self.assertEqual(high.matched_matrix_rule, "R-SEV")

    def test_a_matrix_out_of_its_effective_window_does_not_fire(self):
        reference = self.reference_data()
        self.matrix_for(reference, reference["forum"])
        frappe.db.set_value(
            "Escalation Matrix",
            frappe.get_all("Escalation Matrix", pluck="name")[0],
            "effective_to",
            "2026-01-02",
        )
        matter = self.make_matter(reference, severity_source="Matrix")
        self.assertIsNone(matter.matched_matrix_rule)

    def test_an_inactive_forum_cannot_be_a_destination(self):
        reference = self.reference_data()
        inactive = make_forum()
        # The forum's own lifecycle is the Governance module's; from here it is
        # simply a forum that is no longer active.
        frappe.db.set_value("Governance Forum", inactive, "is_active", 0)
        with self.assertRaises(frappe.ValidationError):
            self.make_matter(
                reference,
                governance_forums=[{"governance_forum": inactive, "role_in_escalation": "Decision"}],
            )

    def test_the_same_forum_cannot_appear_twice_on_a_pathway(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_matter(
                reference,
                governance_forums=[
                    {"governance_forum": reference["forum"], "role_in_escalation": "Decision"},
                    {"governance_forum": reference["forum"], "role_in_escalation": "Oversight"},
                ],
            )

    def test_a_condition_may_only_test_a_routable_attribute(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_matrix(
                reference,
                rules=[
                    {
                        "rule_code": "R-BAD",
                        "condition": json.dumps({"escalation_title": "anything"}),
                        "resulting_severity": "High",
                    }
                ],
            )

    def test_a_destination_must_name_a_rule_the_matrix_defines(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_matrix(
                reference,
                rules=[{"rule_code": "R-1", "condition": json.dumps({}), "resulting_severity": "Low"}],
                routes=[{"rule_code": "R-2", "governance_forum": reference["forum"]}],
            )

    def test_a_rule_code_cannot_repeat_within_a_matrix(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_matrix(
                reference,
                rules=[
                    {"rule_code": "R-1", "condition": json.dumps({}), "resulting_severity": "Low"},
                    {"rule_code": "R-1", "condition": json.dumps({}), "resulting_severity": "High"},
                ],
            )

    def test_matrix_scope_limits_which_matters_it_routes(self):
        reference = self.reference_data()
        other_risk_type = self.reference_data()["risk_type"]
        self.make_matrix(
            reference,
            rules=[{"rule_code": "R-1", "condition": json.dumps({}), "resulting_severity": "High"}],
            routes=[{"rule_code": "R-1", "governance_forum": reference["forum"]}],
            scope_risk_types=[{"risk_type": other_risk_type}],
        )
        matter = self.make_matter(reference, severity_source="Matrix")
        self.assertIsNone(matter.matched_matrix_rule, msg="out of scope, so no rule fires")
