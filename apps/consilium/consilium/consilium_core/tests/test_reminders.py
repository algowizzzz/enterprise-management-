"""Scheduled reminders: who is told, when, and never twice.

Each test creates its own records and asks the reminder functions about those
records only (every function takes the names to consider), because the site
the suite runs on may hold other data with due dates of its own. Where a test
drives the whole daily job, it counts only what was sent about its own record.

Records are put into the dated, in-force condition a reminder looks for with a
direct write of the date and the semantic flag. What is under test is the
reminder; how a record reaches that condition is its own module's business and
is tested there.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate

from consilium.consilium_core import notification, reminders
from consilium.consilium_core.setup import notification_templates
from consilium.escalation.tests.utils import EscalationTestCase
from consilium.escalation.tests.utils import make_user as make_escalation_user
from consilium.governance.tests.utils import GovernanceTestCase, make_forum
from consilium.governance.tests.utils import make_user as make_governance_user
from consilium.policy.tests.utils import PolicyTestCase, make_document
from consilium.policy.tests.utils import make_user as make_policy_user

TODAY = getdate("2026-09-18")


def sent_about(doctype: str, name: str, event_code: str | None = None) -> list[dict]:
    filters = {"subject_doctype": doctype, "subject_name": name}
    if event_code:
        filters["event_code"] = event_code
    return frappe.get_all("Reminder Log", filters=filters, fields=["event_code", "recipient", "dispatch",
                                                                     "sent_for_date", "due_on"])


class ReminderMixin:
    def setUp(self):
        # Runs even if setUp fails, so an aborted transaction cannot cascade.
        self.addCleanup(frappe.db.rollback)
        super().setUp()

    def prepare(self):
        notification_templates.seed_all()
        # Record-only delivery keeps these tests about reminders, not mail.
        patcher = patch.object(notification, "email_configured", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestDocumentReviewReminders(ReminderMixin, PolicyTestCase):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.doc = make_document()
        self.owner = self.doc.document_owner
        self.approver = self.doc.document_approver

    def due(self, day):
        frappe.db.set_value("Governing Document", self.doc.name, {"is_active": 1, "next_review_on": day})

    def test_the_owner_is_told_a_review_is_coming(self):
        self.due(add_days(TODAY, 10))
        dispatches = reminders.remind_document_reviews(TODAY, documents=[self.doc.name])
        self.assertEqual(len(dispatches), 1)
        row = frappe.get_doc("Notification Dispatch", dispatches[0])
        self.assertEqual(row.recipient, self.owner)
        self.assertIn(self.doc.document_name, row.rendered_subject)
        self.assertIn("in 10 day(s)", row.rendered_body)

    def test_nothing_is_sent_outside_the_notice_period(self):
        self.due(add_days(TODAY, reminders.NOTICE_DAYS["document_review"] + 1))
        self.assertEqual(reminders.remind_document_reviews(TODAY, documents=[self.doc.name]), [])

    def test_running_the_daily_job_twice_sends_one_reminder(self):
        self.due(add_days(TODAY, -3))
        reminders.daily(TODAY)
        reminders.daily(TODAY)
        sent = sent_about("Governing Document", self.doc.name)
        self.assertEqual([(s.event_code, s.recipient) for s in sent], [("policy.review.overdue", self.owner)])
        self.assertTrue(frappe.db.exists("Notification Dispatch", sent[0].dispatch))

    def test_an_overdue_review_is_chased_weekly_not_daily(self):
        self.due(add_days(TODAY, -3))
        reminders.remind_document_reviews(TODAY, documents=[self.doc.name])
        self.assertEqual(reminders.remind_document_reviews(add_days(TODAY, 1), documents=[self.doc.name]), [])
        again = reminders.remind_document_reviews(add_days(TODAY, reminders.REPEAT_OVERDUE_DAYS),
                                                  documents=[self.doc.name])
        self.assertEqual(len(again), 1)

    def test_a_long_overdue_review_is_escalated_to_the_approver(self):
        self.due(add_days(TODAY, -reminders.ESCALATE_AFTER_DAYS))
        reminders.remind_document_reviews(TODAY, documents=[self.doc.name])
        sent = {(s.event_code, s.recipient) for s in sent_about("Governing Document", self.doc.name)}
        self.assertEqual(sent, {("policy.review.overdue", self.owner), ("policy.review.escalated", self.approver)})

    def test_a_document_not_in_force_is_not_chased(self):
        frappe.db.set_value("Governing Document", self.doc.name,
                            {"is_active": 0, "next_review_on": add_days(TODAY, -3)})
        self.assertEqual(reminders.remind_document_reviews(TODAY, documents=[self.doc.name]), [])

    def test_an_open_review_cycle_takes_over_from_the_document_reminder(self):
        self.due(add_days(TODAY, -3))
        reviewer = make_policy_user("Policy Reviewer")
        cycle = frappe.get_doc(
            {
                "doctype": "Document Review Cycle",
                "document": self.doc.name,
                "cycle_year": "2026",
                "scheduled_start": add_days(TODAY, 3),
                "due_on": add_days(TODAY, -20),
                "reviewer": reviewer,
                "cycle_status": "Planned",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(cycle.is_open)

        self.assertEqual(reminders.remind_document_reviews(TODAY, documents=[self.doc.name]), [])
        reminders.remind_review_cycles(TODAY, cycles=[cycle.name])
        sent = {(s.event_code, s.recipient) for s in sent_about("Document Review Cycle", cycle.name)}
        self.assertEqual(sent, {
            ("policy.review_cycle.starting", reviewer), ("policy.review_cycle.starting", self.owner),
            ("policy.review_cycle.overdue", reviewer), ("policy.review_cycle.overdue", self.owner),
            ("policy.review_cycle.escalated", self.approver),
        })

    def test_one_record_failing_does_not_stop_the_others(self):
        other = make_document()
        self.due(add_days(TODAY, -3))
        frappe.db.set_value("Governing Document", other.name, {"is_active": 1, "next_review_on": add_days(TODAY, -3)})
        real = reminders.remind

        def fail_for_first(event_code, recipients, **kwargs):
            if kwargs.get("subject_name") == self.doc.name:
                raise RuntimeError("could not read the record")
            return real(event_code, recipients, **kwargs)

        with patch.object(reminders, "remind", side_effect=fail_for_first):
            sent = reminders.remind_document_reviews(TODAY, documents=[self.doc.name, other.name])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent_about("Governing Document", other.name)[0].recipient, other.document_owner)
        self.assertEqual(sent_about("Governing Document", self.doc.name), [])

    def test_a_broken_template_still_reminds(self):
        name = frappe.db.get_value("Notification Template", {"event_code": "policy.review.overdue"}, "name")
        frappe.db.set_value("Notification Template", name, "subject", "{{ 1 // 0 }}")
        self.due(add_days(TODAY, -3))
        [dispatch] = reminders.remind_document_reviews(TODAY, documents=[self.doc.name])
        self.assertEqual(frappe.db.get_value("Notification Dispatch", dispatch, "rendered_subject"),
                         f"Review overdue: {self.doc.document_name}")


class TestMonitoringReminders(ReminderMixin, PolicyTestCase):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.doc = make_document()
        self.responsible = make_policy_user("Policy Owner")
        self.activity = frappe.get_doc(
            {
                "doctype": "Monitoring Activity",
                "document": self.doc.name,
                "activity_title": "Quarterly sample test",
                "frequency": "Quarterly",
                "responsible": self.responsible,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

    def test_due_soon_then_overdue_then_escalated(self):
        name = self.activity.name
        frappe.db.set_value("Monitoring Activity", name, "next_due_on", add_days(TODAY, 5))
        reminders.remind_monitoring(TODAY, activities=[name])
        frappe.db.set_value("Monitoring Activity", name, "next_due_on", add_days(TODAY, -20))
        reminders.remind_monitoring(TODAY, activities=[name])
        sent = {(s.event_code, s.recipient) for s in sent_about("Monitoring Activity", name)}
        self.assertEqual(sent, {
            ("policy.monitoring.due_soon", self.responsible),
            ("policy.monitoring.overdue", self.responsible),
            ("policy.monitoring.escalated", self.doc.document_owner),
        })

    def test_an_inactive_activity_is_not_chased(self):
        frappe.db.set_value("Monitoring Activity", self.activity.name,
                            {"is_active": 0, "next_due_on": add_days(TODAY, -20)})
        self.assertEqual(reminders.remind_monitoring(TODAY, activities=[self.activity.name]), [])


class TestEscalationReminders(ReminderMixin, EscalationTestCase):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.reference = self.reference_data()
        self.matter = self.make_matter(self.reference)
        self.executive = self.reference["user"]

    def acceptance(self, **dates):
        doc = frappe.get_doc(
            {
                "doctype": "Risk Acceptance",
                "escalation_matter": self.matter.name,
                "risk_acceptance_name": "Accept until the platform is replaced",
                "start_date": "2026-01-10",
                "end_date": "2027-12-31",
                "accountable_executive": self.executive,
                "rationale": "Remediation costs more than the exposure for the remaining life of the platform.",
            }
        ).insert(ignore_permissions=True)
        frappe.db.set_value("Risk Acceptance", doc.name, {"is_active": 1, **dates})
        return doc.name

    def test_reassessment_due_and_overdue_reach_the_accountable_executive(self):
        soon = self.acceptance(next_reassessment_on=add_days(TODAY, 7))
        late = self.acceptance(next_reassessment_on=add_days(TODAY, -7))
        reminders.remind_risk_acceptances(TODAY, acceptances=[soon, late])
        self.assertEqual([(s.event_code, s.recipient) for s in sent_about("Risk Acceptance", soon)],
                         [("escalation.risk_acceptance.reassessment_due", self.executive)])
        self.assertEqual([(s.event_code, s.recipient) for s in sent_about("Risk Acceptance", late)],
                         [("escalation.risk_acceptance.reassessment_overdue", self.executive)])

    def test_an_acceptance_nearing_or_past_its_end_date_is_flagged(self):
        ending = self.acceptance(end_date=add_days(TODAY, 20))
        ended = self.acceptance(end_date=add_days(TODAY, -1))
        reminders.remind_risk_acceptances(TODAY, acceptances=[ending, ended])
        self.assertEqual([s.event_code for s in sent_about("Risk Acceptance", ending)],
                         ["escalation.risk_acceptance.expiring"])
        self.assertEqual([s.event_code for s in sent_about("Risk Acceptance", ended)],
                         ["escalation.risk_acceptance.expired"])

    def test_an_acceptance_not_in_force_is_left_alone(self):
        name = self.acceptance(next_reassessment_on=add_days(TODAY, -7))
        frappe.db.set_value("Risk Acceptance", name, "is_active", 0)
        self.assertEqual(reminders.remind_risk_acceptances(TODAY, acceptances=[name]), [])

    def test_an_action_plan_past_its_end_date_reaches_owner_and_executive(self):
        owner = make_escalation_user("Escalation Owner")
        plan = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": self.matter.name,
                "action_plan_name": "Replace the reconciliation job",
                "start_date": "2026-06-01",
                "end_date": add_days(TODAY, -2),
                "accountable_executive": self.executive,
                "owner_user": owner,
                "status": "Open",
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(plan.is_open)
        reminders.remind_action_plans(TODAY, plans=[plan.name])
        reminders.remind_action_plans(TODAY, plans=[plan.name])
        sent = sorted((s.event_code, s.recipient) for s in sent_about("Action Plan", plan.name))
        self.assertEqual(sent, sorted([("escalation.action_plan.overdue", owner),
                                       ("escalation.action_plan.overdue", self.executive)]))

    def test_a_quarter_opening_creates_its_return_once_and_tells_its_owner(self):
        owner = make_escalation_user("Escalation Owner")
        previous = frappe.get_doc(
            {"doctype": "Periodic Submission", "period_label": "2031-Q1",
             "period_start": "2031-01-01", "period_end": "2031-03-31"}
        ).insert(ignore_permissions=True)
        frappe.db.set_value("Periodic Submission", previous.name, "owner", owner)

        opened_on = getdate("2031-04-01")
        created = reminders.open_quarter(opened_on)
        self.assertEqual(reminders.open_quarter(opened_on), [], msg="a second run creates nothing")
        self.assertEqual(len(created), 1)
        new = frappe.get_doc("Periodic Submission", created[0])
        self.assertEqual((new.period_label, str(new.period_start), str(new.period_end)),
                         ("2031-Q2", "2031-04-01", "2031-06-30"))
        self.assertEqual(new.owner, owner, msg="the return inherits the previous return's owner")
        self.assertTrue(new.is_open)
        self.assertEqual([(s.event_code, s.recipient) for s in sent_about("Periodic Submission", new.name)],
                         [("escalation.periodic_return.opened", owner)])

        # Quarter end plus the grace period has passed and the return is still open.
        late = add_days("2031-06-30", reminders.PERIODIC_RETURN_GRACE_DAYS + 3)
        reminders.remind_periodic_returns(late, submissions=[new.name])
        self.assertIn(("escalation.periodic_return.overdue", owner),
                      [(s.event_code, s.recipient) for s in sent_about("Periodic Submission", new.name)])

    def test_quarter_boundaries(self):
        self.assertEqual(reminders.quarter_of("2026-09-18")[0], "2026-Q3")
        self.assertEqual(str(reminders.quarter_of("2026-12-31")[2]), "2026-12-31")
        self.assertEqual(str(reminders.quarter_of("2028-02-10")[2]), "2028-03-31")


class TestForumReviewReminders(ReminderMixin, GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.prepare()
        self.owner = make_governance_user()
        self.forum = make_forum(forum_owner=self.owner)
        frappe.db.set_value("Governance Forum", self.forum.name,
                            {"is_active": 1, "next_review_on": add_days(TODAY, -10)})

    def test_the_overdue_review_list_now_reaches_the_forum_owner(self):
        first = reminders.remind_forum_reviews(TODAY, forums=[self.forum.name])
        second = reminders.remind_forum_reviews(TODAY, forums=[self.forum.name])
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        [log] = sent_about("Governance Forum", self.forum.name)
        self.assertEqual((log.event_code, log.recipient), ("governance.forum_review.overdue", self.owner))
        self.assertIn(self.forum.forum_name, frappe.db.get_value("Notification Dispatch", log.dispatch,
                                                                  "rendered_subject"))


class TestReminderLog(ReminderMixin, PolicyTestCase):
    def setUp(self):
        super().setUp()
        self.prepare()

    def test_the_same_key_cannot_be_claimed_twice(self):
        user = make_policy_user()
        values = {"doctype": "Reminder Log", "reminder_key": reminders._key("x", user), "event_code": "x",
                  "recipient": user, "sent_for_date": TODAY}
        frappe.get_doc(values).insert(ignore_permissions=True)
        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            frappe.get_doc(values).insert(ignore_permissions=True)

    def test_an_auditor_may_read_the_log_but_not_write_it(self):
        auditor = make_policy_user("Consilium Audit")
        frappe.set_user(auditor)
        try:
            self.assertTrue(frappe.has_permission("Reminder Log", "read"))
            self.assertFalse(frappe.has_permission("Reminder Log", "create"))
        finally:
            frappe.set_user("Administrator")
