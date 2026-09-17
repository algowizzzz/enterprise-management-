"""The classification rules engine: rules as data, versioned, with a stored trace."""

import json

import frappe
from frappe.utils import nowdate

from consilium.consilium_core import classification
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, refusals_for, unique


def rule_set_values(**overrides):
    values = {
        "doctype": "Classification Rule Set",
        "rule_set_title": "Change classification",
        "applies_to_doctype": "Guide Article",
        "version_label": "1.0",
        "effective_from": nowdate(),
        "is_active": 1,
        "default_outcome": "Major",
        "questions": [
            {"question_code": "scope", "question_text": "What is the scope of the change?",
             "answer_mode": "Single", "is_required": 1, "display_order": 1},
            {"question_code": "cost", "question_text": "What does the change cost?",
             "answer_mode": "Numeric", "is_required": 0, "display_order": 2},
        ],
        "answer_options": [
            {"question_code": "scope", "option_code": "wording", "option_text": "Wording only"},
            {"question_code": "scope", "option_code": "requirement", "option_text": "A requirement changes"},
        ],
        "rules": [
            {"rule_code": "R10", "priority": 10,
             "condition": json.dumps({"all": [{"question": "scope", "equals": "requirement"}]}),
             "outcome": "Major", "outcome_rationale": "A changed requirement needs full re-approval.",
             "is_active": 1},
            {"rule_code": "R20", "priority": 20,
             "condition": json.dumps(
                 {"all": [{"question": "scope", "equals": "wording"},
                          {"question": "cost", "less_than": 1000}]}),
             "outcome": "Minor", "outcome_rationale": "Wording at negligible cost is a minor change.",
             "is_active": 1},
        ],
    }
    values.update(overrides)
    return values


class TestClassification(CoreTestCase):
    def setUp(self):
        self.subject = make_guide_article()
        self.rule_set = frappe.get_doc(rule_set_values()).insert(ignore_permissions=True)

    def _classify(self, answers):
        return classification.classify(
            self.rule_set.name, answers, subject_doctype="Guide Article", subject_name=self.subject.name
        )

    def test_first_matching_rule_wins_and_is_recorded(self):
        assessment = self._classify({"scope": "requirement", "cost": 10})
        self.assertEqual(assessment.outcome, "Major")
        self.assertEqual(assessment.matched_rule_code, "R10")
        self.assertEqual(assessment.rule_set_version_label, "1.0")

    def test_a_lower_priority_rule_applies_when_the_first_does_not_match(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        self.assertEqual(assessment.outcome, "Minor")
        self.assertEqual(assessment.matched_rule_code, "R20")

    def test_the_conservative_default_applies_when_nothing_matches(self):
        assessment = self._classify({"scope": "wording", "cost": 50000})
        self.assertIsNone(assessment.matched_rule_code)
        self.assertEqual(assessment.outcome, "Major")

    def test_the_trace_records_every_rule_considered(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        trace = json.loads(assessment.evaluation_trace) if isinstance(assessment.evaluation_trace, str) else assessment.evaluation_trace
        codes = [entry["rule_code"] for entry in trace["rules"]]
        self.assertEqual(codes, ["R10", "R20"])
        self.assertFalse(trace["rules"][0]["matched"])
        self.assertTrue(trace["rules"][1]["matched"])
        self.assertIn("scope", trace["rules"][0]["reason"])

    def test_a_missing_required_answer_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._classify({"cost": 10})

    def test_an_answer_outside_the_options_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._classify({"scope": "invented"})

    def test_an_unknown_question_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._classify({"scope": "wording", "nonsense": 1})

    def test_a_rule_set_locks_once_it_has_classified(self):
        self.assertFalse(self.rule_set.is_sealed)
        self._classify({"scope": "wording", "cost": 10})
        self.rule_set.reload()
        self.assertTrue(self.rule_set.is_sealed)

        self.rule_set.rules[0].outcome = "Minor"
        with self.assertRaises(frappe.PermissionError):
            self.rule_set.save(ignore_permissions=True)
        self.assertEqual(
            refusals_for("Classification Rule Set", self.rule_set.name)[-1]["control"], "rule set lock"
        )
        self.purge_on_teardown("Classification Rule Set", self.rule_set.name)

    def test_history_survives_a_new_rule_set_version(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        self.assertEqual(assessment.outcome, "Minor")

        new_version = frappe.get_doc(
            rule_set_values(
                version_label="2.0",
                rules=[
                    {"rule_code": "R10", "priority": 10,
                     "condition": json.dumps({"all": [{"question": "scope", "equals": "wording"}]}),
                     "outcome": "Major", "outcome_rationale": "Wording changes now need re-approval.",
                     "is_active": 1}
                ],
            )
        ).insert(ignore_permissions=True)
        later = classification.classify(
            new_version.name,
            {"scope": "wording", "cost": 10},
            subject_doctype="Guide Article",
            subject_name=self.subject.name,
        )
        self.assertEqual(later.outcome, "Major")

        assessment.reload()
        self.assertEqual(assessment.outcome, "Minor")
        self.assertEqual(assessment.rule_set_version_label, "1.0")

    def test_an_assessment_cannot_be_edited_or_deleted(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        assessment.outcome = "Major"
        with self.assertRaises(frappe.PermissionError):
            assessment.save(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Classification Assessment", assessment.name, ignore_permissions=True, force=True)
        self.purge_on_teardown("Guide Article", self.subject.name)

    def test_an_override_is_recorded_beside_the_original_outcome(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        overridden = classification.override(
            assessment.name, "Major", "The policy office judged the wording material."
        )
        self.assertEqual(overridden.outcome, "Minor")
        self.assertEqual(overridden.override_outcome, "Major")
        self.assertEqual(classification.effective_outcome(assessment.name), "Major")

    def test_an_override_without_a_justification_is_refused(self):
        assessment = self._classify({"scope": "wording", "cost": 10})
        with self.assertRaises(frappe.ValidationError):
            classification.override(assessment.name, "Major", "  ")
        self.purge_on_teardown("Guide Article", self.subject.name)

    def test_an_unreadable_condition_is_rejected_at_configuration_time(self):
        values = rule_set_values(version_label="3.0")
        values["rules"][0]["condition"] = json.dumps({"question": "scope", "nonsense": 1})
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(values).insert(ignore_permissions=True)

    def test_an_answer_option_for_an_unasked_question_is_rejected(self):
        values = rule_set_values(version_label="4.0")
        values["answer_options"].append({"question_code": "absent", "option_code": "x"})
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(values).insert(ignore_permissions=True)

    def test_nested_conditions_evaluate(self):
        condition = {
            "any": [
                {"question": "scope", "equals": "requirement"},
                {"all": [{"question": "scope", "equals": "wording"}, {"question": "cost", "greater_than": 100}]},
            ]
        }
        self.assertTrue(classification.matches(condition, {"scope": "wording", "cost": 500})[0])
        self.assertFalse(classification.matches(condition, {"scope": "wording", "cost": 50})[0])
        self.assertTrue(classification.matches(condition, {"scope": "requirement", "cost": 0})[0])
