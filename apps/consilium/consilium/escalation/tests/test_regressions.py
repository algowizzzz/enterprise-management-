"""Regressions found while loading a realistic demonstration organisation.

Each test here failed before its fix; the docstring names the bug.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now

from consilium.escalation import resolution
from consilium.escalation.tests.utils import EscalationTestCase


class TestBreachIsNotRepeated(EscalationTestCase):
    def test_saving_a_breached_matter_does_not_start_a_second_overdue_clock(self):
        """After a breach the clock is no longer open, so the next save started a
        fresh clock from the original open date — already overdue — and the daily
        sweep breached the matter again, every day."""
        reference = self.reference_data()
        definition = self.make_sla_definition(target_hours=1)
        self.make_matrix(
            reference,
            rules=[{"rule_code": "R-SLA", "condition": {}, "resulting_severity": "Medium",
                    "sla_definition": definition.name}],
            routes=[{"rule_code": "R-SLA", "governance_forum": reference["forum"]}],
        )
        opened = add_to_date(now(), days=-3, as_string=True)
        matter = self.make_matter(reference, severity_source="Matrix", opened_on=opened)
        first_clock = matter.sla_clock
        frappe.db.set_value("SLA Clock", first_clock, "target_on", add_to_date(now(), hours=-2, as_string=True))

        resolution.sweep_breaches()
        matter.reload()
        self.assertEqual(matter.breach_count, 1)

        matter.description = "An update from the owner."
        matter.save(ignore_permissions=True)
        resolution.sweep_breaches()
        resolution.sweep_breaches()

        matter.reload()
        self.assertEqual(matter.breach_count, 1, msg="one breach, however often the matter is saved")
        self.assertEqual(matter.sla_clock, first_clock)
        # Only the threshold's own clocks: a site may also time the matter's
        # statuses (Time In State definitions), and those clocks rightly run.
        running = frappe.get_all(
            "SLA Clock",
            filters={"subject_doctype": "Escalation Matter", "subject_name": matter.name, "is_open": 1,
                     "sla_definition": definition.name},
            pluck="name",
        )
        self.assertEqual(running, [], msg="no second clock is started from the old open date")

    def test_a_new_matter_on_the_same_threshold_still_gets_its_own_clock(self):
        reference = self.reference_data()
        definition = self.make_sla_definition(target_hours=4)
        self.make_matrix(
            reference,
            rules=[{"rule_code": "R-SLA", "condition": {}, "resulting_severity": "Medium",
                    "sla_definition": definition.name}],
            routes=[{"rule_code": "R-SLA", "governance_forum": reference["forum"]}],
        )
        matter = self.make_matter(reference, severity_source="Matrix")
        matter.reload()
        self.assertTrue(matter.sla_clock)
        self.assertTrue(frappe.db.get_value("SLA Clock", matter.sla_clock, "is_open"))


class TestOpenedOnDefault(EscalationTestCase):
    def test_opened_on_is_stamped_by_the_server_when_not_given(self):
        """Required but with no default, so it took the client's clock — hours out
        for a user in another zone, and once later than the matter's closing."""
        reference = self.reference_data()
        values = self.matter_values(reference)
        values.pop("opened_on", None)
        matter = frappe.get_doc(values).insert(ignore_permissions=True)
        self.assertTrue(matter.opened_on)
