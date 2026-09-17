"""Tests for Attestation Campaign."""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAttestationCampaign(FrappeTestCase):
    """The entity's own shape. Behaviour is covered in consilium_core/tests."""

    DOCTYPE = "Attestation Campaign"

    def test_the_entity_is_installed_with_its_table(self):
        self.assertTrue(frappe.db.exists("DocType", self.DOCTYPE))
        self.assertTrue(frappe.db.table_exists(self.DOCTYPE))

    def test_every_declared_field_reached_the_table(self):
        columns = set(frappe.db.get_table_columns(self.DOCTYPE))
        for field in frappe.get_meta(self.DOCTYPE).fields:
            if field.fieldtype in frappe.model.table_fields or field.fieldtype in frappe.model.no_value_fields:
                continue
            self.assertIn(field.fieldname, columns)

    def test_it_is_readable_by_someone(self):
        meta = frappe.get_meta(self.DOCTYPE)
        if meta.istable:
            self.assertFalse(meta.permissions)
        else:
            self.assertTrue(any(perm.read for perm in meta.permissions))
