"""Create, read, update, permission and validation cover for the remaining entities.

The entities exercised in depth elsewhere — the document, the intake request, the
scan, the glossary — are not repeated here. This file covers the rest, so every
Policy entity has create/read/update/permission/validation cover somewhere.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, nowdate

from consilium.policy import applicability
from consilium.policy.doctype.applicability_exemption.applicability_exemption import lapse_expired
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_document_type,
    make_user,
    make_user_group,
    unique,
)

DOCTYPE = "Governing Document"


class TestDocumentTemplate(PolicyTestCase):
    def _template(self, **values):
        defaults = {
            "doctype": "Document Template",
            "template_title": unique("Template"),
            "document_type": make_document_type(),
            "action": "New",
            "required_fields": json.dumps(["effective_on"]),
            "naming_convention_pattern": "POL-{unit}-{sequence}",
            "sections": [
                {"section_title": "Purpose", "sequence": 1, "is_mandatory": 1},
                {"section_title": "Scope", "sequence": 2, "is_mandatory": 1},
                {"section_title": "Appendix", "sequence": 3, "is_mandatory": 0},
            ],
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_template_carries_its_sections_and_required_fields(self):
        template = self._template()
        template.reload()
        self.assertEqual(len(template.sections), 3)
        required = template.required_fields
        if isinstance(required, str):
            required = json.loads(required)
        self.assertEqual(required, ["effective_on"])

    def test_a_template_can_be_updated(self):
        template = self._template()
        template.append("sections", {"section_title": "Review", "sequence": 4, "is_mandatory": 1})
        template.save(ignore_permissions=True)
        template.reload()
        self.assertEqual(len(template.sections), 4)

    def test_a_template_needs_a_document_type(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Document Template", "template_title": unique("T"), "action": "New"}
            ).insert(ignore_permissions=True)

    def test_a_policy_owner_cannot_change_a_template(self):
        template = self._template()
        owner = make_user("Policy Owner")
        with as_user(owner):
            fetched = frappe.get_doc("Document Template", template.name)
            self.assertEqual(fetched.name, template.name)
            fetched.naming_convention_pattern = "whatever"
            with self.assertRaises(frappe.PermissionError):
                fetched.save()


class TestReviewCycle(PolicyTestCase):
    def _cycle(self, doc, **values):
        defaults = {
            "doctype": "Document Review Cycle",
            "document": doc.name,
            "cycle_year": "2026",
            "scheduled_start": nowdate(),
            "due_on": add_days(nowdate(), 60),
            "reviewer": doc.document_owner,
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_cycle_is_open_until_it_concludes(self):
        doc = make_document()
        cycle = self._cycle(doc)
        self.assertTrue(int(cycle.is_open or 0))

        cycle.cycle_status = "Concluded"
        cycle.outcome = "Minor Update"
        cycle.outcome_notes = "Two clauses reworded."
        cycle.save(ignore_permissions=True)
        cycle.reload()
        self.assertFalse(int(cycle.is_open or 0))

    def test_a_cycle_can_name_the_intake_request_it_produced(self):
        doc = make_document()
        request = frappe.get_doc(
            {
                "doctype": "Document Intake Request",
                "request_type": "Change",
                "subject_document": doc.name,
                "requester": doc.document_owner,
                "business_justification": "The review found a gap.",
            }
        ).insert(ignore_permissions=True)
        cycle = self._cycle(doc, resulting_intake_request=request.name)
        cycle.reload()
        self.assertEqual(cycle.resulting_intake_request, request.name)

    def test_a_cycle_needs_a_document(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Document Review Cycle", "cycle_year": "2026"}
            ).insert(ignore_permissions=True)

    def test_an_auditor_cannot_change_a_cycle(self):
        doc = make_document()
        cycle = self._cycle(doc)
        auditor = make_user("Consilium Audit")
        with as_user(auditor):
            fetched = frappe.get_doc("Document Review Cycle", cycle.name)
            fetched.outcome_notes = "Edited."
            with self.assertRaises(frappe.PermissionError):
                fetched.save()


class TestImplementationPlan(PolicyTestCase):
    def _plan(self, doc, **values):
        defaults = {
            "doctype": "Implementation Plan",
            "document": doc.name,
            "plan_title": "Rollout",
            "plan_owner": doc.document_owner,
            "impact_people": "Forty front-line staff need briefing.",
            "impact_process": "Two procedures change.",
            "impact_sizing": "Medium",
            "target_completion": add_days(nowdate(), 90),
            "tasks": [
                {"task_title": "Brief the teams", "assigned_to": doc.document_owner,
                 "due_on": add_days(nowdate(), 30)},
            ],
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_plan_carries_its_impact_assessment_and_tasks(self):
        doc = make_document()
        plan = self._plan(doc)
        plan.reload()
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.impact_sizing, "Medium")
        self.assertTrue(int(plan.is_open or 0))

    def test_working_groups_and_references_are_multi_valued(self):
        doc = make_document()
        group = make_user_group([make_user()])
        system = frappe.get_doc(
            {
                "doctype": "External System",
                "system_code": unique("SYS"),
                "title": "Process inventory",
            }
        ).insert(ignore_permissions=True)
        reference = frappe.get_doc(
            {
                "doctype": "External Reference",
                "subject_doctype": DOCTYPE,
                "subject_name": doc.name,
                "external_system": system.name,
                "external_key": unique("PROC"),
                "label": "Onboarding process",
            }
        ).insert(ignore_permissions=True)
        plan = self._plan(
            doc,
            working_groups=[{"user_group": group}],
            impacted_processes=[{"external_reference": reference.name}],
            impacted_controls=[{"external_reference": reference.name}],
        )
        plan.reload()
        self.assertEqual(len(plan.working_groups), 1)
        self.assertEqual(len(plan.impacted_processes), 1)
        self.assertEqual(len(plan.impacted_controls), 1)

    def test_a_plan_closes_when_it_concludes(self):
        doc = make_document()
        plan = self._plan(doc)
        plan.plan_status = "Concluded"
        plan.verified_by = doc.document_approver
        plan.verified_on = nowdate()
        plan.save(ignore_permissions=True)
        plan.reload()
        self.assertFalse(int(plan.is_open or 0))

    def test_a_plan_needs_an_owner(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Implementation Plan", "document": doc.name, "plan_title": "Nameless"}
            ).insert(ignore_permissions=True)

    def test_a_reviewer_cannot_create_a_plan(self):
        doc = make_document()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": "Implementation Plan",
                    "document": doc.name,
                    "plan_title": "Unauthorised",
                    "plan_owner": reviewer,
                    "impact_sizing": "Low",
                }
            ).insert()


class TestExemptionLifecycle(PolicyTestCase):
    def _exemption(self, doc, **values):
        defaults = {
            "doctype": "Applicability Exemption",
            "document": doc.name,
            "exemption_type": "Exemption",
            "scope_type": "Organization Unit",
            "scope_value": doc.owning_operating_group,
            "justification": "Covered by a stricter local standard.",
            "requested_by": doc.document_owner,
            "valid_from": add_days(nowdate(), -10),
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def test_a_requested_exemption_is_not_yet_in_force(self):
        doc = make_document()
        exemption = self._exemption(doc)
        self.assertFalse(int(exemption.is_active or 0))
        self.assertTrue(int(exemption.is_open or 0))
        self.assertEqual(applicability.active_exemptions(doc.name), [])

    def test_authorising_puts_it_in_force_and_names_the_authoriser(self):
        doc = make_document()
        exemption = self._exemption(doc)
        exemption.authorise(approved_by=doc.document_approver)
        exemption.reload()
        self.assertTrue(int(exemption.is_active or 0))
        self.assertEqual(exemption.approved_by, doc.document_approver)
        self.assertTrue(exemption.approved_on)

    def test_an_exemption_cannot_expire_before_it_begins(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            self._exemption(doc, valid_from=nowdate(), valid_to=add_days(nowdate(), -5))

    def test_an_expired_exemption_lapses_and_stops_excusing_the_scope(self):
        doc = make_document()
        exemption = self._exemption(doc, valid_to=add_days(nowdate(), 1))
        exemption.authorise(approved_by=doc.document_approver)
        self.assertEqual(len(applicability.active_exemptions(doc.name)), 1)

        frappe.db.set_value(
            "Applicability Exemption", exemption.name, "valid_to", add_days(nowdate(), -1)
        )
        lapsed = lapse_expired()
        self.assertIn(exemption.name, lapsed)
        exemption.reload()
        self.assertFalse(int(exemption.is_active or 0))
        self.assertEqual(applicability.active_exemptions(doc.name), [])

    def test_a_reviewer_cannot_authorise_an_exemption(self):
        doc = make_document()
        exemption = self._exemption(doc)
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Applicability Exemption", exemption.name).authorise()


class TestAccountabilityAndReferences(PolicyTestCase):
    def test_further_accountability_roles_are_many_per_document(self):
        doc = make_document()
        monitor, partner = make_user(), make_user()
        doc.append("accountability_roles", {"role": "MONITOR", "user": monitor, "is_primary": 1})
        doc.append("accountability_roles", {"role": "PARTNER", "user": partner})
        doc.save(ignore_permissions=True)
        doc.reload()
        self.assertEqual(len(doc.accountability_roles), 2)

    def test_regulatory_references_cite_the_shared_library(self):
        requirement = frappe.get_doc(
            {
                "doctype": "Regulatory Requirement",
                "regulatory_requirement_code": unique("REG"),
                "regulatory_requirement_name": "Operational resilience rule",
            }
        ).insert(ignore_permissions=True)
        doc = make_document(
            regulatory_required=1,
            regulatory_references=[
                {
                    "regulatory_requirement": requirement.name,
                    "citation": "s.12(3)",
                    "obligation_summary": "Maintain and test a resilience plan.",
                    "last_verified_on": nowdate(),
                }
            ],
        )
        doc.reload()
        self.assertEqual(doc.regulatory_references[0].regulatory_requirement, requirement.name)

    def test_organisational_and_risk_scope_are_multi_valued(self):
        unit = make_document().owning_operating_group
        doc = make_document(owning_business_units=[{"organization_unit": unit}])
        doc.reload()
        self.assertEqual(len(doc.owning_business_units), 1)


class TestMetadataRemediationTask(PolicyTestCase):
    def test_a_task_can_be_raised_read_updated_and_closed(self):
        doc = make_document()
        task = frappe.get_doc(
            {
                "doctype": "Metadata Remediation Task",
                "subject_doctype": DOCTYPE,
                "subject_name": doc.name,
                "invalid_fieldname": "document_sponsor",
                "trigger_event": "Owner Deactivated",
                "assigned_to": doc.document_owner,
                "due_on": add_days(nowdate(), 14),
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(int(task.is_open or 0))

        task.task_status = "Dismissed"
        task.resolution_note = "The field is not required for this document type."
        task.save(ignore_permissions=True)
        task.reload()
        self.assertFalse(int(task.is_open or 0))

    def test_a_task_needs_a_field(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Metadata Remediation Task",
                    "subject_doctype": DOCTYPE,
                    "subject_name": doc.name,
                    "trigger_event": "Parent Retired",
                }
            ).insert(ignore_permissions=True)

    def test_an_auditor_cannot_close_a_task(self):
        doc = make_document()
        task = frappe.get_doc(
            {
                "doctype": "Metadata Remediation Task",
                "subject_doctype": DOCTYPE,
                "subject_name": doc.name,
                "invalid_fieldname": "effective_on",
                "trigger_event": "Missing Required Metadata",
            }
        ).insert(ignore_permissions=True)
        auditor = make_user("Consilium Audit")
        with as_user(auditor):
            fetched = frappe.get_doc("Metadata Remediation Task", task.name)
            fetched.task_status = "Resolved"
            with self.assertRaises(frappe.PermissionError):
                fetched.save()
