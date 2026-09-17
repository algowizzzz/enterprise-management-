"""Every Escalation entity: create, read, update, permissions, validation."""

from __future__ import annotations

import json

import frappe

from consilium.escalation.tests.utils import EscalationTestCase, make_user, unique

STANDALONE = [
    "Escalation Matrix",
    "Escalation Template",
    "Escalation Matter",
    "Action Plan",
    "Risk Acceptance",
    "Escalation Closure",
    "Periodic Submission",
]

CHILD = [
    "Escalation Matrix Rule",
    "Escalation Matrix Route",
    "Escalation Matrix Notification",
    "Escalation Template Field",
    "Escalation Forum Link",
    "Escalation Impacted Entity",
    "Escalation Review",
    "Closure Criterion",
    "Escalation Forum Reference",
    "Escalation Risk Type Reference",
    "Escalation Legal Entity Reference",
]


class TestModuleShape(EscalationTestCase):
    def test_every_entity_belongs_to_the_module(self):
        for doctype in STANDALONE + CHILD:
            with self.subTest(doctype=doctype):
                self.assertEqual(frappe.db.get_value("DocType", doctype, "module"), "Escalation")

    def test_every_standalone_entity_has_permission_rows(self):
        for doctype in STANDALONE:
            with self.subTest(doctype=doctype):
                roles = frappe.get_all("DocPerm", filters={"parent": doctype}, pluck="role")
                self.assertIn("System Manager", roles)
                self.assertIn("Consilium Audit", roles)

    def test_every_entity_tracks_changes(self):
        for doctype in STANDALONE:
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.db.get_value("DocType", doctype, "track_changes"))


class TestEscalationMatter(EscalationTestCase):
    def test_create_read_update(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)

        self.assertTrue(matter.name.startswith("ESC-"))
        self.assertEqual(matter.escalation_id, matter.name)
        self.assertTrue(matter.is_open, msg="a new matter is open")
        self.assertTrue(matter.opened_on)

        read_back = frappe.get_doc("Escalation Matter", matter.name)
        self.assertEqual(read_back.escalation_title, "A matter requiring a decision")
        self.assertEqual(len(read_back.impacted_entities), 1)
        self.assertEqual(read_back.impacted_entities[0].entity_doctype, "Legal Entity")

        read_back.escalation_title = "A renamed matter"
        read_back.save(ignore_permissions=True)
        self.assertEqual(
            frappe.db.get_value("Escalation Matter", matter.name, "escalation_title"), "A renamed matter"
        )

    def test_identification_and_escalation_dates_are_separate_fields(self):
        reference = self.reference_data()
        matter = self.make_matter(
            reference, escalation_identification_date="2026-01-05", escalation_date="2026-01-09"
        )
        self.assertNotEqual(str(matter.escalation_identification_date), str(matter.escalation_date))

        matter.escalation_date = "2026-01-01"
        with self.assertRaises(frappe.ValidationError):
            matter.save(ignore_permissions=True)

    def test_forums_and_impacted_entities_are_plural(self):
        reference = self.reference_data()
        second_forum = self.reference_data()["forum"]
        matter = self.make_matter(
            reference,
            governance_forums=[
                {"governance_forum": reference["forum"], "role_in_escalation": "Decision"},
                {"governance_forum": second_forum, "role_in_escalation": "Oversight"},
            ],
            impacted_entities=[
                {"entity_type": "Legal Entity", "entity_value": reference["legal_entity"]},
                {"entity_type": "Business Unit", "entity_value": self.an_org_unit()},
            ],
        )
        self.assertEqual(len(matter.governance_forums), 2)
        self.assertEqual(len(matter.impacted_entities), 2)

    def an_org_unit(self) -> str:
        return frappe.get_doc(
            {
                "doctype": "Organization Unit",
                "org_unit_code": unique("OU").upper(),
                "org_unit_name": "A business unit",
                "unit_level": "Business Unit",
            }
        ).insert(ignore_permissions=True).name

    def test_a_matter_needs_its_mandatory_fields(self):
        reference = self.reference_data()
        values = self.matter_values(reference)
        values.pop("escalation_trigger")
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(values).insert(ignore_permissions=True)

    def test_an_unknown_impacted_entity_kind_is_refused(self):
        reference = self.reference_data()
        values = self.matter_values(reference)
        values["impacted_entities"] = [{"entity_type": "Spaceship", "entity_value": "X"}]
        with self.assertRaises(Exception):
            frappe.get_doc(values).insert(ignore_permissions=True)

    def test_permissions(self):
        owner = make_user("Escalation Owner")
        reviewer = make_user("Escalation Reviewer")
        auditor = make_user("Consilium Audit")
        nobody = make_user()

        self.assertTrue(frappe.has_permission("Escalation Matter", "create", user=owner))
        self.assertTrue(frappe.has_permission("Escalation Matter", "write", user=owner))
        self.assertFalse(frappe.has_permission("Escalation Matter", "delete", user=owner))

        self.assertFalse(frappe.has_permission("Escalation Matter", "create", user=reviewer))
        self.assertTrue(frappe.has_permission("Escalation Matter", "write", user=reviewer))

        self.assertTrue(frappe.has_permission("Escalation Matter", "read", user=auditor))
        self.assertFalse(frappe.has_permission("Escalation Matter", "write", user=auditor))

        self.assertFalse(frappe.has_permission("Escalation Matter", "read", user=nobody))

    def test_a_role_without_the_right_cannot_write_the_matrix(self):
        """The matrix is configuration; an escalation owner may read it, not change it."""
        owner = make_user("Escalation Owner")
        reviewer = make_user("Escalation Reviewer")
        self.assertTrue(frappe.has_permission("Escalation Matrix", "read", user=owner))
        self.assertFalse(frappe.has_permission("Escalation Matrix", "write", user=owner))
        self.assertFalse(frappe.has_permission("Escalation Matrix", "create", user=owner))
        self.assertFalse(frappe.has_permission("Escalation Matrix", "write", user=reviewer))

    def test_creating_a_matter_as_a_role_without_create_is_refused(self):
        reference = self.reference_data()
        reviewer = make_user("Escalation Reviewer")
        values = self.matter_values(reference)
        frappe.set_user(reviewer)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(values).insert()
        finally:
            frappe.set_user("Administrator")


class TestActionPlan(EscalationTestCase):
    def test_several_plans_per_matter_with_their_own_dates_and_owners(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        second_owner = make_user("Escalation Owner")

        first = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": matter.name,
                "action_plan_name": "Rebuild the control",
                "start_date": "2026-01-10",
                "end_date": "2026-03-31",
                "accountable_executive": reference["user"],
                "owner_user": reference["user"],
                "status": "Open",
            }
        ).insert(ignore_permissions=True)
        second = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": matter.name,
                "action_plan_name": "Retrain the team",
                "start_date": "2026-02-01",
                "end_date": "2026-04-30",
                "accountable_executive": reference["user"],
                "owner_user": second_owner,
                "status": "Open",
            }
        ).insert(ignore_permissions=True)

        plans = frappe.get_all("Action Plan", filters={"escalation_matter": matter.name}, pluck="name")
        self.assertEqual(sorted(plans), sorted([first.name, second.name]))
        self.assertTrue(first.is_open)

        first.status = "Completed"
        first.save(ignore_permissions=True)
        self.assertFalse(first.is_open)
        self.assertTrue(first.completed_on, msg="a completed plan is stamped")

    def test_a_plan_cannot_end_before_it_starts(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Action Plan",
                    "escalation_matter": matter.name,
                    "action_plan_name": "Backwards",
                    "start_date": "2026-03-01",
                    "end_date": "2026-02-01",
                    "accountable_executive": reference["user"],
                    "owner_user": reference["user"],
                }
            ).insert(ignore_permissions=True)


class TestPeriodicSubmission(EscalationTestCase):
    def test_a_period_with_no_matters_must_be_a_nil_return(self):
        submission = frappe.get_doc(
            {
                "doctype": "Periodic Submission",
                "period_label": "2026-Q1",
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
                "scope_filter": json.dumps({"severity": "High"}),
            }
        ).insert(ignore_permissions=True)
        self.assertEqual(submission.matter_count, 0)

        submission.status = "Submitted"
        with self.assertRaises(frappe.ValidationError):
            submission.save(ignore_permissions=True)

        submission.reload()
        submission.status = "Submitted"
        submission.nil_return = 1
        submission.save(ignore_permissions=True)
        self.assertFalse(submission.is_open)
        self.assertTrue(submission.submitted_on)
