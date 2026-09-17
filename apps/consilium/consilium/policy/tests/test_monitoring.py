"""E15 — monitoring, violations, the glossary and the maintenance view."""

from __future__ import annotations

import json

import frappe
from frappe.utils import nowdate

from consilium.consilium_core import versioning
from consilium.policy import glossary, metadata
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_document_type,
    make_user,
    unique,
)

DOCTYPE = "Governing Document"


def make_activity(doc, **values):
    defaults = {
        "doctype": "Monitoring Activity",
        "document": doc.name,
        "activity_title": "Quarterly control test",
        "frequency": "Quarterly",
        "responsible": doc.document_owner,
        "next_due_on": nowdate(),
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class TestMonitoring(PolicyTestCase):
    def test_an_activity_and_its_result_record_outcome_and_evidence(self):
        doc = make_document()
        activity = make_activity(doc)
        result = frappe.get_doc(
            {
                "doctype": "Monitoring Result",
                "monitoring_activity": activity.name,
                "period_label": "2026 Q1",
                "performed_by": doc.document_owner,
                "performed_on": "2026-03-31",
                "outcome": "Partially Effective",
                "findings": "Two of forty samples were not evidenced.",
            }
        ).insert(ignore_permissions=True)
        result.reload()
        self.assertEqual(result.document, doc.name)
        self.assertEqual(result.outcome, "Partially Effective")

    def test_a_performed_activity_without_findings_or_evidence_is_refused(self):
        doc = make_document()
        activity = make_activity(doc)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Monitoring Result",
                    "monitoring_activity": activity.name,
                    "period_label": "2026 Q1",
                    "performed_by": doc.document_owner,
                    "performed_on": "2026-03-31",
                    "outcome": "Effective",
                }
            ).insert(ignore_permissions=True)

    def test_recording_a_result_advances_the_activity(self):
        doc = make_document()
        activity = make_activity(doc, next_due_on="2026-03-31")
        frappe.get_doc(
            {
                "doctype": "Monitoring Result",
                "monitoring_activity": activity.name,
                "period_label": "2026 Q1",
                "performed_by": doc.document_owner,
                "performed_on": "2026-03-31",
                "outcome": "Effective",
                "findings": "No exceptions.",
            }
        ).insert(ignore_permissions=True)
        activity.reload()
        self.assertEqual(str(activity.next_due_on), "2026-06-30")

    def test_a_reviewer_cannot_create_a_monitoring_activity(self):
        doc = make_document()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": "Monitoring Activity",
                    "document": doc.name,
                    "activity_title": "Unauthorised",
                    "frequency": "Annual",
                    "responsible": reviewer,
                }
            ).insert()


class TestViolations(PolicyTestCase):
    def _violation(self, doc, **values):
        defaults = {
            "doctype": "Policy Violation",
            "document": doc.name,
            "violation_type": "Control",
            "severity": "High",
            "identified_on": nowdate(),
            "description": "The approval threshold was exceeded without sign-off.",
            "responsible_party": doc.document_owner,
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_violation_is_open_until_it_is_resolved(self):
        doc = make_document()
        violation = self._violation(doc)
        self.assertTrue(int(violation.is_open or 0))
        self.assertTrue(int(violation.requires_review or 0))

        violation.violation_status = "Resolved"
        violation.resolved_on = nowdate()
        violation.resolution_note = "Control redesigned and retested."
        violation.save(ignore_permissions=True)
        violation.reload()
        self.assertFalse(int(violation.is_open or 0))

    def test_a_violation_can_be_linked_to_a_monitoring_result(self):
        doc = make_document()
        activity = make_activity(doc)
        violation = self._violation(doc)
        result = frappe.get_doc(
            {
                "doctype": "Monitoring Result",
                "monitoring_activity": activity.name,
                "period_label": "2026 Q2",
                "performed_by": doc.document_owner,
                "performed_on": nowdate(),
                "outcome": "Not Effective",
                "findings": "The control failed.",
                "resulting_violation": violation.name,
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(result.resulting_violation, violation.name)

    def test_the_escalation_link_is_optional_and_does_not_require_that_module(self):
        doc = make_document()
        violation = self._violation(doc)
        self.assertFalse(violation.resulting_escalation)
        self.assertEqual(violation.escalation_doctype, "Escalation Matter")

    def test_a_violation_needs_a_description(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Policy Violation",
                    "document": doc.name,
                    "severity": "Low",
                    "identified_on": nowdate(),
                }
            ).insert(ignore_permissions=True)

    def test_a_reviewer_cannot_close_a_violation(self):
        doc = make_document()
        violation = self._violation(doc)
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer):
            fetched = frappe.get_doc("Policy Violation", violation.name)
            fetched.violation_status = "Dismissed"
            with self.assertRaises(frappe.PermissionError):
                fetched.save()


class TestGlossary(PolicyTestCase):
    def _term(self, **values):
        defaults = {
            "doctype": "Glossary Term",
            "term": unique("Term"),
            "definition": "The first definition.",
            "scope_level": "Enterprise",
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_proposed_term_is_not_yet_in_force(self):
        term = self._term()
        self.assertFalse(int(term.is_active or 0))

    def test_publishing_a_term_versions_it(self):
        term = self._term()
        glossary.publish(term.name, change_summary="Agreed at the policy forum.")
        term.reload()
        self.assertTrue(int(term.is_active or 0))
        self.assertTrue(term.current_version)
        self.assertEqual(term.version_label, "1")

    def test_a_change_writes_a_new_version_and_keeps_the_old_wording(self):
        term = self._term()
        glossary.publish(term.name, change_summary="First.")
        glossary.supersede(term.name, "The second definition.", change_summary="Clarified.")
        history = glossary.history(term.name)
        self.assertEqual(len(history), 2)
        first = frappe.get_doc("Document Version", history[0]["name"])
        self.assertEqual(first.body_text, "The first definition.")

    def test_a_revert_writes_a_new_version_rather_than_rewriting_one(self):
        term = self._term()
        glossary.publish(term.name, change_summary="First.")
        first_version = glossary.history(term.name)[0]["name"]
        glossary.supersede(term.name, "The second definition.", change_summary="Clarified.")

        glossary.revert(term.name, first_version, "The clarification was wrong.")
        history = glossary.history(term.name)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-1]["origin"], "Reverted")
        term.reload()
        self.assertEqual(term.definition, "The first definition.")

    def test_two_terms_cannot_be_in_force_at_the_same_scope(self):
        first = self._term(term="Material Entity")
        glossary.publish(first.name, change_summary="First.")
        second = self._term(term="Material Entity")
        with self.assertRaises(frappe.ValidationError):
            glossary.publish(second.name, change_summary="Second.")

    def test_a_scoped_term_must_name_its_document(self):
        with self.assertRaises(frappe.ValidationError):
            self._term(scope_level="Document")

    def test_definitions_are_surfaced_for_a_document(self):
        doc = make_document()
        enterprise = self._term(definition="An enterprise-wide meaning.")
        glossary.publish(enterprise.name, change_summary="Agreed.")
        specific = self._term(scope_level="Document", scope_document=doc.name,
                              definition="What it means here.")
        glossary.publish(specific.name, change_summary="Agreed.")
        proposed = self._term(definition="Not yet agreed.")

        doc.reload()
        doc.append("glossary_terms", {"glossary_term": specific.name,
                                      "context_note": "Used in section 3."})
        doc.save(ignore_permissions=True)

        names = {row["name"] for row in glossary.definitions_for(doc.name)}
        self.assertIn(enterprise.name, names)
        self.assertIn(specific.name, names)
        self.assertNotIn(proposed.name, names)

    def test_a_reviewer_cannot_publish_a_term(self):
        term = self._term()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            glossary.publish(term.name, change_summary="Sneaky.")


class TestMetadataMaintenance(PolicyTestCase):
    def test_the_maintenance_view_lists_records_with_missing_required_metadata(self):
        document_type = make_document_type()
        frappe.get_doc(
            {
                "doctype": "Document Template",
                "template_title": unique("Template"),
                "document_type": document_type,
                "action": "New",
                "required_fields": json.dumps(["effective_on", "document_sponsor"]),
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

        doc = make_document(document_type=document_type)
        missing = metadata.missing_fields(doc)
        self.assertIn("effective_on", missing)
        self.assertIn("document_sponsor", missing)

        listed = {row["name"] for row in metadata.incomplete_records(DOCTYPE)}
        self.assertIn(doc.name, listed)

    def test_a_complete_record_is_not_listed(self):
        doc = make_document()
        self.assertEqual(metadata.missing_fields(doc), [])

    def test_a_record_can_be_corrected_in_place(self):
        document_type = make_document_type()
        frappe.get_doc(
            {
                "doctype": "Document Template",
                "template_title": unique("Template"),
                "document_type": document_type,
                "action": "New",
                "required_fields": json.dumps(["effective_on"]),
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        doc = make_document(document_type=document_type)
        metadata.sweep(DOCTYPE)

        result = metadata.correct(DOCTYPE, doc.name, {"effective_on": "2026-01-01"})
        self.assertEqual(result["missing"], [])
        self.assertEqual(len(result["tasks_resolved"]), 1)
        task = frappe.get_doc("Metadata Remediation Task", result["tasks_resolved"][0])
        self.assertFalse(int(task.is_open or 0))

    def test_correcting_a_field_the_doctype_does_not_have_is_refused(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            metadata.correct(DOCTYPE, doc.name, {"invented_field": "x"})

    def test_a_reviewer_cannot_correct_a_record(self):
        doc = make_document()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            metadata.correct(DOCTYPE, doc.name, {"document_abstract": "edited"})

    def test_a_parent_leaving_force_raises_a_task_on_its_children(self):
        parent = make_document()
        child = make_document(parent_document=parent.name)

        frappe.db.set_value(DOCTYPE, parent.name, "is_active", 1)
        parent.reload()
        raised = metadata.raise_tasks_for_deactivated_parent(parent)
        self.assertEqual(len(raised), 1)

        task = frappe.get_doc("Metadata Remediation Task", raised[0])
        self.assertEqual(task.subject_name, child.name)
        self.assertEqual(task.invalid_fieldname, "parent_document")
        self.assertEqual(task.trigger_event, "Parent Retired")
        self.assertEqual(task.assigned_to, child.document_owner)
        self.assertTrue(int(task.is_open or 0))

    def test_a_duplicate_open_task_is_not_raised_twice(self):
        parent = make_document()
        make_document(parent_document=parent.name)
        first = metadata.raise_tasks_for_deactivated_parent(parent)
        second = metadata.raise_tasks_for_deactivated_parent(parent)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
