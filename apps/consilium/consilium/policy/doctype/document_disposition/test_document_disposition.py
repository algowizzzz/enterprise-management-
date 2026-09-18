"""Tests for Document Disposition.

The behaviour — when a disposition is written, what it says, who is told — is
tested with the lifecycle in ``consilium.policy.tests.test_wave3``. This file
pins only that the record cannot be changed once written.
"""

import frappe
from frappe.utils import now

from consilium.policy.tests.utils import PolicyTestCase, make_document


class TestDocumentDisposition(PolicyTestCase):
    def test_a_disposition_cannot_be_edited_after_it_is_written(self):
        doc = make_document()
        row = frappe.get_doc(
            {
                "doctype": "Document Disposition",
                "document": doc.name,
                "disposition_kind": "Review Returned",
                "decided_by": "Administrator",
                "decided_on": now(),
                "reason": "Section 3 contradicts the parent framework.",
            }
        ).insert(ignore_permissions=True)
        self.purge_on_teardown("Document Disposition", row.name)
        row.reason = "Rewritten afterwards."
        with self.assertRaises(frappe.PermissionError):
            row.save(ignore_permissions=True)
