"""Per-person dashboard layouts on the Insights pages (O-3; consilium_core/dashboard_layout.py).

A viewer chooses which sections and dimensions a page shows and in what order,
saves it as their own, and can reset it. These tests hold the layouts to that,
and to the two limits that matter: a layout is one person's, and a section the
person may not read is never offered and never comes back from a saved layout.
"""

from __future__ import annotations

import json

import frappe

from consilium.consilium_core import dashboard_layout as layouts
from consilium.consilium_core.tests.utils import CoreTestCase, make_user


def keys(layout: list[dict]) -> list[str]:
	return [entry["key"] for entry in layout]


class TestDashboardLayout(CoreTestCase):
	def setUp(self):
		super().setUp()
		# Reads forums, documents and escalations: every reports section is offered.
		self.cro = make_user("Risk Governance Office")
		frappe.get_doc("User", self.cro).add_roles("Policy Owner", "Escalation Owner")
		self.other = make_user("Risk Governance Office")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_the_default_is_the_page_as_it_ships(self):
		frappe.set_user(self.cro)
		out = layouts.get_layout("reports")
		self.assertFalse(out["customised"])
		self.assertEqual(keys(out["layout"]), keys(out["default"]))
		self.assertEqual(keys(out["layout"])[0], "headline-heading")
		self.assertTrue(all(entry["shown"] for entry in out["layout"]))

	def test_a_saved_layout_is_read_back_in_its_order_with_its_choices(self):
		frappe.set_user(self.cro)
		default = layouts.get_layout("reports")["layout"]
		mine = list(reversed(default))
		mine[0]["shown"] = False
		forums = next(entry for entry in mine if entry["key"] == "forums-heading")
		forums["dimensions"] = list(reversed(forums["dimensions"]))
		forums["dimensions"][0]["shown"] = False
		saved = layouts.save_layout("reports", json.dumps(mine))
		self.assertTrue(saved["customised"])

		again = layouts.get_layout("reports")
		self.assertEqual(keys(again["layout"]), keys(mine))
		self.assertFalse(again["layout"][0]["shown"])
		read_forums = next(entry for entry in again["layout"] if entry["key"] == "forums-heading")
		self.assertEqual(keys(read_forums["dimensions"]), ["forum-type-heading", "forum-status-heading"])
		self.assertFalse(read_forums["dimensions"][0]["shown"])
		# Stored server-side, on the person's own row.
		self.assertEqual(frappe.db.count("Dashboard Layout", {"user": self.cro, "page": "reports"}), 1)

	def test_reset_returns_the_default_and_keeps_the_row(self):
		frappe.set_user(self.cro)
		default = layouts.get_layout("reports")["layout"]
		layouts.save_layout("reports", json.dumps(list(reversed(default))))
		out = layouts.reset_layout("reports")
		self.assertFalse(out["customised"])
		self.assertEqual(keys(out["layout"]), keys(default))
		self.assertEqual(frappe.db.get_value("Dashboard Layout", {"user": self.cro, "page": "reports"},
			"is_customised"), 0)
		# A later save reuses the same row.
		layouts.save_layout("reports", json.dumps(list(reversed(default))))
		self.assertEqual(frappe.db.count("Dashboard Layout", {"user": self.cro, "page": "reports"}), 1)

	def test_one_persons_layout_is_not_anothers(self):
		frappe.set_user(self.cro)
		default = layouts.get_layout("reports")["layout"]
		layouts.save_layout("reports", json.dumps(list(reversed(default))))

		frappe.set_user(self.other)
		theirs = layouts.get_layout("reports")
		self.assertFalse(theirs["customised"])
		self.assertEqual(keys(theirs["layout"]), keys(theirs["default"]))
		mine_for_them = theirs["layout"]
		mine_for_them[-1]["shown"] = False
		layouts.save_layout("reports", json.dumps(mine_for_them))

		frappe.set_user(self.cro)
		again = layouts.get_layout("reports")
		self.assertEqual(keys(again["layout"]), list(reversed(keys(default))))
		self.assertTrue(all(entry["shown"] for entry in again["layout"]))
		# Reset touches only the caller's row.
		frappe.set_user(self.other)
		layouts.reset_layout("reports")
		frappe.set_user(self.cro)
		self.assertTrue(layouts.get_layout("reports")["customised"])

	def test_a_section_the_viewer_cannot_read_is_never_offered_or_kept(self):
		reader = make_user("Governance Viewer")
		frappe.set_user(reader)
		offered = keys(layouts.get_layout("reports")["sections"])
		self.assertIn("headline-heading", offered)
		self.assertIn("forums-heading", offered)
		self.assertNotIn("escalations-heading", offered)
		# A layout naming it is saved without it.
		out = layouts.save_layout("reports", json.dumps([
			{"key": "escalations-heading", "shown": True, "dimensions": []},
			{"key": "forums-heading", "shown": True, "dimensions": []},
		]))
		self.assertNotIn("escalations-heading", keys(out["layout"]))
		self.assertEqual(keys(out["layout"])[0], "forums-heading")

	def test_nothing_shown_is_refused(self):
		frappe.set_user(self.cro)
		layout = layouts.get_layout("emerging-risks")["layout"]
		for entry in layout:
			entry["shown"] = False
		with self.assertRaises(frappe.ValidationError):
			layouts.save_layout("emerging-risks", json.dumps(layout))

	def test_an_unknown_page_and_a_visitor_are_refused(self):
		frappe.set_user(self.cro)
		with self.assertRaises(frappe.ValidationError):
			layouts.get_layout("admin")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			layouts.get_layout("reports")
		with self.assertRaises(frappe.PermissionError):
			layouts.save_layout("reports", "[]")

	def test_the_customise_control_is_on_the_insights_pages(self):
		from consilium.consilium_core.tests.test_portal_pages import render

		for route in ("reports", "governance-gaps", "emerging-risks"):
			with self.subTest(route=route):
				status, body = render(route, "Administrator")
				self.assertEqual(status, 200)
				self.assertIn("Customise this page", body)
				self.assertIn("Reset to default", body)
				self.assertIn('data-page="' + route + '"', body)
		frappe.local.request = None
		frappe.set_user("Administrator")
