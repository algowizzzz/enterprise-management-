"""Semantic state flags, and the check that keeps them the only branch point."""

import subprocess
import sys
import tempfile
from pathlib import Path

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import state_flags
from consilium.consilium_core.setup.state_flag_seed import STATE_FLAGS
from consilium.consilium_core.tests.utils import CoreTestCase, unique

APP_ROOT = Path(frappe.get_app_path("consilium")).parent
CHECKER = APP_ROOT / "scripts" / "check_state_flags.py"


class TestStateFlags(CoreTestCase):
    def test_every_seeded_state_is_configured(self):
        for doctype, state_field, state_value, *_ in STATE_FLAGS:
            self.assertIsNotNone(
                state_flags.flags_for(doctype, state_field, state_value),
                msg=f"{doctype}.{state_field} = {state_value} has no flag row",
            )

    def test_flags_follow_the_state_on_save(self):
        campaign = frappe.get_doc(
            {
                "doctype": "Attestation Campaign",
                "campaign_title": "Flag test",
                "campaign_type": "Forum Inventory",
                "period_label": unique("period"),
                "target_doctype": "Guide Article",
                "participant_source": "Record Field",
                "participant_field": "owner",
                "opens_on": nowdate(),
                "due_on": add_days(nowdate(), 10),
                "status": "Draft",
            }
        ).insert(ignore_permissions=True)
        self.assertFalse(campaign.is_open)
        self.assertTrue(campaign.is_editable)

        campaign.status = "Open"
        campaign.save(ignore_permissions=True)
        self.assertTrue(campaign.is_open)

        campaign.status = "Closed"
        campaign.save(ignore_permissions=True)
        self.assertFalse(campaign.is_open)
        self.assertFalse(campaign.is_editable)

    def test_an_unconfigured_state_is_refused_rather_than_guessed(self):
        flag = frappe.get_doc(
            {
                "doctype": "Workflow State Flag",
                "target_doctype": "Attestation Campaign",
                "state_field": "status",
                "state_value": "Open",
            }
        )
        # Deleting the mapping for a state must make that state unusable, not
        # silently leave the previous flags in place.
        existing = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": "Attestation Campaign", "state_field": "status", "state_value": "Open"},
            "name",
        )
        frappe.delete_doc("Workflow State Flag", existing, ignore_permissions=True, force=True)
        state_flags.clear_cache()

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Attestation Campaign",
                    "campaign_title": "Unmapped",
                    "campaign_type": "Forum Inventory",
                    "period_label": unique("period"),
                    "target_doctype": "Guide Article",
                    "participant_source": "Record Field",
                    "participant_field": "owner",
                    "opens_on": nowdate(),
                    "due_on": add_days(nowdate(), 10),
                    "status": "Open",
                }
            ).insert(ignore_permissions=True)
        del flag

    def test_a_state_cannot_be_mapped_twice(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Workflow State Flag",
                    "target_doctype": "Attestation Campaign",
                    "state_field": "status",
                    "state_value": "Draft",
                }
            ).insert(ignore_permissions=True)

    # ------------------------------------------------------------- the checker

    def test_the_checker_passes_on_the_app(self):
        result = subprocess.run(
            [sys.executable, str(CHECKER)], capture_output=True, text=True, cwd=str(APP_ROOT)
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_the_checker_catches_a_state_name_in_a_conditional(self):
        offending = (
            "def handle(doc):\n"
            "    if doc.status == 'Attested':\n"
            "        return 1\n"
            "    return 0\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offender.py"
            path.write_text(offending)
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path)],
                capture_output=True,
                text=True,
                cwd=str(APP_ROOT),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Attested", result.stderr)
        self.assertIn("comparison", result.stderr)

    def test_the_checker_allows_a_state_name_being_assigned(self):
        permitted = (
            "def close(doc):\n"
            "    doc.status = 'Attested'\n"
            "    doc.save()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "permitted.py"
            path.write_text(permitted)
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(path)],
                capture_output=True,
                text=True,
                cwd=str(APP_ROOT),
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
