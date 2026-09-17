"""Analysis: volumes, durations, destinations and outcomes (E17-S5)."""

from __future__ import annotations

import csv
import io

import frappe

from consilium.escalation import analysis, sensitivity
from consilium.escalation.tests.utils import (
    EscalationTestCase,
    as_user,
    escalation_permission_hooks,
    make_user,
)


class TestAnalysis(EscalationTestCase):
    def closed_matter(self, reference, **overrides):
        matter = self.make_matter(reference, response_template_completed=1, **overrides)
        self.make_closure(matter)
        matter.reload()
        matter.status = "Closed"
        matter.save(ignore_permissions=True)
        return matter

    def test_volumes_by_period_type_and_severity(self):
        reference = self.reference_data()
        self.make_matter(reference, opened_on="2026-01-10 09:00:00", severity="High")
        self.make_matter(reference, opened_on="2026-01-20 09:00:00", severity="High")
        self.make_matter(reference, opened_on="2026-02-03 09:00:00", severity="Low")

        rows = analysis.volumes({"escalation_type": reference["escalation_type"]})
        by_key = {(row["period"], row["severity"]): row["raised"] for row in rows}
        self.assertEqual(by_key[("2026-01", "High")], 2)
        self.assertEqual(by_key[("2026-02", "Low")], 1)

        quarterly = analysis.volumes({"escalation_type": reference["escalation_type"]}, period="Quarter")
        self.assertEqual({row["period"] for row in quarterly}, {"2026-Q1"})

    def test_durations_over_closed_matters(self):
        reference = self.reference_data()
        matter = self.closed_matter(reference, opened_on="2026-01-10 09:00:00")
        frappe.db.set_value("Escalation Matter", matter.name, "closed_on", "2026-01-12 09:00:00")

        rows = analysis.durations({"escalation_type": reference["escalation_type"]})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["closed"], 1)
        self.assertEqual(rows[0]["mean_hours_open"], 48.0)

    def test_destinations_and_outcomes(self):
        reference = self.reference_data()
        matter = self.closed_matter(
            reference,
            governance_forums=[{"governance_forum": reference["forum"], "role_in_escalation": "Decision"}],
        )

        destinations = analysis.destinations({"escalation_type": reference["escalation_type"]})
        self.assertEqual(destinations[0]["governance_forum"], reference["forum"])
        self.assertEqual(destinations[0]["matters"], 1)

        outcomes = analysis.outcomes({"escalation_type": reference["escalation_type"]})
        self.assertEqual(outcomes[0]["closure_type"], "Resolved")
        self.assertEqual(outcomes[0]["matters"], 1)
        self.assertTrue(matter.name)

    def test_the_summary_is_exportable_as_csv(self):
        reference = self.reference_data()
        self.make_matter(reference, opened_on="2026-01-10 09:00:00", severity="High")

        exported = analysis.export("volumes", {"escalation_type": reference["escalation_type"]})
        rows = list(csv.DictReader(io.StringIO(exported)))
        self.assertEqual(rows[0]["severity"], "High")
        self.assertEqual(rows[0]["raised"], "1")

        with self.assertRaises(frappe.ValidationError):
            analysis.export("nonsense")

    def test_the_analysis_shows_only_what_the_viewer_may_see(self):
        reference = self.reference_data()
        self.make_matter(reference, opened_on="2026-01-10 09:00:00", severity="High")
        self.make_matter(reference, opened_on="2026-01-11 09:00:00", severity="High", sensitive=1)

        cleared = make_user("Escalation Owner", sensitivity.SENSITIVE_ROLE)
        uncleared = make_user("Escalation Owner")
        filters = {"escalation_type": reference["escalation_type"]}

        with escalation_permission_hooks():
            with as_user(uncleared):
                restricted_total = sum(row["raised"] for row in analysis.volumes(filters))
            with as_user(cleared):
                full_total = sum(row["raised"] for row in analysis.volumes(filters))

        self.assertEqual(restricted_total, 1)
        self.assertEqual(full_total, 2)
