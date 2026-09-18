"""The attestation engine: one engine, three campaign types."""

import frappe
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import attestation
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user, unique


class TestAttestation(CoreTestCase):
    def setUp(self):
        # The population is scoped to this test's own records, so whatever else
        # the site holds (a demonstration organisation, an earlier run) stays out.
        self.marker = unique("Attested article")
        self.owner = make_user()
        self.second = make_user()
        self.in_scope = make_guide_article(category="Policy Lifecycle", title=self.marker)
        frappe.db.set_value("Guide Article", self.in_scope.name, "owner", self.owner)
        self.out_of_scope = make_guide_article(category="Getting Started")

        self.campaign = frappe.get_doc(
            {
                "doctype": "Attestation Campaign",
                "campaign_title": "Annual review",
                "campaign_type": "Governing Document",
                "period_label": unique("period"),
                "target_doctype": "Guide Article",
                "population_filter": frappe.as_json({"category": "Policy Lifecycle", "title": self.marker}),
                "participant_source": "Record Field",
                "participant_field": "owner",
                "opens_on": nowdate(),
                "due_on": add_days(nowdate(), 30),
                "status": "Open",
            }
        ).insert(ignore_permissions=True)

    def test_the_campaign_carries_semantic_flags_not_a_label_check(self):
        self.assertTrue(self.campaign.is_open)
        self.campaign.status = "Closed"
        self.campaign.save(ignore_permissions=True)
        self.assertFalse(self.campaign.is_open)

    def test_the_population_is_derived_from_live_data(self):
        self.assertEqual(attestation.population(self.campaign), [self.in_scope.name])

        late = make_guide_article(category="Policy Lifecycle", title=self.marker)
        frappe.db.set_value("Guide Article", late.name, "owner", self.owner)
        self.assertEqual(
            sorted(attestation.population(self.campaign)), sorted([self.in_scope.name, late.name])
        )

    def test_generation_creates_one_task_per_record_and_participant(self):
        result = attestation.generate_tasks(self.campaign)
        self.assertEqual(len(result["created"]), 1)
        task = frappe.get_doc("Attestation Task", result["created"][0])
        self.assertEqual(task.subject_name, self.in_scope.name)
        self.assertEqual(task.assigned_to, self.owner)
        self.assertEqual(getdate(task.due_on), getdate(self.campaign.due_on))
        self.assertTrue(task.is_open)

    def test_regenerating_does_not_duplicate_an_open_task(self):
        first = attestation.generate_tasks(self.campaign)
        second = attestation.generate_tasks(self.campaign)
        self.assertEqual(second["created"], [])
        self.assertEqual(second["skipped"], first["created"])
        self.assertEqual(
            frappe.db.count("Attestation Task", {"campaign": self.campaign.name}), 1
        )

    def test_regeneration_picks_up_a_record_added_after_the_campaign_opened(self):
        attestation.generate_tasks(self.campaign)
        late = make_guide_article(category="Policy Lifecycle", title=self.marker)
        frappe.db.set_value("Guide Article", late.name, "owner", self.owner)
        result = attestation.generate_tasks(self.campaign)
        self.assertEqual(len(result["created"]), 1)
        self.assertEqual(len(result["skipped"]), 1)

    def test_a_duplicate_task_is_refused_outright(self):
        attestation.generate_tasks(self.campaign)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Attestation Task",
                    "campaign": self.campaign.name,
                    "subject_doctype": "Guide Article",
                    "subject_name": self.in_scope.name,
                    "assigned_to": self.owner,
                    "due_on": self.campaign.due_on,
                    "status": "Pending",
                }
            ).insert(ignore_permissions=True)

    def test_a_closed_campaign_generates_nothing(self):
        self.campaign.status = "Closed"
        self.campaign.save(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            attestation.generate_tasks(self.campaign)

    def test_an_exception_response_needs_a_statement(self):
        task_name = attestation.generate_tasks(self.campaign)["created"][0]
        with self.assertRaises(frappe.ValidationError):
            attestation.respond(task_name, "Attested With Exceptions")

        task = attestation.respond(
            task_name, "Attested With Exceptions", statement="Two entries could not be confirmed."
        )
        self.assertTrue(task.requires_statement)
        self.assertFalse(task.is_open)
        self.assertTrue(task.responded_on)

    def test_a_clean_attestation_needs_no_statement(self):
        task_name = attestation.generate_tasks(self.campaign)["created"][0]
        task = attestation.respond(task_name, "Attested")
        self.assertFalse(task.is_open)
        self.assertFalse(task.requires_statement)

    def test_dual_signature_campaigns_carry_a_second_signatory(self):
        self.campaign.status = "Draft"
        self.campaign.save(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            self.campaign.requires_dual_signature = 1
            self.campaign.second_signatory_field = None
            self.campaign.save(ignore_permissions=True)

        self.campaign.reload()
        self.campaign.requires_dual_signature = 1
        self.campaign.second_signatory_field = "modified_by"
        self.campaign.status = "Open"
        self.campaign.save(ignore_permissions=True)
        frappe.db.set_value(
            "Guide Article", self.in_scope.name, "modified_by", self.second, update_modified=False
        )

        task_name = attestation.generate_tasks(self.campaign)["created"][0]
        task = frappe.get_doc("Attestation Task", task_name)
        self.assertEqual(task.second_signatory, self.second)

        with self.assertRaises(frappe.ValidationError):
            attestation.second_sign(task_name, user=self.owner)

        attestation.respond(task_name, "Attested")
        signed = attestation.second_sign(task_name, user=self.second)
        self.assertTrue(signed.second_signed_on)

    def test_the_seat_role_query_only_draws_attesting_seats(self):
        self.campaign.status = "Draft"
        self.campaign.participant_source = "Seat Role"
        self.campaign.seat_doctype = "Attestation Task"
        self.campaign.seat_subject_field = "subject_name"
        self.campaign.seat_user_field = "assigned_to"
        self.campaign.seat_role_field = "assigned_role"
        self.campaign.seat_end_date_field = "responded_on"
        self.campaign.save(ignore_permissions=True)

        query = attestation.seat_query(self.campaign, self.in_scope.name)
        self.assertEqual(query["subject_name"], self.in_scope.name)
        attesting = frappe.get_all("Governance Forum Role", filters={"can_attest": 1}, pluck="name")
        self.assertEqual(sorted(query["assigned_role"][1]), sorted(attesting))
        self.assertIn("CHAIR", attesting)
        self.assertNotIn("OBSERVER", attesting)

    def test_two_campaigns_cannot_share_a_type_and_period(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Attestation Campaign",
                    "campaign_title": "Duplicate",
                    "campaign_type": self.campaign.campaign_type,
                    "period_label": self.campaign.period_label,
                    "target_doctype": "Guide Article",
                    "participant_source": "Record Field",
                    "participant_field": "owner",
                    "opens_on": nowdate(),
                    "due_on": add_days(nowdate(), 30),
                    "status": "Draft",
                }
            ).insert(ignore_permissions=True)

    def test_overdue_tasks_expire(self):
        self.campaign.status = "Draft"
        self.campaign.save(ignore_permissions=True)
        self.campaign.due_on = add_days(nowdate(), -1)
        self.campaign.opens_on = add_days(nowdate(), -30)
        self.campaign.status = "Open"
        self.campaign.save(ignore_permissions=True)
        task_name = attestation.generate_tasks(self.campaign)["created"][0]

        attestation.expire_overdue(self.campaign.name)
        task = frappe.get_doc("Attestation Task", task_name)
        self.assertEqual(task.status, "Expired")
        self.assertFalse(task.is_open)



class TestUnconfiguredRecordsDoNotStopACampaign(CoreTestCase):
    """One record missing its second signatory must not stop the rest being asked.

    An annual attestation covers a whole population. Raising on the first record
    that cannot supply a second signatory would mean nobody is asked at all
    because of one unfilled field — and the person who has to fix it would learn
    about it from a failed job rather than from a list.
    """

    def setUp(self):
        self.marker = unique("Attested article")
        self.owner = make_user()
        self.second = make_user()
        self.configured = make_guide_article(category="Policy Lifecycle", title=self.marker)
        self.unconfigured = make_guide_article(category="Policy Lifecycle", title=self.marker)
        for article in (self.configured, self.unconfigured):
            frappe.db.set_value("Guide Article", article.name, "owner", self.owner)
        # Only one of the two names a second signatory.
        frappe.db.set_value("Guide Article", self.configured.name, "modified_by",
                            self.second, update_modified=False)
        frappe.db.set_value("Guide Article", self.unconfigured.name, "modified_by",
                            "", update_modified=False)

        self.campaign = frappe.get_doc(
            {
                "doctype": "Attestation Campaign",
                "campaign_title": "Annual review",
                "campaign_type": "Governing Document",
                "period_label": unique("period"),
                "target_doctype": "Guide Article",
                "population_filter": frappe.as_json({"category": "Policy Lifecycle", "title": self.marker}),
                "participant_source": "Record Field",
                "participant_field": "owner",
                "requires_dual_signature": 1,
                "second_signatory_field": "modified_by",
                "opens_on": nowdate(),
                "due_on": add_days(nowdate(), 30),
                "status": "Open",
            }
        ).insert(ignore_permissions=True)

    def test_the_configured_record_is_asked_and_the_other_is_reported(self):
        result = attestation.generate_tasks(self.campaign)

        subjects = [
            frappe.db.get_value("Attestation Task", name, "subject_name")
            for name in result["created"]
        ]
        self.assertIn(self.configured.name, subjects)
        self.assertNotIn(self.unconfigured.name, subjects)
        self.assertIn(self.unconfigured.name, result["unconfigured"])

    def test_filling_the_field_in_picks_the_record_up_on_the_next_run(self):
        attestation.generate_tasks(self.campaign)
        frappe.db.set_value("Guide Article", self.unconfigured.name, "modified_by",
                            self.second, update_modified=False)

        result = attestation.generate_tasks(self.campaign)

        subjects = [
            frappe.db.get_value("Attestation Task", name, "subject_name")
            for name in result["created"]
        ]
        self.assertIn(self.unconfigured.name, subjects)
        self.assertEqual(result["unconfigured"], [])
        # And the record that was already asked is not asked twice.
        self.assertNotIn(self.configured.name, subjects)

    def test_a_record_whose_second_signatory_is_its_participant_is_reported_not_raised(self):
        """The task would refuse to save (a dual signature needs two people), and
        that refusal, raised from generation, stopped every other record."""
        frappe.db.set_value("Guide Article", self.unconfigured.name, "modified_by",
                            self.owner, update_modified=False)
        result = attestation.generate_tasks(self.campaign)
        subjects = [
            frappe.db.get_value("Attestation Task", name, "subject_name")
            for name in result["created"]
        ]
        self.assertIn(self.configured.name, subjects)
        self.assertIn(self.unconfigured.name, result["unconfigured"])
