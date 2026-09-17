"""The notification layer: every send leaves evidence, and failure falls back."""

import frappe

from consilium.consilium_core import notification
from consilium.consilium_core.tests.utils import CoreTestCase, make_user, unique


@notification.register_adapter("test_always_fails")
def _always_fails(dispatch, channel):
    raise RuntimeError("the channel is unreachable")


class TestNotification(CoreTestCase):
    def setUp(self):
        self.recipient = make_user()
        self.good = frappe.get_doc(
            {
                "doctype": "Notification Channel",
                "channel_code": unique("GOOD"),
                "title": "Recorded",
                "channel_type": "In App",
                "adapter": "record_only",
            }
        ).insert(ignore_permissions=True)

    def test_a_successful_send_is_recorded_as_evidence(self):
        row = notification.dispatch(self.good.name, self.recipient, subject="Due soon", body="Text")
        self.assertEqual(row.status, "Sent")
        self.assertTrue(row.sent_on)
        self.assertFalse(row.is_open)
        self.assertEqual(row.recipient, self.recipient)

    def test_a_failure_is_recorded_and_falls_back(self):
        failing = frappe.get_doc(
            {
                "doctype": "Notification Channel",
                "channel_code": unique("BAD"),
                "title": "Unreachable",
                "channel_type": "Chat",
                "adapter": "test_always_fails",
                "fallback_channel": self.good.name,
            }
        ).insert(ignore_permissions=True)

        result = notification.dispatch(failing.name, self.recipient, subject="Due soon")
        self.assertEqual(result.channel, self.good.name)
        self.assertEqual(result.status, "Sent")

        failed = frappe.get_doc("Notification Dispatch", result.fallback_of)
        self.assertEqual(failed.status, "Failed")
        self.assertTrue(failed.is_open)
        self.assertIn("unreachable", failed.failure_reason)

    def test_a_failure_without_a_fallback_stays_failed(self):
        failing = frappe.get_doc(
            {
                "doctype": "Notification Channel",
                "channel_code": unique("BAD"),
                "title": "Unreachable",
                "channel_type": "Chat",
                "adapter": "test_always_fails",
            }
        ).insert(ignore_permissions=True)
        row = notification.dispatch(failing.name, self.recipient)
        self.assertEqual(row.status, "Failed")
        self.assertTrue(row.is_open)

    def test_an_inactive_channel_suppresses_rather_than_pretends(self):
        self.good.is_active = 0
        self.good.save(ignore_permissions=True)
        row = notification.dispatch(self.good.name, self.recipient)
        self.assertEqual(row.status, "Suppressed")
        self.assertFalse(row.is_open)

    def test_an_unknown_adapter_is_refused_at_configuration_time(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Notification Channel",
                    "channel_code": unique("X"),
                    "title": "Nowhere",
                    "channel_type": "Webhook",
                    "adapter": "no_such_adapter",
                }
            ).insert(ignore_permissions=True)

    def test_a_fallback_cycle_is_refused(self):
        other = frappe.get_doc(
            {
                "doctype": "Notification Channel",
                "channel_code": unique("B"),
                "title": "Second",
                "channel_type": "Email",
                "adapter": "record_only",
                "fallback_channel": self.good.name,
            }
        ).insert(ignore_permissions=True)
        self.good.fallback_channel = other.name
        with self.assertRaises(frappe.ValidationError):
            self.good.save(ignore_permissions=True)
