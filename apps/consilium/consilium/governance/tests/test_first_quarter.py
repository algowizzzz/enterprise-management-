"""G-10: the annual forum inventory attestation is conducted in the first quarter.

Three things are tested: the daily job opens the year's campaign in the first
quarter (once, and only then); opening one due outside a first quarter is
refused and audited unless an off-cycle reason is recorded; and a year with no
first-quarter campaign is reported. Years far in the future are used so that
the site's own campaigns never decide an outcome.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate

from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import reviews
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_seat, make_user, seat_role, unique

YEAR = 2091


def refusal_controls(label: str) -> list[str]:
    return [row["control"] for row in refusals_for("Attestation Campaign", label)]


class TestTheCampaignIsDueInTheFirstQuarter(GovernanceTestCase):
    def test_a_campaign_due_outside_the_quarter_is_refused_and_audited(self):
        label = unique("period")
        self.purge_on_teardown("Attestation Campaign", label)
        with self.assertRaises(frappe.ValidationError):
            reviews.open_inventory_attestation(label, due_on=f"{YEAR}-06-30")
        self.assertIn("inventory attestation first quarter", refusal_controls(label))
        self.assertFalse(frappe.db.exists("Attestation Campaign", {"period_label": label}))

    def test_a_campaign_due_in_the_quarter_opens(self):
        campaign = reviews.open_inventory_attestation(unique("period"), due_on=f"{YEAR}-03-31")
        self.assertEqual(str(campaign.due_on), f"{YEAR}-03-31")
        self.assertTrue(campaign.is_open)

    def test_with_no_due_date_the_next_quarter_deadline_is_used(self):
        campaign = reviews.open_inventory_attestation(unique("period"), opens_on=f"{YEAR}-11-02")
        self.assertEqual(str(campaign.due_on), f"{YEAR + 1}-03-31")
        campaign = reviews.open_inventory_attestation(unique("period"), opens_on=f"{YEAR}-02-02")
        self.assertEqual(str(campaign.due_on), f"{YEAR}-03-31")

    def test_an_off_cycle_campaign_opens_only_with_its_reason_recorded(self):
        reason = "Catch-up for the forums formed after the quarter closed."
        campaign = reviews.open_inventory_attestation(unique("period"), due_on=f"{YEAR}-09-30",
                                                      off_cycle_reason=reason)
        comments = frappe.get_all("Comment", filters={"reference_doctype": "Attestation Campaign",
                                                      "reference_name": campaign.name}, pluck="content")
        self.assertTrue(any(reason in (text or "") for text in comments))

    def test_the_portal_refuses_an_off_cycle_campaign_without_a_reason(self):
        label = unique("period")
        self.purge_on_teardown("Attestation Campaign", label)
        with self.assertRaises(frappe.ValidationError):
            reviews.open_forum_campaign("inventory", label, f"{YEAR}-07-15")
        self.assertIn("inventory attestation first quarter", refusal_controls(label))
        opened = reviews.open_forum_campaign("inventory", unique("period"), f"{YEAR}-07-15",
                                             off_cycle_reason="Added forums need attesting now.")
        self.assertTrue(frappe.db.exists("Attestation Campaign", opened["campaign"]))

    def test_the_dual_review_is_not_held_to_the_quarter(self):
        opened = reviews.open_forum_campaign("annual_review", unique("period"), f"{YEAR}-07-15")
        self.assertTrue(frappe.db.exists("Attestation Campaign", opened["campaign"]))


class TestTheDailyJobOpensIt(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.forum = make_forum()
        self.chair = make_user()
        make_seat(self.forum.name, seat_role(is_chair_role=1, max_holders=1, can_attest=1), self.chair)

    def test_in_the_first_quarter_it_opens_the_campaign_once(self):
        name = reviews.open_first_quarter_inventory(f"{YEAR}-01-02")
        self.assertTrue(name)
        campaign = frappe.get_doc("Attestation Campaign", name)
        self.assertEqual(campaign.campaign_type, reviews.INVENTORY_CAMPAIGN)
        self.assertEqual(str(campaign.opens_on), f"{YEAR}-01-02")
        self.assertEqual(str(campaign.due_on), f"{YEAR}-03-31")
        self.assertTrue(campaign.generated_on)
        # The chairs, secretaries and owners are asked at once.
        self.assertTrue(frappe.db.exists("Attestation Task", {"campaign": name, "assigned_to": self.chair}))
        # The first reminder falls on the opening day, then two before the deadline.
        offsets = sorted(int(row.offset_days) for row in campaign.reminder_schedule)
        self.assertEqual(offsets, [3, 14, (getdate(f"{YEAR}-03-31") - getdate(f"{YEAR}-01-02")).days])

        self.assertIsNone(reviews.open_first_quarter_inventory(f"{YEAR}-01-03"))
        self.assertEqual(frappe.db.count("Attestation Campaign", {"campaign_type": reviews.INVENTORY_CAMPAIGN,
                                                                  "due_on": f"{YEAR}-03-31"}), 1)

    def test_outside_the_first_quarter_it_does_nothing(self):
        self.assertIsNone(reviews.open_first_quarter_inventory(f"{YEAR}-04-01"))
        self.assertIsNone(reviews.open_first_quarter_inventory(f"{YEAR}-12-31"))

    def test_a_campaign_the_office_opened_is_not_opened_again(self):
        reviews.open_inventory_attestation(str(YEAR), opens_on=f"{YEAR - 1}-12-01", due_on=f"{YEAR}-03-15")
        self.assertIsNone(reviews.open_first_quarter_inventory(f"{YEAR}-01-02"))

    def test_a_label_already_used_off_cycle_does_not_stop_it(self):
        reviews.open_inventory_attestation(str(YEAR), due_on=f"{YEAR - 1}-10-01", off_cycle_reason="Catch-up.")
        name = reviews.open_first_quarter_inventory(f"{YEAR}-01-02")
        self.assertEqual(frappe.db.get_value("Attestation Campaign", name, "period_label"), f"{YEAR} Q1")

    def test_it_is_registered_on_the_daily_schedule(self):
        self.assertIn("consilium.governance.reviews.open_first_quarter_inventory",
                      frappe.get_hooks("scheduler_events").get("daily", []))


class TestAMissedQuarterIsReported(GovernanceTestCase):
    def test_a_year_without_a_first_quarter_campaign_is_flagged(self):
        standing = reviews.inventory_q1_standing(f"{YEAR}-05-01")
        self.assertIn(YEAR, standing["missed"])
        by_year = {row["year"]: row for row in standing["years"]}
        self.assertEqual(by_year[YEAR]["standing"], "missed")

    def test_a_year_whose_quarter_is_under_way_is_due_not_missed(self):
        standing = reviews.inventory_q1_standing(f"{YEAR}-02-01")
        self.assertIn(YEAR, standing["due"])
        self.assertNotIn(YEAR, standing["missed"])

    def test_a_held_year_is_not_flagged_and_an_off_cycle_one_is_listed(self):
        held = reviews.open_inventory_attestation(unique("period"), due_on=f"{YEAR}-03-31")
        off = reviews.open_inventory_attestation(unique("period"), due_on=f"{YEAR}-10-31", off_cycle_reason="Late.")
        standing = reviews.inventory_q1_standing(f"{YEAR}-11-01")
        by_year = {row["year"]: row for row in standing["years"]}
        self.assertEqual(by_year[YEAR]["campaign"], held.name)
        self.assertNotIn(YEAR, standing["missed"])
        self.assertIn(off.name, [row["name"] for row in standing["off_cycle"]])

    def test_the_campaign_screen_and_reporting_carry_it(self):
        from consilium.www import attestation_campaigns, reports

        context = frappe._dict()
        attestation_campaigns.get_context(context)
        self.assertIn("missed", context.inventory_q1)
        self.assertTrue(context.inventory_q1["next_due_label"])
        context = frappe._dict()
        reports.get_context(context)
        self.assertIn("missed", context.inventory_q1)
        self.assertIn("years", reviews.inventory_attestation_standing())
