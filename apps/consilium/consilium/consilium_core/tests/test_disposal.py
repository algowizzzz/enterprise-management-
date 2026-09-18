"""The records manager's disposal screen and archiving on the retention trigger
(G-16, P-18, E-18; consilium_core/records.py).

What these hold the platform to:

* a record reaching its terminal retention trigger is archived — hashed,
  chained, read-only — and the daily flag then puts it up for a decision;
* a disposal decision takes two people, and nobody approves their own;
* a legal hold refuses disposal at every step, and each refusal is audited;
* executing a disposal redacts in place and logs what it did: nothing is
  deleted, and the record stays as a tombstone;
* a decision to retain holds the record back from the flag until its date;
* the screen and its endpoints are for records managers only.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import records, retention
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user, refusals_for, unique


class DisposalCase(CoreTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.article = make_guide_article(category="Policy Lifecycle", body="<p>Confidential body text.</p>")
		self.retention_class = frappe.get_doc({
			"doctype": "Retention Class", "class_code": unique("RC"), "title": "Already elapsed",
			"retention_period_months": 0, "trigger_event": "Creation", "disposition_action": "Review",
			"requires_worm": 0, "is_active": 1,
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "Retention Assignment", "assignment_title": unique("assignment"),
			"target_doctype": "Guide Article", "record_filter": json.dumps({"name": self.article.name}),
			"retention_class": self.retention_class.name, "priority": 900, "is_active": 1,
		}).insert(ignore_permissions=True)
		retention.clear_cache()
		self.first = make_user("Records Manager")
		self.second = make_user("Records Manager")
		self.purge_on_teardown("Guide Article", self.article.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def due_event(self) -> str:
		self.archive = records.archive("Guide Article", self.article.name)
		out = retention.flag_due_for_disposal(add_days(nowdate(), 1))
		events = frappe.get_all("Disposition Event", filters={"archive_record": self.archive}, pluck="name")
		self.assertEqual(len(events), 1)
		self.assertIn(events[0], out["scheduled"] + out["held"])
		return events[0]

	def place_hold(self) -> str:
		hold = frappe.get_doc({
			"doctype": "Legal Hold", "hold_reference": unique("HOLD"), "description": "Litigation.",
			"placed_on": nowdate(), "scope_doctype": "Guide Article",
			"scope_filter": json.dumps({"name": self.article.name}),
		}).insert(ignore_permissions=True)
		retention.clear_cache()
		return hold.name

	def as_(self, user):
		frappe.set_user(user)


class TestArchiving(DisposalCase):
	def test_archiving_writes_a_hashed_payload_and_makes_the_record_read_only(self):
		name = records.archive("Guide Article", self.article.name)
		archive = frappe.get_doc("Archive Record", name)
		self.assertEqual(archive.retention_class, self.retention_class.name)
		self.assertEqual(len(archive.payload_sha256), 64)
		self.assertTrue(archive.chain_hash)
		payload = frappe.get_doc("File", {"file_url": archive.payload_file}).get_content()
		self.assertIn("Confidential body text", payload if isinstance(payload, str) else payload.decode())
		self.assertIn("archived", retention.retention_lock("Guide Article", self.article.name)["reason"])
		# Idempotent: a second call returns the same archive.
		self.assertEqual(records.archive("Guide Article", self.article.name), name)

	def test_a_disbanded_forum_is_archived_on_its_trigger_and_a_live_one_is_not(self):
		from consilium.governance.tests.utils import make_forum

		gov_class = frappe.get_doc({
			"doctype": "Retention Class", "class_code": unique("RC"), "title": "After disbandment",
			"retention_period_months": 120, "trigger_event": "Disbandment",
			"disposition_action": "Archive Permanently", "is_active": 1,
		}).insert(ignore_permissions=True)
		gone = make_forum(disbanded_on=add_days(nowdate(), -2), is_active=0)
		live = make_forum()
		self.purge_on_teardown("Governance Forum", gone.name)
		self.purge_on_teardown("Governance Forum", live.name)
		frappe.get_doc({
			"doctype": "Retention Assignment", "assignment_title": unique("assignment"),
			"target_doctype": "Governance Forum",
			"record_filter": json.dumps({"name": ["in", [gone.name, live.name]]}),
			"retention_class": gov_class.name, "priority": 900, "is_active": 1,
		}).insert(ignore_permissions=True)
		retention.clear_cache()
		made = records.archive_on_trigger()
		self.assertTrue(records.archived("Governance Forum", gone.name))
		self.assertIn(records.archived("Governance Forum", gone.name), made)
		self.assertFalse(records.archived("Governance Forum", live.name))
		due = frappe.db.get_value("Archive Record", records.archived("Governance Forum", gone.name), "disposition_due_on")
		self.assertEqual(str(due), str(frappe.utils.add_months(add_days(nowdate(), -2), 120)))
		# A second sweep archives nothing new.
		self.assertEqual(records.archive_on_trigger(), [])


class TestTwoPersonDecision(DisposalCase):
	def test_a_proposal_needs_a_second_person_and_the_proposer_is_refused(self):
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Dispose", "Past its period, nothing pending.")
		with self.assertRaises(frappe.PermissionError):
			records.approve_disposition(event)
		self.assertEqual(refusals_for("Guide Article", self.article.name)[-1]["control"], "four eyes")
		self.as_(self.second)
		records.approve_disposition(event, "Agreed.")
		doc = frappe.get_doc("Disposition Event", event)
		self.assertEqual(doc.approved_by, self.second)
		self.assertTrue(int(doc.is_open))

	def test_executing_redacts_in_place_logs_and_deletes_nothing(self):
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Dispose", "Past its period.")
		self.as_(self.second)
		records.approve_disposition(event)
		overview = records.execute_disposition(event)

		doc = frappe.get_doc("Disposition Event", event)
		self.assertFalse(int(doc.is_open))
		self.assertTrue(doc.executed_on)
		self.assertEqual(doc.executed_by, self.second)
		evidence = json.loads(doc.evidence) if isinstance(doc.evidence, str) else doc.evidence
		self.assertIn("body", evidence["fields"])
		self.assertEqual(evidence["archive_payload_sha256"],
			frappe.db.get_value("Archive Record", self.archive, "payload_sha256"))
		# A tombstone: the record is still there, its title kept, its body gone.
		self.assertTrue(frappe.db.exists("Guide Article", self.article.name))
		body = frappe.db.get_value("Guide Article", self.article.name, "body")
		self.assertNotIn("Confidential body text", body)
		self.assertIn(event, body)
		self.assertEqual(frappe.db.get_value("Guide Article", self.article.name, "title"), self.article.title)
		# The archive payload is replaced by a disposal note naming the original hash.
		payload = frappe.get_doc("File", {"file_url": frappe.db.get_value("Archive Record", self.archive,
			"payload_file")}).get_content()
		payload = payload if isinstance(payload, str) else payload.decode()
		self.assertNotIn("Confidential body text", payload)
		self.assertIn(evidence["archive_payload_sha256"], payload)
		# The log shows it.
		self.assertIn(event, [row["name"] for row in overview["decided"]])
		self.assertTrue(frappe.db.exists("Archive Record", self.archive))

	def test_nothing_is_executed_without_approval(self):
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Dispose", "Past its period.")
		with self.assertRaises(frappe.ValidationError):
			records.execute_disposition(event)
		self.assertIn("Confidential body text", frappe.db.get_value("Guide Article", self.article.name, "body"))

	def test_a_permanent_class_cannot_be_disposed_of(self):
		self.retention_class.db_set("disposition_action", "Archive Permanently")
		event = self.due_event()
		self.as_(self.first)
		with self.assertRaises(frappe.ValidationError):
			records.propose_disposition(event, "Dispose", "Tidy up.")
		self.assertEqual(refusals_for("Guide Article", self.article.name)[-1]["control"], "retention class")


class TestLegalHold(DisposalCase):
	def test_a_hold_or_assignment_scoped_by_name_covers_only_that_record(self):
		"""Regression: the record's name used to overwrite the filter's own name
		condition, so a hold on one record froze every record of the DocType."""
		other = make_guide_article(category="Policy Lifecycle")
		self.purge_on_teardown("Guide Article", other.name)
		hold = self.place_hold()
		self.assertEqual(retention.active_legal_hold("Guide Article", self.article.name), hold)
		self.assertIsNone(retention.active_legal_hold("Guide Article", other.name))
		self.assertIsNone(retention.effective_retention("Guide Article", other.name))
		other.title = "Changed freely"
		other.save(ignore_permissions=True)
		self.assertEqual(refusals_for("Guide Article", other.name), [])

	def test_a_hold_refuses_proposal_approval_and_execution_and_is_audited(self):
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Dispose", "Past its period.")
		self.as_(self.second)
		records.approve_disposition(event)
		frappe.set_user("Administrator")
		hold = self.place_hold()
		self.as_(self.second)
		with self.assertRaises(frappe.PermissionError):
			records.execute_disposition(event)
		refusal = refusals_for("Guide Article", self.article.name)[-1]
		self.assertEqual(refusal["control"], "legal hold")
		self.assertEqual(refusal["legal_hold"], hold)
		self.assertIn("Confidential body text", frappe.db.get_value("Guide Article", self.article.name, "body"))

	def test_a_held_record_cannot_be_proposed_for_disposal_until_the_hold_is_released(self):
		hold = self.place_hold()
		event = self.due_event()
		self.assertEqual(frappe.db.get_value("Disposition Event", event, "held_by_legal_hold"), hold)
		self.as_(self.first)
		with self.assertRaises(frappe.PermissionError):
			records.propose_disposition(event, "Dispose", "Past its period.")
		self.assertEqual(refusals_for("Guide Article", self.article.name)[-1]["attempted_action"], "Dispose")
		overview = records.release_legal_hold(hold, "Litigation settled.")
		self.assertFalse(frappe.db.get_value("Legal Hold", hold, "is_active"))
		self.assertFalse(frappe.db.get_value("Disposition Event", event, "held_by_legal_hold"))
		self.assertNotIn(hold, [h["name"] for h in overview["holds"]])
		records.propose_disposition(event, "Dispose", "Past its period, hold released.")

	def test_a_held_record_may_still_be_retained(self):
		self.place_hold()
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Retain", "Keep while the hold runs.", add_days(nowdate(), 365))
		self.as_(self.second)
		records.approve_disposition(event)
		self.assertFalse(int(frappe.db.get_value("Disposition Event", event, "is_open")))


class TestRetain(DisposalCase):
	def test_a_retained_record_is_not_flagged_again_until_its_date(self):
		event = self.due_event()
		until = add_days(nowdate(), 30)
		self.as_(self.first)
		with self.assertRaises(frappe.ValidationError):
			records.propose_disposition(event, "Retain", "No date given.")
		records.propose_disposition(event, "Retain", "Still referenced by an open review.", until)
		self.as_(self.second)
		records.approve_disposition(event)
		frappe.set_user("Administrator")
		self.assertFalse(int(frappe.db.get_value("Disposition Event", event, "is_open")))
		retention.flag_due_for_disposal(add_days(nowdate(), 1))
		self.assertEqual(frappe.db.count("Disposition Event", {"archive_record": self.archive}), 1)
		retention.flag_due_for_disposal(add_days(until, 1))
		self.assertEqual(frappe.db.count("Disposition Event", {"archive_record": self.archive}), 2)

	def test_a_sent_back_proposal_is_cleared_with_its_reason_kept(self):
		event = self.due_event()
		self.as_(self.first)
		records.propose_disposition(event, "Dispose", "Past its period.")
		self.as_(self.second)
		records.send_back_disposition(event, "Check the open review first.")
		doc = frappe.get_doc("Disposition Event", event)
		self.assertFalse(doc.decision)
		self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "Disposition Event",
			"reference_name": event, "content": ["like", "%Check the open review first.%"]}))


class TestScreen(DisposalCase):
	def test_only_records_managers_reach_the_screen(self):
		self.due_event()
		self.as_(make_user("Governance Viewer"))
		with self.assertRaises(frappe.PermissionError):
			records.disposal_overview()
		self.as_(self.first)
		overview = records.disposal_overview()
		row = next(r for r in overview["due"] if r["archive_record"] == self.archive)
		self.assertTrue(row["may_propose"])
		self.assertFalse(row["may_execute"])

	def test_run_check_flags_what_is_due_now(self):
		archive = records.archive("Guide Article", self.article.name)
		self.as_(self.first)
		out = records.run_check()
		self.assertGreaterEqual(out["check"]["scheduled"], 1)
		self.assertIn(archive, [row["archive_record"] for row in out["due"]])
