"""P-6, O-7: a change to a regulatory requirement reaches everyone who cites it."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import nowdate

from consilium.consilium_core import notification
from consilium.consilium_core.setup import notification_templates
from consilium.governance.tests.utils import GovernanceTestCase, make_forum
from consilium.governance.tests.utils import make_user as make_governance_user
from consilium.policy.tests.utils import make_document, unique

EVENT = "regulatory.requirement.changed"


def dispatches_on(doctype: str, name: str) -> list[dict]:
    """Regulatory-change notices only: saving a forum can raise other notices
    (a watched-field change), which are not what these tests are about."""
    return frappe.get_all(
        "Notification Dispatch",
        filters={"subject_doctype": doctype, "subject_name": name,
                 "rendered_subject": ["like", "Regulatory change%"]},
        fields=["recipient", "rendered_subject", "rendered_body"],
    )


class TestRegulatoryChangeFanOut(GovernanceTestCase):
    def setUp(self):
        self.addCleanup(frappe.db.rollback)
        super().setUp()
        notification_templates.seed_all()
        patcher = patch.object(notification, "email_configured", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

        code = unique("REQ").upper()
        self.requirement = frappe.get_doc(
            {
                "doctype": "Regulatory Requirement",
                "regulatory_requirement_code": code,
                "regulatory_requirement_name": "Operational resilience rule",
                "citation": "Rule 4.1",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

        self.document = make_document()
        self.document.append("regulatory_references", {"regulatory_requirement": self.requirement.name})
        self.document.save(ignore_permissions=True)

        self.forum_owner = make_governance_user()
        self.forum = make_forum(forum_owner=self.forum_owner)
        self.forum.append("regulatory_requirements", {"regulatory_requirement": self.requirement.name})
        self.forum.save(ignore_permissions=True)

    def change(self, **values):
        self.requirement.reload()
        self.requirement.update(values)
        self.requirement.save(ignore_permissions=True)

    def test_owners_of_citing_documents_and_forums_are_told_what_changed(self):
        self.change(citation="Rule 4.1 (as amended)")

        [on_document] = dispatches_on("Governing Document", self.document.name)
        self.assertEqual(on_document.recipient, self.document.document_owner)
        self.assertIn("Operational resilience rule", on_document.rendered_subject)
        self.assertIn("Rule 4.1 -> Rule 4.1 (as amended)", on_document.rendered_body)

        [on_forum] = dispatches_on("Governance Forum", self.forum.name)
        self.assertEqual(on_forum.recipient, self.forum_owner)

    def test_a_substantive_change_is_dated(self):
        self.change(summary="Now applies to third-party providers too.")
        self.assertEqual(str(frappe.db.get_value("Regulatory Requirement", self.requirement.name,
                                                 "last_change_on")), nowdate())

    def test_housekeeping_changes_tell_nobody(self):
        self.change(sort_order=7)
        self.assertEqual(dispatches_on("Governing Document", self.document.name), [])
        self.assertEqual(dispatches_on("Governance Forum", self.forum.name), [])

    def test_a_retired_document_is_not_told(self):
        frappe.db.set_value("Governing Document", self.document.name, "retired_on", nowdate())
        self.change(citation="Rule 4.2")
        self.assertEqual(dispatches_on("Governing Document", self.document.name), [])
        self.assertEqual(len(dispatches_on("Governance Forum", self.forum.name)), 1)

    def test_a_disbanded_forum_is_not_told(self):
        frappe.db.set_value("Governance Forum", self.forum.name, "is_active", 0)
        self.change(citation="Rule 4.2")
        self.assertEqual(dispatches_on("Governance Forum", self.forum.name), [])

    def test_a_notification_failure_does_not_undo_the_edit(self):
        with patch.object(notification, "notify", side_effect=RuntimeError("no channel")):
            self.change(citation="Rule 9")
        self.assertEqual(frappe.db.get_value("Regulatory Requirement", self.requirement.name, "citation"), "Rule 9")
