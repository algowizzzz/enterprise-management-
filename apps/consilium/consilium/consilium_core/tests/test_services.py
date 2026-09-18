"""Service levels, AI provenance, approval decisions and watched fields."""

import frappe
from frappe.utils import add_to_date, now

from consilium.consilium_core import approvals, provenance, sla, versioning, watched_fields
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user, unique


class TestServiceLevels(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article()
        self.definition = frappe.get_doc(
            {
                "doctype": "SLA Definition",
                "sla_code": unique("SLA"),
                "title": "Time to close",
                "target_doctype": "Guide Article",
                "measure": "Total Open Time",
                "target_hours": 24,
                "warning_threshold_pct": 80,
                "calendar": "24x7",
            }
        ).insert(ignore_permissions=True)

    def test_a_clock_starts_once_per_record(self):
        first = sla.start_clock(self.definition.name, "Guide Article", self.article.name)
        second = sla.start_clock(self.definition.name, "Guide Article", self.article.name)
        self.assertEqual(first.name, second.name)
        self.assertTrue(first.is_open)

    def test_stopping_inside_the_target_meets_it(self):
        clock = sla.start_clock(self.definition.name, "Guide Article", self.article.name)
        stopped = sla.stop_clock(clock, stopped_on=add_to_date(clock.started_on, hours=2, as_string=True))
        self.assertEqual(stopped.status, "Met")
        self.assertFalse(stopped.is_open)
        self.assertGreater(stopped.elapsed_seconds, 0)

    def test_stopping_past_the_target_breaches_it(self):
        clock = sla.start_clock(self.definition.name, "Guide Article", self.article.name)
        stopped = sla.stop_clock(clock, stopped_on=add_to_date(clock.started_on, hours=48, as_string=True))
        self.assertEqual(stopped.status, "Breached")
        self.assertTrue(stopped.breached_on)

    def test_the_sweep_breaches_an_overdue_clock(self):
        started = add_to_date(now(), hours=-72, as_string=True)
        clock = sla.start_clock(self.definition.name, "Guide Article", self.article.name, started_on=started)
        sla.sweep()
        clock.reload()
        self.assertEqual(clock.status, "Breached")

    def test_business_hours_skip_a_non_working_day(self):
        calendar = frappe.get_doc(
            {
                "doctype": "Business Calendar",
                "calendar_code": unique("CAL"),
                "title": "Standard week",
                "day_start": "09:00:00",
                "day_end": "17:00:00",
                "works_saturday": 0,
                "works_sunday": 0,
            }
        ).insert(ignore_permissions=True)
        definition = frappe.get_doc(
            {
                "doctype": "SLA Definition",
                "sla_code": unique("SLA"),
                "title": "Business hours",
                "target_doctype": "Guide Article",
                "measure": "Total Open Time",
                "target_hours": 8,
                "calendar": "Business Hours",
                "business_calendar": calendar.name,
            }
        ).insert(ignore_permissions=True)
        # Friday 15:00 plus eight working hours lands on the Monday, not Saturday.
        target = sla.target_datetime(definition, "2026-01-02 15:00:00")
        self.assertTrue(str(target).startswith("2026-01-05"))

    def test_a_calendar_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Business Calendar",
                    "calendar_code": unique("CAL"),
                    "title": "Impossible",
                    "day_start": "17:00:00",
                    "day_end": "09:00:00",
                }
            ).insert(ignore_permissions=True)


class TestProvenance(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article()

    def test_a_request_and_its_response_are_recorded_once(self):
        request = provenance.record_request(
            capability="summarise",
            context_sent="Body text sent for summary.",
            context_classification="Internal",
            subject_doctype="Guide Article",
            subject_name=self.article.name,
        )
        self.assertEqual(request.status, "Sent")

        provenance.record_response(request, status="Succeeded", payload="A summary.", duration_ms=120)
        request.reload()
        self.assertEqual(request.status, "Succeeded")

        request.response_received_on = now()
        with self.assertRaises(frappe.ValidationError):
            request.save(ignore_permissions=True)

    def test_a_request_field_cannot_be_rewritten(self):
        request = provenance.record_request(capability="summarise", context_sent="Original context.")
        request.context_sent = "Something else"
        with self.assertRaises(frappe.PermissionError):
            request.save(ignore_permissions=True)
        self.purge_on_teardown(request.doctype, request.name)

    def test_an_acceptance_records_who_took_responsibility_and_against_which_version(self):
        version = versioning.create_version(self.article, change_summary="First")
        request = provenance.record_request(capability="draft", context_sent="context")
        acceptance = provenance.record_acceptance(
            ai_service_request=request.name,
            subject_doctype="Guide Article",
            subject_name=self.article.name,
            target_fieldname="body",
            suggested_value="Suggested wording.",
            accepted_value="Edited wording.",
        )
        self.assertEqual(acceptance.applied_to_version, version.name)
        self.assertTrue(acceptance.edited_before_accept)
        self.assertEqual(acceptance.accepted_by, frappe.session.user)

    def test_an_acceptance_cannot_be_edited(self):
        request = provenance.record_request(capability="draft", context_sent="context")
        acceptance = provenance.record_acceptance(
            ai_service_request=request.name,
            subject_doctype="Guide Article",
            subject_name=self.article.name,
            target_fieldname="body",
            suggested_value="Same",
            accepted_value="Same",
        )
        self.assertFalse(acceptance.edited_before_accept)
        acceptance.accepted_value = "Changed"
        with self.assertRaises(frappe.PermissionError):
            acceptance.save(ignore_permissions=True)
        self.purge_on_teardown("Guide Article", self.article.name)
        # The refusal names the acceptance itself, whose reference restarts from
        # the same number once this test rolls back.
        self.purge_on_teardown(acceptance.doctype, acceptance.name)


class TestApprovals(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article()
        self.approver = make_user()
        self.delegate = make_user()
        self.stranger = make_user()
        self.decision = approvals.request_decision(
            subject_doctype="Guide Article",
            subject_name=self.article.name,
            approval_step="Second line review",
            assigned_to=self.approver,
        )

    def test_a_pending_decision_is_outstanding(self):
        self.assertTrue(self.decision.is_open)
        self.assertEqual(
            approvals.outstanding("Guide Article", self.article.name), [self.decision.name]
        )

    def test_the_named_approver_can_decide(self):
        decided = approvals.record_decision(
            self.decision, "Approved", comments="Reviewed.", acting_user=self.approver
        )
        self.assertFalse(decided.is_open)
        self.assertEqual(decided.acted_by, self.approver)
        self.assertIsNone(decided.acting_delegation)

    def test_a_delegate_decides_under_a_recorded_delegation(self):
        delegation_row = frappe.get_doc(
            {
                "doctype": "Authority Delegation",
                "delegator": self.approver,
                "delegate": self.delegate,
                "scope_type": "DocType",
                "scope_doctype": "Guide Article",
                "valid_from": frappe.utils.nowdate(),
                "delegated_actions": [{"delegable_action": "APPROVE"}],
            }
        ).insert(ignore_permissions=True)

        decided = approvals.record_decision(self.decision, "Approved", acting_user=self.delegate)
        self.assertEqual(decided.acting_delegation, delegation_row.name)
        self.assertEqual(decided.acted_by, self.delegate)
        self.assertEqual(decided.assigned_to, self.approver)

    def test_someone_with_no_delegation_is_refused_and_audited(self):
        with self.assertRaises(frappe.PermissionError):
            approvals.record_decision(self.decision, "Approved", acting_user=self.stranger)
        self.purge_on_teardown("Guide Article", self.article.name)

    def test_the_decision_records_the_version_it_was_given_against(self):
        version = versioning.create_version(self.article, change_summary="For approval")
        decision = approvals.request_decision(
            subject_doctype="Guide Article",
            subject_name=self.article.name,
            approval_step="Policy office",
            assigned_to=self.approver,
            step_sequence=2,
        )
        self.assertEqual(decision.based_on_version, version.name)


class TestWatchedFields(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article(category="Getting Started")
        frappe.get_doc(
            {
                "doctype": "Watched Field Set",
                "target_doctype": "Guide Article",
                "is_active": 1,
                "on_change_action": "Raise Review Task",
                "fields": [
                    {"fieldname": "category", "compare_mode": "Any Change"},
                    {"fieldname": "is_published", "compare_mode": "Set From Empty"},
                ],
            }
        ).insert(ignore_permissions=True)
        watched_fields.clear_cache()

    def test_a_change_to_a_watched_field_raises_a_review_task(self):
        self.article.category = "Policy Lifecycle"
        self.article.save(ignore_permissions=True)
        todos = frappe.get_all(
            "ToDo",
            filters={"reference_type": "Guide Article", "reference_name": self.article.name},
            pluck="description",
        )
        self.assertTrue(todos)
        self.assertIn("Category", todos[0])

    def test_a_change_to_an_unwatched_field_does_nothing(self):
        self.article.title = "New title"
        self.article.save(ignore_permissions=True)
        self.assertEqual(
            frappe.db.count("ToDo", {"reference_type": "Guide Article", "reference_name": self.article.name}), 0
        )

    def test_the_compare_mode_decides_what_counts_as_a_change(self):
        self.article.is_published = 1
        hits = {hit["fieldname"] for hit in self._changes()}
        self.assertIn("is_published", hits)

        self.article.reload()
        self.article.is_published = 0
        self.assertNotIn("is_published", {hit["fieldname"] for hit in self._changes()})

    def _changes(self):
        self.article._doc_before_save = frappe.get_doc("Guide Article", self.article.name)
        return watched_fields.changed_watched_fields(self.article)

    def test_a_watched_field_that_does_not_exist_is_refused(self):
        frappe.delete_doc("Watched Field Set", "Guide Article", ignore_permissions=True, force=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Watched Field Set",
                    "target_doctype": "Guide Article",
                    "on_change_action": "Notify Only",
                    "fields": [{"fieldname": "not_a_field", "compare_mode": "Any Change"}],
                }
            ).insert(ignore_permissions=True)
