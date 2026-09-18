"""The event API: templates as data, the email channel, fallbacks, retries.

Every test raises its own event code or uses its own channel, so nothing here
depends on — or disturbs — the templates the site ships with.
"""

from unittest.mock import patch

import frappe

from consilium.consilium_core import notification
from consilium.consilium_core.setup import notification_templates
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user


def _event() -> str:
    return f"test.{frappe.generate_hash(length=10)}"


class NotificationCase(CoreTestCase):
    def setUp(self):
        # Runs even if setUp fails, so an aborted transaction cannot cascade.
        self.addCleanup(frappe.db.rollback)
        super().setUp()
        # The framework's dummy outgoing account stands in for a mail server:
        # messages are queued, never sent. No real account is configured.
        frappe.flags.mute_emails = True
        notification_templates.seed_all()
        self.recipient = make_user()
        self.article = make_guide_article(title="Retention schedule")

    def tearDown(self):
        frappe.flags.mute_emails = False
        super().tearDown()

    def template(self, event_code, channel="EMAIL", **values):
        return frappe.get_doc(
            {
                "doctype": "Notification Template",
                "event_code": event_code,
                "channel": channel,
                "subject": values.pop("subject", "{{ doc.title }} is due {{ due_on }}"),
                "body": values.pop("body", "Hello {{ recipient_name }}.\n\n{{ doc.title }} is due on {{ due_on }}."),
                **values,
            }
        ).insert(ignore_permissions=True)

    def raise_event(self, event_code, recipients=None, **context):
        return notification.notify(
            event_code, recipients or [self.recipient], context or {"due_on": "2026-10-01"},
            "Guide Article", self.article.name,
        )

    def email_rows(self, dispatch_name):
        return frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Notification Dispatch", "reference_name": dispatch_name},
            fields=["name", "status", "message"],
        )


class TestSeeding(NotificationCase):
    def test_every_event_the_application_raises_has_a_template(self):
        for event_code, *_ in notification_templates.EVENTS:
            self.assertTrue(
                frappe.db.exists("Notification Template", {"event_code": event_code}),
                msg=f"no template seeded for {event_code}",
            )
        self.assertEqual(frappe.db.get_value("Notification Channel", "EMAIL", "adapter"), "email")
        self.assertEqual(frappe.db.get_value("Notification Channel", "EMAIL", "fallback_channel"), "RECORD")

    def test_seeding_twice_changes_nothing_and_keeps_an_administrators_wording(self):
        name = frappe.db.get_value("Notification Template", {"event_code": "policy.review.overdue"}, "name")
        frappe.db.set_value("Notification Template", name, "subject", "Our own wording")
        count = frappe.db.count("Notification Template")

        notification_templates.seed_all()

        self.assertEqual(frappe.db.count("Notification Template"), count)
        self.assertEqual(frappe.db.get_value("Notification Template", name, "subject"), "Our own wording")


class TestEventApi(NotificationCase):
    def test_a_template_is_rendered_against_the_context_and_the_record(self):
        event = _event()
        self.template(event)
        [name] = self.raise_event(event)
        row = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(row.channel, "EMAIL")
        self.assertEqual(row.status, "Sent")
        self.assertEqual(row.rendered_subject, "Retention schedule is due 2026-10-01")
        self.assertIn("Hello Test Person", row.rendered_body)
        self.assertEqual((row.subject_doctype, row.subject_name), ("Guide Article", self.article.name))

    def test_email_is_handed_to_the_framework_mail_queue(self):
        event = _event()
        self.template(event)
        [name] = self.raise_event(event)
        [queued] = self.email_rows(name)
        self.assertEqual(queued.status, "Not Sent")
        self.assertIn("Retention schedule is due 2026-10-01", queued.message)

    def test_one_event_can_go_to_two_channels(self):
        event = _event()
        self.template(event)
        self.template(event, channel="RECORD", subject="Recorded: {{ doc.title }}")
        rows = [frappe.get_doc("Notification Dispatch", n) for n in self.raise_event(event)]
        self.assertEqual(sorted(r.channel for r in rows), ["EMAIL", "RECORD"])

    def test_without_outgoing_email_the_record_channel_is_used_and_nothing_fails(self):
        event = _event()
        self.template(event)
        with patch.object(notification, "email_configured", return_value=False):
            [name] = self.raise_event(event)
        row = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(row.channel, "RECORD")
        self.assertEqual(row.status, "Sent")
        self.assertEqual(row.rendered_subject, "Retention schedule is due 2026-10-01")
        # A deployment without mail is not a failure to retry every hour.
        self.assertFalse(frappe.db.exists("Notification Dispatch", {"recipient": self.recipient, "is_open": 1}))
        self.assertFalse(self.email_rows(name))

    def test_a_person_who_turned_email_off_is_not_emailed_and_the_refusal_is_recorded(self):
        event = _event()
        self.template(event)
        settings = frappe.get_doc("Notification Settings", self.recipient) if frappe.db.exists(
            "Notification Settings", self.recipient) else frappe.get_doc(
            {"doctype": "Notification Settings", "name": self.recipient}).insert(ignore_permissions=True)
        settings.enable_email_notifications = 0
        settings.save(ignore_permissions=True)

        [name] = self.raise_event(event)
        fallback = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(fallback.channel, "RECORD")
        refused = frappe.get_doc("Notification Dispatch", fallback.fallback_of)
        self.assertEqual((refused.channel, refused.status), ("EMAIL", "Suppressed"))
        self.assertIn("turned email notifications off", refused.failure_reason)
        self.assertFalse(self.email_rows(refused.name))

    def test_a_disabled_account_is_not_emailed(self):
        event = _event()
        self.template(event)
        frappe.db.set_value("User", self.recipient, "enabled", 0)
        [name] = self.raise_event(event)
        refused = frappe.get_doc("Notification Dispatch", frappe.db.get_value(
            "Notification Dispatch", name, "fallback_of"))
        self.assertEqual(refused.status, "Suppressed")
        self.assertIn("disabled", refused.failure_reason)

    def test_an_event_with_no_active_template_is_still_recorded(self):
        event = _event()
        self.template(event, is_active=0)
        [name] = self.raise_event(event)
        row = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(row.channel, "RECORD")
        self.assertTrue(row.rendered_subject.startswith(event))

    def test_a_known_event_without_templates_uses_its_built_in_wording(self):
        frappe.db.set_value("Notification Template", {"event_code": "policy.monitoring.overdue"}, "is_active", 0)
        [name] = notification.notify(
            "policy.monitoring.overdue", [self.recipient],
            {"document_name": "Anti-bribery policy", "due_on": "2026-08-15", "days_overdue": 34},
        )
        body = frappe.db.get_value("Notification Dispatch", name, "rendered_body")
        self.assertIn("Anti-bribery policy fell due on 2026-08-15 and is 34 day(s) overdue", body)

    def test_people_who_are_not_users_are_dropped(self):
        event = _event()
        self.template(event)
        names = self.raise_event(event, [self.recipient, "nobody@example.com", None, self.recipient])
        self.assertEqual(len(names), 1)

    def test_a_long_subject_is_shortened_rather_than_refused(self):
        event = _event()
        self.template(event, subject="{{ 'x' * 400 }}")
        [name] = self.raise_event(event)
        self.assertEqual(len(frappe.db.get_value("Notification Dispatch", name, "rendered_subject")), 140)


class TestTemplateFailures(NotificationCase):
    def test_a_template_that_does_not_parse_is_refused_when_saved(self):
        with self.assertRaises(frappe.ValidationError):
            self.template(_event(), body="{% if due_on %}never closed")

    def test_a_template_reaching_for_internals_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.template(_event(), subject="{{ doc.__class__ }}")

    def test_a_template_that_fails_to_render_falls_back_and_is_logged(self):
        event = _event()
        broken = self.template(event)
        # Parses, so it was accepted; divides by zero when rendered.
        frappe.db.set_value("Notification Template", broken.name, "body", "{{ 1 // 0 }}")
        errors_before = frappe.db.count("Error Log")

        [name] = self.raise_event(event)

        row = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(row.status, "Sent")
        self.assertTrue(row.rendered_subject.startswith(event), msg="the built-in fallback wording is used")
        self.assertGreater(frappe.db.count("Error Log"), errors_before)

    def test_a_broken_template_does_not_stop_the_next_recipient_or_event(self):
        broken_event, good_event = _event(), _event()
        broken = self.template(broken_event)
        frappe.db.set_value("Notification Template", broken.name, "subject", "{{ 1 // 0 }}")
        self.template(good_event)
        second = make_user()

        broken_rows = self.raise_event(broken_event, [self.recipient, second])
        good_rows = self.raise_event(good_event, [self.recipient, second])

        self.assertEqual(len(broken_rows), 2)
        self.assertEqual(len(good_rows), 2)
        subjects = {frappe.db.get_value("Notification Dispatch", n, "rendered_subject") for n in good_rows}
        self.assertEqual(subjects, {"Retention schedule is due 2026-10-01"})

    def test_a_dispatch_that_raises_does_not_stop_the_next_recipient(self):
        event = _event()
        self.template(event)
        second = make_user()
        real = notification.dispatch

        def flaky(channel, recipient, **kwargs):
            if recipient == self.recipient:
                raise RuntimeError("the database hiccupped")
            return real(channel, recipient, **kwargs)

        with patch.object(notification, "dispatch", side_effect=flaky):
            rows = self.raise_event(event, [self.recipient, second])
        self.assertEqual([frappe.db.get_value("Notification Dispatch", rows[0], "recipient")], [second])


class TestEmailRetry(NotificationCase):
    def test_a_message_the_mail_server_refused_is_sent_again(self):
        event = _event()
        self.template(event)
        [name] = self.raise_event(event)
        [queued] = self.email_rows(name)
        frappe.db.set_value("Email Queue", queued.name, {"status": "Error", "error": "550 mailbox unavailable"})

        retried = notification.retry_failed()

        self.assertIn(name, retried)
        row = frappe.get_doc("Notification Dispatch", name)
        self.assertEqual(row.status, "Sent")
        self.assertEqual(row.retry_count, 1)
        self.assertEqual(len(self.email_rows(name)), 2, msg="a fresh message was queued")

        # The refused row is history now; the next run must not retry it again.
        self.assertNotIn(name, notification.retry_failed())
        self.assertEqual(len(self.email_rows(name)), 2)

    def test_queueing_that_fails_is_retried_by_the_hourly_job(self):
        event = _event()
        self.template(event)
        with patch.object(frappe, "sendmail", side_effect=RuntimeError("queue unavailable")):
            [name] = self.raise_event(event)
        fallback = frappe.get_doc("Notification Dispatch", name)
        failed = frappe.get_doc("Notification Dispatch", fallback.fallback_of)
        self.assertEqual((failed.channel, failed.status), ("EMAIL", "Failed"))
        self.assertTrue(failed.is_open)

        self.assertIn(failed.name, notification.retry_failed())
        failed.reload()
        self.assertEqual(failed.status, "Sent")
        self.assertEqual(len(self.email_rows(failed.name)), 1)

    def test_retries_stop_after_the_limit(self):
        event = _event()
        self.template(event)
        with patch.object(frappe, "sendmail", side_effect=RuntimeError("queue unavailable")):
            [name] = self.raise_event(event)
            failed = frappe.db.get_value("Notification Dispatch", name, "fallback_of")
            for _ in range(notification.MAX_RETRIES + 2):
                notification.retry_failed()
        row = frappe.get_doc("Notification Dispatch", failed)
        self.assertEqual(row.retry_count, notification.MAX_RETRIES)
        self.assertTrue(row.is_open, msg="left open for a person to see, not silently closed")


class TestTemplatePermissions(NotificationCase):
    def test_an_auditor_may_read_templates_but_not_change_them(self):
        auditor = make_user("Consilium Audit")
        name = frappe.db.get_value("Notification Template", {"event_code": "policy.review.overdue"}, "name")
        frappe.set_user(auditor)
        try:
            self.assertTrue(frappe.has_permission("Notification Template", "read", doc=name))
            doc = frappe.get_doc("Notification Template", name)
            doc.subject = "Changed by an auditor"
            with self.assertRaises(frappe.PermissionError):
                doc.save()
        finally:
            frappe.set_user("Administrator")

    def test_an_administrator_role_may_change_the_wording(self):
        admin = make_user("Consilium Administrator")
        name = frappe.db.get_value("Notification Template", {"event_code": "policy.review.overdue"}, "name")
        frappe.set_user(admin)
        try:
            doc = frappe.get_doc("Notification Template", name)
            doc.subject = "Review overdue — {{ doc.document_name }}"
            doc.save()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(frappe.db.get_value("Notification Template", name, "subject"),
                         "Review overdue — {{ doc.document_name }}")
