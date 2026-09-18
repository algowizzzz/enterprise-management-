"""Delegate nomination from the forum page (G-13; governance/delegates.py).

The chair, sponsor or secretary of a forum nominates their own delegate for the
forum's administrative tasks: dated, scoped to the forum, recorded in the
forum's history, and notified to the delegate. Nobody else may, nothing but an
administrative task may be delegated this way, and ending a delegation keeps it.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import delegation
from consilium.governance import delegates
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_user


class TestDelegateNomination(GovernanceTestCase):
	def setUp(self):
		super().setUp()
		self.chair = make_user("Committee Secretary")
		self.sponsor = make_user("Governance Viewer")
		self.delegate = make_user("Governance Viewer")
		self.forum = make_forum(committee_chair=self.chair)
		self.forum.db_set("sponsor", self.sponsor)
		self.purge_on_teardown("Governance Forum", self.forum.name)

	def nominate(self, **overrides):
		args = {
			"forum": self.forum.name, "delegate": self.delegate, "actions": json.dumps(["APPROVE", "SUBMIT"]),
			"valid_from": nowdate(), "valid_to": add_days(nowdate(), 14), "reason": "Annual leave.",
		}
		args.update(overrides)
		return delegates.nominate_delegate(**args)

	def test_the_chair_nominates_a_dated_forum_scoped_delegate(self):
		frappe.set_user(self.chair)
		out = self.nominate()
		self.assertEqual(out["capacities"], ["Chair"])
		row = out["delegations"][0]
		self.assertEqual((row["delegator"], row["delegate"]), (self.chair, self.delegate))
		self.assertEqual(row["actions"], ["APPROVE", "SUBMIT"])
		self.assertEqual(row["standing"], "current")
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Authority Delegation", row["name"])
		self.assertEqual((doc.scope_type, doc.scope_doctype, doc.scope_record), ("Forum", "Governance Forum",
			self.forum.name))
		self.assertEqual(getdate(doc.valid_to), getdate(add_days(nowdate(), 14)))
		# It works where delegation is honoured: on this forum, not another.
		self.assertTrue(delegation.resolve_actor(self.chair, "APPROVE", acting_user=self.delegate,
			doctype="Governance Forum", name=self.forum.name)["permitted"])
		self.assertFalse(delegation.resolve_actor(self.chair, "APPROVE", acting_user=self.delegate,
			doctype="Governance Forum", name="some-other-forum")["permitted"])

	def test_it_is_recorded_on_the_forum_and_the_delegate_is_notified(self):
		frappe.set_user(self.sponsor)
		out = self.nominate()
		frappe.set_user("Administrator")
		name = out["delegations"][0]["name"]
		self.assertTrue(frappe.db.exists("Comment", {"reference_doctype": "Governance Forum",
			"reference_name": self.forum.name, "content": ["like", f"%{name}%"]}))
		dispatch = frappe.get_all("Notification Dispatch", filters={"subject_doctype": "Authority Delegation",
			"subject_name": name, "recipient": self.delegate}, fields=["rendered_subject"])
		self.assertTrue(dispatch)
		self.assertIn(self.forum.forum_name, dispatch[0].rendered_subject)

	def test_someone_who_is_not_chair_sponsor_or_secretary_is_refused(self):
		self.purge_on_teardown("Governance Forum", self.forum.name)
		frappe.set_user(make_user("Committee Secretary"))
		self.assertFalse(delegates.forum_delegates(self.forum.name)["may_nominate"])
		with self.assertRaises(frappe.PermissionError):
			self.nominate()
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("Authority Delegation", {"scope_record": self.forum.name}))

	def test_only_administrative_tasks_and_sensible_dates(self):
		frappe.set_user(self.chair)
		with self.assertRaises(frappe.PermissionError):
			self.nominate(actions=json.dumps(["ATTEST"]))
		with self.assertRaises(frappe.ValidationError):
			self.nominate(valid_from=add_days(nowdate(), -3))
		with self.assertRaises(frappe.ValidationError):
			self.nominate(valid_to=add_days(nowdate(), 400))
		with self.assertRaises(frappe.ValidationError):
			self.nominate(delegate=self.chair)
		with self.assertRaises(frappe.ValidationError):
			self.nominate(reason=" ")
		self.assertNotIn("ATTEST", [a.name for a in delegates.administrative_actions()])

	def test_ending_early_closes_the_delegation_and_keeps_it(self):
		frappe.set_user(self.chair)
		name = self.nominate()["delegations"][0]["name"]
		out = delegates.end_delegation(name, "Back early.")
		row = next(r for r in out["delegations"] if r["name"] == name)
		self.assertEqual(row["standing"], "ended")
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Authority Delegation", name))
		self.assertFalse(frappe.db.get_value("Authority Delegation", name, "is_active"))
		self.assertFalse(delegation.resolve_actor(self.chair, "APPROVE", acting_user=self.delegate,
			doctype="Governance Forum", name=self.forum.name)["permitted"])
		# Only the delegator may end it.
		frappe.set_user(self.chair)
		name2 = self.nominate()["delegations"][0]["name"]
		frappe.set_user(self.sponsor)
		with self.assertRaises(frappe.PermissionError):
			delegates.end_delegation(name2)

	def test_the_forum_page_offers_the_panel(self):
		from consilium.consilium_core.tests.test_portal_pages import render

		status, body = render("forum", self.chair, {"name": self.forum.name})
		frappe.local.request = None
		frappe.set_user("Administrator")
		self.assertEqual(status, 200)
		self.assertIn("Delegates", body)
		self.assertIn("Nominate your delegate", body)
		self.assertIn("Time limits", body)
