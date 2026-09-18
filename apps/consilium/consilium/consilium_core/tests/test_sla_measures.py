"""Service levels driven by status changes, and the warning threshold (P-7, E-13).

A Guide Article stands in for "any record with a status": it tracks changes and
has a Select field (``category``) whose value the definitions below measure.
The values the definitions name are test configuration, which is the point —
the engine compares a record's field with whatever the definition says.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, get_datetime, now

from consilium.consilium_core import notification, sla
from consilium.consilium_core.setup import notification_templates
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user, unique


def clocks_for(definition: str, name: str) -> list[dict]:
    return frappe.get_all(
        "SLA Clock",
        filters={"sla_definition": definition, "subject_doctype": "Guide Article", "subject_name": name},
        fields=["name", "started_on", "stopped_on", "status", "is_open", "breached_on", "warning_sent_on"],
        order_by="started_on asc",
    )


def backdate_versions(name: str, minutes: int) -> None:
    """Move a record's history into the past, as if the changes happened then."""
    frappe.db.sql(
        """UPDATE "tabVersion" SET "creation" = "creation" - %s * interval '1 minute'
           WHERE "ref_doctype" = 'Guide Article' AND "docname" = %s""",
        (minutes, name),
    )


class SLACase(CoreTestCase):
    def setUp(self):
        # Registered first so it runs even when setUp itself fails: without it a
        # setUp that dies mid-transaction (a lock wait on a shared test site)
        # leaves the transaction aborted and fails every test after it.
        self.addCleanup(frappe.db.rollback)
        super().setUp()
        notification_templates.seed_all()
        patcher = patch.object(notification, "email_configured", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        sla.clear_cache()

    def tearDown(self):
        sla.clear_cache()
        super().tearDown()

    def definition(self, measure=sla.MEASURE_TIME_IN_STATE, **values):
        defaults = {
            "doctype": "SLA Definition",
            "sla_code": unique("SLA"),
            "title": "Time spent as a template article",
            "target_doctype": "Guide Article",
            "measure": measure,
            "state_field": "category",
            "state_value": "Templates",
            "target_hours": 10,
            "warning_threshold_pct": 80,
            "calendar": "24x7",
        }
        defaults.update(values)
        return frappe.get_doc(defaults).insert(ignore_permissions=True)

    def move(self, article, category):
        article.category = category
        # The framework skips its change log under test unless asked; the
        # change log is exactly what these clocks are rebuilt from.
        article.save(ignore_permissions=True, ignore_version=False)
        return article


class TestDefinitionValidation(SLACase):
    def test_time_in_state_needs_a_state(self):
        with self.assertRaises(frappe.ValidationError):
            self.definition(state_value=None)

    def test_a_state_field_the_record_does_not_have_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.definition(state_field="no_such_field")

    def test_a_doctype_without_change_tracking_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.definition(target_doctype="Notification Dispatch", state_field="status", state_value="Queued")

    def test_a_threshold_outside_a_percentage_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.definition(warning_threshold_pct=150)

    def test_total_open_time_needs_no_state(self):
        self.definition(measure="Total Open Time", state_field=None, state_value=None)


class TestTimeInState(SLACase):
    def setUp(self):
        super().setUp()
        self.sla = self.definition()
        self.article = make_guide_article(category="Getting Started")

    def sync(self):
        return sla.sync_state_clocks("Guide Article", names=[self.article.name])

    def test_a_record_outside_the_state_has_no_clock(self):
        self.sync()
        self.assertEqual(clocks_for(self.sla.name, self.article.name), [])

    def test_entering_the_state_starts_a_clock_when_it_happened(self):
        # The hourly job is the safety net for a move the live hook did not see,
        # and that is the case measured here: the change log says the move
        # happened 90 minutes ago and nothing has clocked it yet. The live hook
        # is held off for the move. Left to itself it would already have started
        # a clock "now", and moving only the log 90 minutes back would then
        # leave the log and that clock disagreeing, so the job would cancel it
        # and open a second. Whether the hook fires at all also depended on a
        # site-wide cache of measured record types that a concurrent run can
        # fill without this test's definition, which is why this test passed or
        # failed depending on what else was running when it ran.
        with patch.object(sla, "on_subject_update"):
            self.move(self.article, "Templates")
        self.assertEqual(clocks_for(self.sla.name, self.article.name), [], "nothing has clocked the move yet")
        backdate_versions(self.article.name, 90)
        self.sync()
        [clock] = clocks_for(self.sla.name, self.article.name)
        self.assertTrue(clock.is_open)
        entered = frappe.get_all("Version", filters={"ref_doctype": "Guide Article", "docname": self.article.name},
                                 pluck="creation")[0]
        self.assertEqual(get_datetime(clock.started_on), get_datetime(entered),
                         msg="the clock starts at the change, not when the job noticed it")

    def test_leaving_stops_it_and_coming_back_starts_another(self):
        self.move(self.article, "Templates")
        self.sync()
        self.move(self.article, "Getting Started")
        self.sync()
        [stopped] = clocks_for(self.sla.name, self.article.name)
        self.assertFalse(stopped.is_open)
        self.assertEqual(stopped.status, "Met")

        self.move(self.article, "Templates")
        self.sync()
        clocks = clocks_for(self.sla.name, self.article.name)
        self.assertEqual(len(clocks), 2)
        self.assertTrue(clocks[-1].is_open)

    def test_synchronising_again_changes_nothing(self):
        self.move(self.article, "Templates")
        self.sync()
        before = clocks_for(self.sla.name, self.article.name)
        self.assertEqual(self.sync(), [])
        self.assertEqual(clocks_for(self.sla.name, self.article.name), before)

    def test_history_missed_while_the_job_was_not_running_is_rebuilt(self):
        # In and out and in again, with no synchronisation in between.
        self.move(self.article, "Templates")
        self.move(self.article, "Getting Started")
        self.move(self.article, "Templates")
        self.sync()
        clocks = clocks_for(self.sla.name, self.article.name)
        self.assertEqual([c.is_open for c in clocks], [0, 1])

    def test_the_live_hook_and_the_hourly_job_agree(self):
        self.move(self.article, "Templates")
        sla.on_subject_update(self.article)
        [live] = clocks_for(self.sla.name, self.article.name)
        self.sync()
        self.assertEqual([c.name for c in clocks_for(self.sla.name, self.article.name)], [live.name])

        self.move(self.article, "Getting Started")
        sla.on_subject_update(self.article)
        [stopped] = clocks_for(self.sla.name, self.article.name)
        self.assertFalse(stopped.is_open)

    def test_a_record_the_definition_does_not_apply_to_is_not_measured(self):
        self.sla.applies_when = frappe.as_json({"applies_to_module": "Policy"})
        self.sla.save(ignore_permissions=True)
        self.move(self.article, "Templates")
        self.sync()
        self.assertEqual(clocks_for(self.sla.name, self.article.name), [])

    def test_the_hourly_job_finds_changed_records_by_itself(self):
        self.move(self.article, "Templates")
        from consilium.consilium_core import reminders

        reminders.hourly()
        self.assertEqual(len(clocks_for(self.sla.name, self.article.name)), 1)


class TestTimeToFirstAction(SLACase):
    def test_the_clock_runs_from_creation_to_the_first_change(self):
        definition = self.definition(measure=sla.MEASURE_FIRST_ACTION, state_field=None, state_value=None)
        article = make_guide_article()
        sla.sync_state_clocks("Guide Article", names=[article.name])
        [clock] = clocks_for(definition.name, article.name)
        self.assertTrue(clock.is_open)
        self.assertEqual(get_datetime(clock.started_on), get_datetime(article.creation))

        article.body = "<p>Reviewed and expanded.</p>"
        article.save(ignore_permissions=True, ignore_version=False)
        sla.sync_state_clocks("Guide Article", names=[article.name])
        [clock] = clocks_for(definition.name, article.name)
        self.assertFalse(clock.is_open)
        self.assertEqual(clock.status, "Met")

        # A second change is not a first action: nothing restarts.
        article.body = "<p>Again.</p>"
        article.save(ignore_permissions=True, ignore_version=False)
        sla.sync_state_clocks("Guide Article", names=[article.name])
        self.assertEqual(len(clocks_for(definition.name, article.name)), 1)


class TestWarningsAndBreaches(SLACase):
    def setUp(self):
        super().setUp()
        self.owner = make_user()
        self.sla = self.definition()
        self.article = make_guide_article(category="Getting Started")
        frappe.db.set_value("Guide Article", self.article.name, "owner", self.owner)
        self.clock = sla.start_clock(self.sla.name, "Guide Article", self.article.name,
                                     started_on=add_to_date(now(), hours=-9))

    def dispatches(self, event_word):
        return frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Guide Article", "subject_name": self.article.name,
                     "rendered_subject": ["like", f"%{event_word}%"]},
            fields=["recipient", "rendered_subject"],
        )

    def test_a_clock_past_its_threshold_warns_once(self):
        sla.sweep()
        sla.sweep()
        warnings = self.dispatches("Approaching")
        self.assertEqual([w.recipient for w in warnings], [self.owner])
        self.clock.reload()
        self.assertTrue(self.clock.warning_sent_on)
        self.assertTrue(self.clock.is_open, msg="a warning is not a breach")

    def test_a_clock_below_its_threshold_is_quiet(self):
        frappe.db.set_value("SLA Clock", self.clock.name, {
            "started_on": add_to_date(now(), hours=-1), "target_on": add_to_date(now(), hours=9)})
        sla.sweep()
        self.assertEqual(self.dispatches("Approaching"), [])

    def test_no_threshold_means_no_warning(self):
        frappe.db.set_value("SLA Definition", self.sla.name, "warning_threshold_pct", 0)
        sla.sweep()
        self.assertEqual(self.dispatches("Approaching"), [])

    def test_a_breach_is_recorded_and_announced_once(self):
        frappe.db.set_value("SLA Clock", self.clock.name, "target_on", add_to_date(now(), hours=-1))
        self.assertEqual(sla.sweep(), [self.clock.name])
        self.assertEqual(sla.sweep(), [])
        self.assertEqual([b.recipient for b in self.dispatches("breached")], [self.owner])
        self.clock.reload()
        self.assertEqual(self.clock.status, "Breached")

    def test_escalation_matters_are_not_told_twice_about_a_breach(self):
        self.assertIn("Escalation Matter", sla.BREACH_NOTIFIED_ELSEWHERE)

    def test_stopping_a_breached_clock_keeps_when_it_breached(self):
        frappe.db.set_value("SLA Clock", self.clock.name, "target_on", add_to_date(now(), hours=-1))
        sla.sweep()
        breached_on = frappe.db.get_value("SLA Clock", self.clock.name, "breached_on")
        stopped = sla.stop_clock(self.clock.name, stopped_on=add_to_date(now(), hours=2))
        self.assertEqual(get_datetime(stopped.breached_on), get_datetime(breached_on))
        self.assertTrue(stopped.elapsed_seconds > 0)

    def test_a_notification_failure_does_not_stop_the_sweep(self):
        frappe.db.set_value("SLA Clock", self.clock.name, "target_on", add_to_date(now(), hours=-1))
        with patch.object(notification, "notify", side_effect=RuntimeError("no channel")):
            self.assertEqual(sla.sweep(), [self.clock.name])
        self.assertEqual(frappe.db.get_value("SLA Clock", self.clock.name, "status"), "Breached")


class TestGoverningDocumentSteps(SLACase):
    """P-7: a lifecycle step of a governing document, timed by configuration alone."""

    def test_a_lifecycle_step_is_timed_from_entry_to_exit(self):
        from contextlib import contextmanager

        from consilium.consilium_core import versioning
        from consilium.policy import lifecycle
        from consilium.policy.tests.utils import make_document, make_user_group

        @contextmanager
        def change_log():
            # The workflow saves through the framework, which skips its change
            # log under test; the clocks are rebuilt from that log.
            flag = frappe.flags.in_test
            frappe.flags.in_test = False
            try:
                yield
            finally:
                frappe.flags.in_test = flag

        definition = self.definition(target_doctype="Governing Document", state_field="lifecycle_phase",
                                     state_value="Review", title="Review step")
        doc = make_document()
        doc.append("applicability", {"scope_type": "Organization Unit", "scope_value": doc.owning_operating_group,
                                     "notification_group": make_user_group([make_user()])})
        doc.save(ignore_permissions=True)
        versioning.create_version(doc, change_summary="First upload.", origin="Uploaded", version_label="1.0")

        with change_log():
            lifecycle.perform(doc, "Submit for Review")
        sla.sync_state_clocks("Governing Document", names=[doc.name])
        [clock] = frappe.get_all("SLA Clock", filters={"sla_definition": definition.name, "subject_name": doc.name},
                                 fields=["name", "is_open"])
        self.assertTrue(clock.is_open)

        # The approval chain is not this test's subject; Record Approval is
        # only the way out of the step being timed.
        from consilium.policy.tests.test_lifecycle import approval_gate_off

        approval_gate_off()
        with change_log():
            lifecycle.perform(doc, "Record Approval")
        sla.sync_state_clocks("Governing Document", names=[doc.name])
        stopped = frappe.get_doc("SLA Clock", clock.name)
        self.assertFalse(stopped.is_open)
        self.assertEqual(stopped.status, "Met")
