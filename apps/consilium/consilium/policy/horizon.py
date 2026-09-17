"""Horizon scanning.

**There is no feed.** A horizon scan is a periodic obligation on the document
owner: a record of what they reviewed, over what period, across which coverage
areas, from which sources, and what they concluded. Everything the requirement
asks for is a human writing down what they read. Nothing here polls anything.

Two derived behaviours make it an obligation rather than a form:

* the **due date** comes from the document's review cadence and the previous
  scan, so an owner cannot quietly stop scanning;
* an impact assessment that triggers a review **creates the downstream review
  cycle and links back to the scan**, so the chain from "I read this" to "and so
  we reviewed the policy" is navigable in both directions.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_months, getdate, nowdate

from consilium.consilium_core import notification
from consilium.policy.applicability import CHANNEL

DOCTYPE = "Governing Document"
SCAN_DOCTYPE = "Horizon Scan"

#: Impact assessments that oblige a review cycle. Assessment outcomes, not
#: workflow states — no record's lifecycle is keyed off them.
TRIGGERS_REVIEW = ("Review Triggered", "Immediate Update Required")

#: How long after the due date an unanswered reminder escalates to the sponsor.
ESCALATE_AFTER_DAYS = 14

DEFAULT_CADENCE_MONTHS = 12


def cadence_months(document) -> int:
    if isinstance(document, str):
        document = frappe.get_doc(DOCTYPE, document)
    return int(document.get("review_frequency_months") or 0) or DEFAULT_CADENCE_MONTHS


def last_scan(document: str) -> dict | None:
    rows = frappe.get_all(
        SCAN_DOCTYPE,
        filters={"document": document, "docstatus": ["<", 2]},
        fields=["name", "scan_date"],
        order_by="scan_date desc, creation desc",
        limit=1,
    )
    return rows[0] if rows else None


def due_on_for(document, *, after=None) -> str:
    """When the next scan falls due: the cadence applied to the last scan.

    With no previous scan the clock starts at the document's effective date, or
    failing that at its creation, because an unscanned document is overdue from
    the moment it exists rather than never due.
    """
    if isinstance(document, str):
        document = frappe.get_doc(DOCTYPE, document)
    months = cadence_months(document)
    anchor = after
    if not anchor:
        previous = last_scan(document.name)
        anchor = previous["scan_date"] if previous else (
            document.get("effective_on") or getdate(document.creation)
        )
    return add_months(getdate(anchor), months)


def overdue_documents(as_of=None) -> list[dict]:
    """Documents in force whose next scan is already due."""
    as_of = getdate(as_of or nowdate())
    out = []
    for row in frappe.get_all(
        DOCTYPE,
        filters={"is_active": 1, "docstatus": ["<", 2]},
        fields=["name", "document_name", "document_owner", "document_sponsor",
                "review_frequency_months", "effective_on", "creation"],
    ):
        document = frappe.get_doc(DOCTYPE, row["name"])
        due = getdate(due_on_for(document))
        if due <= as_of:
            out.append({**row, "due_on": str(due), "days_overdue": (as_of - due).days})
    return out


def remind_due(as_of=None) -> list[str]:
    """Remind owners that a scan is due, escalating to the sponsor when it is late.

    Scheduled work. Each reminder is a Core dispatch, so "was the owner told"
    has an answer that outlives the mail queue.
    """
    dispatched = []
    for entry in overdue_documents(as_of):
        recipients = [entry["document_owner"]]
        escalated = entry["days_overdue"] >= ESCALATE_AFTER_DAYS
        if escalated and entry.get("document_sponsor"):
            recipients.append(entry["document_sponsor"])
        subject = _("Horizon scan due for {0}").format(entry["document_name"])
        body = _(
            "A horizon scan for {0} ({1}) fell due on {2}, {3} day(s) ago. "
            "Record what you reviewed, the period covered, the sources and your impact assessment."
        ).format(entry["document_name"], entry["name"], entry["due_on"], entry["days_overdue"])
        if escalated:
            body += _(" This reminder has been escalated to the document sponsor.")
        dispatched.extend(
            notification.notify_many(
                CHANNEL,
                sorted(set(r for r in recipients if r)),
                subject=subject,
                body=body,
                subject_doctype=DOCTYPE,
                subject_name=entry["name"],
            )
        )
    return dispatched


def open_review_cycle(scan) -> str | None:
    """Create the review a scan triggered, and link it back to the scan (E14-S3)."""
    if isinstance(scan, str):
        scan = frappe.get_doc(SCAN_DOCTYPE, scan)
    if scan.resulting_review_cycle:
        return scan.resulting_review_cycle
    if scan.impact_assessment not in TRIGGERS_REVIEW:
        return None

    document = frappe.get_doc(DOCTYPE, scan.document)
    cycle = frappe.get_doc(
        {
            "doctype": "Document Review Cycle",
            "document": scan.document,
            "cycle_year": str(getdate(scan.scan_date).year),
            "scheduled_start": scan.scan_date,
            "due_on": add_months(getdate(scan.scan_date), 3),
            "reviewer": document.document_owner,
            "cycle_status": "Planned",
            "triggered_by_horizon_scan": scan.name,
            "outcome_notes": _("Opened by horizon scan {0}: {1}").format(scan.name, scan.summary or ""),
        }
    ).insert(ignore_permissions=True)

    frappe.db.set_value(SCAN_DOCTYPE, scan.name, "resulting_review_cycle", cycle.name)
    return cycle.name


@frappe.whitelist()
def coverage(document: str) -> dict:
    """The scanning position of one document: last scan, next due, and gaps."""
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    doc = frappe.get_doc(DOCTYPE, document)
    previous = last_scan(document)
    covered = set()
    if previous:
        covered = set(
            frappe.get_all(
                "Horizon Scan Coverage",
                filters={"parent": previous["name"], "parenttype": SCAN_DOCTYPE},
                pluck="coverage_area",
            )
        )
    expected = set(
        frappe.get_all("Horizon Scanning Coverage Area", filters={"is_active": 1}, pluck="name")
    )
    return {
        "document": document,
        "cadence_months": cadence_months(doc),
        "last_scan": previous["name"] if previous else None,
        "last_scan_date": previous["scan_date"] if previous else None,
        "due_on": str(due_on_for(doc)),
        "areas_covered": sorted(covered),
        "areas_not_covered": sorted(expected - covered),
    }
