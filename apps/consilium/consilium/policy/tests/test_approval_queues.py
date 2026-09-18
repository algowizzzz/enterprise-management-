"""P-8: approval steps routed to a role queue or a user group, and chased when left pending.

Two clauses of P-8 that were missing: "routing of approvals and notifications
to user groups" with "role-based assignment of approval steps", and
"automated routing, reminders and escalations". A route step may now send its
step to a role queue or a user group — every member sees it, any member may
decide it, and Core's sequential order still holds — and a daily section of
the reminder job tells the assignee (or queue) before a step falls due, chases
it after, and escalates it to the document approver or sponsor.

As elsewhere in the policy tests, no assertion names a state: records move by
performing configured actions and are read back through their flags.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

from consilium.consilium_core import approvals, inbox, reminders
from consilium.policy import routing
from consilium.policy.tests.test_portal_actions import (
    DOCTYPE,
    OFFICE,
    OWNER,
    PortalCase,
    _in_review,
    make_user,
)
from consilium.policy.tests.utils import as_user, make_user_group, refusals_for, unique


def make_role() -> str:
    return frappe.get_doc({"doctype": "Role", "role_name": unique("Queue Role"), "desk_access": 1}).insert(
        ignore_permissions=True
    ).name


def grant(role: str, *users: str) -> None:
    for user in users:
        frappe.get_doc("User", user).add_roles(role)


def only_route(*steps) -> str:
    """Make this the one active route for governing documents (rolled back after the test)."""
    frappe.db.sql('UPDATE "tabApproval Route" SET "is_active" = 0 WHERE "target_doctype" = %s', (DOCTYPE,))
    return frappe.get_doc(
        {
            "doctype": "Approval Route",
            "route_title": unique("Queue Route"),
            "target_doctype": DOCTYPE,
            "priority": 1,
            "is_active": 1,
            "steps": [{"is_mandatory": 1, "mode": "Sequential", **step} for step in steps],
        }
    ).insert(ignore_permissions=True).name


def decision_of(doc, approval_step: str):
    return frappe.get_doc("Approval Decision", frappe.db.get_value(
        "Approval Decision", {"subject_doctype": DOCTYPE, "subject_name": doc.name, "approval_step": approval_step},
        "name"))


def requested(doc) -> set[str]:
    return set(frappe.get_all("Notification Dispatch", filters={"subject_doctype": DOCTYPE, "subject_name": doc.name},
                              pluck="recipient"))


class TestRoleQueue(PortalCase):
    def setUp(self):
        super().setUp()
        self.role = make_role()
        self.first, self.second = make_user(), make_user()
        grant(self.role, self.first, self.second)
        only_route({"step_sequence": 1, "approval_step": "Second Line Review", "assignee_source": "Role Queue",
                    "required_role": self.role})

    def test_the_whole_queue_is_asked_and_any_member_may_decide(self):
        doc = _in_review()
        with as_user(make_user(OFFICE)):
            routing.raise_steps(doc.name)
        self.assertTrue({self.first, self.second} <= requested(doc))

        row = decision_of(doc, "Second Line Review")
        self.assertIn(row.assigned_to, (self.first, self.second))
        other = self.second if row.assigned_to == self.first else self.first
        with as_user(other):
            self.assertIn(row.name, routing.decidable_steps(frappe.get_doc(DOCTYPE, doc.name)))
            context = routing.decide_step(doc.name, row.name, "Approved", "Reviewed for the second line.")
        row.reload()
        self.assertEqual(row.assigned_to, other)
        self.assertEqual(row.acted_by, other)
        self.assertFalse(row.is_open)
        self.assertTrue(context["approval"]["chain"]["complete"])

    def test_someone_outside_the_queue_is_refused_and_audited(self):
        doc = _in_review()
        routing.instantiate(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        row = decision_of(doc, "Second Line Review")
        stranger = make_user()
        with as_user(stranger), self.assertRaises(frappe.PermissionError):
            routing.decide_step(doc.name, row.name, "Approved", "Not mine to give.")
        self.assertTrue(refusals_for(DOCTYPE, doc.name))
        row.reload()
        self.assertTrue(row.is_open)

    def test_the_path_shows_the_queue_before_it_is_raised(self):
        doc = _in_review()
        steps = routing.preview(doc.name)["steps"]
        self.assertEqual(steps[0]["queue"], f"role {self.role}")
        self.assertIn(steps[0]["assigned_to"], (self.first, self.second))

    def test_a_queue_step_without_its_queue_is_refused_as_configuration(self):
        with self.assertRaises(frappe.ValidationError):
            only_route({"step_sequence": 1, "approval_step": "Nobody", "assignee_source": "Role Queue"})
        with self.assertRaises(frappe.ValidationError):
            only_route({"step_sequence": 1, "approval_step": "Nobody", "assignee_source": "User Group"})


class TestUserGroupQueue(PortalCase):
    def setUp(self):
        super().setUp()
        self.first, self.second = make_user(), make_user()
        self.group = make_user_group([self.first, self.second])
        only_route(
            {"step_sequence": 1, "approval_step": "Owner Sign-off", "assignee_source": "Document Owner"},
            {"step_sequence": 2, "approval_step": "Committee Approval", "assignee_source": "User Group",
             "user_group": self.group},
        )

    def test_every_member_sees_it_in_my_work_once_it_is_their_turn(self):
        doc = _in_review()
        routing.instantiate(doc)
        row = decision_of(doc, "Committee Approval")
        other = self.second if row.assigned_to == self.first else self.first

        # Sequential: behind the owner's sign-off it is nobody's task yet.
        self.assertNotIn(row.name, [item["reference"] for item in inbox.collect(other)])
        owner_step = decision_of(doc, "Owner Sign-off")
        approvals.record_decision(owner_step, "Approved", comments="Signed off.", acting_user=owner_step.assigned_to)

        self.assertIn(row.name, [r.name for r in routing.queued_steps_for(other)])
        self.assertIn(row.name, [item["reference"] for item in inbox.collect(other)])
        self.assertIn(row.name, [item["approval_decision"] for item in self._my_open_steps(other)])

    def test_a_member_may_not_decide_out_of_turn(self):
        doc = _in_review()
        routing.instantiate(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        row = decision_of(doc, "Committee Approval")
        other = self.second if row.assigned_to == self.first else self.first
        with as_user(other), self.assertRaises(frappe.ValidationError):
            routing.decide_step(doc.name, row.name, "Approved", "Too early.")
        controls = [entry["control"] for entry in refusals_for(DOCTYPE, doc.name)]
        self.assertIn("sequential approval order", controls)
        row.reload()
        self.assertTrue(row.is_open)

    def test_raising_tells_the_group(self):
        doc = _in_review()
        with as_user(make_user(OFFICE)):
            routing.raise_steps(doc.name)
        self.assertTrue({self.first, self.second} <= requested(doc))

    @staticmethod
    def _my_open_steps(user):
        with as_user(user):
            return routing.my_open_steps()


class TestPendingStepReminders(PortalCase):
    def setUp(self):
        super().setUp()
        self.today = getdate(nowdate())

    def raised(self, source="Document Owner", **doc_values):
        only_route({"step_sequence": 1, "approval_step": "Pending Step", "assignee_source": source})
        doc = _in_review(**doc_values)
        routing.instantiate(doc)
        return doc, decision_of(doc, "Pending Step")

    def sent(self, row, event_subject: str) -> set[str]:
        return {r["recipient"] for r in frappe.get_all(
            "Notification Dispatch", filters={"subject_doctype": "Approval Decision", "subject_name": row.name},
            fields=["recipient", "rendered_subject"]) if (r["rendered_subject"] or "").startswith(event_subject)}

    def test_the_assignee_is_told_before_the_step_falls_due_and_only_once(self):
        doc, row = self.raised()
        due = reminders.approval_step_due(row)
        self.assertEqual(due, add_days(self.today, reminders.APPROVAL_STEP_DUE_DAYS))
        as_of = add_days(due, -1)
        self.assertTrue(reminders.remind_approval_steps(as_of, decisions=[row.name]))
        self.assertEqual(self.sent(row, "Approval due"), {row.assigned_to})
        self.assertEqual(reminders.remind_approval_steps(as_of, decisions=[row.name]), [])
        self.assertTrue(frappe.db.exists("Reminder Log", {"event_code": "policy.approval.step_due_soon",
                                                          "subject_name": row.name}))

    def test_overdue_is_chased_then_escalated_to_the_approver(self):
        doc, row = self.raised()
        due = reminders.approval_step_due(row)
        reminders.remind_approval_steps(add_days(due, 1), decisions=[row.name])
        self.assertEqual(self.sent(row, "Approval overdue"), {row.assigned_to})
        self.assertFalse(self.sent(row, "Escalated"))

        reminders.remind_approval_steps(add_days(due, reminders.APPROVAL_STEP_ESCALATE_DAYS), decisions=[row.name])
        self.assertEqual(self.sent(row, "Escalated"), {doc.document_approver})

    def test_when_the_approver_holds_the_step_the_sponsor_is_told(self):
        sponsor = make_user(OWNER)
        doc, row = self.raised(source="Document Approver")
        frappe.db.set_value(DOCTYPE, doc.name, "document_sponsor", sponsor, update_modified=False)
        due = reminders.approval_step_due(row)
        reminders.remind_approval_steps(add_days(due, reminders.APPROVAL_STEP_ESCALATE_DAYS + 1), decisions=[row.name])
        self.assertEqual(self.sent(row, "Escalated"), {sponsor})

    def test_a_queue_step_reminds_the_whole_queue(self):
        role = make_role()
        first, second = make_user(), make_user()
        grant(role, first, second)
        only_route({"step_sequence": 1, "approval_step": "Pending Step", "assignee_source": "Role Queue",
                    "required_role": role})
        doc = _in_review()
        routing.instantiate(doc)
        row = decision_of(doc, "Pending Step")
        reminders.remind_approval_steps(add_days(reminders.approval_step_due(row), -1), decisions=[row.name])
        self.assertEqual(self.sent(row, "Approval due"), {first, second})

    def test_a_step_waiting_its_turn_is_not_chased_and_its_clock_starts_when_it_is_turn(self):
        only_route(
            {"step_sequence": 1, "approval_step": "First", "assignee_source": "Document Owner"},
            {"step_sequence": 2, "approval_step": "Pending Step", "assignee_source": "Document Approver"},
        )
        doc = _in_review()
        routing.instantiate(doc)
        row = decision_of(doc, "Pending Step")
        self.assertEqual(reminders.remind_approval_steps(add_days(self.today, 30), decisions=[row.name]), [])

        first = decision_of(doc, "First")
        approvals.record_decision(first, "Approved", comments="Done.", acting_user=first.assigned_to)
        frappe.db.set_value("Approval Decision", first.name, "decided_on", add_to_date(now_datetime(), days=10))
        self.assertEqual(reminders.approval_step_due(row),
                         add_days(add_days(self.today, 10), reminders.APPROVAL_STEP_DUE_DAYS))

    def test_a_service_level_clock_on_the_step_sets_its_due_date(self):
        doc, row = self.raised()
        definition = frappe.get_doc({
            "doctype": "SLA Definition", "sla_code": unique("STEP"), "title": "Approval step",
            "target_doctype": "Approval Decision", "measure": "Total Open Time", "target_hours": 48,
            "calendar": "24x7", "is_active": 1,
        }).insert(ignore_permissions=True)
        target = add_to_date(now_datetime(), days=2)
        frappe.get_doc({
            "doctype": "SLA Clock", "subject_doctype": "Approval Decision", "subject_name": row.name,
            "sla_definition": definition.name, "started_on": now_datetime(), "target_on": target,
            "status": "Running", "is_open": 1,
        }).insert(ignore_permissions=True)
        self.assertEqual(reminders.approval_step_due(row), getdate(target))

    def test_the_daily_run_includes_approval_steps(self):
        self.assertIn("approval steps", [label for label, _doctype, _fn in reminders.DAILY])
