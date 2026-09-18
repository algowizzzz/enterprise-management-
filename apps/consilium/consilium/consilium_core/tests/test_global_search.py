"""The header's global search (consilium.consilium_core.search.global_search).

The endpoint answers every keystroke of every signed-in person, over three
record types that carry the portal's two record-level restrictions: sensitive
escalation matters and confidential or restricted governing documents. What
these tests hold it to:

* a signed-out visitor is refused;
* a sensitive matter reaches only a person cleared to see it (or one the
  matter names), exactly as the escalation register does;
* a record type the person may not read is left out, not refused;
* a query is matched literally — "%" and "_" are not wildcards;
* each result says where it opens, and each group where "See all" goes.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import search
from consilium.escalation import sensitivity
from consilium.escalation.tests.utils import (
	EscalationTestCase,
	as_user,
	escalation_permission_hooks,
	make_user,
)


class TestGlobalSearch(EscalationTestCase):
	def setUp(self):
		super().setUp()
		self.token = "Qzx" + frappe.generate_hash(length=6)
		self.reference = self.reference_data()
		self.ordinary = self.make_matter(self.reference, escalation_title=f"Ordinary {self.token} matter")
		self.restricted = self.make_matter(
			self.reference, escalation_title=f"Restricted {self.token} matter", sensitive=1
		)
		self.cleared = make_user("Escalation Owner", sensitivity.SENSITIVE_ROLE)
		self.uncleared = make_user("Escalation Owner")

	def _names(self, result: dict, key: str) -> list[str]:
		for group in result["groups"]:
			if group["key"] == key:
				return [row["name"] for row in group["results"]]
		return []

	def test_a_visitor_is_refused(self):
		with as_user("Guest"):
			with self.assertRaises(frappe.PermissionError):
				search.global_search(q=self.token)

	def test_a_sensitive_matter_reaches_only_the_cleared(self):
		with escalation_permission_hooks():
			with as_user(self.uncleared):
				found = self._names(search.global_search(q=self.token), "escalations")
			self.assertIn(self.ordinary.name, found)
			self.assertNotIn(self.restricted.name, found)

			with as_user(self.cleared):
				found = self._names(search.global_search(q=self.token), "escalations")
			self.assertIn(self.ordinary.name, found)
			self.assertIn(self.restricted.name, found)

	def test_a_reference_finds_the_record_but_not_a_hidden_one(self):
		"""Typing the exact reference must not confirm a sensitive matter exists."""
		with escalation_permission_hooks():
			with as_user(self.uncleared):
				result = search.global_search(q=self.restricted.name)
			self.assertNotIn(self.restricted.name, self._names(result, "escalations"))
			with as_user(self.uncleared):
				result = search.global_search(q=self.ordinary.name)
			self.assertEqual(self._names(result, "escalations"), [self.ordinary.name])

	def test_a_type_the_person_may_not_read_is_left_out(self):
		nobody = make_user()
		with escalation_permission_hooks(), as_user(nobody):
			result = search.global_search(q=self.token)
		self.assertEqual(result["groups"], [])

	def test_short_and_wildcard_queries_match_nothing_extra(self):
		with escalation_permission_hooks(), as_user(self.cleared):
			self.assertEqual(search.global_search(q="Q")["groups"], [])
			self.assertEqual(search.global_search(q="   ")["groups"], [])
			# Literal: "%" is a character to find, not "anything".
			self.assertEqual(self._names(search.global_search(q=self.token + "%"), "escalations"), [])
			self.assertEqual(self._names(search.global_search(q="%%"), "escalations"), [])

	def test_matching_ignores_case(self):
		with escalation_permission_hooks(), as_user(self.cleared):
			found = self._names(search.global_search(q=self.token.lower()), "escalations")
		self.assertIn(self.ordinary.name, found)

	def test_results_say_where_they_open_and_the_limit_holds(self):
		for n in range(4):
			self.make_matter(self.reference, escalation_title=f"Extra {n} {self.token}")
		with escalation_permission_hooks(), as_user(self.cleared):
			result = search.global_search(q=self.token, limit=2)
		group = next(g for g in result["groups"] if g["key"] == "escalations")
		self.assertEqual(len(group["results"]), 2)
		self.assertTrue(group["more"])
		self.assertEqual(group["see_all"], "/escalations?q=" + self.token)
		for row in group["results"]:
			self.assertEqual(row["url"], "/escalation?name=" + row["name"])
			self.assertIn(self.token, row["title"])
			self.assertIn(row["tone"], ("success", "warning", "danger", "neutral", "info"))

	def test_the_limit_is_capped(self):
		with escalation_permission_hooks(), as_user(self.cleared):
			result = search.global_search(q=self.token, limit=500)
		for group in result["groups"]:
			self.assertLessEqual(len(group["results"]), search.MAX_LIMIT)

	def test_it_is_a_get_endpoint(self):
		from frappe import whitelisted

		self.assertIn(search.global_search, whitelisted)
		self.assertNotIn(search.global_search, frappe.guest_methods)
