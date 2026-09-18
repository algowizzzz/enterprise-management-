"""Service levels and time limits for forums (G-12; governance/service_levels.py).

The forum page's Time limits tab and the reporting page's forum time-limit
section: dated obligations judged against today, time at each compliance
status judged against any configured target, and totals counted over the
forums the viewer may read — so two people with different access see different
totals, which is the test the coverage measurement asked for.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.governance import service_levels
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_user, unique


class TestForumServiceLevels(GovernanceTestCase):
	def setUp(self):
		super().setUp()
		self.overdue = make_forum(next_review_on=add_days(nowdate(), -10),
			last_attested_on=add_days(nowdate(), -400))
		self.fine = make_forum(next_review_on=add_days(nowdate(), 200), last_attested_on=add_days(nowdate(), -30))
		for forum in (self.overdue, self.fine):
			forum.db_set("is_active", 1)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_two_viewers_with_different_access_see_different_totals(self):
		office = make_user("Risk Governance Office")
		narrow = make_user("Risk Governance Office")
		frappe.get_doc({"doctype": "User Permission", "user": narrow, "allow": "Governance Forum",
			"for_value": self.fine.name, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)

		frappe.set_user(office)
		wide = service_levels.forum_service_levels()
		frappe.set_user(narrow)
		small = service_levels.forum_service_levels()

		self.assertEqual(small["forums"], 1)
		self.assertGreaterEqual(wide["forums"], 2)
		self.assertGreater(wide["forums"], small["forums"])
		self.assertEqual(small["review"]["overdue"], 0)
		self.assertGreaterEqual(wide["review"]["overdue"], 1)
		self.assertIn(self.overdue.name, [row["forum"] for row in wide["late"]])
		self.assertNotIn(self.overdue.name, [row["forum"] for row in small["late"]])

	def test_a_late_forum_is_listed_with_what_is_late(self):
		frappe.set_user(make_user("Risk Governance Office"))
		late = [row for row in service_levels.forum_service_levels()["late"] if row["forum"] == self.overdue.name]
		self.assertEqual(sorted(row["kind"] for row in late), ["attestation", "review"])
		review = next(row for row in late if row["kind"] == "review")
		self.assertEqual(review["days_late"], 10)

	def test_the_reporting_section_is_refused_to_someone_who_reads_no_forum(self):
		frappe.set_user(make_user("Policy Owner"))
		with self.assertRaises(frappe.PermissionError):
			service_levels.forum_service_levels()

	def test_one_forums_time_limits(self):
		frappe.set_user(make_user("Governance Viewer"))
		out = service_levels.forum_time_limits(self.overdue.name)
		self.assertEqual(out["review"]["standing"], "overdue")
		self.assertEqual(out["review"]["days"], -10)
		self.assertEqual(out["attestation"]["standing"], "overdue")
		self.assertTrue(out["status"]["stretches"])
		self.assertEqual(out["status"]["stretches"][-1]["outcome"], "no_target")

	def test_a_configured_target_judges_the_status_stretch(self):
		# The forum has sat at its status for two days, against a one-hour target.
		frappe.db.set_value("Governance Forum", self.overdue.name, "creation",
			frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-2), update_modified=False)
		frappe.get_doc({
			"doctype": "SLA Definition", "sla_code": unique("SLA"), "title": "Draft settled within a day",
			"target_doctype": "Governance Forum", "measure": "Time In State", "state_field": "compliance_status",
			"state_value": self.overdue.compliance_status, "target_hours": 1, "calendar": "24x7",
			"is_active": 1,
		}).insert(ignore_permissions=True)
		frappe.set_user(make_user("Governance Viewer"))
		out = service_levels.forum_time_limits(self.overdue.name)
		current = out["status"]["stretches"][-1]
		self.assertEqual(current["outcome"], "breached")
		self.assertEqual(current["target_hours"], 1.0)

	def test_a_reader_without_access_is_refused(self):
		frappe.set_user(make_user())
		with self.assertRaises(frappe.PermissionError):
			service_levels.forum_time_limits(self.overdue.name)

	def test_the_reporting_page_carries_the_section(self):
		from consilium.consilium_core.tests.test_portal_pages import render

		status, body = render("reports", "Administrator")
		frappe.local.request = None
		frappe.set_user("Administrator")
		self.assertEqual(status, 200)
		self.assertIn("Forum time limits", body)
		self.assertIn("forum-service-heading", body)
