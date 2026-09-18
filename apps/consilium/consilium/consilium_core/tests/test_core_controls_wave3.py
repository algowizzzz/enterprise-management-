"""Core controls closed in wave 3.

Each class names the story or defect it covers; each test failed, or the
behaviour did not exist, before its change.

* E7-S4 — a sequential approval step cannot be decided before the steps ahead.
* Core revert restores content, never the lifecycle phase or workflow state
  (the policy-side proof is in ``policy/tests/test_wave3_policy.py``).
* ``importing.validate_batch`` could not validate a batch twice on PostgreSQL.
* Watched fields raise a templated event.
* E4-S2 — a record's history lists the notifications sent about it.
* E4-S4 — a record's evidence pack.
* E5-S5 — records past their retention period are flagged for disposal review.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import (
    approvals,
    evidence,
    importing,
    inbox,
    notification,
    retention,
    versioning,
    watched_fields,
)
from consilium.consilium_core.setup import notification_templates
from consilium.consilium_core.tests.utils import (
    CoreTestCase,
    make_guide_article,
    make_user,
    refusals_for,
    unique,
)


# ------------------------------------------------------------------ E7-S4


def _inbox_references() -> list[str]:
    return [item["reference"] for group in inbox.my_tasks()["groups"] for item in group["items"]]


class TestSequentialApprovals(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article()
        self.first_approver = make_user()
        self.second_approver = make_user()
        self.first = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="First line", assigned_to=self.first_approver, step_sequence=1,
        )
        self.second = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="Second line", assigned_to=self.second_approver, step_sequence=2,
        )
        self.purge_on_teardown("Guide Article", self.article.name)

    def test_a_later_sequential_step_is_refused_until_the_earlier_one_is_decided(self):
        self.assertFalse(approvals.is_turn(self.second.name))
        with self.assertRaises(frappe.ValidationError):
            approvals.record_decision(self.second.name, "Approved", acting_user=self.second_approver)
        self.assertTrue(frappe.db.get_value("Approval Decision", self.second.name, "is_open"))

        refusal = refusals_for("Guide Article", self.article.name)[-1]
        self.assertEqual(refusal["control"], "sequential approval order")
        self.assertIn("First line", refusal["refusal_reason"])

        approvals.record_decision(self.first.name, "Approved", acting_user=self.first_approver)
        self.assertTrue(approvals.is_turn(self.second.name))
        decided = approvals.record_decision(self.second.name, "Approved", acting_user=self.second_approver)
        self.assertFalse(decided.is_open)

    def test_a_parallel_step_does_not_wait(self):
        parallel = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="Sponsor", assigned_to=self.second_approver, step_sequence=2, mode="Parallel",
        )
        decided = approvals.record_decision(parallel.name, "Approved", acting_user=self.second_approver)
        self.assertFalse(decided.is_open)

    def test_steps_sharing_a_sequence_number_are_peers(self):
        peer = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="First line peer", assigned_to=self.second_approver, step_sequence=1,
        )
        decided = approvals.record_decision(peer.name, "Approved", acting_user=self.second_approver)
        self.assertFalse(decided.is_open)

    def test_a_bypass_under_an_exception_authorisation_is_not_held_to_the_order(self):
        authorisation = frappe.get_doc(
            {
                "doctype": "Exception Authorisation",
                "subject_doctype": "Guide Article",
                "subject_name": self.article.name,
                "exception_type": "Approval Bypass",
                "justification": "Second line is unavailable for the quarter.",
                "requested_by": frappe.session.user,
                "approved_by": frappe.session.user,
                "approved_on": frappe.utils.now(),
            }
        ).insert(ignore_permissions=True)
        decided = approvals.record_decision(
            self.second.name, "Bypassed", acting_user=self.second_approver,
            exception_authorisation=authorisation.name,
        )
        self.assertFalse(decided.is_open)

    def test_an_earlier_cycles_open_step_does_not_block_this_cycle(self):
        # The two steps above were raised against no version. A new version
        # starts a new cycle; its first step is at sequence 2 of a route whose
        # sequence 1 step belongs to the old cycle.
        versioning.create_version(self.article, change_summary="Changed after the first cycle")
        new_cycle = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="Second line (new version)", assigned_to=self.second_approver, step_sequence=2,
        )
        self.assertTrue(new_cycle.based_on_version)
        self.assertTrue(approvals.is_turn(new_cycle.name))

    def test_the_inbox_offers_a_step_only_when_it_is_the_approvers_turn(self):
        frappe.set_user(self.second_approver)
        try:
            listed = _inbox_references()
        finally:
            frappe.set_user("Administrator")
        self.assertNotIn(self.second.name, listed)
        approvals.record_decision(self.first.name, "Approved", acting_user=self.first_approver)
        frappe.set_user(self.second_approver)
        try:
            listed = _inbox_references()
        finally:
            frappe.set_user("Administrator")
        self.assertIn(self.second.name, listed)


# ------------------------------------------------------------------ revert


class TestCoreRevertProtectsState(CoreTestCase):
    def test_the_protected_fields_are_the_state_fields_and_the_flags(self):
        protected = versioning.protected_fields("Governing Document")
        for fieldname in ("lifecycle_phase", "workflow_state", "is_editable", "is_active", "current_version"):
            self.assertIn(fieldname, protected)
        self.assertNotIn("document_name", protected)

    def test_a_guide_article_still_reverts_its_content(self):
        article = make_guide_article(title="Original")
        first = versioning.create_version(article, change_summary="First")
        article.title = "Changed"
        article.save(ignore_permissions=True)
        versioning.create_version(article, change_summary="Second")
        versioning.revert_to_version("Guide Article", article.name, first.name, "Back to the original.")
        article.reload()
        self.assertEqual(article.title, "Original")


# --------------------------------------------------------------- importing


class TestRevalidatingABatch(CoreTestCase):
    def test_a_batch_with_a_refused_row_validates_again(self):
        """The second validation deleted the staged rows through the framework's
        archive, which on PostgreSQL refused the row's JSON messages list:
        "Value for Messages cannot be a list"."""
        system = frappe.get_doc(
            {"doctype": "External System", "system_code": unique("SYS"), "title": "Upstream register"}
        ).insert(ignore_permissions=True)
        profile = frappe.get_doc(
            {
                "doctype": "Import Profile",
                "profile_title": unique("profile"),
                "source_system": system.name,
                "target_doctype": "Risk Type",
                "key_strategy": "External Key",
                "external_key_column": "id",
                "on_missing_required": "Reject Row",
                "on_unknown_taxonomy": "Reject Row",
                "on_duplicate_key": "Update",
                "mappings": [
                    {"source_column": "code", "target_fieldname": "risk_type_code",
                     "transform": "Trim", "is_required": 1},
                    {"source_column": "name", "target_fieldname": "risk_type_name",
                     "transform": "Trim", "is_required": 1},
                    {"source_column": "tier", "target_fieldname": "tier", "transform": "None",
                     "is_required": 1},
                ],
            }
        ).insert(ignore_permissions=True)
        batch = frappe.get_doc(
            {
                "doctype": "Import Batch",
                "batch_reference": unique("batch"),
                "source_system": system.name,
                "import_profile": profile.name,
                "target_doctype": "Risk Type",
                "received_on": frappe.utils.now(),
                "status": "Uploaded",
            }
        ).insert(ignore_permissions=True)
        rows = [
            {"id": "R-1", "code": unique("RT").upper(), "name": "Complete", "tier": "1"},
            {"id": "R-2", "code": "", "name": "Missing its code", "tier": "1"},
        ]
        first = importing.validate_batch(batch.name, rows)
        second = importing.validate_batch(batch.name, rows)
        self.assertEqual(first, second)
        self.assertEqual(second["errors"], 1)
        self.assertEqual(frappe.db.count("Import Row", {"import_batch": batch.name}), 2)


# ---------------------------------------------------------- watched fields


class TestWatchedFieldEvent(CoreTestCase):
    def setUp(self):
        frappe.flags.mute_emails = True
        notification_templates.seed_all()
        self.article = make_guide_article(category="Getting Started")
        frappe.get_doc(
            {
                "doctype": "Watched Field Set",
                "target_doctype": "Guide Article",
                "is_active": 1,
                "on_change_action": "Notify Only",
                "fields": [{"fieldname": "category", "compare_mode": "Any Change"}],
            }
        ).insert(ignore_permissions=True)
        watched_fields.clear_cache()

    def tearDown(self):
        frappe.flags.mute_emails = False
        super().tearDown()

    def test_notify_only_raises_the_templated_event(self):
        self.article.category = "Policy Lifecycle"
        self.article.save(ignore_permissions=True)
        rows = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Guide Article", "subject_name": self.article.name},
            fields=["rendered_subject", "rendered_body"],
        )
        self.assertTrue(rows)
        self.assertIn(f"Watched field changed on Guide Article {self.article.name}", rows[0].rendered_subject)
        self.assertIn("Category", rows[0].rendered_body)


# ---------------------------------------------------- E4-S2 and E4-S4


class TestHistoryAndEvidencePack(CoreTestCase):
    def setUp(self):
        frappe.flags.mute_emails = True
        notification_templates.seed_all()
        self.article = make_guide_article(title="Evidence subject")
        self.recipient = make_user()
        # Guide Article does not track changes, so the framework's change row is
        # written here the way ``track_changes`` would write it.
        frappe.get_doc(
            {
                "doctype": "Version",
                "ref_doctype": "Guide Article",
                "docname": self.article.name,
                "data": json.dumps({"changed": [["title", "Evidence subject", "Evidence subject, retitled"]]}),
            }
        ).insert(ignore_permissions=True)
        self.article.add_comment("Comment", "Checked against the source.")
        self.dispatched = notification.notify(
            "core.watched_field.changed", [self.recipient], {"summary": "Title"},
            "Guide Article", self.article.name,
        )
        self.purge_on_teardown("Guide Article", self.article.name)

    def tearDown(self):
        frappe.flags.mute_emails = False
        frappe.local.response = frappe._dict()
        super().tearDown()

    def test_the_history_lists_changes_comments_and_notifications_in_one_list(self):
        history = evidence.record_history("Guide Article", self.article.name)
        kinds = {entry["kind"] for entry in history["entries"]}
        self.assertTrue({"change", "comment", "notification"} <= kinds, kinds)
        change = next(e for e in history["entries"] if e["kind"] == "change")
        self.assertIn("Title", change["summary"], "field changes are told by label, in plain language")
        notices = [e for e in history["entries"] if e["kind"] == "notification"]
        self.assertIn(self.recipient, [e["recipient"] for e in notices])
        stamps = [entry["on"] for entry in history["entries"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True), "newest first")

    def test_the_history_is_refused_to_someone_who_cannot_read_the_record(self):
        frappe.set_user(make_user())
        try:
            with self.assertRaises(frappe.PermissionError):
                evidence.record_history("Consilium Nonexistent", "X")
        finally:
            frappe.set_user("Administrator")

    def _pack(self) -> zipfile.ZipFile:
        evidence.export_pack("Guide Article", self.article.name)
        response = frappe.local.response
        self.assertEqual(response.type, "download")
        self.assertTrue(response.filename.endswith(".zip"))
        return zipfile.ZipFile(io.BytesIO(response.filecontent))

    def test_the_pack_holds_the_record_its_history_and_a_verifiable_manifest(self):
        attached = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": "evidence-note.txt",
                "content": b"attached evidence",
                "attached_to_doctype": "Guide Article",
                "attached_to_name": self.article.name,
                "is_private": 1,
            }
        ).insert(ignore_permissions=True)
        pack = self._pack()
        names = set(pack.namelist())
        for part in ("manifest.json", "record.json", "history.json", "revisions.json", "approvals.json",
                     "refusals.json", "notifications.json"):
            self.assertIn(part, names)

        record = json.loads(pack.read("record.json"))
        self.assertEqual(record["name"], self.article.name)
        notices = json.loads(pack.read("notifications.json"))
        self.assertIn(self.dispatched[0], [row["name"] for row in notices["dispatches"]])

        manifest = json.loads(pack.read("manifest.json"))
        self.assertEqual(manifest["subject_name"], self.article.name)
        for entry in manifest["entries"]:
            self.assertEqual(hashlib.sha256(pack.read(entry["path"])).hexdigest(), entry["sha256"])
        attachment_paths = [row["path"] for row in manifest["attachments"]]
        self.assertEqual(len(attachment_paths), 1)
        self.assertEqual(pack.read(attachment_paths[0]), b"attached evidence")
        self.assertEqual(manifest["attachments"][0]["file"], attached.name)

    def test_the_pack_is_refused_without_an_evidence_role_and_the_refusal_is_audited(self):
        # Guide Article is readable by every desk user, so read access alone is
        # what this user has.
        reader = make_user("Consilium Author") if frappe.db.exists("Role", "Consilium Author") else make_user()
        frappe.set_user(reader)
        try:
            with self.assertRaises(frappe.PermissionError):
                evidence.export_pack("Guide Article", self.article.name)
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(refusals_for("Guide Article", self.article.name)[-1]["control"], "evidence pack export")


# ------------------------------------------------------------------ E5-S5


class TestScheduledDisposalReview(CoreTestCase):
    def setUp(self):
        self.article = make_guide_article(category="Getting Started")
        self.retention_class = frappe.get_doc(
            {
                "doctype": "Retention Class",
                "class_code": unique("RC"),
                "title": "Short retention",
                "retention_period_months": 1,
                "trigger_event": "Creation",
                "disposition_action": "Review",
                "requires_worm": 0,
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

    def _archive(self, due_on):
        return frappe.get_doc(
            {
                "doctype": "Archive Record",
                "subject_doctype": "Guide Article",
                "subject_name": self.article.name,
                "archived_on": frappe.utils.now(),
                "retention_class": self.retention_class.name,
                "disposition_due_on": due_on,
                "payload_sha256": "0" * 64,
            }
        ).insert(ignore_permissions=True)

    def _events(self, archive):
        return frappe.get_all(
            "Disposition Event", filters={"archive_record": archive.name},
            fields=["name", "status", "is_open", "held_by_legal_hold", "executed_on"],
        )

    def test_a_record_past_its_retention_is_flagged_once_and_nothing_is_deleted(self):
        archive = self._archive(add_days(nowdate(), -1))
        flagged = retention.flag_due_for_disposal()
        events = self._events(archive)
        self.assertEqual(len(events), 1)
        self.assertIn(events[0].name, flagged["scheduled"])
        self.assertTrue(events[0].is_open, "flagged for review, awaiting an approver")
        self.assertFalse(events[0].executed_on)
        self.assertTrue(frappe.db.exists("Guide Article", self.article.name), "nothing is deleted")

        retention.flag_due_for_disposal()
        self.assertEqual(len(self._events(archive)), 1, "a second run flags nothing new")

    def test_a_record_still_within_retention_is_not_flagged(self):
        archive = self._archive(add_days(nowdate(), 30))
        retention.flag_due_for_disposal()
        self.assertEqual(self._events(archive), [])

    def test_a_held_record_is_flagged_as_held(self):
        archive = self._archive(add_days(nowdate(), -1))
        frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "placed_on": nowdate(),
                "scope_doctype": "Guide Article",
                "scope_filter": json.dumps({"name": self.article.name}),
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()
        flagged = retention.flag_due_for_disposal()
        events = self._events(archive)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].held_by_legal_hold)
        self.assertIn(events[0].name, flagged["held"])

    def test_a_hold_placed_after_scheduling_holds_the_scheduled_disposal(self):
        archive = self._archive(add_days(nowdate(), -1))
        retention.flag_due_for_disposal()
        frappe.get_doc(
            {
                "doctype": "Legal Hold",
                "hold_reference": unique("HOLD"),
                "placed_on": nowdate(),
                "scope_doctype": "Guide Article",
                "scope_filter": json.dumps({"name": self.article.name}),
            }
        ).insert(ignore_permissions=True)
        retention.clear_cache()
        retention.flag_due_for_disposal()
        events = self._events(archive)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].held_by_legal_hold)

    def test_the_job_is_on_the_daily_schedule(self):
        daily = frappe.get_hooks("scheduler_events").get("daily") or []
        self.assertIn("consilium.consilium_core.retention.flag_due_for_disposal", daily)
