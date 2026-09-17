"""The governed import pipeline and the external references it leaves behind."""

import json

import frappe
from frappe.utils import now

from consilium.consilium_core import importing
from consilium.consilium_core.tests.utils import CoreTestCase, unique


class TestImportPipeline(CoreTestCase):
    def setUp(self):
        self.system = frappe.get_doc(
            {
                "doctype": "External System",
                "system_code": unique("SYS"),
                "title": "Upstream register",
                "reference_url_pattern": "https://internal.invalid/record/{key}",
            }
        ).insert(ignore_permissions=True)
        self.profile = frappe.get_doc(
            {
                "doctype": "Import Profile",
                "profile_title": unique("profile"),
                "source_system": self.system.name,
                "target_doctype": "Risk Type",
                "key_strategy": "External Key",
                "external_key_column": "id",
                "on_missing_required": "Reject Row",
                "on_unknown_taxonomy": "Reject Row",
                "on_duplicate_key": "Update",
                "mappings": [
                    {"source_column": "code", "target_fieldname": "risk_type_code",
                     "transform": "Trim", "is_required": 1},
                    {"source_column": "name", "target_fieldname": "risk_type_name",
                     "transform": "Trim", "is_required": 1},
                    {"source_column": "tier", "target_fieldname": "tier", "transform": "None",
                     "is_required": 1},
                ],
            }
        ).insert(ignore_permissions=True)

    def _batch(self):
        return frappe.get_doc(
            {
                "doctype": "Import Batch",
                "batch_reference": unique("batch"),
                "source_system": self.system.name,
                "import_profile": self.profile.name,
                "target_doctype": self.profile.target_doctype,
                "received_on": now(),
                "status": "Uploaded",
            }
        ).insert(ignore_permissions=True)

    def test_a_clean_file_validates_and_commits(self):
        batch = self._batch()
        rows = [
            {"id": "X-1", "code": unique("RT").upper(), "name": "Operational risk", "tier": "1"},
            {"id": "X-2", "code": unique("RT").upper(), "name": "Technology risk", "tier": "1"},
        ]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report, {"valid": 2, "warnings": 0, "errors": 0})
        batch.reload()
        self.assertEqual(batch.status, "Validated")
        self.assertTrue(batch.is_editable)

        result = importing.commit_batch(batch)
        self.assertEqual(len(result["committed"]), 2)
        batch.reload()
        self.assertEqual(batch.status, "Committed")
        self.assertFalse(batch.is_editable)

        created = frappe.get_all("Import Row", filters={"import_batch": batch.name}, pluck="target_name")
        for name in created:
            self.assertTrue(frappe.db.exists("Risk Type", name))

        reference = frappe.get_all(
            "External Reference",
            filters={"external_system": self.system.name, "external_key": "X-1"},
            fields=["subject_doctype", "subject_name", "source_import_batch"],
        )
        self.assertEqual(len(reference), 1)
        self.assertEqual(reference[0]["subject_doctype"], "Risk Type")
        self.assertEqual(reference[0]["source_import_batch"], batch.name)

    def test_a_row_missing_a_required_value_is_held_back(self):
        batch = self._batch()
        rows = [
            {"id": "Y-1", "code": unique("RT").upper(), "name": "Complete", "tier": "1"},
            {"id": "Y-2", "code": "", "name": "Incomplete", "tier": "1"},
        ]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["errors"], 1)

        bad = frappe.get_doc(
            "Import Row", frappe.get_all("Import Row", filters={"import_batch": batch.name, "row_number": 2}, pluck="name")[0]
        )
        self.assertEqual(bad.status, "Error")
        self.assertFalse(bad.is_committable)
        self.assertIn("required value missing", json.dumps(bad.messages))

        result = importing.commit_batch(batch)
        self.assertEqual(len(result["committed"]), 1)
        self.assertEqual(len(result["skipped"]), 1)
        batch.reload()
        self.assertEqual(batch.status, "Partially Committed")

    def test_reject_batch_handling_rejects_the_whole_file(self):
        self.profile.db_set("on_missing_required", "Reject Batch")
        self.profile.reload()
        batch = self._batch()
        rows = [{"id": "Z-1", "code": "", "name": "Incomplete", "tier": "1"}]
        with self.assertRaises(importing.BatchRejected):
            importing.validate_batch(batch, rows)
        batch.reload()
        self.assertEqual(batch.status, "Rejected")

    def test_an_unknown_taxonomy_value_is_handled_as_configured(self):
        self.profile.append(
            "mappings",
            {
                "source_column": "parent",
                "target_fieldname": "parent_risk_type",
                "transform": "Lookup",
                "lookup_doctype": "Risk Type",
                "lookup_field": "risk_type_code",
            },
        )
        self.profile.save(ignore_permissions=True)

        batch = self._batch()
        rows = [{"id": "W-1", "code": unique("RT").upper(), "name": "Child", "tier": "2", "parent": "ABSENT"}]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["errors"], 1)

        self.profile.db_set("on_unknown_taxonomy", "Warn And Continue")
        self.profile.reload()
        batch = self._batch()
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["warnings"], 1)

    def test_a_second_import_of_the_same_key_updates_rather_than_duplicates(self):
        batch = self._batch()
        code = unique("RT").upper()
        importing.validate_batch(batch, [{"id": "U-1", "code": code, "name": "First name", "tier": "1"}])
        importing.commit_batch(batch)

        again = self._batch()
        importing.validate_batch(again, [{"id": "U-1", "code": code, "name": "Second name", "tier": "1"}])
        importing.commit_batch(again)

        self.assertEqual(frappe.db.count("Risk Type", {"risk_type_code": code}), 1)
        self.assertEqual(frappe.db.get_value("Risk Type", code, "risk_type_name"), "Second name")
        self.assertEqual(
            frappe.db.count("External Reference", {"external_system": self.system.name, "external_key": "U-1"}), 1
        )

    def test_skip_handling_leaves_the_existing_record_alone(self):
        batch = self._batch()
        code = unique("RT").upper()
        importing.validate_batch(batch, [{"id": "S-1", "code": code, "name": "Original", "tier": "1"}])
        importing.commit_batch(batch)

        self.profile.db_set("on_duplicate_key", "Skip")
        self.profile.reload()
        again = self._batch()
        importing.validate_batch(again, [{"id": "S-1", "code": code, "name": "Replacement", "tier": "1"}])
        result = importing.commit_batch(again)
        self.assertEqual(result["committed"], [])
        self.assertEqual(frappe.db.get_value("Risk Type", code, "risk_type_name"), "Original")

    def test_a_committed_batch_cannot_be_committed_again(self):
        batch = self._batch()
        importing.validate_batch(batch, [{"id": "C-1", "code": unique("RT").upper(), "name": "One", "tier": "1"}])
        importing.commit_batch(batch)
        batch.reload()
        with self.assertRaises(frappe.ValidationError):
            importing.commit_batch(batch)

    def test_a_mapping_onto_a_field_that_does_not_exist_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Import Profile",
                    "profile_title": unique("profile"),
                    "source_system": self.system.name,
                    "target_doctype": "Risk Type",
                    "key_strategy": "Always Insert",
                    "on_missing_required": "Reject Row",
                    "on_unknown_taxonomy": "Reject Row",
                    "on_duplicate_key": "Update",
                    "mappings": [
                        {"source_column": "x", "target_fieldname": "not_a_field", "transform": "None"}
                    ],
                }
            ).insert(ignore_permissions=True)

    def test_an_export_batch_records_what_left(self):
        batch, content = importing.export_records(
            export_profile="risk types",
            target_system=self.system.name,
            source_doctype="Governance Forum Role",
            fields=["name", "governance_forum_role_name"],
        )
        self.assertGreater(batch.record_count, 0)
        self.assertTrue(batch.output_sha256)
        self.assertIn("governance_forum_role_name", content.splitlines()[0])
