"""E14 — horizon scanning as a periodic obligation on the owner."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_months, getdate, nowdate

from consilium.policy import horizon
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_coverage_area,
    make_document,
    make_user,
)

SCAN = "Horizon Scan"


def make_scan(document, **values):
    scan_date = values.get("scan_date", nowdate())
    defaults = {
        "doctype": SCAN,
        "document": document.name,
        "scanned_by": document.document_owner,
        "scan_date": scan_date,
        "period_covered": "2026 H1",
        "summary": "Reviewed the published consultations and the regulator's newsletter.",
        "impact_assessment": "No Change",
        "coverage_areas": [{"coverage_area": make_coverage_area()}],
        "sources": [
            {
                "source_type": "Regulatory Publication",
                "reference": "Consultation 12/26",
                "reviewed_on": scan_date,
            }
        ],
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class TestHorizonScanRecord(PolicyTestCase):
    def test_a_scan_records_date_period_areas_sources_and_impact(self):
        doc = make_document(review_frequency_months=12)
        scan = make_scan(doc)
        scan.reload()
        self.assertEqual(str(scan.scan_date), nowdate())
        self.assertEqual(scan.period_covered, "2026 H1")
        self.assertEqual(len(scan.coverage_areas), 1)
        self.assertEqual(len(scan.sources), 1)
        self.assertEqual(scan.impact_assessment, "No Change")

    def test_a_scan_with_no_sources_is_refused(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            make_scan(doc, sources=[])

    def test_a_scan_with_no_coverage_is_refused(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            make_scan(doc, coverage_areas=[])

    def test_a_source_cannot_be_reviewed_after_the_scan(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            make_scan(
                doc,
                sources=[{"source_type": "Industry Report", "reference": "Later",
                          "reviewed_on": add_days(nowdate(), 5)}],
            )

    def test_a_reviewer_cannot_record_a_scan(self):
        doc = make_document()
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": SCAN,
                    "document": doc.name,
                    "scanned_by": reviewer,
                    "scan_date": nowdate(),
                    "period_covered": "2026",
                    "summary": "x",
                    "impact_assessment": "No Change",
                }
            ).insert()

    def test_findings_can_fan_out_to_several_documents(self):
        doc = make_document()
        other = make_document()
        scan = make_scan(doc)
        finding = frappe.get_doc(
            {
                "doctype": "Horizon Scan Finding",
                "horizon_scan": scan.name,
                "finding_title": "New disclosure expectation",
                "description": "The regulator expects annual disclosure.",
                "assessed_impact": "Medium",
                "action_taken": "Review Triggered",
                "finding_owner": doc.document_owner,
                "impacted_documents": [
                    {"governing_document": doc.name},
                    {"governing_document": other.name},
                ],
            }
        ).insert(ignore_permissions=True)
        finding.reload()
        self.assertEqual(len(finding.impacted_documents), 2)
        self.assertTrue(int(finding.is_open or 0))


class TestScanCadence(PolicyTestCase):
    def test_the_due_date_derives_from_the_review_cadence(self):
        doc = make_document(review_frequency_months=6, effective_on="2026-01-01")
        self.assertEqual(str(horizon.due_on_for(doc)), "2026-07-01")

    def test_the_due_date_moves_forward_after_a_scan(self):
        doc = make_document(review_frequency_months=6, effective_on="2026-01-01")
        make_scan(doc, scan_date="2026-03-01")
        doc.reload()
        self.assertEqual(str(horizon.due_on_for(doc)), "2026-09-01")

    def test_the_scan_stores_the_due_date_it_was_answering(self):
        doc = make_document(review_frequency_months=12, effective_on="2025-01-01")
        scan = make_scan(doc, scan_date="2026-02-01")
        scan.reload()
        self.assertEqual(str(scan.due_on), "2026-01-01")

    def test_a_document_with_no_cadence_falls_back_to_twelve_months(self):
        doc = make_document(effective_on="2026-01-01")
        self.assertEqual(str(horizon.due_on_for(doc)), "2027-01-01")

    def test_an_overdue_document_is_listed_and_its_owner_reminded(self):
        doc = make_document(review_frequency_months=12, effective_on="2020-01-01")
        frappe.db.set_value("Governing Document", doc.name, "is_active", 1)
        overdue = [row["name"] for row in horizon.overdue_documents()]
        self.assertIn(doc.name, overdue)

        dispatched = horizon.remind_due()
        recipients = [
            frappe.db.get_value("Notification Dispatch", name, "recipient") for name in dispatched
        ]
        self.assertIn(doc.document_owner, recipients)

    def test_an_overdue_reminder_escalates_to_the_sponsor(self):
        sponsor = make_user("Policy Owner")
        doc = make_document(
            review_frequency_months=12, effective_on="2020-01-01", document_sponsor=sponsor
        )
        frappe.db.set_value("Governing Document", doc.name, "is_active", 1)
        dispatched = horizon.remind_due()
        recipients = {
            frappe.db.get_value("Notification Dispatch", name, "recipient") for name in dispatched
        }
        self.assertIn(sponsor, recipients)

    def test_a_document_not_in_force_is_not_chased(self):
        doc = make_document(review_frequency_months=12, effective_on="2020-01-01")
        self.assertNotIn(doc.name, [row["name"] for row in horizon.overdue_documents()])

    def test_coverage_reports_the_areas_a_scan_did_not_reach(self):
        area_covered = make_coverage_area()
        area_missed = make_coverage_area()
        doc = make_document()
        make_scan(doc, coverage_areas=[{"coverage_area": area_covered}])
        position = horizon.coverage(doc.name)
        self.assertIn(area_covered, position["areas_covered"])
        self.assertIn(area_missed, position["areas_not_covered"])


class TestScanTriggersReview(PolicyTestCase):
    def test_a_review_triggered_assessment_opens_a_review_cycle(self):
        doc = make_document(review_frequency_months=12)
        scan = make_scan(doc, impact_assessment="Review Triggered")
        scan.reload()
        self.assertTrue(scan.resulting_review_cycle)

        cycle = frappe.get_doc("Document Review Cycle", scan.resulting_review_cycle)
        self.assertEqual(cycle.document, doc.name)
        self.assertEqual(cycle.triggered_by_horizon_scan, scan.name)
        self.assertTrue(int(cycle.is_open or 0))

    def test_an_immediate_update_assessment_also_opens_one(self):
        doc = make_document()
        scan = make_scan(doc, impact_assessment="Immediate Update Required")
        scan.reload()
        self.assertTrue(scan.resulting_review_cycle)

    def test_no_change_opens_nothing(self):
        doc = make_document()
        scan = make_scan(doc, impact_assessment="No Change")
        scan.reload()
        self.assertFalse(scan.resulting_review_cycle)

    def test_the_review_cycle_is_not_duplicated_on_re_save(self):
        doc = make_document()
        scan = make_scan(doc, impact_assessment="Review Triggered")
        scan.reload()
        first = scan.resulting_review_cycle
        scan.summary = "Amended after a second read."
        scan.save(ignore_permissions=True)
        scan.reload()
        self.assertEqual(scan.resulting_review_cycle, first)
        self.assertEqual(
            len(frappe.get_all("Document Review Cycle", filters={"document": doc.name})), 1
        )

    def test_the_cycle_links_back_to_the_scan_that_caused_it(self):
        doc = make_document()
        scan = make_scan(doc, impact_assessment="Review Triggered")
        scan.reload()
        cycles = frappe.get_all(
            "Document Review Cycle",
            filters={"triggered_by_horizon_scan": scan.name},
            pluck="name",
        )
        self.assertEqual(cycles, [scan.resulting_review_cycle])
