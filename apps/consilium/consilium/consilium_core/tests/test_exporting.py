"""The governed outbound export (G-19, P-20, E-19; consilium_core/exporting.py).

Every run is an Export Batch that says who exported what; rows are read with
the exporter's own permissions; restricted records stay out unless the profile
allows them and the exporter may read them, and never in a scheduled drop;
spreadsheet formulas are neutralised; the row limit holds; and a scheduled drop
writes only under the root the server administrator configured.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile

import frappe

from consilium.consilium_core import exporting
from consilium.consilium_core.tests.utils import CoreTestCase, make_user, refusals_for, unique
from consilium.escalation.tests.utils import EscalationTestCase
from consilium.governance.tests.utils import make_forum
from consilium.policy.tests.utils import PolicyTestCase, make_document


def make_system() -> str:
	code = unique("SYS").upper()
	return frappe.get_doc({"doctype": "External System", "system_code": code, "title": "Risk register (file)",
		"is_active": 1}).insert(ignore_permissions=True).name


def make_profile(source: str, names: list[str], **values):
	defaults = {
		"doctype": "Export Profile", "profile_title": unique("Profile"), "source_doctype": source,
		"target_system": make_system(), "file_format": "CSV",
		"record_filter": json.dumps({"name": ["in", names]}), "allowed_roles": "Risk Governance Office",
		"schedule": "Manual Only", "is_active": 1,
	}
	defaults.update(values)
	return frappe.get_doc(defaults).insert(ignore_permissions=True)


def rows_of(content: str) -> list[list[str]]:
	return list(csv.reader(io.StringIO(content)))


class TestForumExport(CoreTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.plain = make_forum(forum_name="=HYPERLINK(\"http://example.com\") " + unique("F"))
		self.secret = make_forum(confidential=1)
		self.other = make_forum()
		self.names = [self.plain.name, self.secret.name, self.other.name]
		self.profile = make_profile("Governance Forum", self.names,
			export_fields="forum_name = Forum\ncompliance_status\nexternal_references")
		self.exporter = make_user("Risk Governance Office")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_an_export_is_logged_with_who_what_and_its_hash(self):
		frappe.set_user(self.exporter)
		out = exporting.export_now(self.profile.name)
		table = rows_of(out["content"])
		self.assertEqual(table[0], ["Identifier", "Forum", "Compliance Status", "External references"])
		exported = [row[0] for row in table[1:]]
		self.assertEqual(sorted(exported), sorted([self.plain.name, self.other.name]))

		frappe.set_user("Administrator")
		batch = frappe.get_doc("Export Batch", out["batch"])
		self.assertEqual(batch.generated_by, self.exporter)
		self.assertEqual(batch.export_profile, self.profile.name)
		self.assertEqual(batch.record_count, 2)
		self.assertEqual(batch.excluded_count, 1)
		names = batch.record_names if isinstance(batch.record_names, list) else json.loads(batch.record_names)
		self.assertEqual(sorted(names), sorted(exported))
		self.assertEqual(batch.output_sha256, frappe.utils.cstr(out["sha256"]))
		import hashlib
		self.assertEqual(batch.output_sha256, hashlib.sha256(out["content"].encode("utf-8")).hexdigest())
		self.assertTrue(batch.output_file)
		self.assertTrue(frappe.db.exists("File", {"attached_to_doctype": "Export Batch",
			"attached_to_name": batch.name, "is_private": 1}))

	def test_a_formula_is_written_as_text(self):
		frappe.set_user(self.exporter)
		table = rows_of(exporting.export_now(self.profile.name)["content"])
		cell = next(row[1] for row in table[1:] if row[0] == self.plain.name)
		self.assertTrue(cell.startswith("'="))

	def test_restricted_records_only_when_the_profile_allows_them(self):
		self.profile.db_set("include_restricted", 1)
		frappe.set_user(self.exporter)
		out = exporting.export_now(self.profile.name)
		self.assertIn(self.secret.name, [row[0] for row in rows_of(out["content"])[1:]])
		self.assertEqual(out["excluded"], 0)

	def test_rows_are_the_exporters_own_reads(self):
		narrow = make_user("Risk Governance Office")
		frappe.get_doc({"doctype": "User Permission", "user": narrow, "allow": "Governance Forum",
			"for_value": self.other.name, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
		frappe.set_user(narrow)
		out = exporting.export_now(self.profile.name)
		self.assertEqual([row[0] for row in rows_of(out["content"])[1:]], [self.other.name])

	def test_someone_without_the_role_is_refused_and_it_is_audited(self):
		self.purge_on_teardown("Export Profile", self.profile.name)
		frappe.set_user(make_user("Governance Viewer"))
		with self.assertRaises(frappe.PermissionError):
			exporting.export_now(self.profile.name)
		self.assertEqual(refusals_for("Export Profile", self.profile.name)[-1]["attempted_action"], "Export")
		self.assertEqual(exporting.my_profiles()["profiles"], [])

	def test_the_row_limit_holds_and_says_so(self):
		self.profile.db_set("max_rows", 1)
		frappe.set_user(self.exporter)
		out = exporting.export_now(self.profile.name)
		self.assertTrue(out["capped"])
		self.assertEqual(len(rows_of(out["content"])) - 1, 1)
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.get_value("Export Batch", out["batch"], "capped"))

	def test_json_carries_the_columns_and_records(self):
		self.profile.db_set("file_format", "JSON")
		frappe.set_user(self.exporter)
		out = exporting.export_now(self.profile.name)
		payload = json.loads(out["content"])
		self.assertEqual(payload["columns"][0]["field"], "name")
		self.assertEqual(len(payload["records"]), 2)
		self.assertTrue(out["file_name"].endswith(".json"))

	def test_the_profile_is_checked(self):
		with self.assertRaises(frappe.ValidationError):
			make_profile("Governance Forum", self.names, export_fields="no_such_field")
		with self.assertRaises(frappe.ValidationError):
			make_profile("Governance Forum", self.names, schedule="Daily", drop_folder="../outside",
				run_as="Administrator")
		with self.assertRaises(frappe.ValidationError):
			make_profile("Governance Forum", self.names, schedule="Daily", drop_folder="register")
		profile = make_profile("Governance Forum", self.names, max_rows=999999)
		self.assertEqual(profile.max_rows, exporting.HARD_CAP)


class TestScheduledDrop(CoreTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.plain = make_forum()
		self.secret = make_forum(confidential=1)
		self.profile = make_profile("Governance Forum", [self.plain.name, self.secret.name], schedule="Daily",
			drop_folder="risk-register", run_as="Administrator", include_restricted=1)
		self.root = tempfile.mkdtemp(prefix="cns-drop-")
		self.previous = frappe.conf.get(exporting.DROP_ROOT_KEY)

	def tearDown(self):
		if self.previous is None:
			frappe.conf.pop(exporting.DROP_ROOT_KEY, None)
		else:
			frappe.conf[exporting.DROP_ROOT_KEY] = self.previous
		shutil.rmtree(self.root, ignore_errors=True)
		super().tearDown()

	def test_without_a_configured_root_nothing_is_written(self):
		frappe.conf.pop(exporting.DROP_ROOT_KEY, None)
		self.assertEqual(exporting.run_scheduled(), [])
		self.assertIn("no export drop root", frappe.db.get_value("Export Profile", self.profile.name, "last_run_note"))
		self.assertFalse(frappe.db.exists("Export Batch", {"export_profile": self.profile.name}))

	def test_a_due_drop_is_written_under_the_root_without_restricted_records(self):
		frappe.conf[exporting.DROP_ROOT_KEY] = self.root
		written = exporting.run_scheduled()
		self.assertEqual(len(written), 1)
		batch = frappe.get_doc("Export Batch", written[0])
		self.assertEqual(batch.status, "Delivered")
		self.assertTrue(batch.delivered_to.startswith(os.path.join(os.path.realpath(self.root), "risk-register")))
		with open(batch.delivered_to, encoding="utf-8") as handle:
			content = handle.read()
		self.assertIn(self.plain.name, content)
		self.assertNotIn(self.secret.name, content)
		# Not due again the same day.
		self.assertEqual(exporting.run_scheduled(), [])


class TestDocumentExport(PolicyTestCase):
	def test_confidential_and_restricted_documents_stay_out(self):
		public = make_document()
		restricted = make_document(handling_classification="Restricted")
		profile = make_profile("Governing Document", [public.name, restricted.name])
		out = exporting.generate(profile, user="Administrator", include_restricted=False, delivered_to="test")
		self.assertEqual([row.name for row in out["collected"]["rows"]], [public.name])
		self.assertEqual(out["collected"]["excluded"], 1)
		self.assertIn("Approving forum", rows_of(out["content"])[0])


class TestEscalationExport(EscalationTestCase):
	def test_a_sensitive_matter_stays_out_and_the_pathway_is_linked(self):
		reference = self.reference_data()
		open_matter = self.make_matter(reference)
		sensitive = self.make_matter(reference, sensitive=1)
		profile = make_profile("Escalation Matter", [open_matter.name, sensitive.name])
		out = exporting.generate(profile, user="Administrator", include_restricted=False, delivered_to="test")
		names = [row.name for row in out["collected"]["rows"]]
		self.assertEqual(names, [open_matter.name])
		header = rows_of(out["content"])[0]
		self.assertEqual(header[0], "Identifier")
		self.assertIn("Governance forums on the pathway", header)
		self.assertIn("Status", header)


class TestReportingDownloadIsLogged(PolicyTestCase):
	"""P-20: a section downloaded from the reporting page is an Export Batch too."""

	def test_a_section_download_is_logged(self):
		from consilium.policy import reporting

		parent = make_document()
		make_document(parent_document=parent.name)
		content = reporting.export("families")
		self.assertTrue(content)
		batch = frappe.get_all("Export Batch", filters={"export_profile": "Management reporting: families"},
			fields=["name", "generated_by", "record_count", "record_names", "output_sha256", "target_system"],
			order_by="creation desc", limit=1)[0]
		self.assertEqual(batch.generated_by, "Administrator")
		self.assertEqual(batch.target_system, reporting.DOWNLOAD_SYSTEM)
		self.assertEqual(batch.record_count, len(rows_of(content)) - 1)
		import hashlib
		self.assertEqual(batch.output_sha256, hashlib.sha256(content.encode("utf-8")).hexdigest())
