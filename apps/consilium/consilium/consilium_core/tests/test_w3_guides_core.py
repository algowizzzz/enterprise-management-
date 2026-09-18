"""Core defects found while writing the illustrated guides (W3-5).

* A Business Calendar with holidays could not be opened on the desk: the form
  came back blank with "Value for Holidays cannot be a list".
* An attestation campaign's reminder schedule was stored and never read.
* The help assistant cited published guide articles by linking to the home
  page, which showed an article only when its category had a card there — so
  the Policy Lifecycle article was cited and could never be found.
"""

from pathlib import Path

import frappe
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import attestation, reminders
from consilium.consilium_core.assistant import corpus
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user, unique

EVENT = "attestation.task.reminder"


class TestBusinessCalendarOpensOnTheDesk(CoreTestCase):
    def test_a_calendar_with_holidays_loads_and_serialises(self):
        from frappe.desk.form.load import getdoc

        code = unique("CAL")
        frappe.get_doc({
            "doctype": "Business Calendar", "calendar_code": code, "title": "Head office",
            "holidays": ["2026-12-25", "2026-12-26"],
        }).insert(ignore_permissions=True)

        doc = frappe.get_doc("Business Calendar", code)
        doc.as_dict()  # raised "Value for Holidays cannot be a list"
        getdoc("Business Calendar", code)
        self.assertEqual(frappe.parse_json(frappe.response.docs[0].holidays), ["2026-12-25", "2026-12-26"])

        # And a loaded calendar saves without anyone touching the field.
        doc.title = "Head office (renamed)"
        doc.save(ignore_permissions=True)

    def test_the_desk_onload_hook_normalises_any_consilium_json_list(self):
        self.assertIn("consilium.consilium_core.jsonfields.normalise_loaded",
                      frappe.get_hooks("doc_events").get("*", {}).get("onload", []))


class TestCampaignReminderSchedule(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.attester = make_user()
        self.article = make_guide_article(category="Policy Lifecycle", title=unique("scheduled"),
                                          owner=self.attester)
        frappe.db.set_value("Guide Article", self.article.name, "owner", self.attester)
        self.due = add_days(nowdate(), 20)
        self.campaign = frappe.get_doc({
            "doctype": "Attestation Campaign",
            "campaign_title": "Scheduled reminders",
            "campaign_type": "Governing Document",
            "period_label": unique("period"),
            "target_doctype": "Guide Article",
            "population_filter": frappe.as_json({"name": self.article.name}),
            "participant_source": "Record Field",
            "participant_field": "owner",
            "opens_on": nowdate(),
            "due_on": self.due,
            "status": "Open",
            "reminder_schedule": [
                {"offset_days": 14, "note": "Two weeks to go."},
                {"offset_days": 3, "note": "Three days to go."},
            ],
        }).insert(ignore_permissions=True)
        [self.task] = attestation.generate_tasks(self.campaign)["created"]

    def run_on(self, day):
        return reminders.remind_attestation_campaigns(as_of=day, campaigns=[self.campaign.name])

    def logged(self) -> list:
        return frappe.get_all("Reminder Log", filters={"event_code": EVENT, "subject_name": self.task},
                              fields=["recipient", "sent_for_date"], order_by="sent_for_date asc")

    def test_reminders_follow_the_schedule_once_per_point(self):
        due = getdate(self.due)
        self.assertEqual(self.run_on(add_days(due, -15)), [], "before the first point, nothing")
        self.assertTrue(self.run_on(add_days(due, -14)), "the fourteen-day point")
        self.assertEqual(self.run_on(add_days(due, -14)), [], "the same run twice sends nothing")
        self.assertEqual(self.run_on(add_days(due, -10)), [], "between points, nothing")
        self.assertTrue(self.run_on(add_days(due, -2)), "the three-day point, caught up a day late")
        self.assertEqual(self.run_on(add_days(due, -1)), [])
        self.assertEqual([row.recipient for row in self.logged()], [self.attester, self.attester])

    def test_an_answered_task_is_not_chased(self):
        attestation.respond(self.task, "Attested", statement="Read and understood.")
        self.assertEqual(self.run_on(add_days(getdate(self.due), -3)), [])

    def test_a_campaign_with_no_schedule_sends_nothing(self):
        self.campaign.set("reminder_schedule", [])
        self.campaign.save(ignore_permissions=True)
        self.assertEqual(self.run_on(add_days(getdate(self.due), -3)), [])

    def test_the_daily_job_runs_it(self):
        self.assertIn(reminders.remind_attestation_campaigns, [fn for _l, _d, fn in reminders.DAILY])


class TestGuideArticlesAreFoundWhereTheAssistantPoints(CoreTestCase):
    def test_a_guide_article_is_cited_at_its_own_anchor(self):
        article = make_guide_article(category="Policy Lifecycle", title="The policy lifecycle, in brief",
                                     is_published=1)
        corpus.clear_cache()
        chunk = next(c for c in corpus.build(None).chunks if c["id"] == f"guide-article:{article.name}")
        self.assertEqual(chunk["href"], "/#" + corpus.guide_anchor(article.name))
        self.assertIn("Policy Lifecycle", chunk["extra"])

    def test_the_home_page_renders_articles_whose_category_has_no_card(self):
        """Every published article is listed, whatever its category, at the anchor
        the assistant links to. (The page once had cards for five categories only,
        and a sixth never showed.)"""
        page = (Path(frappe.get_app_path("consilium")) / "www" / "index.html").read_text()
        self.assertIn('id="guide-more"', page)
        self.assertIn("anchor(article.name)", page)
        self.assertNotIn("data-guide-category", page,
                         "no hard-coded category cards: every published article is listed")
