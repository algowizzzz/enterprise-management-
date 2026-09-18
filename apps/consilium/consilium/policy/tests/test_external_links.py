"""Links from a governing document to risk-programme records elsewhere (P-5;
policy/external_links.py).

Readers of the document see its links; someone who may edit it adds, corrects
and removes them; only http(s) addresses are accepted; removing keeps the row;
every change lands in the document's history; and a document under legal hold
freezes its links, with the refusal audited.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import nowdate

from consilium.consilium_core import retention
from consilium.policy import external_links as links
from consilium.policy.tests.utils import PolicyTestCase, as_user, make_document, make_user, refusals_for, unique


class TestExternalLinks(PolicyTestCase):
	def setUp(self):
		super().setUp()
		self.owner = make_user("Policy Owner")
		self.document = make_document(owner_user=self.owner)
		self.editor = self.owner

	def add(self, **values):
		args = {"document": self.document.name, "url": "https://risk.example.com/controls/C-104",
			"label": "Control C-104: access review", "external_type": "Control"}
		args.update(values)
		return links.add_document_link(**args)

	def test_an_editor_adds_a_link_and_a_reader_sees_it(self):
		self.assertTrue(frappe.has_permission("Governing Document", "write", doc=self.document.name, user=self.editor))
		with as_user(self.editor):
			out = self.add()
		self.assertTrue(out["may_edit"])
		row = out["links"][0]
		self.assertEqual((row["label"], row["url"], row["external_type"]),
			("Control C-104: access review", "https://risk.example.com/controls/C-104", "Control"))
		self.assertEqual(row["external_system"], links.WEB_LINK_SYSTEM)
		reader = make_user("Policy Reviewer")
		self.assertTrue(frappe.has_permission("Governing Document", "read", doc=self.document.name, user=reader))
		with as_user(reader):
			seen = links.document_links(self.document.name)
		self.assertEqual([r["name"] for r in seen["links"]], [row["name"]])
		self.assertFalse(seen["may_edit"])

	def test_only_http_and_https_are_accepted(self):
		with as_user(self.editor):
			for bad in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "ftp://example.com/x",
					"https://", "example.com/page", 'https://example.com/"onmouseover=x'):
				with self.subTest(url=bad), self.assertRaises(frappe.ValidationError):
					self.add(url=bad)
			self.add(url="http://intranet.example.com/risk/R-7")

	def test_someone_who_may_not_edit_is_refused(self):
		stranger = make_user("Policy Reviewer")
		with as_user(stranger), self.assertRaises(frappe.PermissionError):
			self.add()

	def test_edit_and_remove_are_logged_and_removal_keeps_the_row(self):
		with as_user(self.editor):
			name = self.add()["links"][0]["name"]
			links.update_document_link(name, "https://risk.example.com/controls/C-105", "Control C-105", "Control")
			out = links.remove_document_link(name, "Control retired.")
		self.assertEqual(out["links"], [])
		row = frappe.get_doc("External Reference", name)
		self.assertFalse(int(row.is_active))
		self.assertEqual(row.removed_by, self.editor)
		self.assertEqual(row.url, "https://risk.example.com/controls/C-105")
		history = frappe.get_all("Comment", filters={"reference_doctype": "Governing Document",
			"reference_name": self.document.name, "content": ["like", f"%{name}%"]}, pluck="content")
		self.assertEqual(len(history), 3)
		self.assertTrue(any("Control retired." in text for text in history))
		with as_user(self.editor), self.assertRaises(frappe.ValidationError):
			links.update_document_link(name, "https://example.com", "Again")

	def test_a_document_under_legal_hold_freezes_its_links(self):
		self.purge_on_teardown("Governing Document", self.document.name)
		frappe.get_doc({"doctype": "Legal Hold", "hold_reference": unique("HOLD"), "placed_on": nowdate(),
			"scope_doctype": "Governing Document",
			"scope_filter": json.dumps({"name": self.document.name})}).insert(ignore_permissions=True)
		retention.clear_cache()
		with as_user(self.editor):
			self.assertFalse(links.document_links(self.document.name)["may_edit"])
			with self.assertRaises(frappe.PermissionError):
				self.add()
		self.assertEqual(refusals_for("Governing Document", self.document.name)[-1]["attempted_action"],
			"Add external link")

	def test_the_policy_page_carries_the_panel(self):
		from consilium.consilium_core.tests.test_portal_pages import render

		status, body = render("policy", "Administrator", {"name": self.document.name})
		frappe.local.request = None
		frappe.set_user("Administrator")
		self.assertEqual(status, 200)
		self.assertIn("Linked risk-programme records", body)


class TestReferenceImport(PolicyTestCase):
	"""P-5 and G-19: links brought in from a file, through the governed import pipeline."""

	def test_a_file_of_links_is_validated_and_committed_as_references(self):
		from consilium.consilium_core import importing

		document = make_document()
		profile = importing.ensure_reference_profile("Governing Document", unique("Document links"))
		self.assertEqual(importing.ensure_reference_profile("Governing Document",
			frappe.db.get_value("Import Profile", profile, "profile_title")), profile)
		system = frappe.get_doc({"doctype": "External System", "system_code": unique("RR").upper(),
			"title": "Risk register", "is_active": 1}).insert(ignore_permissions=True)
		content = "\n".join([
			"Record,System,Identifier,Kind,Label,Link",
			f"{document.name},{system.system_code},RSK-1,Risk,Fraud risk,https://risk.example.com/RSK-1",
			f"NO-SUCH-DOC,{system.system_code},RSK-2,Risk,Unknown document,https://risk.example.com/RSK-2",
			f"{document.name},{system.system_code},RSK-3,Risk,Bad address,javascript:alert(1)",
		])
		review = importing.upload_batch(profile, "links.csv", content)
		batch = review["batch"]["name"]
		self.assertEqual(frappe.db.get_value("Import Batch", batch, "error_count"), 1)
		importing.commit_reviewed_batch(batch)
		rows = frappe.get_all("External Reference", filters={"subject_doctype": "Governing Document",
			"subject_name": document.name}, fields=["external_key", "url", "external_system"])
		self.assertEqual([(r.external_key, r.url) for r in rows], [("RSK-1", "https://risk.example.com/RSK-1")])
		self.assertEqual(links.document_links(document.name)["links"][0]["external_key"], "RSK-1")
