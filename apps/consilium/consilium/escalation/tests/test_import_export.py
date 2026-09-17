"""The file import path that replaces the integrations (D-18, E21, E17-S5 export).

Integrations are out of scope, so a matter that originates elsewhere arrives as
a file through Core's governed pipeline. Nothing here reads a feed: the batch
holds the file and its hash, the rows hold both payloads, and the foreign
identifier survives as an External Reference.
"""

from __future__ import annotations

import frappe
from frappe.utils import now

from consilium.consilium_core import importing
from consilium.escalation import importing as escalation_importing
from consilium.escalation.setup import install
from consilium.escalation.tests.utils import EscalationTestCase


class TestImportPath(EscalationTestCase):
    def setUp(self):
        super().setUp()
        self.profile = install.ensure_import_profile()
        self.reference = self.reference_data()

    def batch(self):
        return frappe.get_doc(
            {
                "doctype": "Import Batch",
                "batch_reference": f"ESC-{frappe.generate_hash(length=6)}",
                "source_system": install.IMPORT_SYSTEM,
                "import_profile": self.profile,
                "target_doctype": "Escalation Matter",
                "received_on": now(),
                "status": "Uploaded",
            }
        ).insert(ignore_permissions=True)

    def row(self, **overrides):
        values = {
            "external_id": f"EXT-{frappe.generate_hash(length=6)}",
            "escalation_title": "A matter raised in the issue system",
            "escalation_type": frappe.db.get_value(
                "Escalation Type", self.reference["escalation_type"], "escalation_type_code"
            ),
            "identification_date": "2026-01-05",
            "escalation_date": "2026-01-08",
            "description": "Raised elsewhere and brought in as a file.",
            "tier_1_risk_type": frappe.db.get_value(
                "Risk Type", self.reference["risk_type"], "risk_type_code"
            ),
            "identified_by": self.reference["user"],
            "organizational_level": frappe.db.get_value(
                "Organizational Level",
                self.reference["organizational_level"],
                "organizational_level_code",
            ),
            "accountable_executive": self.reference["user"],
            "escalation_trigger": "A repeat finding.",
            "severity": "Medium",
            "impacted_entity_type": "Legal Entity",
            "impacted_entity": self.reference["legal_entity"],
        }
        values.update(overrides)
        return values

    def test_a_file_of_matters_validates_and_commits(self):
        batch = self.batch()
        rows = [self.row()]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["valid"], 1)
        self.assertEqual(report["errors"], 0)

        outcome = escalation_importing.commit(batch)
        self.assertEqual(len(outcome["committed"]), 1)

        matter_name = frappe.db.get_value(
            "Import Row", outcome["committed"][0], "target_name"
        )
        matter = frappe.get_doc("Escalation Matter", matter_name)
        self.assertEqual(matter.escalation_title, "A matter raised in the issue system")
        self.assertNotEqual(str(matter.escalation_identification_date), str(matter.escalation_date))

        reference = frappe.db.get_value(
            "External Reference",
            {"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            ["external_system", "source_import_batch"],
            as_dict=True,
        )
        self.assertEqual(reference.external_system, install.IMPORT_SYSTEM)
        self.assertEqual(reference.source_import_batch, batch.name)

    def test_a_row_missing_a_required_value_is_reported_and_not_written(self):
        batch = self.batch()
        rows = [self.row(escalation_title="")]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["errors"], 1)

        before = frappe.db.count("Escalation Matter")
        # Core rejects a batch in which no row is usable, and a rejected batch
        # cannot be committed at all: no partial application of a failed file.
        with self.assertRaises(frappe.ValidationError):
            escalation_importing.commit(batch)
        self.assertEqual(frappe.db.count("Escalation Matter"), before)

    def test_an_unknown_taxonomy_value_is_rejected_row_by_row(self):
        batch = self.batch()
        rows = [self.row(), self.row(tier_1_risk_type="NO-SUCH-CODE")]
        report = importing.validate_batch(batch, rows)
        self.assertEqual(report["valid"], 1)
        self.assertEqual(report["errors"], 1)

        outcome = escalation_importing.commit(batch)
        self.assertEqual(len(outcome["committed"]), 1)
        self.assertEqual(len(outcome["skipped"]), 1)

    def test_records_can_be_extracted_as_a_file(self):
        matter = self.make_matter(self.reference)
        batch, content = importing.export_records(
            export_profile="Escalation extract",
            target_system=install.IMPORT_SYSTEM,
            source_doctype="Escalation Matter",
            fields=["name", "escalation_title", "severity", "status"],
            filters={"name": matter.name},
        )
        self.assertEqual(batch.record_count, 1)
        self.assertIn(matter.escalation_title, content)
