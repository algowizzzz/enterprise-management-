"""Policy behaviour closed in wave 3.

* A Core revert restores a document's content and never its lifecycle phase.
* ``lifecycle.transition`` accepts POST only.
* Horizon-scan reminders go through Core's reminder log, so an overdue scan is
  chased weekly rather than every day.
* The audience notice is a templated event.
* E7-S4 on the document approval chain: a later sequential step waits.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import approvals, versioning
from consilium.consilium_core.setup import notification_templates
from consilium.policy import applicability, horizon, lifecycle, publication, routing
from consilium.policy.tests.utils import PolicyTestCase, make_document, make_user

DOCTYPE = "Governing Document"


class TestRevertLeavesTheLifecycleAlone(PolicyTestCase):
    def test_reverting_restores_the_content_but_not_the_phase(self):
        doc = make_document(document_name="Original title")
        first = versioning.create_version(doc, change_summary="As drafted")

        # The document moves on — into review — and its title changes there.
        frappe.db.set_value(DOCTYPE, doc.name, "lifecycle_phase", "Review")
        doc.reload()
        doc.save(ignore_permissions=True)  # the flags follow the phase
        doc.reload()
        flags_in_review = (doc.is_editable, doc.requires_review, doc.is_active)
        doc.document_name = "Changed in review"
        doc.save(ignore_permissions=True)
        versioning.create_version(doc, change_summary="Retitled in review")

        publication.revert(doc.name, first.name, "The retitling was not agreed.")
        doc.reload()
        self.assertEqual(doc.document_name, "Original title", "the content is restored")
        self.assertEqual(doc.lifecycle_phase, "Review", "the phase is not written back to Draft")
        self.assertEqual((doc.is_editable, doc.requires_review, doc.is_active), flags_in_review)


class TestTransitionIsPostOnly(PolicyTestCase):
    def test_the_whitelisted_transition_refuses_get(self):
        allowed = frappe.allowed_http_methods_for_whitelisted_func.get(lifecycle.transition)
        self.assertEqual(allowed, ["POST"])


class TestHorizonReminderCadence(PolicyTestCase):
    def setUp(self):
        super().setUp()
        frappe.flags.mute_emails = True
        notification_templates.seed_all()

    def tearDown(self):
        frappe.flags.mute_emails = False
        super().tearDown()

    def _owner_reminders(self, doc, as_of):
        dispatched = horizon.remind_due(as_of)
        return [
            name for name in dispatched
            if frappe.db.get_value("Notification Dispatch", name, "subject_name") == doc.name
        ]

    def test_an_overdue_scan_is_not_chased_every_day(self):
        doc = make_document(review_frequency_months=12, effective_on="2020-01-01")
        frappe.db.set_value(DOCTYPE, doc.name, "is_active", 1)
        today = getdate(nowdate())

        self.assertTrue(self._owner_reminders(doc, today))
        self.assertEqual(self._owner_reminders(doc, today), [], "never twice on one day")
        self.assertEqual(self._owner_reminders(doc, add_days(today, 1)), [], "not again the next day")
        self.assertTrue(self._owner_reminders(doc, add_days(today, 7)), "chased again a week later")

        subject = frappe.db.get_value(
            "Notification Dispatch", {"subject_doctype": DOCTYPE, "subject_name": doc.name}, "rendered_subject"
        )
        self.assertEqual(subject, f"Horizon scan due for {doc.document_name}")
        self.assertTrue(frappe.db.exists(
            "Reminder Log", {"event_code": "policy.horizon_scan.due", "subject_name": doc.name}
        ))


class TestAudienceNotice(PolicyTestCase):
    def test_the_audience_notice_is_the_templated_event(self):
        frappe.flags.mute_emails = True
        try:
            notification_templates.seed_all()
            member = make_user()
            group = frappe.get_doc(
                {"doctype": "User Group", "name": frappe.generate_hash(length=8),
                 "user_group_members": [{"user": member}]}
            ).insert(ignore_permissions=True)
            doc = make_document()
            doc.append("applicability", {"scope_type": "Organization Unit",
                                         "scope_value": doc.owning_operating_group,
                                         "notification_group": group.name})
            doc.save(ignore_permissions=True)
            dispatched = applicability.notify_affected(doc.name, "Published")
            self.assertTrue(dispatched)
            row = frappe.get_doc("Notification Dispatch", dispatched[0])
            self.assertEqual(row.recipient, member)
            self.assertEqual(row.rendered_subject, f"{doc.document_name} ({doc.name}) — Published")
            self.assertIn("has been published", row.rendered_body)
        finally:
            frappe.flags.mute_emails = False


class TestDocumentStepOrder(PolicyTestCase):
    def test_the_screen_holds_back_a_step_behind_an_open_one(self):
        approver = make_user("Policy Owner")
        doc = make_document(document_approver=approver)
        frappe.db.set_value(DOCTYPE, doc.name, "lifecycle_phase", "Review")
        doc.reload()
        rows = [frappe.get_doc("Approval Decision", name) for name in routing.instantiate(doc)]
        rows.sort(key=lambda row: (row.step_sequence, row.creation))
        later = [row for row in rows if row.step_sequence > rows[0].step_sequence and row.mode == "Sequential"]
        if not later:
            self.skipTest("the seeded route for this document has a single sequence")
        frappe.set_user(later[0].assigned_to)
        try:
            context = routing.approval_context(frappe.get_doc(DOCTYPE, doc.name))
        finally:
            frappe.set_user("Administrator")
        row = next(d for d in context["decisions"] if d["name"] == later[0].name)
        self.assertFalse(row["can_decide"])
        self.assertTrue(row["waiting_on"])
        self.assertFalse(approvals.is_turn(later[0].name))
