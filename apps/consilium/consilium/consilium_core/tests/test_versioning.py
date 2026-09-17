"""Version chain and revert.

The property under test is the one the model insists on: a revert writes a new
version and never touches history.
"""

import frappe

from consilium.consilium_core import versioning
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, refusals_for
from consilium.consilium_core.versioning import as_dict


class TestVersioning(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article(title="First Title")
        self.v1 = versioning.create_version(self.article, change_summary="Initial version", body_text="one")
        self.article.title = "Second Title"
        self.article.save(ignore_permissions=True)
        self.v2 = versioning.create_version(self.article, change_summary="Retitled", body_text="two")
        self.purge_on_teardown("Guide Article", self.article.name)

    def test_chain_is_numbered_and_linked(self):
        self.assertEqual(self.v1.version_number, 1)
        self.assertEqual(self.v2.version_number, 2)
        self.v1.reload()
        self.assertEqual(self.v1.superseded_by, self.v2.name)
        self.assertFalse(self.v1.is_current)
        self.assertTrue(self.v2.is_current)
        self.assertEqual(self.v2.created_from_version, self.v1.name)

    def test_snapshot_holds_the_field_state(self):
        snapshot = as_dict(self.v1.metadata_snapshot)
        self.assertEqual(snapshot["title"], "First Title")

    def test_revert_writes_a_new_version_and_keeps_history(self):
        log = versioning.revert_to_version(
            "Guide Article", self.article.name, self.v1.name, "Restoring the approved wording."
        )

        resulting = frappe.get_doc("Document Version", log.resulting_version)
        self.assertEqual(resulting.version_number, 3)
        self.assertEqual(resulting.origin, "Reverted")
        self.assertNotEqual(resulting.name, self.v1.name)
        self.assertTrue(resulting.is_current)

        # History survives, unchanged, and still says what it said.
        self.assertTrue(frappe.db.exists("Document Version", self.v1.name))
        self.assertTrue(frappe.db.exists("Document Version", self.v2.name))
        self.v1.reload()
        self.assertEqual(as_dict(self.v1.metadata_snapshot)["title"], "First Title")
        self.assertEqual(self.v1.version_number, 1)
        self.assertEqual(
            [v["version_number"] for v in versioning.version_history("Guide Article", self.article.name)],
            [1, 2, 3],
        )

        # The revert is itself auditable.
        self.assertEqual(log.from_version, self.v2.name)
        self.assertEqual(log.target_version, self.v1.name)
        self.assertEqual(log.reverted_by, frappe.session.user)
        self.assertTrue(log.reverted_on)
        self.assertIn("approved wording", log.justification)

        # And the subject itself carries the restored content.
        self.article.reload()
        self.assertEqual(self.article.title, "First Title")

    def test_revert_without_a_reason_is_refused_and_audited(self):
        with self.assertRaises(frappe.ValidationError):
            versioning.revert_to_version("Guide Article", self.article.name, self.v1.name, "   ")

        refusals = refusals_for("Guide Article", self.article.name)
        self.assertTrue(refusals)
        self.assertEqual(refusals[-1]["attempted_action"], "Revert")
        self.assertIn("mandatory reason", refusals[-1]["refusal_reason"])

    def test_a_version_row_cannot_be_edited(self):
        self.v1.reload()
        self.v1.change_summary = "Rewriting history"
        with self.assertRaises(frappe.PermissionError):
            self.v1.save(ignore_permissions=True)

    def test_a_version_row_cannot_be_deleted(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Document Version", self.v1.name, ignore_permissions=True, force=True)
        self.assertTrue(frappe.db.exists("Document Version", self.v1.name))

    def test_revert_to_the_current_version_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            versioning.revert_to_version(
                "Guide Article", self.article.name, self.v2.name, "Already current."
            )

    def test_revert_to_a_foreign_version_is_rejected(self):
        other = make_guide_article()
        other_v1 = versioning.create_version(other, change_summary="Other record")
        with self.assertRaises(frappe.ValidationError):
            versioning.revert_to_version(
                "Guide Article", self.article.name, other_v1.name, "Wrong subject."
            )

    def test_two_current_versions_are_refused(self):
        stray = frappe.get_doc(
            {
                "doctype": "Document Version",
                "subject_doctype": "Guide Article",
                "subject_name": self.article.name,
                "version_number": 99,
                "metadata_snapshot": "{}",
                "change_summary": "Second current version",
                "origin": "Authored",
                "is_current": 1,
            }
        )
        with self.assertRaises(frappe.ValidationError):
            stray.insert(ignore_permissions=True)
