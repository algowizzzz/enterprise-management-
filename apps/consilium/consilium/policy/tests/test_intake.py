"""E13 — intake and classification.

The property the whole epic hangs on is the last test in this file: a
classification made under one rule-set version does not change when the rules are
later edited.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core.versioning import as_dict

from consilium.consilium_core import classification
from consilium.policy import intake, routing
from consilium.policy.setup import seed
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_user,
    unique,
)

REQUEST = "Document Intake Request"

MAJOR_ANSWERS = {"q_scope": "enterprise", "q_obligation": "yes", "q_control": "yes"}
MINOR_ANSWERS = {"q_scope": "local", "q_obligation": "no", "q_control": "no"}


def make_request(**values):
    defaults = {
        "doctype": REQUEST,
        "request_type": "Create",
        "requester": values.pop("requester", None) or make_user("Policy Owner"),
        "business_justification": "The regulator has changed its expectations.",
        "proposed_document_name": unique("Proposed"),
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class TestIntakeRequest(PolicyTestCase):
    def test_a_request_captures_the_need_the_date_and_who_to_engage(self):
        engage = [make_user(), make_user()]
        request = make_request(
            proposed_effective_date="2026-06-01",
            parties_to_engage=[{"party": user} for user in engage],
        )
        request.reload()
        self.assertEqual(str(request.proposed_effective_date), "2026-06-01")
        self.assertEqual({row.party for row in request.parties_to_engage}, set(engage))
        self.assertTrue(int(request.is_open or 0))

    def test_a_request_needs_a_justification(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": REQUEST, "request_type": "Create", "requester": make_user()}
            ).insert(ignore_permissions=True)

    def test_a_reviewer_cannot_delete_a_request(self):
        request = make_request()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.delete_doc(REQUEST, request.name)

    def test_a_request_creates_the_repository_record(self):
        request = make_request()
        intake.classify(request.name, MINOR_ANSWERS)
        document = intake.create_document(
            request.name,
            document_type=make_document().document_type,
            owning_operating_group=make_document().owning_operating_group,
            primary_risk_category=make_document().primary_risk_category,
        )
        request.reload()
        self.assertEqual(request.created_document, document)
        self.assertFalse(int(request.is_open or 0))


class TestClassification(PolicyTestCase):
    def test_the_questions_and_options_are_data(self):
        rule_set = frappe.get_doc("Classification Rule Set", intake.active_rule_set())
        self.assertEqual({q.question_code for q in rule_set.questions},
                         {"q_scope", "q_obligation", "q_control"})
        self.assertTrue(rule_set.answer_options)
        self.assertTrue(rule_set.rules)

    def test_an_administrator_can_add_a_question_without_a_code_change(self):
        # A rule set that has classified anything is sealed, so the question is
        # added the way an administrator does it on a live system: by publishing
        # a new version, which the next classification picks up.
        rule_set = frappe.copy_doc(frappe.get_doc("Classification Rule Set", intake.active_rule_set()))
        rule_set.version_label = frappe.generate_hash(length=6)
        rule_set.effective_from = frappe.utils.nowdate()
        rule_set.is_sealed = 0
        rule_set.append("questions", {"question_code": "q_new", "question_text": "Anything else?",
                                      "answer_mode": "Single", "display_order": 99})
        rule_set.append("answer_options", {"question_code": "q_new", "option_code": "yes",
                                           "option_text": "Yes", "display_order": 1})
        rule_set.insert(ignore_permissions=True)
        self.assertEqual(intake.active_rule_set(), rule_set.name)
        request = make_request()
        assessment = intake.classify(request.name, {**MINOR_ANSWERS, "q_new": "yes"})
        self.assertEqual(as_dict(assessment.evaluation_trace)["answers"]["q_new"], "yes")

    def test_an_answer_outside_the_option_set_is_refused(self):
        request = make_request()
        with self.assertRaises(frappe.ValidationError):
            intake.classify(request.name, {**MINOR_ANSWERS, "q_scope": "galactic"})

    def test_a_major_answer_set_yields_the_major_outcome(self):
        request = make_request()
        assessment = intake.classify(request.name, MAJOR_ANSWERS)
        self.assertEqual(assessment.outcome, "Major")
        self.assertEqual(assessment.matched_rule_code, "R10")
        request.reload()
        self.assertEqual(request.change_classification, "Major")

    def test_a_minor_answer_set_yields_the_minor_outcome(self):
        request = make_request()
        assessment = intake.classify(request.name, MINOR_ANSWERS)
        self.assertEqual(assessment.outcome, "Minor")
        self.assertEqual(assessment.matched_rule_code, "R20")

    def test_the_rule_set_version_is_stored_on_the_assessment(self):
        request = make_request()
        assessment = intake.classify(request.name, MINOR_ANSWERS)
        self.assertEqual(assessment.rule_set_version_label, seed.RULE_SET_VERSION)

    def test_the_outcome_is_explained_and_can_be_challenged(self):
        request = make_request()
        intake.classify(request.name, MAJOR_ANSWERS)
        explanation = intake.explain(request.name)
        self.assertTrue(explanation["classified"])
        self.assertEqual(explanation["matched_rule_code"], "R10")
        self.assertIn("major change", explanation["outcome_rationale"])

        intake.challenge(request.name, "The change is local to one unit.")
        request.reload()
        self.assertEqual(request.classification_challenge, "The change is local to one unit.")
        self.assertEqual(request.challenged_by, "Administrator")
        # A challenge is recorded; it does not move the outcome.
        self.assertEqual(intake.explain(request.name)["effective_outcome"], "Major")

    def test_an_empty_challenge_is_refused(self):
        request = make_request()
        intake.classify(request.name, MAJOR_ANSWERS)
        with self.assertRaises(frappe.ValidationError):
            intake.challenge(request.name, "   ")

    def test_an_override_is_recorded_without_erasing_the_original(self):
        request = make_request()
        assessment = intake.classify(request.name, MAJOR_ANSWERS)
        intake.override(request.name, "Minor", "The policy office reclassified it after review.")
        assessment.reload()
        self.assertEqual(assessment.outcome, "Major")
        self.assertEqual(assessment.override_outcome, "Minor")
        request.reload()
        self.assertEqual(request.change_classification, "Minor")

    # ------------------------------------------------- the version property

    def test_a_classification_does_not_change_when_the_rules_are_later_edited(self):
        request = make_request()
        assessment = intake.classify(request.name, MINOR_ANSWERS)
        original_outcome = assessment.outcome
        original_rule = assessment.matched_rule_code
        original_version = assessment.rule_set_version_label
        original_trace = as_dict(assessment.evaluation_trace)

        # The administrator now decides the same answers mean Major. Because the
        # rule set has classified something it is sealed, so the change is a new
        # version rather than an edit in place.
        old = frappe.get_doc("Classification Rule Set", assessment.rule_set)
        self.assertTrue(int(old.is_sealed or 0), "a rule set that has classified is sealed")
        frappe.db.set_value("Classification Rule Set", old.name, "is_active", 0)

        new = frappe.copy_doc(old)
        new.version_label = "2.0"
        new.is_sealed = 0
        new.is_active = 1
        new.effective_from = frappe.utils.nowdate()
        for rule in new.rules:
            rule.outcome = "Major"
        new.insert(ignore_permissions=True)

        assessment.reload()
        self.assertEqual(assessment.outcome, original_outcome)
        self.assertEqual(assessment.matched_rule_code, original_rule)
        self.assertEqual(assessment.rule_set_version_label, original_version)
        self.assertEqual(as_dict(assessment.evaluation_trace), original_trace)

        # And a request classified today, under the new rules, gets the new answer.
        later = make_request()
        later_assessment = intake.classify(later.name, MINOR_ANSWERS)
        self.assertEqual(later_assessment.rule_set_version_label, "2.0")
        self.assertEqual(later_assessment.outcome, "Major")


class TestClassificationDrivesRoutingAndService(PolicyTestCase):
    def _document_for(self, answers):
        request = make_request()
        intake.classify(request.name, answers)
        document = make_document()
        frappe.db.set_value(REQUEST, request.name, "created_document", document.name)
        return document, request

    def test_a_major_classification_selects_the_major_route(self):
        document, _request = self._document_for(MAJOR_ANSWERS)
        preview = routing.preview(document.name)
        self.assertEqual(preview["change_classification"], "Major")
        self.assertEqual(preview["route"], "Major Change Route")
        self.assertEqual(len(preview["steps"]), 3)

    def test_a_minor_classification_selects_the_minor_route(self):
        document, _request = self._document_for(MINOR_ANSWERS)
        preview = routing.preview(document.name)
        self.assertEqual(preview["change_classification"], "Minor")
        self.assertEqual(preview["route"], "Minor Change Route")
        self.assertEqual(len(preview["steps"]), 1)

    def test_an_override_reroutes_the_document(self):
        document, request = self._document_for(MAJOR_ANSWERS)
        self.assertEqual(routing.preview(document.name)["route"], "Major Change Route")
        intake.override(request.name, "Minor", "Reclassified after review.")
        self.assertEqual(routing.preview(document.name)["route"], "Minor Change Route")

    def test_classification_starts_the_matching_service_level_clock(self):
        request = make_request()
        intake.classify(request.name, MAJOR_ANSWERS)
        request.reload()
        self.assertTrue(request.sla_clock)
        clock = frappe.get_doc("SLA Clock", request.sla_clock)
        self.assertEqual(clock.sla_definition, "POL-INTAKE-MAJOR")

    def test_a_minor_classification_gets_the_longer_service_level(self):
        request = make_request()
        intake.classify(request.name, MINOR_ANSWERS)
        request.reload()
        clock = frappe.get_doc("SLA Clock", request.sla_clock)
        self.assertEqual(clock.sla_definition, "POL-INTAKE-MINOR")
