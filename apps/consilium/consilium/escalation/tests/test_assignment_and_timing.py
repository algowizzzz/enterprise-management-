"""Assignment by role or group, the systemic route, the challenge service level,
and time in each status (E-5, E-8, E-9, E-13).

Each behaviour is exercised through the entry points the portal calls — the
inbox, the matter's workbench, ``take_ownership``, the review round, the time
in state payload — on the path that should work and on the paths that must
not: someone outside the queue, a matter already taken, a matter a member may
not see. A refusal on standing is audited out of band, so the tests that
expect one purge it afterwards.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, get_datetime, now, nowdate

from consilium.consilium_core import inbox, sla, state_durations
from consilium.consilium_core.tests.utils import refusals_for
from consilium.escalation import assignment, resolution, timing
from consilium.escalation.tests.test_portal_actions import PortalTestCase
from consilium.escalation.tests.utils import as_user, make_forum, make_user, unique


def make_group(*members: str) -> str:
    name = unique("Queue")
    frappe.get_doc({
        "doctype": "User Group", "__newname": name,
        "user_group_members": [{"user": m} for m in members],
    }).insert(ignore_permissions=True)
    return name


def make_role() -> str:
    name = unique("Queue Role")
    frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert(ignore_permissions=True)
    return name


def quiet_site_service_levels() -> None:
    """Switch off, for this test's transaction, the status-driven service levels
    the site already has on escalation matters. A shared or demonstration site
    carries its own; the tests measure against the ones they create."""
    for name in frappe.get_all("SLA Definition", filters={"target_doctype": "Escalation Matter", "is_active": 1,
                                                          "measure": ["in", list(sla.STATE_MEASURES)]},
                               pluck="name"):
        frappe.db.set_value("SLA Definition", name, "is_active", 0, update_modified=False)
    sla.clear_cache()


def queue_items(user: str) -> list[str]:
    with as_user(user):
        return [item["reference"] for item in inbox.collect(user) if item["kind"] == "escalation_queue"]


class AssignmentTestCase(PortalTestCase):
    """A matter raised with no response owner, and people in and out of its queue."""

    def build(self):
        super().build()
        self.member_a = make_user("Escalation Owner")
        self.member_b = make_user("Escalation Owner")
        self.outsider = make_user("Escalation Owner")
        self.group = make_group(self.member_a, self.member_b)

    def route(self, *, group=None, role=None, condition=None, extra_rules=(), **rule):
        """A matrix whose rule for this test's escalation type names a queue.

        Effective today, so it is the first live matrix routing reads.
        """
        condition = condition if condition is not None else {"escalation_type": self.reference["escalation_type"]}
        return self.make_matrix(
            self.reference,
            effective_from=nowdate(),
            rules=[{"rule_code": "R-QUEUE", "priority": 10, "condition": condition,
                    "resulting_severity": "Medium", "route_to_group": group, "route_to_role": role,
                    "is_active": 1, **rule},
                   *extra_rules],
        )

    def queued_matter(self, **overrides):
        return self.make_matter(self.reference, response_owner=None, **overrides)


class TestAssignmentByGroup(AssignmentTestCase):
    def test_the_rule_puts_the_matter_in_its_groups_queue(self):
        self.route(group=self.group)
        matter = self.queued_matter()
        self.assertEqual(matter.assigned_group, self.group)
        self.assertEqual(matter.assignment_rule, "R-QUEUE")
        self.assertTrue(assignment.is_waiting(matter))
        self.assertIn(matter.name, queue_items(self.member_a))
        self.assertIn(matter.name, queue_items(self.member_b))
        self.assertNotIn(matter.name, queue_items(self.outsider))

    def test_the_queue_is_told_when_the_matter_enters_it(self):
        self.route(group=self.group)
        matter = self.queued_matter()
        told = set(frappe.get_all("Notification Dispatch",
                                  filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
                                  pluck="recipient"))
        self.assertTrue({self.member_a, self.member_b} <= told)
        self.assertNotIn(self.outsider, told)

    def test_a_member_takes_ownership_and_it_leaves_every_queue(self):
        self.route(group=self.group)
        matter = self.queued_matter()
        with as_user(self.member_a):
            wb = resolution.get_matter_workbench(matter.name)
            self.assertTrue(wb["actions"]["take_ownership"])
            self.assertTrue(wb["matter"]["waiting_for_owner"])
            wb = assignment.take_ownership(matter.name)
        self.assertFalse(wb["actions"]["take_ownership"])
        fresh = frappe.get_doc("Escalation Matter", matter.name)
        self.assertEqual(fresh.response_owner, self.member_a)
        self.assertTrue(fresh.ownership_taken_on)
        self.assertFalse(assignment.is_waiting(fresh))
        self.assertNotIn(matter.name, queue_items(self.member_a))
        self.assertNotIn(matter.name, queue_items(self.member_b))

    def test_a_matter_already_taken_is_refused_with_its_owner(self):
        self.route(group=self.group)
        matter = self.queued_matter()
        with as_user(self.member_a):
            assignment.take_ownership(matter.name)
        with as_user(self.member_b):
            self.assertFalse(resolution.get_matter_workbench(matter.name)["actions"]["take_ownership"])
            with self.assertRaises(frappe.ValidationError) as caught:
                assignment.take_ownership(matter.name)
        self.assertIn(self.member_a, str(caught.exception))
        self.assertEqual(frappe.db.get_value("Escalation Matter", matter.name, "response_owner"), self.member_a)

    def test_someone_outside_the_queue_is_refused_and_audited(self):
        self.route(group=self.group)
        matter = self.queued_matter()
        self.purge_on_teardown("Escalation Matter", matter.name)
        with as_user(self.outsider):
            self.assertFalse(resolution.get_matter_workbench(matter.name)["actions"]["take_ownership"])
            with self.assertRaises(frappe.PermissionError):
                assignment.take_ownership(matter.name)
        self.assertIn("escalation queue", [r.control for r in refusals_for("Escalation Matter", matter.name)])
        self.assertFalse(frappe.db.get_value("Escalation Matter", matter.name, "response_owner"))

    def test_a_member_without_the_owner_role_cannot_take_it(self):
        reader = make_user("Escalation Reviewer")
        frappe.get_doc("User Group", self.group).append("user_group_members", {"user": reader}).save(
            ignore_permissions=True)
        self.route(group=self.group)
        matter = self.queued_matter()
        self.purge_on_teardown("Escalation Matter", matter.name)
        with as_user(reader), self.assertRaises(frappe.PermissionError):
            assignment.take_ownership(matter.name)
        self.assertIn("escalation action role",
                      [r.control for r in refusals_for("Escalation Matter", matter.name)])

    def test_an_owner_named_from_the_queue_has_already_taken_it(self):
        self.route(group=self.group)
        matter = self.make_matter(self.reference, response_owner=self.member_b)
        self.assertEqual(matter.assigned_group, self.group)
        self.assertFalse(assignment.is_waiting(matter))
        self.assertNotIn(matter.name, queue_items(self.member_a))

    def test_a_sensitive_matter_reaches_its_group_but_only_cleared_holders_of_a_role(self):
        # A group is a list of named people: its members see the matter.
        self.route(group=self.group)
        matter = self.queued_matter(sensitive=1)
        self.assertIn(matter.name, queue_items(self.member_a))
        self.assertIn(self.member_a, frappe.get_all(
            "Notification Dispatch", filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            pluck="recipient"))
        self.assertNotIn(matter.name, queue_items(self.outsider))

    def test_a_sensitive_matter_in_a_role_queue_reaches_only_cleared_holders(self):
        role = make_role()
        cleared = make_user("Escalation Owner", "Sensitive Escalation Access", role)
        frappe.get_doc("User", self.outsider).add_roles(role)
        self.route(role=role)
        matter = self.queued_matter(sensitive=1)
        self.assertIn(matter.name, queue_items(cleared))
        self.assertNotIn(matter.name, queue_items(self.outsider))
        told = frappe.get_all("Notification Dispatch",
                              filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
                              pluck="recipient")
        self.assertIn(cleared, told)
        self.assertNotIn(self.outsider, told, "a notice would name a matter the holder may not see")

    def test_a_rule_without_a_queue_clears_it(self):
        self.route(group=self.group, condition={"escalation_type": self.reference["escalation_type"],
                                                "severity": "Medium"},
                   extra_rules=[{"rule_code": "R-PLAIN", "priority": 20, "condition": json.dumps({}),
                                 "resulting_severity": "Low", "is_active": 1}])
        matter = self.queued_matter(severity="Medium")
        self.assertEqual(matter.assigned_group, self.group)
        matter.severity = "Low"
        matter.save(ignore_permissions=True)
        self.assertFalse(matter.assigned_group)
        self.assertFalse(matter.assignment_rule)


class TestAssignmentByRole(AssignmentTestCase):
    def test_every_holder_of_the_role_sees_it_and_one_takes_it(self):
        role = make_role()
        frappe.get_doc("User", self.member_a).add_roles(role)
        frappe.get_doc("User", self.outsider).add_roles(role)
        self.route(role=role)
        matter = self.queued_matter()
        self.assertEqual(matter.assigned_role, role)
        self.assertIn(matter.name, queue_items(self.member_a))
        self.assertIn(matter.name, queue_items(self.outsider))
        self.assertNotIn(matter.name, queue_items(self.member_b))
        self.assertEqual(set(assignment.queue_members(matter)), {self.member_a, self.outsider})
        with as_user(self.outsider):
            assignment.take_ownership(matter.name)
        self.assertEqual(frappe.db.get_value("Escalation Matter", matter.name, "response_owner"), self.outsider)
        self.assertNotIn(matter.name, queue_items(self.member_a))


class TestSystemicRoute(AssignmentTestCase):
    """A matter flagged systemic follows the systemic rule: a higher forum and owner."""

    def build(self):
        super().build()
        self.head_role = make_role()
        self.head = make_user("Escalation Owner", self.head_role)
        self.higher_forum = make_forum()

    def systemic_matrix(self):
        return self.make_matrix(
            self.reference,
            effective_from=nowdate(),
            rules=[
                {"rule_code": "R-SYSTEMIC", "priority": 5, "condition": json.dumps({"systemic": True}),
                 "resulting_severity": "High", "route_to_role": self.head_role, "is_active": 1},
                {"rule_code": "R-ORDINARY", "priority": 50,
                 "condition": json.dumps({"escalation_type": self.reference["escalation_type"]}),
                 "resulting_severity": "Low", "route_to_group": self.group, "is_active": 1},
            ],
            routes=[{"rule_code": "R-SYSTEMIC", "governance_forum": self.higher_forum,
                     "role_in_escalation": "Decision"},
                    {"rule_code": "R-ORDINARY", "governance_forum": self.reference["forum"]}],
        )

    def test_flagging_a_matter_systemic_reroutes_it_to_the_higher_forum_and_owner(self):
        self.systemic_matrix()
        matter = self.make_matter(self.reference, severity_source="Matrix", response_owner=self.member_a)
        self.assertEqual(matter.matched_matrix_rule, "R-ORDINARY")
        self.assertEqual(matter.severity, "Low")
        self.assertNotIn(self.higher_forum, [row.governance_forum for row in matter.governance_forums])

        matter.systemic = 1
        matter.save(ignore_permissions=True)
        self.assertEqual(matter.matched_matrix_rule, "R-SYSTEMIC")
        self.assertEqual(matter.severity, "High")
        self.assertIn(self.higher_forum, [row.governance_forum for row in matter.governance_forums])
        self.assertEqual(matter.assigned_role, self.head_role)
        self.assertFalse(matter.assigned_group)

        # The named owner is not in the systemic queue, so the matter waits for
        # the head of the function, who is told and takes it over.
        self.assertTrue(assignment.is_waiting(matter))
        self.assertIn(matter.name, queue_items(self.head))
        self.assertTrue(frappe.db.exists("Notification Dispatch", {
            "subject_doctype": "Escalation Matter", "subject_name": matter.name, "recipient": self.head}))
        with as_user(self.head):
            assignment.take_ownership(matter.name)
        self.assertEqual(frappe.db.get_value("Escalation Matter", matter.name, "response_owner"), self.head)

    def test_the_matrix_proposes_the_systemic_route_before_the_matter_is_saved(self):
        self.systemic_matrix()
        values = self.matter_values(self.reference, systemic=1)
        values.pop("doctype")
        proposal = resolution.routing.propose_pathway(matter=values)
        self.assertEqual(proposal["rule_code"], "R-SYSTEMIC")
        self.assertEqual(proposal["route_to_role"], self.head_role)


class TestChallengeServiceLevel(AssignmentTestCase):
    """A second-line challenge on a systemic matter runs to a configured service level."""

    def build(self):
        super().build()
        quiet_site_service_levels()
        self.challenge = frappe.get_doc({
            "doctype": "SLA Definition", "sla_code": unique("SLA-CHALLENGE").upper(),
            "title": "Second-line challenge of a systemic matter", "target_doctype": "Escalation Matter",
            "measure": sla.MEASURE_TIME_IN_STATE, "state_field": timing.CHALLENGE_FLAG, "state_value": "1",
            "applies_when": json.dumps({"systemic": 1}), "target_hours": 16, "warning_threshold_pct": 75,
            "calendar": "24x7", "is_active": 1,
        }).insert(ignore_permissions=True)
        self.matter.systemic = 1
        self.matter.save(ignore_permissions=True)

    def challenge_clocks(self, name=None):
        return frappe.get_all("SLA Clock", filters={"sla_definition": self.challenge.name,
                                                    "subject_name": name or self.matter.name},
                              fields=["name", "is_open", "stopped_on", "breached_on"])

    def test_the_clock_starts_when_the_matter_goes_to_the_second_line_and_stops_when_it_comes_back(self):
        self.assertEqual(self.challenge_clocks(), [], "no clock while the first line has it")
        self.send_for_review()
        clock = timing.open_challenge_clock(self.matter.name)
        self.assertTrue(clock)

        with as_user(self.reviewer):
            resolution.record_review_round(self.matter.name, "Challenged", "The root cause is not evidenced.")
            round_ = self.fresh().reviews[-1]
            self.assertEqual(round_.sla_clock, clock, "the round is answered against the running clock")
            resolution.move_matter_status(self.matter.name, self.open_target(review=False))

        [stopped] = self.challenge_clocks()
        self.assertFalse(stopped.is_open)
        self.assertTrue(stopped.stopped_on)
        self.assertFalse(stopped.breached_on)
        payload = timing.time_in_state(self.matter.name)
        self.assertEqual([c["name"] for c in payload["challenge"]], [clock])

    def test_a_matter_that_is_not_systemic_runs_no_challenge_clock(self):
        self.matter.systemic = 0
        self.matter.save(ignore_permissions=True)
        self.send_for_review()
        self.assertIsNone(timing.open_challenge_clock(self.matter.name))
        self.assertEqual(self.challenge_clocks(), [])

    def test_a_late_challenge_breaches_without_raising_the_matter(self):
        self.send_for_review()
        severity = self.fresh().severity
        resolution.sweep_breaches(as_of=add_to_date(now(), hours=17, as_string=True))
        [clock] = self.challenge_clocks()
        self.assertTrue(clock.breached_on)
        fresh = self.fresh()
        self.assertEqual(fresh.severity, severity)
        self.assertFalse(fresh.threshold_breached)


class TestTimeInStatus(PortalTestCase):
    """Per-status durations from the change log, judged against configured targets."""

    def build(self):
        super().build()
        quiet_site_service_levels()
        self.first = self.matter.status
        self.second = self.open_target(review=False)
        self.move(self.second)
        self.third = self.open_target(review=True)
        self.move(self.third)
        # Put the history on a known timeline: created at T0, moved at T0+2h
        # and T0+5h. The change log is the evidence, so it is what is moved.
        self.t0 = get_datetime("2026-03-02 09:00:00")
        frappe.db.set_value("Escalation Matter", self.matter.name, "creation", self.t0, update_modified=False)
        moves = [
            row.name for row in frappe.get_all(
                "Version", filters={"ref_doctype": "Escalation Matter", "docname": self.matter.name},
                fields=["name", "data"], order_by="creation asc")
            if any(entry[0] == "status" for entry in json.loads(row.data or "{}").get("changed") or [])
        ]
        self.assertEqual(len(moves), 2)
        for name, hours in zip(moves, (2, 5)):
            frappe.db.set_value("Version", name, "creation", self.t0 + timedelta(hours=hours),
                                update_modified=False)
        self.as_of = self.t0 + timedelta(hours=6)

    def move(self, status):
        doc = self.fresh()
        doc.status = status
        # The framework skips its change log under test unless asked; the log
        # is exactly what the durations are rebuilt from.
        doc.save(ignore_permissions=True, ignore_version=False)

    def target(self, value, hours, **extra):
        return frappe.get_doc({
            "doctype": "SLA Definition", "sla_code": unique("SLA-STATE").upper(),
            "title": f"Time in {value}", "target_doctype": "Escalation Matter",
            "measure": sla.MEASURE_TIME_IN_STATE, "state_field": "status", "state_value": value,
            "target_hours": hours, "warning_threshold_pct": 50, "calendar": "24x7", "is_active": 1, **extra,
        }).insert(ignore_permissions=True)

    def test_each_stay_is_rebuilt_from_the_change_log(self):
        result = state_durations.summary("Escalation Matter", self.matter.name, "status", as_of=self.as_of)
        stays = [(row["value"], row["seconds"], row["is_current"]) for row in result["stretches"]]
        self.assertEqual(stays, [(self.first, 7200, False), (self.second, 10800, False), (self.third, 3600, True)])
        self.assertEqual({t["value"]: t["seconds"] for t in result["totals"]},
                         {self.first: 7200, self.second: 10800, self.third: 3600})
        self.assertTrue(all(row["outcome"] == "no_target" for row in result["stretches"]))

    def test_a_configured_target_judges_each_stay(self):
        self.target(self.first, 1)
        self.target(self.second, 4)
        self.target(self.third, 1.5)
        result = state_durations.summary("Escalation Matter", self.matter.name, "status", as_of=self.as_of)
        outcomes = {row["value"]: row["outcome"] for row in result["stretches"]}
        self.assertEqual(outcomes[self.first], "breached", "two hours against a one-hour target")
        self.assertEqual(outcomes[self.second], "within", "three hours against four")
        self.assertEqual(outcomes[self.third], "warning", "an hour into ninety minutes, past the 50% warning")
        totals = {t["value"]: t for t in result["totals"]}
        self.assertEqual(totals[self.first]["breaches"], 1)
        self.assertEqual(totals[self.second]["target_hours"], 4.0)
        self.assertEqual(len(result["configured"]), 3)

    def test_a_target_scoped_to_other_matters_does_not_apply(self):
        self.target(self.first, 1, applies_when=json.dumps({"systemic": 1}))
        result = state_durations.summary("Escalation Matter", self.matter.name, "status", as_of=self.as_of)
        self.assertEqual(result["stretches"][0]["outcome"], "no_target")

    def test_the_page_payload_follows_read_access(self):
        self.target(self.first, 1)
        with as_user(self.auditor):
            payload = timing.get_time_in_state(self.matter.name)
        self.assertEqual([t["value"] for t in payload["status"]["totals"]], [self.first, self.second, self.third])
        stranger = make_user()
        with as_user(stranger), self.assertRaises(frappe.PermissionError):
            timing.get_time_in_state(self.matter.name)

    def test_closing_stops_the_matters_own_clock_and_not_only_a_status_clock(self):
        total = self.make_sla_definition(target_hours=400)
        self.make_matrix(self.reference, effective_from=nowdate(),
                         rules=[{"rule_code": "R-TOTAL", "condition": json.dumps({}), "resulting_severity": "Medium",
                                 "sla_definition": total.name, "is_active": 1}])
        matter = self.make_matter(self.reference, response_owner=self.owner, response_template_completed=1)
        in_state = self.target(matter.status, 400)
        # Give the status-driven clock the lower name, so "the first open
        # clock" is the wrong one.
        sla.start_clock(in_state.name, "Escalation Matter", matter.name, started_on=matter.creation)
        self.make_closure(matter)
        matter.reload()
        matter.status = resolution.closing_states()[0]["value"]
        matter.save(ignore_permissions=True)
        open_clocks = frappe.get_all("SLA Clock", filters={"subject_doctype": "Escalation Matter",
                                                           "subject_name": matter.name, "is_open": 1},
                                     fields=["sla_definition"])
        self.assertEqual(open_clocks, [], "every clock stops when the matter comes to rest")


class TestRetiredValuesAreNotOffered(PortalTestCase):
    """A new review round is recorded against a line of defence in use."""

    def line(self, *, is_active: int) -> str:
        code = unique("LOD").upper()
        return frappe.get_doc({"doctype": "Line Of Defence", "line_of_defence_code": code,
                               "line_of_defence_name": "A line", "line_number": 2,
                               "is_active": is_active}).insert(ignore_permissions=True).name

    def test_a_retired_line_is_neither_offered_nor_accepted(self):
        live, retired = self.line(is_active=1), self.line(is_active=0)
        self.send_for_review()
        with as_user(self.reviewer):
            offered = [row.name for row in resolution.get_matter_workbench(self.matter.name)["lines_of_defence"]]
            self.assertIn(live, offered)
            self.assertNotIn(retired, offered)
            with self.assertRaises(frappe.ValidationError):
                resolution.record_review_round(self.matter.name, "Accepted", "Proportionate.", review_line=retired)
            resolution.record_review_round(self.matter.name, "Accepted", "Proportionate.", review_line=live)
        self.assertEqual(self.fresh().reviews[-1].review_line, live)
