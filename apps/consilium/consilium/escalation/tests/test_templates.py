"""Configurable templates per escalation type (E16-S1, E16-S2)."""

from __future__ import annotations

import frappe

from consilium.escalation import templates
from consilium.escalation.tests.utils import EscalationTestCase, make_user


class TestTemplates(EscalationTestCase):
    def test_three_templates_share_one_standard_field_set(self):
        for scope in (templates.SCOPE_ESCALATION, templates.SCOPE_ACTION_PLAN, templates.SCOPE_RISK_ACCEPTANCE):
            with self.subTest(scope=scope):
                meta = frappe.get_meta(templates.SCOPE_DOCTYPES[scope])
                for fieldname in templates.standard_fields(scope):
                    self.assertTrue(
                        meta.has_field(fieldname),
                        msg=f"{fieldname} is offered by the {scope} template but the record has no such field",
                    )

    def test_selecting_a_type_applies_its_template(self):
        reference = self.reference_data()
        template = self.make_template(
            reference, templates.SCOPE_ESCALATION, [{"fieldname": "response_owner", "is_required": 1}]
        )
        matter = self.make_matter(reference, response_owner=reference["user"])
        self.assertEqual(matter.escalation_template, template.name)

    def test_a_required_field_is_enforced(self):
        reference = self.reference_data()
        self.make_template(
            reference, templates.SCOPE_ESCALATION, [{"fieldname": "response_owner", "is_required": 1}]
        )
        with self.assertRaises(frappe.ValidationError):
            self.make_matter(reference)

    def test_a_requirement_can_start_at_a_severity(self):
        reference = self.reference_data()
        self.make_template(
            reference,
            templates.SCOPE_ESCALATION,
            [{"fieldname": "response_owner", "is_required": 1, "required_when_severity": "High"}],
        )
        # Medium: the requirement does not bite.
        self.make_matter(reference, severity="Medium")
        # High: it does.
        with self.assertRaises(frappe.ValidationError):
            self.make_matter(reference, severity="High")

    def test_action_plan_and_risk_acceptance_have_their_own_templates(self):
        reference = self.reference_data()
        self.make_template(
            reference, templates.SCOPE_ACTION_PLAN, [{"fieldname": "description", "is_required": 1}]
        )
        self.make_template(
            reference,
            templates.SCOPE_RISK_ACCEPTANCE,
            [{"fieldname": "next_reassessment_on", "is_required": 1}],
        )
        matter = self.make_matter(reference)

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Action Plan",
                    "escalation_matter": matter.name,
                    "action_plan_name": "No description",
                    "start_date": "2026-01-10",
                    "end_date": "2026-02-10",
                    "accountable_executive": reference["user"],
                    "owner_user": reference["user"],
                }
            ).insert(ignore_permissions=True)

        plan = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": matter.name,
                "action_plan_name": "With description",
                "description": "What will be done, and by when.",
                "start_date": "2026-01-10",
                "end_date": "2026-02-10",
                "accountable_executive": reference["user"],
                "owner_user": reference["user"],
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(plan.escalation_template)

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Risk Acceptance",
                    "escalation_matter": matter.name,
                    "risk_acceptance_name": "No reassessment date",
                    "start_date": "2026-01-10",
                    "end_date": "2026-12-31",
                    "accountable_executive": reference["user"],
                    "rationale": "The remediation costs more than the exposure.",
                }
            ).insert(ignore_permissions=True)

    def test_a_template_cannot_require_a_field_that_does_not_exist(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_template(
                reference, templates.SCOPE_ESCALATION, [{"fieldname": "favourite_colour", "is_required": 1}]
            )

    def test_a_template_cannot_require_a_field_of_another_scope(self):
        reference = self.reference_data()
        with self.assertRaises(frappe.ValidationError):
            self.make_template(
                reference, templates.SCOPE_ESCALATION, [{"fieldname": "owner_user", "is_required": 1}]
            )

    def test_templates_are_configuration_and_administrators_own_them(self):
        owner = make_user("Escalation Owner")
        admin = make_user("Consilium Administrator")
        self.assertTrue(frappe.has_permission("Escalation Template", "read", user=owner))
        self.assertFalse(frappe.has_permission("Escalation Template", "create", user=owner))
        self.assertTrue(frappe.has_permission("Escalation Template", "create", user=admin))
