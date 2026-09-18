"""Escalation behaviour closed in wave 3.

* Only the resolution threshold the matrix imposed raises a matter on breach. A
  status-driven clock (Time In State) on the same matter breaching used to be
  picked up by ``resolution.sweep_breaches`` too, and raised the severity.
* Breach and material-entity notices are templated events.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now

from consilium.consilium_core import sla
from consilium.consilium_core.setup import notification_templates
from consilium.escalation import resolution
from consilium.escalation.tests.utils import EscalationTestCase, unique


class TestOnlyTheResolutionThresholdRaisesAMatter(EscalationTestCase):
    def setUp(self):
        super().setUp()
        frappe.flags.mute_emails = True
        notification_templates.seed_all()

    def tearDown(self):
        frappe.flags.mute_emails = False
        super().tearDown()

    def _matter_with_threshold(self):
        reference = self.reference_data()
        resolution_sla = self.make_sla_definition(target_hours=100)
        self.make_matrix(
            reference,
            rules=[{"rule_code": "R-BASE", "condition": {}, "resulting_severity": "Low",
                    "sla_definition": resolution_sla.name}],
            routes=[{"rule_code": "R-BASE", "governance_forum": reference["forum"]}],
        )
        matter = self.make_matter(reference, severity="Low", severity_source="Matrix")
        matter.reload()
        self.assertEqual(matter.sla_definition, resolution_sla.name)
        return reference, matter

    def _time_in_state_clock(self, matter):
        definition = frappe.get_doc(
            {
                "doctype": "SLA Definition",
                "sla_code": unique("TIS").upper(),
                "title": "Time in triage",
                "target_doctype": "Escalation Matter",
                "measure": "Time In State",
                "state_field": "status",
                "state_value": matter.status,
                "target_hours": 1,
                "calendar": "24x7",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        clock = sla.start_clock(definition.name, "Escalation Matter", matter.name)
        frappe.db.set_value("SLA Clock", clock.name, "target_on", add_to_date(now(), hours=-2, as_string=True))
        return clock

    def test_a_time_in_state_breach_does_not_raise_the_severity(self):
        reference, matter = self._matter_with_threshold()
        clock = self._time_in_state_clock(matter)

        escalated = resolution.sweep_breaches()
        self.assertNotIn(matter.name, escalated)
        self.assertTrue(frappe.db.get_value("SLA Clock", clock.name, "breached_on"), "the clock did breach")

        matter.reload()
        self.assertEqual(matter.severity, "Low", "severity is not raised by a status clock")
        self.assertFalse(matter.threshold_breached)
        self.assertFalse(matter.breach_count)

        # The breach is still announced — by Core's generic notice, since the
        # escalation module does not handle this clock.
        told = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            pluck="rendered_subject",
        )
        self.assertTrue(told, "the status clock's breach is announced")
        self.assertNotIn(
            f"Escalation {matter.escalation_id or matter.name} has breached its time threshold", told,
            "but not as a resolution breach",
        )

    def test_the_resolution_threshold_still_raises_the_matter(self):
        reference, matter = self._matter_with_threshold()
        frappe.db.set_value(
            "SLA Clock", matter.sla_clock, "target_on", add_to_date(now(), hours=-2, as_string=True)
        )
        self.assertIn(matter.name, resolution.sweep_breaches())
        matter.reload()
        self.assertEqual(matter.breach_count, 1)
        self.assertNotEqual(matter.severity, "Low")

        subjects = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name},
            pluck="rendered_subject",
        )
        self.assertIn(
            f"Escalation {matter.escalation_id or matter.name} has breached its time threshold", subjects
        )
