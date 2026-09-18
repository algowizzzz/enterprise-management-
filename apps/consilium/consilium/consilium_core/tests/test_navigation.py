"""The portal header's menus (consilium.consilium_core.navigation).

A menu or an item someone cannot use is a dead end, so each is shown only to
the people who may use it — the same rule the flat tab list followed. These
tests hold the menus to that, to the old tab ids still highlighting the right
menu, and to the current page being marked.
"""

from __future__ import annotations

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from consilium.consilium_core import navigation
from consilium.consilium_core.tests.utils import CoreTestCase, make_user


def _urls(menus: list[dict]) -> dict[str, list[str]]:
	return {
		menu["id"]: [item["url"] for group in menu["groups"] for item in group["items"]]
		for menu in menus
	}


class TestNavigation(CoreTestCase):
	def tearDown(self):
		frappe.local.request = None
		frappe.set_user("Administrator")
		super().tearDown()

	def _as(self, user: str, path: str = "/", active: str | None = None) -> list[dict]:
		frappe.set_user(user)
		frappe.local.request = Request(
			EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ()
		)
		return navigation.cns_nav(active)

	def test_a_visitor_gets_no_menus(self):
		self.assertEqual(self._as("Guest"), [])

	def test_a_person_with_no_role_sees_no_admin_and_no_restricted_areas(self):
		menus = _urls(self._as(make_user()))
		self.assertIn("home", menus)
		self.assertIn("mywork", menus)
		for area in ("admin", "escalations", "policies"):
			self.assertNotIn(area, menus)
		self.assertNotIn("/formation-requests", sum(menus.values(), []))

	def test_an_administrator_sees_every_menu(self):
		menus = _urls(self._as("Administrator"))
		for area in ("home", "mywork", "governance", "policies", "escalations", "insights", "admin"):
			self.assertIn(area, menus)
		self.assertIn("/integrations", menus["admin"])
		self.assertIn("/formation-requests", menus["governance"])

	def test_horizon_scanning_follows_the_integration_settings(self):
		"""Shown, and named, exactly as the page buttons are."""
		from unittest.mock import patch

		on = {"horizon": {"shown": True, "state": "connected", "label": "Regulatory radar", "new_tab": True}}
		off = {"horizon": {"shown": False, "state": "off", "label": "", "new_tab": False}}
		target = "consilium.consilium_core.integrations.external_tools.cns_external_tools"
		with patch(target, return_value=on):
			items = [item for menu in self._as("Administrator") for group in menu["groups"]
				for item in group["items"] if item["url"] == "/horizon-scanning"]
		self.assertEqual([(i["label"], i["new_tab"]) for i in items], [("Regulatory radar", True)])
		with patch(target, return_value=off):
			self.assertNotIn("/horizon-scanning", sum(_urls(self._as("Administrator")).values(), []))

	def test_horizon_scanning_says_when_it_is_not_connected(self):
		"""Until an address is set the page behind the item only says it is not
		connected, so the item says so too and does not open a new tab."""
		from unittest.mock import patch

		pending = {"horizon": {"shown": True, "state": "not_connected", "label": "Horizon scanning", "new_tab": True}}
		connected = {"horizon": {"shown": True, "state": "connected", "label": "Horizon scanning", "new_tab": True}}
		target = "consilium.consilium_core.integrations.external_tools.cns_external_tools"

		def item(settings):
			with patch(target, return_value=settings):
				return next(i for menu in self._as("Administrator") for group in menu["groups"]
					for i in group["items"] if i["url"] == "/horizon-scanning")

		waiting = item(pending)
		self.assertEqual(waiting["description"], "Not connected yet.")
		self.assertFalse(waiting["new_tab"])
		ready = item(connected)
		self.assertNotIn("Not connected", ready["description"])
		self.assertTrue(ready["new_tab"])

	def test_menu_labels_match_the_page_titles(self):
		"""A page is called what the menu calls it: the menu item's label is the
		page's title (or, for filtered views, the plain list page's title)."""
		from consilium.consilium_core.tests.test_portal_pages import render

		titles = {
			"/policies": "Policy library", "/forums": "Forum inventory", "/escalations": "Escalation register",
			"/reports": "Management reporting", "/governance-gaps": "Gaps and risk",
			"/emerging-risks": "Emerging risks", "/regulatory-updates": "Regulatory updates",
			"/admin": "Administration", "/imports": "Imports", "/integrations": "Integrations",
			"/attestation-campaigns": "Attestation campaigns", "/policy-intake": "Request a policy or change",
			"/create-forum": "Request a new forum", "/formation-requests": "Formation requests",
			"/raise-escalation": "Raise an escalation",
		}
		labels = {item["url"]: item["label"] for menu in self._as("Administrator")
			for group in menu["groups"] for item in group["items"]}
		for url, title in titles.items():
			with self.subTest(url=url):
				self.assertEqual(labels.get(url), title)
				status, body = render(url.lstrip("/"), "Administrator")
				self.assertEqual(status, 200)
				self.assertIn("<title>" + title, body)

	def test_the_formation_queue_is_for_the_governance_office(self):
		office = make_user("Risk Governance Office")
		self.assertIn("/formation-requests", _urls(self._as(office)).get("governance", []))

	def test_administration_roles_see_the_admin_menu(self):
		admin = make_user("Consilium Administrator")
		self.assertIn("admin", _urls(self._as(admin)))

	def test_old_tab_ids_highlight_the_menus_that_replaced_them(self):
		for old, new in (("inbox", "mywork"), ("forums", "governance"), ("requests", "governance"),
				("reports", "insights")):
			with self.subTest(old=old):
				menus = self._as("Administrator", active=old)
				active = [menu["id"] for menu in menus if menu["active"]]
				self.assertEqual(active, [new])

	def test_the_current_page_is_marked_filtered_view_first(self):
		menus = self._as("Administrator", path="/forums?standing=overdue", active="governance")
		current = [item["url"] for menu in menus for group in menu["groups"] for item in group["items"]
			if item.get("current")]
		self.assertEqual(current, ["/forums?standing=overdue"])

		menus = self._as("Administrator", path="/forums?cadence=Monthly", active="governance")
		current = [item["url"] for menu in menus for group in menu["groups"] for item in group["items"]
			if item.get("current")]
		self.assertEqual(current, ["/forums"])

	def test_the_header_renders_the_menus(self):
		from consilium.consilium_core.tests.test_portal_pages import render

		status, body = render("forums", "Administrator")
		self.assertEqual(status, 200)
		self.assertIn('aria-controls="cns-menu-governance"', body)
		self.assertIn('id="cns-menu-governance-btn"', body)
		self.assertIn("data-cns-search", body)
		self.assertRegex(body, r'id="cns-menu-governance-btn"[^>]*data-active')
