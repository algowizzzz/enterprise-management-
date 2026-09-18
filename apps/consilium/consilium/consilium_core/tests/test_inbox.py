"""The personal inbox (CS-10), answering attestations from it, and running campaigns.

Every endpoint here decides who may act from who the record names, not from a
role, so each is tested with the person it names, a delegate, and a stranger —
and the stranger's refusal is asserted, not assumed.

Everything is scoped to records these tests make: the campaigns target Guide
Articles marked with a unique title, so whatever else the site holds stays out.
"""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import approvals, attestation, inbox
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, refusals_for, unique


def _kinds(payload) -> dict:
    return {group["kind"]: group["items"] for group in payload["groups"]}


def _references(payload, kind) -> list[str]:
    return [item["reference"] for item in _kinds(payload).get(kind, [])]



#: Committed people shared by the classes below, removed when the module ends.
PEOPLE = PersonaPool()


def tearDownModule():
    PEOPLE.remove()

class InboxCase(CoreTestCase):
    #: The people each test works with, made once per class (see portal_personas).
    PERSONAS = {
        "attester": (), "second": (), "delegate": (), "stranger": (),
        "admin": ("Consilium Administrator",), "auditor": ("Consilium Audit",),
        "office": ("Risk Governance Office",), "policy_owner": ("Policy Owner",),
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        PEOPLE.attach(cls, cls.PERSONAS)

    def setUp(self):
        self.marker = unique("Inbox article")
        self.article = make_guide_article(category="Policy Lifecycle", title=self.marker)
        frappe.db.set_value("Guide Article", self.article.name, "owner", self.attester)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def campaign(self, **overrides):
        values = {
            "doctype": "Attestation Campaign",
            "campaign_title": "Inbox test campaign",
            "campaign_type": "Governing Document",
            "period_label": unique("period"),
            "target_doctype": "Guide Article",
            "population_filter": frappe.as_json({"title": self.marker}),
            "participant_source": "Record Field",
            "participant_field": "owner",
            "opens_on": nowdate(),
            "due_on": add_days(nowdate(), 30),
            "status": "Open",
        }
        values.update(overrides)
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def task(self, **overrides) -> str:
        created = attestation.generate_tasks(self.campaign(**overrides))["created"]
        self.assertEqual(len(created), 1)
        self.purge_on_teardown("Attestation Task", created[0])
        return created[0]

    def dual_task(self) -> str:
        frappe.db.set_value("Guide Article", self.article.name, "modified_by", self.second, update_modified=False)
        return self.task(requires_dual_signature=1, second_signatory_field="modified_by")

    def delegation(self, action: str, delegator=None, delegate=None):
        return frappe.get_doc(
            {
                "doctype": "Authority Delegation",
                "delegator": delegator or self.attester,
                "delegate": delegate or self.delegate,
                "scope_type": "DocType",
                "scope_doctype": "Guide Article",
                "valid_from": nowdate(),
                "valid_to": add_days(nowdate(), 30),
                "delegated_actions": [{"delegable_action": action}],
            }
        ).insert(ignore_permissions=True)

    def as_user(self, user):
        frappe.set_user(user)


class TestInboxAttestation(InboxCase):
    def test_the_assignee_sees_their_open_task_and_a_stranger_does_not(self):
        task = self.task()
        self.as_user(self.attester)
        payload = inbox.my_tasks()
        self.assertIn(task, _references(payload, "attestation"))
        item = next(i for i in _kinds(payload)["attestation"] if i["reference"] == task)
        self.assertEqual(item["action"], "respond")
        self.assertEqual(item["title"], self.marker)
        self.assertIsNone(item["acting_for"])

        self.as_user(self.stranger)
        self.assertNotIn(task, _references(inbox.my_tasks(), "attestation"))

    def test_the_assignee_answers_in_place_and_the_task_leaves_the_inbox(self):
        task = self.task()
        self.as_user(self.attester)
        result = attestation.respond_to_task(task, "Attested", statement="Accurate.")
        self.assertEqual(result["is_open"], 0)
        doc = frappe.get_doc("Attestation Task", task)
        self.assertFalse(doc.is_open)
        self.assertTrue(doc.responded_on)
        self.assertIsNone(doc.acting_delegation)
        self.assertNotIn(task, _references(inbox.my_tasks(), "attestation"))

    def test_a_stranger_is_refused_and_the_refusal_is_audited(self):
        task = self.task()
        self.as_user(self.stranger)
        with self.assertRaises(frappe.PermissionError):
            attestation.respond_to_task(task, "Attested")
        frappe.set_user("Administrator")
        self.assertTrue(frappe.db.get_value("Attestation Task", task, "is_open"))
        refusals = refusals_for("Attestation Task", task)
        self.assertTrue(refusals)
        self.assertEqual(refusals[-1]["control"], "attestation participant")

    def test_a_delegate_of_attestation_sees_and_answers_the_task_under_the_delegation(self):
        task = self.task()
        grant = self.delegation(attestation.ATTEST_ACTION)
        self.as_user(self.delegate)
        item = next(i for i in _kinds(inbox.my_tasks())["attestation"] if i["reference"] == task)
        self.assertEqual(item["acting_for"], self.attester)

        attestation.respond_to_task(task, "Attested")
        self.assertEqual(frappe.db.get_value("Attestation Task", task, "acting_delegation"), grant.name)

    def test_a_delegation_of_another_action_does_not_let_the_delegate_attest(self):
        task = self.task()
        self.delegation("APPROVE")
        self.as_user(self.delegate)
        self.assertNotIn(task, _references(inbox.my_tasks(), "attestation"))
        with self.assertRaises(frappe.PermissionError):
            attestation.respond_to_task(task, "Attested")

    def test_an_answer_needing_a_statement_is_refused_without_one(self):
        task = self.task()
        needs = [c["status"] for c in attestation.response_choices() if c["requires_statement"]]
        self.assertTrue(needs, "the flag map configures no answer that needs a statement")
        self.as_user(self.attester)
        with self.assertRaises(frappe.ValidationError):
            attestation.respond_to_task(task, needs[0], statement="   ")
        self.assertTrue(frappe.db.get_value("Attestation Task", task, "is_open"))

    def test_only_an_answer_is_accepted_not_an_open_or_lapsed_status(self):
        task = self.task()
        answers = {c["status"] for c in attestation.response_choices()}
        options = frappe.get_meta("Attestation Task").get_field("status").options.split("\n")
        not_answers = [o for o in options if o and o not in answers]
        self.assertTrue(not_answers)
        self.as_user(self.attester)
        for status in not_answers:
            with self.assertRaises(frappe.ValidationError):
                attestation.respond_to_task(task, status, statement="x")

    def test_a_task_cannot_be_answered_twice(self):
        task = self.task()
        self.as_user(self.attester)
        attestation.respond_to_task(task, "Attested")
        with self.assertRaises(frappe.ValidationError):
            attestation.respond_to_task(task, "Attested")


class TestSecondSignature(InboxCase):
    def test_the_answer_waits_in_the_second_signatorys_inbox_until_signed(self):
        task = self.dual_task()
        self.as_user(self.second)
        self.assertNotIn(task, _references(inbox.my_tasks(), "second_signature"),
                         "nothing to counter-sign before the first signatory answers")

        self.as_user(self.attester)
        attestation.respond_to_task(task, "Attested", statement="Operating within charter.")

        self.as_user(self.second)
        item = next(i for i in _kinds(inbox.my_tasks())["second_signature"] if i["reference"] == task)
        self.assertEqual(item["first_signatory"], self.attester)
        self.assertEqual(item["response_statement"], "Operating within charter.")

        attestation.second_sign_task(task)
        self.assertTrue(frappe.db.get_value("Attestation Task", task, "second_signed_on"))
        self.assertNotIn(task, _references(inbox.my_tasks(), "second_signature"))

    def test_anyone_but_the_named_second_signatory_is_refused(self):
        task = self.dual_task()
        self.as_user(self.attester)
        attestation.respond_to_task(task, "Attested")
        for user in (self.attester, self.stranger):
            self.as_user(user)
            with self.assertRaises(frappe.PermissionError):
                attestation.second_sign_task(task)
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.get_value("Attestation Task", task, "second_signed_on"))

    def test_a_task_that_lapsed_unanswered_cannot_be_counter_signed(self):
        task = self.dual_task()
        frappe.db.set_value("Attestation Task", task, "due_on", add_days(nowdate(), -1))
        campaign = frappe.db.get_value("Attestation Task", task, "campaign")
        self.assertIn(task, attestation.expire_overdue(campaign))

        self.as_user(self.second)
        self.assertNotIn(task, _references(inbox.my_tasks(), "second_signature"))
        with self.assertRaises(frappe.ValidationError):
            attestation.second_sign_task(task)


class TestInboxApprovalsAndReadRules(InboxCase):
    def test_an_approval_step_reaches_its_assignee_and_their_approval_delegate(self):
        step = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="Content approval", assigned_to=self.attester,
        )
        self.as_user(self.attester)
        self.assertIn(step.name, _references(inbox.my_tasks(), "approval"))

        self.as_user(self.delegate)
        self.assertNotIn(step.name, _references(inbox.my_tasks(), "approval"))
        frappe.set_user("Administrator")
        self.delegation("APPROVE")
        self.as_user(self.delegate)
        item = next(i for i in _kinds(inbox.my_tasks())["approval"] if i["reference"] == step.name)
        self.assertEqual(item["acting_for"], self.attester)

        self.as_user(self.stranger)
        self.assertNotIn(step.name, _references(inbox.my_tasks(), "approval"))

    def test_a_decided_step_leaves_the_inbox(self):
        step = approvals.request_decision(
            subject_doctype="Guide Article", subject_name=self.article.name,
            approval_step="Content approval", assigned_to=self.attester,
        )
        self.as_user(self.attester)
        approvals.record_decision(step.name, "Approved")
        self.assertNotIn(step.name, _references(inbox.my_tasks(), "approval"))

    def test_a_record_the_person_may_not_read_is_not_listed_even_when_they_are_named(self):
        """A remediation task names its assignee, but the list is read through the
        permission engine: without a role that reads the type, the screen it would
        open refuses them, so it is not offered."""
        def remediation(user):
            return frappe.get_doc(
                {
                    "doctype": "Metadata Remediation Task",
                    "subject_doctype": "Guide Article",
                    "subject_name": self.article.name,
                    "invalid_fieldname": "category",
                    "trigger_event": "Taxonomy Deactivated",
                    "assigned_to": user,
                    "due_on": add_days(nowdate(), -2),
                    "task_status": "Raised",
                }
            ).insert(ignore_permissions=True)

        unreadable = remediation(self.attester)
        self.as_user(self.attester)
        self.assertNotIn(unreadable.name, _references(inbox.my_tasks(), "remediation"))

        frappe.set_user("Administrator")
        task = remediation(self.policy_owner)
        self.as_user(self.policy_owner)
        payload = inbox.my_tasks()
        item = next(i for i in _kinds(payload)["remediation"] if i["reference"] == task.name)
        self.assertTrue(item["overdue"])
        self.assertGreaterEqual(payload["overdue"], 1)


class TestCountAndAccess(InboxCase):
    def test_the_badge_counts_what_the_inbox_lists(self):
        self.task()
        self.as_user(self.attester)
        payload = inbox.my_tasks()
        self.assertEqual(inbox.my_task_count(), {"count": payload["count"], "overdue": payload["overdue"]})
        self.assertGreaterEqual(payload["count"], 1)

    def test_a_signed_out_visitor_is_refused(self):
        self.as_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            inbox.my_tasks()
        with self.assertRaises(frappe.PermissionError):
            inbox.my_task_count()

    def test_the_acting_endpoints_accept_post_only(self):
        allowed = frappe.allowed_http_methods_for_whitelisted_func
        for fn in (attestation.respond_to_task, attestation.second_sign_task, attestation.generate_campaign_tasks):
            self.assertEqual(allowed[fn], ["POST"], fn.__name__)
        for fn in (inbox.my_tasks, inbox.my_task_count):
            self.assertEqual(allowed[fn], ["GET"], fn.__name__)


class TestCampaignAdministration(InboxCase):
    def test_an_administrator_generates_tasks_and_sees_the_board(self):
        campaign = self.campaign()
        self.as_user(self.admin)
        result = attestation.generate_campaign_tasks(campaign.name)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["unconfigured"], [])
        self.purge_on_teardown("Attestation Task", frappe.db.get_value("Attestation Task", {"campaign": campaign.name}))

        again = attestation.generate_campaign_tasks(campaign.name)
        self.assertEqual((again["created"], again["skipped"]), (0, 1))

        board = {row["name"]: row for row in attestation.campaign_overview()["campaigns"]}
        self.assertEqual((board[campaign.name]["tasks"], board[campaign.name]["open"]), (1, 1))

    def test_unconfigured_records_are_named_so_they_can_be_chased(self):
        # No second signatory on the record: the dual campaign cannot ask it.
        campaign = self.campaign(requires_dual_signature=1, second_signatory_field="modified_by")
        frappe.db.set_value("Guide Article", self.article.name, "modified_by", self.attester, update_modified=False)
        self.as_user(self.admin)
        result = attestation.generate_campaign_tasks(campaign.name)
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["unconfigured"], [{"name": self.article.name, "label": self.marker}])

    def test_anyone_else_is_refused(self):
        campaign = self.campaign()
        for user in (self.stranger, self.auditor, self.office):
            self.as_user(user)
            with self.assertRaises(frappe.PermissionError):
                attestation.generate_campaign_tasks(campaign.name)
            frappe.set_user("Administrator")
        self.assertFalse(frappe.db.exists("Attestation Task", {"campaign": campaign.name}))

        self.as_user(self.stranger)
        with self.assertRaises(frappe.PermissionError):
            attestation.campaign_overview()

    def test_the_governance_office_runs_forum_campaigns_only(self):
        from consilium.governance import reviews

        other = self.campaign()
        self.as_user(self.office)
        # A campaign over another record type is an administrator's.
        with self.assertRaises(frappe.PermissionError):
            reviews.generate_forum_campaign_tasks(other.name)
        with self.assertRaises(frappe.ValidationError):
            reviews.open_forum_campaign("not-a-kind", unique("period"), str(add_days(nowdate(), 30)))

        # Due in a first quarter: the inventory attestation is conducted then (G-10).
        opened = reviews.open_forum_campaign("inventory", unique("period"), str(reviews.next_first_quarter_due()))
        doc = frappe.get_doc("Attestation Campaign", opened["campaign"])
        self.assertEqual(doc.target_doctype, "Governance Forum")
        self.assertTrue(doc.is_open)
        self.assertTrue(doc.generated_on)
        for name in frappe.get_all("Attestation Task", filters={"campaign": doc.name}, pluck="name"):
            self.purge_on_teardown("Attestation Task", name)
        self.assertIn(doc.name, [row["name"] for row in reviews.forum_campaign_overview()["campaigns"]])

    def test_someone_outside_the_office_cannot_open_a_forum_campaign(self):
        from consilium.governance import reviews

        self.as_user(self.stranger)
        with self.assertRaises(frappe.PermissionError):
            reviews.open_forum_campaign("inventory", unique("period"), str(add_days(nowdate(), 30)))
        with self.assertRaises(frappe.PermissionError):
            reviews.forum_campaign_overview()
