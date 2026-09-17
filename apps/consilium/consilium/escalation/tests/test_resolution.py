"""Resolution: states, closure, service levels and automatic escalation (E17-S3, E17-S4)."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, now

from consilium.consilium_core import sla
from consilium.escalation import approvals, resolution
from consilium.escalation.tests.utils import EscalationTestCase, make_forum, make_user


class TestStatesAndClosure(EscalationTestCase):
    def test_a_matter_moves_through_its_states(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        self.assertTrue(matter.is_open)
        self.assertTrue(matter.is_editable)

        matter.status = "In Progress"
        matter.save(ignore_permissions=True)
        self.assertTrue(matter.is_open)

        matter.status = "Pending Review"
        matter.save(ignore_permissions=True)
        self.assertTrue(matter.requires_review)
        self.assertTrue(matter.is_open)

    def test_closing_without_a_recorded_outcome_is_refused(self):
        reference = self.reference_data()
        matter = self.make_matter(reference, response_template_completed=1)
        matter.status = "Closed"
        with self.assertRaises(frappe.ValidationError):
            matter.save(ignore_permissions=True)

        matter.reload()
        self.make_closure(matter)
        matter.status = "Closed"
        matter.save(ignore_permissions=True)
        self.assertFalse(matter.is_open)
        self.assertTrue(matter.closed_on)

    def test_closing_without_the_response_template_is_refused(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        self.make_closure(matter)
        matter.reload()
        matter.status = "Closed"
        with self.assertRaises(frappe.ValidationError):
            matter.save(ignore_permissions=True)

    def test_an_externally_tracked_closure_needs_its_external_reference(self):
        reference = self.reference_data()
        matter = self.make_matter(reference, response_template_completed=1)
        self.make_closure(matter, closure_type="Transferred Externally", external_reference=self.a_reference(matter))
        matter.reload()
        matter.status = "Closed — Tracked Externally"
        with self.assertRaises(frappe.ValidationError):
            matter.save(ignore_permissions=True)

        matter.reload()
        matter.status = "Closed — Tracked Externally"
        matter.external_reference = self.a_reference(matter)
        matter.save(ignore_permissions=True)
        self.assertTrue(matter.is_committable)
        self.assertFalse(matter.is_open)

    def test_a_closure_with_an_unmet_required_criterion_is_refused(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        with self.assertRaises(frappe.ValidationError):
            self.make_closure(
                matter,
                criteria_met=[
                    {"criterion": "Root cause understood", "required": 1, "met": 0},
                ],
            )

    def test_a_closure_transferring_tracking_needs_the_external_reference(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        with self.assertRaises(frappe.ValidationError):
            self.make_closure(matter, closure_type="Transferred Externally")

    def test_one_closure_per_matter(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        self.make_closure(matter)
        with self.assertRaises(Exception):
            self.make_closure(matter)

    def a_reference(self, matter) -> str:
        system = frappe.db.get_value("External System", {"system_code": "ESC_TEST"}, "name")
        if not system:
            system = frappe.get_doc(
                {
                    "doctype": "External System",
                    "system_code": "ESC_TEST",
                    "title": "Issue management",
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True).name
        return frappe.get_doc(
            {
                "doctype": "External Reference",
                "subject_doctype": "Escalation Matter",
                "subject_name": matter.name,
                "external_system": system,
                "external_key": frappe.generate_hash(length=8),
            }
        ).insert(ignore_permissions=True).name


class TestRiskAcceptanceApproval(EscalationTestCase):
    def acceptance_values(self, reference, matter, **overrides):
        values = {
            "doctype": "Risk Acceptance",
            "escalation_matter": matter.name,
            "risk_acceptance_name": "Accept until the platform is replaced",
            "start_date": "2026-01-10",
            "end_date": "2026-12-31",
            "accountable_executive": reference["user"],
            "rationale": "Remediation costs more than the exposure for the remaining life of the platform.",
        }
        values.update(overrides)
        return values

    def test_an_acceptance_without_an_approval_cannot_take_effect(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        acceptance = frappe.get_doc(self.acceptance_values(reference, matter)).insert(ignore_permissions=True)
        self.assertFalse(acceptance.is_active, msg="a draft acceptance has no effect")

        acceptance.status = "Approved"
        with self.assertRaises(frappe.ValidationError):
            acceptance.save(ignore_permissions=True)

    def test_an_explicit_approval_lets_it_take_effect(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        approver = make_user("Consilium Administrator")
        acceptance = frappe.get_doc(self.acceptance_values(reference, matter)).insert(ignore_permissions=True)

        approvals.request_approval(acceptance.name, approver)
        acceptance.reload()
        self.assertTrue(acceptance.approval_decision)

        acceptance.status = "Pending Approval"
        acceptance.save(ignore_permissions=True)
        self.assertTrue(acceptance.requires_review)

        approvals.record_approval(acceptance.name, "Approved", acting_user=approver)
        acceptance.reload()
        self.assertEqual(acceptance.approved_by, approver)

        acceptance.status = "Approved"
        acceptance.save(ignore_permissions=True)
        self.assertTrue(acceptance.is_active)
        self.assertTrue(acceptance.is_committable)

    def test_a_rejected_decision_is_not_an_approval(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        approver = make_user("Consilium Administrator")
        acceptance = frappe.get_doc(self.acceptance_values(reference, matter)).insert(ignore_permissions=True)
        approvals.request_approval(acceptance.name, approver)
        approvals.record_approval(acceptance.name, "Rejected", acting_user=approver)

        acceptance.reload()
        self.assertIsNone(acceptance.approved_by)
        acceptance.status = "Approved"
        with self.assertRaises(frappe.ValidationError):
            acceptance.save(ignore_permissions=True)

    def test_a_forum_motion_is_the_other_accepted_evidence(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        acceptance = frappe.get_doc(
            self.acceptance_values(reference, matter, approval_motion=self.a_motion(reference))
        ).insert(ignore_permissions=True)
        acceptance.status = "Approved"
        acceptance.save(ignore_permissions=True)
        self.assertTrue(acceptance.is_active)

    def a_motion(self, reference) -> str:
        """A forum motion belongs to the Governance module; only its key is used here."""
        meta = frappe.get_meta("Forum Motion")
        values = {"doctype": "Forum Motion"}
        for field, value in (
            ("forum", reference["forum"]),
            ("motion_reference", f"MOT-{frappe.generate_hash(length=6)}"),
            ("motion_text", "That the risk be accepted for the stated period."),
            ("decision_date", "2026-01-15"),
            ("voting_mode", "In Meeting"),
            ("proposed_by", reference["user"]),
        ):
            if value is not None and meta.has_field(field):
                values[field] = value
        return frappe.get_doc(values).insert(ignore_permissions=True).name

    def test_the_acceptance_period_is_bounded(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(self.acceptance_values(reference, matter, end_date=None)).insert(
                ignore_permissions=True
            )


class TestServiceLevels(EscalationTestCase):
    def matrix_with_threshold(self, reference, definition, forum=None):
        return self.make_matrix(
            reference,
            rules=[
                {
                    "rule_code": "R-SLA",
                    "condition": {},
                    "resulting_severity": "Medium",
                    "sla_definition": definition.name,
                }
            ],
            routes=[{"rule_code": "R-SLA", "governance_forum": forum or reference["forum"]}],
        )

    def test_a_matter_runs_a_core_clock_against_its_threshold(self):
        reference = self.reference_data()
        definition = self.make_sla_definition(target_hours=4)
        self.matrix_with_threshold(reference, definition)

        matter = self.make_matter(reference, severity_source="Matrix")
        self.assertEqual(matter.sla_definition, definition.name)
        matter.reload()
        self.assertTrue(matter.sla_clock)

        clock = frappe.get_doc("SLA Clock", matter.sla_clock)
        self.assertEqual(clock.subject_doctype, "Escalation Matter")
        self.assertTrue(clock.is_open)

    def test_the_threshold_honours_the_business_calendar(self):
        reference = self.reference_data()
        calendar = self.make_business_calendar()
        definition = self.make_sla_definition(target_hours=4, business_calendar=calendar.name)
        self.matrix_with_threshold(reference, definition)

        matter = self.make_matter(reference, severity_source="Matrix", opened_on="2026-01-02 16:00:00")
        matter.reload()
        clock = frappe.get_doc("SLA Clock", matter.sla_clock)
        # Four working hours from 16:00 on a Friday runs into the next working day.
        self.assertGreater(str(clock.target_on), "2026-01-03")

    def test_closing_a_matter_stops_its_clock(self):
        reference = self.reference_data()
        definition = self.make_sla_definition(target_hours=4)
        self.matrix_with_threshold(reference, definition)
        matter = self.make_matter(reference, severity_source="Matrix", response_template_completed=1)
        self.make_closure(matter)

        matter.reload()
        matter.status = "Closed"
        matter.save(ignore_permissions=True)

        clock = frappe.get_doc("SLA Clock", matter.sla_clock)
        self.assertFalse(clock.is_open)
        self.assertTrue(clock.stopped_on)

    def test_a_breach_raises_the_matter_records_it_and_notifies(self):
        reference = self.reference_data()
        escalation_forum = make_forum()
        definition = self.make_sla_definition(target_hours=1)
        self.make_matrix(
            reference,
            rules=[
                {
                    "rule_code": "R-BASE",
                    "priority": 20,
                    "condition": {},
                    "resulting_severity": "Low",
                    "sla_definition": definition.name,
                },
                {
                    "rule_code": "R-RAISED",
                    "priority": 10,
                    "condition": {"severity": "Medium"},
                    "resulting_severity": "Medium",
                    "sla_definition": definition.name,
                },
            ],
            routes=[
                {"rule_code": "R-BASE", "governance_forum": reference["forum"]},
                {"rule_code": "R-RAISED", "governance_forum": escalation_forum},
            ],
            notifications=[{"rule_code": "R-BASE", "user_group": self.a_user_group(reference["user"])}],
        )

        matter = self.make_matter(reference, severity="Low", severity_source="Matrix")
        matter.reload()
        self.assertEqual(matter.severity, "Low")

        # Wind the clock back so that it is past its target.
        frappe.db.set_value(
            "SLA Clock", matter.sla_clock, "target_on", add_to_date(now(), hours=-2, as_string=True)
        )

        escalated = resolution.sweep_breaches()
        self.assertIn(matter.name, escalated)

        matter.reload()
        self.assertTrue(matter.threshold_breached, msg="the breach is recorded on the matter")
        self.assertEqual(matter.breach_count, 1)
        self.assertTrue(matter.last_breach_on)
        self.assertTrue(matter.auto_escalated)
        self.assertEqual(matter.severity, "Medium", msg="the matter is raised")
        self.assertIn(
            escalation_forum,
            [row.governance_forum for row in matter.governance_forums],
            msg="the raised matter reaches the higher destination",
        )

        dispatched = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            pluck="recipient",
        )
        self.assertIn(reference["user"], dispatched)

    def test_a_breach_is_recorded_once(self):
        reference = self.reference_data()
        definition = self.make_sla_definition(target_hours=1)
        self.make_matrix(
            reference,
            rules=[
                {
                    "rule_code": "R-SLA",
                    "condition": {},
                    "resulting_severity": "Medium",
                    "sla_definition": definition.name,
                }
            ],
            routes=[{"rule_code": "R-SLA", "governance_forum": reference["forum"]}],
        )
        matter = self.make_matter(reference, severity_source="Matrix")
        frappe.db.set_value(
            "SLA Clock", matter.sla_clock, "target_on", add_to_date(now(), hours=-2, as_string=True)
        )
        resolution.sweep_breaches()
        resolution.sweep_breaches()
        matter.reload()
        self.assertEqual(matter.breach_count, 1)

    def a_user_group(self, member: str) -> str:
        return frappe.get_doc(
            {
                "doctype": "User Group",
                "name": frappe.generate_hash(length=8),
                "user_group_members": [{"user": member}],
            }
        ).insert(ignore_permissions=True).name


class TestSecondLineChallenge(EscalationTestCase):
    """E-9: effective challenge is recorded as rounds against the matter."""

    def test_review_rounds_are_recorded_against_the_matter(self):
        reference = self.reference_data()
        reviewer = make_user("Escalation Reviewer")
        second_line = frappe.db.get_value("Line Of Defence", {"line_number": 2}, "name")
        matter = self.make_matter(reference)

        matter.append(
            "reviews",
            {
                "round": 1,
                "reviewer": reviewer,
                "review_line": second_line,
                "received_on": now(),
                "outcome": "Challenged",
                "comments": "The root cause is not evidenced.",
            },
        )
        matter.status = "Under Review"
        matter.save(ignore_permissions=True)

        self.assertTrue(matter.requires_review)
        self.assertEqual(len(matter.reviews), 1)
        self.assertEqual(matter.reviews[0].reviewer, reviewer)

        matter.append(
            "reviews",
            {"round": 2, "reviewer": reviewer, "review_line": second_line, "outcome": "Accepted"},
        )
        matter.status = "In Progress"
        matter.save(ignore_permissions=True)
        self.assertFalse(matter.requires_review)
        self.assertEqual(len(matter.reviews), 2)

    def test_material_entity_impact_notifies(self):
        reference = self.reference_data()
        matter = self.make_matter(reference)
        matter.material_entity_impact = 1
        matter.save(ignore_permissions=True)

        recipients = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            pluck="recipient",
        )
        self.assertIn(reference["user"], recipients)
