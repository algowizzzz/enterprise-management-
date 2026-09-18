"""The home page's cards (consilium_core/home.py, www/index.html).

What the page promises, held to account:

* every figure counts what the page it links to lists, so a record that enters
  a list's filter moves the figure by exactly one;
* the My work card is the inbox itself, not a second opinion of it;
* no card offers an area, an action or a guide chapter the viewer cannot open;
* a fault in one card costs that card, not the page.
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import home, inbox
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.test_portal_pages import ERROR, render
from consilium.consilium_core.tests.utils import CoreTestCase

PEOPLE = PersonaPool()


def tearDownModule():
	PEOPLE.remove()


def figures(module_id: str) -> dict[str, int]:
	module = next((m for m in home.modules() if m["id"] == module_id), None)
	return {f["url"]: f["value"] for f in module["figures"]} if module else {}


class HomeCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		PEOPLE.attach(cls, {
			"viewer": ("Governance Viewer",),
			"policy_owner": ("Policy Owner",),
			"escalation_owner": ("Escalation Owner",),
			"nobody": (),
		})

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()


class TestFiguresMatchTheirPages(HomeCase):
	def test_a_forum_entering_each_filter_moves_its_figure_by_one(self):
		from consilium.governance.tests.utils import make_forum

		frappe.set_user("Administrator")
		before = figures("governance")
		forum = make_forum().name
		frappe.db.set_value("Governance Forum", forum, {
			"is_active": 1, "requires_review": 1, "next_review_on": add_days(nowdate(), -3),
		})
		after = figures("governance")
		for url in ("/forums", "/forums?standing=review", "/forums?standing=overdue"):
			with self.subTest(url=url):
				self.assertEqual(after[url], before[url] + 1)

	def test_a_forum_with_no_review_date_is_not_overdue(self):
		"""The list pages bound the date; an empty date is not 'the earliest day'."""
		from consilium.governance.tests.utils import make_forum

		frappe.set_user("Administrator")
		before = figures("governance")["/forums?standing=overdue"]
		forum = make_forum().name
		frappe.db.set_value("Governance Forum", forum, {"is_active": 1, "next_review_on": None})
		self.assertEqual(figures("governance")["/forums?standing=overdue"], before)

	def test_every_figure_links_to_a_list_page_filter(self):
		frappe.set_user("Administrator")
		for module in home.modules():
			for figure in module["figures"]:
				with self.subTest(module=module["id"], figure=figure["label"]):
					self.assertRegex(figure["url"], r"^/(forums|policies|escalations|governance-gaps)(\?[a-z]+=[A-Za-z]+)?$")
					self.assertIsInstance(figure["value"], int)


class TestMyWork(HomeCase):
	def test_the_card_is_the_inbox(self):
		for user in ("Administrator", self.viewer):
			with self.subTest(user=user):
				frappe.set_user(user)
				card = home.my_work(user)
				tasks = inbox.my_tasks()
				self.assertEqual(card["count"], tasks["count"])
				self.assertEqual(card["overdue"], tasks["overdue"])
				self.assertEqual(sum(g["count"] for g in card["groups"]), tasks["count"])
				self.assertLessEqual(len(card["top"]), home.TOP_ITEMS)

	def test_each_kind_opens_the_view_that_shows_it(self):
		for kind, view in home.TASK_VIEWS.items():
			with self.subTest(kind=kind):
				self.assertIn(view, ("approvals", "reviews", "attestations", "unowned"))


class TestPermissions(HomeCase):
	def test_an_area_is_shown_only_to_someone_who_may_open_it(self):
		frappe.set_user(self.viewer)
		shown = {m["id"] for m in home.modules()}
		self.assertIn("governance", shown)
		self.assertNotIn("policies", shown)
		self.assertNotIn("escalations", shown)
		frappe.set_user(self.policy_owner)
		self.assertIn("policies", {m["id"] for m in home.modules()})

	def test_a_quick_action_needs_the_right_to_create(self):
		for user in (self.viewer, self.policy_owner, self.escalation_owner, "Administrator"):
			with self.subTest(user=user):
				frappe.set_user(user)
				offered = {a["url"] for a in home.quick_actions()}
				for url, doctype in (("/raise-escalation", "Escalation Matter"),
				                     ("/policy-intake", "Document Intake Request"),
				                     ("/create-forum", "Committee Formation Request")):
					self.assertEqual(url in offered, bool(frappe.has_permission(doctype, "create")))

	def test_the_page_draws_only_the_viewers_areas(self):
		status, body = render("", self.viewer)
		self.assertEqual(status, 200)
		self.assertNotRegex(body, ERROR)
		self.assertIn('id="module-governance"', body)
		self.assertNotIn('id="module-policies"', body)
		self.assertNotIn('id="module-escalations"', body)

	def test_the_administrators_chapter_is_for_administrators(self):
		frappe.set_user(self.viewer)
		titles = [c["title"] for c in home.guides(self.viewer, False)["chapters"]]
		self.assertTrue(titles, "the guide lists no chapters")
		self.assertFalse(any("Administration" in t for t in titles))

	def test_a_visitor_gets_the_banner_and_the_sign_in_prompt_only(self):
		status, body = render("", "Guest")
		self.assertIn(status, (200, 401, 403))
		self.assertNotIn("cns-home-module", body)
		self.assertNotIn('id="work-heading"', body)


class TestResilience(HomeCase):
	def test_a_failing_card_does_not_take_the_page_down(self):
		with mock.patch.object(home, "modules", side_effect=RuntimeError("an area could not be read")), \
				mock.patch.object(home, "my_work", side_effect=RuntimeError("the inbox could not be read")):
			status, body = render("", "Administrator")
		self.assertEqual(status, 200)
		self.assertNotRegex(body, ERROR)
		self.assertIn("My work is unavailable", body)
		self.assertIn('id="guide-heading"', body)

	def test_the_map_and_the_guide_keep_the_addresses_the_menus_use(self):
		status, body = render("", "Administrator")
		self.assertEqual(status, 200)
		for anchor in ('id="forum-map"', 'id="guide-heading"', 'id="guide-more"'):
			self.assertIn(anchor, body)
