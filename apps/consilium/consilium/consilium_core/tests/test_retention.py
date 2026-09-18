"""Retention, legal hold and disposal."""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import retention
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, refusals_for, unique


class TestRetention(CoreTestCase):
    def setUp(self):
        self.retained = make_guide_article(category="Policy Lifecycle")
        self.free = make_guide_article(category="Getting Started")
        self.retention_class = frappe.get_doc(
            {
                "doctype": "Retention Class",
                "class_code": unique("RC"),
                "title": "Seven year retention",
                "retention_period_months": 84,
                "trigger_event": "Creation",
                "disposition_action": "Review",
                "requires_worm": 1,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        self.assignment = frappe.get_doc(
            {
                "doctype": "Retention Assignment",
                "assignment_title": unique("assignment"),
                "target_doctype": "Guide Article",
                "record_filter": '{"category": "Policy Lifecycle"}',
                "retention_class": self.retention_class.name,
                "priority": 100,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        # Most tests here are refused on purpose, and refusals are committed on
        # their own connection; take them away with the records they name.
        self.purge_on_teardown("Guide Article", self.retained.name)
        self.purge_on_teardown("Guide Article", self.free.name)


    # ---------------------------------------------------------------- retention

    def test_a_retained_record_cannot_be_modified(self):
        self.retained.title = "Changed"
        with self.assertRaises(frappe.PermissionError):
            self.retained.save(ignore_permissions=True)

        refusals = refusals_for("Guide Article", self.retained.name)
        self.assertEqual(refusals[-1]["attempted_action"], "Modify")
        self.assertEqual(refusals[-1]["retention_class"], self.retention_class.name)
        self.assertIn("write-once", refusals[-1]["refusal_reason"])
        self.assertIn(self.retention_class.name, refusals[-1]["refusal_reason"])

    def test_a_retained_record_cannot_be_deleted(self):
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Guide Article", self.retained.name, ignore_permissions=True, force=True)
        self.assertTrue(frappe.db.exists("Guide Article", self.retained.name))
        self.assertEqual(refusals_for("Guide Article", self.retained.name)[-1]["attempted_action"], "Delete")

    def test_a_record_outside_the_assignment_is_untouched(self):
        self.free.title = "Changed freely"
        self.free.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value("Guide Article", self.free.name, "title"), "Changed freely")
        self.assertEqual(refusals_for("Guide Article", self.free.name), [])

    def test_a_class_without_worm_does_not_freeze_the_record(self):
        self.retention_class.db_set("requires_worm", 0)
        retention.clear_cache()
        self.assertIsNone(retention.retention_lock("Guide Article", self.retained.name))

    def test_the_most_specific_assignment_wins(self):
        other_class = frappe.get_doc(
            {
                "doctype": "Retention Class",
                "class_code": unique("RC"),
                "title": "Ten year retention",
                "retention_period_months": 120,
                "trigger_event": "Creation",
                "disposition_action": "Destroy",
                "requires_worm": 1,
            }
        ).insert(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "Retention Assignment",
                "assignment_title": unique("assignment"),
                "target_doctype": "Guide Article",
                "record_filter": '{"category": "Policy Lifecycle"}',
                "retention_class": other_class.name,
                "priority": 500,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()
        winner = retention.effective_retention("Guide Article", self.retained.name)
        self.assertEqual(winner["retention_class"], other_class.name)

    # -------------------------------------------------------------- legal hold

    def test_a_legal_hold_freezes_a_record_that_no_retention_class_covers(self):
        frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "description": "Investigation in progress.",
                "placed_on": nowdate(),
                "scope_doctype": "Guide Article",
                "scope_filter": '{"category": "Getting Started"}',
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()

        self.free.title = "Changed"
        with self.assertRaises(frappe.PermissionError):
            self.free.save(ignore_permissions=True)
        self.assertIn("legal hold", refusals_for("Guide Article", self.free.name)[-1]["refusal_reason"])

    def test_a_released_hold_is_not_active(self):
        hold = frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "placed_on": add_days(nowdate(), -10),
                "released_on": add_days(nowdate(), -1),
                "scope_doctype": "Guide Article",
            }
        ).insert(ignore_permissions=True)
        self.assertFalse(hold.is_active)
        self.assertIsNone(retention.active_legal_hold("Guide Article", self.free.name))

    def test_a_hold_released_before_it_was_placed_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Legal Hold",
                    "hold_reference": unique("HOLD"),
                    "placed_on": nowdate(),
                    "released_on": add_days(nowdate(), -5),
                    "scope_doctype": "Guide Article",
                }
            ).insert(ignore_permissions=True)

    # -------------------------------------------------------------- disposal

    def _archive(self, article):
        return frappe.get_doc(
            {
                "doctype": "Archive Record",
                "subject_doctype": "Guide Article",
                "subject_name": article.name,
                "archived_on": frappe.utils.now(),
                "retention_class": self.retention_class.name,
                "disposition_due_on": retention.disposition_due_date(
                    self.retention_class.name, "Guide Article", article.name
                ),
                "payload_sha256": "0" * 64,
            }
        ).insert(ignore_permissions=True)

    def test_an_archive_record_is_hash_chained_and_immutable(self):
        first = self._archive(self.retained)
        second = self._archive(self.free)
        self.assertTrue(first.chain_hash)
        self.assertEqual(second.previous_archive_hash, first.chain_hash)

        # Archive references restart from the same number after the rollback.
        self.purge_on_teardown("Archive Record", first.name)
        first.payload_sha256 = "1" * 64
        with self.assertRaises(frappe.PermissionError):
            first.save(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            frappe.delete_doc("Archive Record", first.name, ignore_permissions=True, force=True)

    def test_a_legal_hold_overrides_a_scheduled_disposal(self):
        archive = self._archive(self.free)
        frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "placed_on": nowdate(),
                "scope_doctype": "Guide Article",
                "scope_filter": '{"category": "Getting Started"}',
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()

        event_name = retention.schedule_disposition(archive.name)
        event = frappe.get_doc("Disposition Event", event_name)
        self.assertEqual(event.status, "Held")
        self.assertTrue(event.held_by_legal_hold)

        event.db_set("approved_by", frappe.session.user)
        with self.assertRaises(frappe.PermissionError):
            retention.execute_disposition(event_name)

        refusal = refusals_for("Guide Article", self.free.name)[-1]
        self.assertEqual(refusal["attempted_action"], "Dispose")
        self.assertEqual(refusal["control"], "legal hold")

    def test_disposal_without_an_approver_is_refused(self):
        archive = self._archive(self.free)
        event_name = retention.schedule_disposition(archive.name)
        with self.assertRaises(frappe.ValidationError):
            retention.execute_disposition(event_name)
        self.assertEqual(
            refusals_for("Guide Article", self.free.name)[-1]["control"], "disposition approval"
        )

    def test_an_approved_disposal_executes(self):
        archive = self._archive(self.free)
        event_name = retention.schedule_disposition(archive.name)
        event = frappe.get_doc("Disposition Event", event_name)
        self.assertEqual(event.status, "Scheduled")
        event.db_set("approved_by", frappe.session.user)
        retention.execute_disposition(event_name, evidence={"method": "reviewed"})
        event.reload()
        self.assertEqual(event.status, "Executed")
        self.assertFalse(event.is_open)
        self.assertTrue(event.executed_on)

    def test_releasing_a_hold_returns_held_events_to_the_schedule(self):
        archive = self._archive(self.free)
        hold = frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "placed_on": nowdate(),
                "scope_doctype": "Guide Article",
                "scope_filter": '{"category": "Getting Started"}',
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()
        event_name = retention.schedule_disposition(archive.name)

        retention.release_hold(hold.name)
        retention.clear_cache()
        event = frappe.get_doc("Disposition Event", event_name)
        self.assertEqual(event.status, "Scheduled")
        self.assertFalse(event.held_by_legal_hold)

    def test_the_due_date_comes_from_the_class_trigger(self):
        due = retention.disposition_due_date(self.retention_class.name, "Guide Article", self.free.name)
        self.assertTrue(str(due) > nowdate())
