"""Restricted handling of sensitive escalations (E-16).

The restriction must hold on every read path, so it is tested on the API path
rather than on the form: `frappe.api.v1.document_list` is what
`GET /api/resource/Escalation Matter` dispatches to, and `frappe.client.get` is
what `GET /api/resource/Escalation Matter/<name>` dispatches to.
"""

from __future__ import annotations

import frappe

from consilium.escalation import sensitivity
from consilium.escalation.tests.utils import (
    EscalationTestCase,
    as_user,
    escalation_permission_hooks,
    make_user,
    rest_get,
    rest_list,
)


class TestSensitiveMatters(EscalationTestCase):
    def setUp(self):
        super().setUp()
        self.reference = self.reference_data()
        self.ordinary = self.make_matter(self.reference, escalation_title="An ordinary matter")
        self.restricted = self.make_matter(
            self.reference, escalation_title="A restricted matter", sensitive=1
        )
        self.cleared = make_user("Escalation Owner", sensitivity.SENSITIVE_ROLE)
        self.uncleared = make_user("Escalation Owner")

    def test_the_api_list_hides_a_sensitive_matter(self):
        with escalation_permission_hooks():
            visible = [row["name"] for row in rest_list("Escalation Matter", self.uncleared, limit_page_length=0)]
            self.assertIn(self.ordinary.name, visible)
            self.assertNotIn(self.restricted.name, visible)

            cleared = [row["name"] for row in rest_list("Escalation Matter", self.cleared, limit_page_length=0)]
            self.assertIn(self.restricted.name, cleared)

    def test_the_time_limit_position_counts_only_what_the_reader_may_see(self):
        """Management reporting counts clocks over the matters the reader may
        read (``sla.clock_position``): the Chief Risk Officer is shown the
        position without the clock records being opened to business roles, and
        a sensitive matter's clock is never counted for someone not cleared."""
        from consilium.consilium_core import sla
        from consilium.escalation.tests.utils import unique

        def escalations(user):
            with as_user(user):
                kinds = {k["kind"]: k for k in sla.clock_position()["kinds"]}
            return kinds.get("Escalation Matter", {}).get("running", 0)

        with escalation_permission_hooks():
            before = {user: escalations(user) for user in (self.cleared, self.uncleared)}
            definition = frappe.get_doc({
                "doctype": "SLA Definition", "sla_code": unique("SLA"), "title": "Reporting position",
                "target_doctype": "Escalation Matter", "measure": "Total Open Time", "target_hours": 8,
                "warning_threshold_pct": 80, "calendar": "24x7",
            }).insert(ignore_permissions=True)
            for matter in (self.ordinary, self.restricted):
                sla.start_clock(definition.name, "Escalation Matter", matter.name)
            self.assertEqual(escalations(self.cleared) - before[self.cleared], 2)
            self.assertEqual(escalations(self.uncleared) - before[self.uncleared], 1)
            with as_user(self.uncleared):
                self.assertFalse(frappe.has_permission("SLA Clock", "read"),
                                 "the counts do not open the clock records themselves")

    def test_the_api_read_of_a_sensitive_matter_is_refused(self):
        with escalation_permission_hooks():
            with self.assertRaises(frappe.PermissionError):
                rest_get("Escalation Matter", self.restricted.name, self.uncleared)

            allowed = rest_get("Escalation Matter", self.restricted.name, self.cleared)
            self.assertEqual(allowed.name, self.restricted.name)

    def test_a_filtered_api_read_cannot_be_used_to_confirm_existence(self):
        """Filtering on the title must not leak the row either."""
        with escalation_permission_hooks():
            rows = rest_list(
                "Escalation Matter",
                self.uncleared,
                filters=[["Escalation Matter", "escalation_title", "=", "A restricted matter"]],
                limit_page_length=0,
            )
            self.assertEqual(rows, [])

    def test_reports_and_counts_are_restricted_too(self):
        with escalation_permission_hooks():
            with as_user(self.uncleared):
                names = frappe.get_list("Escalation Matter", pluck="name", limit_page_length=0)
                self.assertNotIn(self.restricted.name, names)
                self.assertFalse(
                    frappe.has_permission("Escalation Matter", "read", doc=self.restricted.name)
                )

    def test_the_restriction_follows_the_records_hanging_off_the_matter(self):
        plan = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": self.restricted.name,
                "action_plan_name": "Remediate quietly",
                "start_date": "2026-01-10",
                "end_date": "2026-02-10",
                "accountable_executive": self.reference["user"],
                "owner_user": self.reference["user"],
            }
        ).insert(ignore_permissions=True)
        self.assertTrue(plan.sensitive, msg="the flag is inherited from the matter")

        with escalation_permission_hooks():
            visible = [row["name"] for row in rest_list("Action Plan", self.uncleared, limit_page_length=0)]
            self.assertNotIn(plan.name, visible)
            with self.assertRaises(frappe.PermissionError):
                rest_get("Action Plan", plan.name, self.uncleared)

    def test_clearing_the_flag_restores_visibility_everywhere(self):
        self.restricted.sensitive = 0
        self.restricted.save(ignore_permissions=True)
        with escalation_permission_hooks():
            visible = [row["name"] for row in rest_list("Escalation Matter", self.uncleared, limit_page_length=0)]
            self.assertIn(self.restricted.name, visible)

    def test_setting_the_flag_propagates_to_existing_children(self):
        plan = frappe.get_doc(
            {
                "doctype": "Action Plan",
                "escalation_matter": self.ordinary.name,
                "action_plan_name": "Remediate openly",
                "start_date": "2026-01-10",
                "end_date": "2026-02-10",
                "accountable_executive": self.reference["user"],
                "owner_user": self.reference["user"],
            }
        ).insert(ignore_permissions=True)
        self.assertFalse(plan.sensitive)

        self.ordinary.sensitive = 1
        self.ordinary.save(ignore_permissions=True)
        self.assertTrue(frappe.db.get_value("Action Plan", plan.name, "sensitive"))


class TestNamedPeopleSeeTheirSensitiveMatters(EscalationTestCase):
    """Restricted handling keeps a matter from people with no part in it, not
    from the people it names: raiser, identifier, accountable executive,
    response owner, members of its group queue."""

    def setUp(self):
        super().setUp()
        self.reference = self.reference_data()
        self.responder = make_user("Escalation Owner")
        self.member = make_user("Escalation Owner")
        self.stranger = make_user("Escalation Owner")
        self.group = frappe.get_doc({"doctype": "User Group", "__newname": f"Queue-{frappe.generate_hash(length=8)}",
                                     "user_group_members": [{"user": self.member}]}).insert(ignore_permissions=True).name
        self.matter = self.make_matter(self.reference, escalation_title="A restricted matter with owners",
                                       sensitive=1, response_owner=self.responder)
        frappe.db.set_value("Escalation Matter", self.matter.name, "assigned_group", self.group)
        self.plan = frappe.get_doc({
            "doctype": "Action Plan", "escalation_matter": self.matter.name, "action_plan_name": "Remediate",
            "start_date": "2026-01-10", "end_date": "2026-02-10",
            "accountable_executive": self.reference["user"], "owner_user": self.reference["user"],
        }).insert(ignore_permissions=True)

    def test_the_named_response_owner_reads_it_on_every_path(self):
        with escalation_permission_hooks():
            listed = [row["name"] for row in rest_list("Escalation Matter", self.responder, limit_page_length=0)]
            self.assertIn(self.matter.name, listed)
            self.assertEqual(rest_get("Escalation Matter", self.matter.name, self.responder).name, self.matter.name)
            plans = [row["name"] for row in rest_list("Action Plan", self.responder, limit_page_length=0)]
            self.assertIn(self.plan.name, plans)
            self.assertEqual(rest_get("Action Plan", self.plan.name, self.responder).name, self.plan.name)

    def test_a_member_of_its_group_queue_reads_it(self):
        with escalation_permission_hooks():
            listed = [row["name"] for row in rest_list("Escalation Matter", self.member, limit_page_length=0)]
            self.assertIn(self.matter.name, listed)
            with as_user(self.member):
                self.assertTrue(frappe.has_permission("Escalation Matter", "read", doc=self.matter.name))

    def test_the_accountable_executive_and_raiser_read_it(self):
        with escalation_permission_hooks():
            self.assertEqual(rest_get("Escalation Matter", self.matter.name, self.reference["user"]).name,
                             self.matter.name)
            raiser = make_user("Escalation Owner", sensitivity.SENSITIVE_ROLE)
            with as_user(raiser):
                raised = frappe.get_doc(self.matter_values(self.reference, escalation_title="Raised in confidence",
                                                           sensitive=1)).insert()
            frappe.get_doc("User", raiser).remove_roles(sensitivity.SENSITIVE_ROLE)
            with as_user(raiser):
                self.assertTrue(frappe.has_permission("Escalation Matter", "read", doc=raised.name))

    def test_someone_it_does_not_name_still_cannot(self):
        with escalation_permission_hooks():
            listed = [row["name"] for row in rest_list("Escalation Matter", self.stranger, limit_page_length=0)]
            self.assertNotIn(self.matter.name, listed)
            with self.assertRaises(frappe.PermissionError):
                rest_get("Escalation Matter", self.matter.name, self.stranger)
            with self.assertRaises(frappe.PermissionError):
                rest_get("Action Plan", self.plan.name, self.stranger)
