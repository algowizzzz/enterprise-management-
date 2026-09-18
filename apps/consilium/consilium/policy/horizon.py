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

from consilium.consilium_core import reminders

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

    Scheduled work, sent through Core's reminder layer: each reminder is logged
    in ``Reminder Log`` against the scan's due date and the recipient, so an
    overdue scan is chased at most once every ``REPEAT_OVERDUE_DAYS`` rather than
    every day it stays overdue, and a second run on the same day sends nothing.
    The sponsor, once the reminder escalates, is a new recipient and is told at
    once. Each reminder is still a Core dispatch, so "was the owner told" has an
    answer that outlives the mail queue.
    """
    as_of = getdate(as_of or nowdate())
    dispatched = []
    for entry in overdue_documents(as_of):
        recipients = [entry["document_owner"]]
        escalated = entry["days_overdue"] >= ESCALATE_AFTER_DAYS
        if escalated and entry.get("document_sponsor"):
            recipients.append(entry["document_sponsor"])
        dispatched.extend(
            reminders.remind(
                "policy.horizon_scan.due",
                sorted(set(r for r in recipients if r)),
                subject_doctype=DOCTYPE,
                subject_name=entry["name"],
                due_on=entry["due_on"],
                as_of=as_of,
                context={"due_on": entry["due_on"], "days_overdue": entry["days_overdue"],
                         "escalated": escalated},
                repeat_days=reminders.REPEAT_OVERDUE_DAYS,
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


# --------------------------------------------------------------------------
# Portal entry points: review cycles (P-10) and horizon scans (P-5, E14)
#
# Both were desk-only. A scan recorded here goes through the same controller as
# one made on the desk, so an impact assessment that triggers a review still
# opens the review cycle and links it back (``open_review_cycle``).
# --------------------------------------------------------------------------

CYCLE_DOCTYPE = "Document Review Cycle"

#: The status a cycle opened by hand starts in, and the one concluding writes.
#: Values handed to the record; the flags they map to are what anything reads.
CYCLE_OPENED = "Planned"
CYCLE_CONCLUDED = "Concluded"


def _options(doctype: str, fieldname: str) -> list[str]:
    field = frappe.get_meta(doctype).get_field(fieldname)
    return [option for option in (field.options or "").split("\n") if option] if field else []


def _position(doc) -> dict:
    """``coverage`` without its permission check, for a caller that has made its own."""
    previous = last_scan(doc.name)
    covered = set()
    if previous:
        covered = set(
            frappe.get_all(
                "Horizon Scan Coverage",
                filters={"parent": previous["name"], "parenttype": SCAN_DOCTYPE},
                pluck="coverage_area",
            )
        )
    expected = set(frappe.get_all("Horizon Scanning Coverage Area", filters={"is_active": 1}, pluck="name"))
    return {
        "cadence_months": cadence_months(doc),
        "last_scan": previous["name"] if previous else None,
        "last_scan_date": previous["scan_date"] if previous else None,
        "due_on": str(due_on_for(doc)),
        "areas_covered": sorted(covered),
        "areas_not_covered": sorted(expected - covered),
    }


def review_context(doc) -> dict:
    """The review and horizon panels of the document page, and what may be done there."""
    from consilium.policy import lifecycle

    stage = lifecycle.stage_actions(doc)
    cycles = frappe.get_all(
        CYCLE_DOCTYPE,
        filters={"document": doc.name, "docstatus": ["<", 2]},
        fields=["name", "cycle_year", "cycle_status", "reviewer", "scheduled_start", "due_on", "outcome",
                "outcome_notes", "is_open", "triggered_by_horizon_scan", "resulting_intake_request"],
        order_by="creation desc",
    )
    scans = frappe.get_all(
        SCAN_DOCTYPE,
        filters={"document": doc.name, "docstatus": ["<", 2]},
        fields=["name", "scan_date", "scanned_by", "period_covered", "impact_assessment", "summary",
                "resulting_review_cycle", "due_on"],
        order_by="scan_date desc, creation desc",
        limit=20,
    )
    open_cycles = [row["name"] for row in cycles if int(row["is_open"] or 0)]

    def allowed(action: str) -> bool:
        return action in stage and lifecycle.may_take(doc, action)

    return {
        "document": doc.name,
        "cycles": cycles,
        "open_cycles": open_cycles,
        "scans": scans,
        "position": _position(doc),
        "coverage_areas": frappe.get_all(
            "Horizon Scanning Coverage Area", filters={"is_active": 1},
            fields=["name", "coverage_area_name"], order_by="coverage_area_name asc",
        ),
        "source_types": _options("Horizon Scan Source", "source_type"),
        "impact_assessments": _options(SCAN_DOCTYPE, "impact_assessment"),
        "triggers_review": list(TRIGGERS_REVIEW),
        "review_outcomes": _options(CYCLE_DOCTYPE, "outcome"),
        "actions": {
            # One open cycle at a time: two concurrent reviews of one document
            # would conclude with two different outcomes and no way to say which stands.
            "open_review_cycle": allowed("open_review_cycle") and not open_cycles,
            "conclude_review_cycle": allowed("conclude_review_cycle") and bool(open_cycles),
            "record_horizon_scan": allowed("record_horizon_scan"),
        },
    }


def _load(document: str):
    doc = frappe.get_doc(DOCTYPE, document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    return doc


@frappe.whitelist(methods=["GET"])
def document_reviews(document: str) -> dict:
    return review_context(_load(document))


@frappe.whitelist(methods=["POST"])
def open_review(document: str, due_on: str, reviewer: str | None = None, scheduled_start: str | None = None) -> dict:
    """Open the periodic review of a document in force (P-10)."""
    from consilium.policy import lifecycle

    doc = _load(document)
    lifecycle.authorise(doc, "open_review_cycle")
    if frappe.db.exists(CYCLE_DOCTYPE, {"document": doc.name, "is_open": 1, "docstatus": ["<", 2]}):
        frappe.throw(_("{0} already has a review cycle open. Conclude it before opening another.").format(doc.name),
                     title=_("Review Already Open"))
    if not due_on:
        frappe.throw(_("A review cycle needs the date it is due."), title=_("Due Date Required"))
    start = scheduled_start or nowdate()
    if getdate(due_on) < getdate(start):
        frappe.throw(_("A review cannot fall due before it starts."), title=_("Dates Out Of Order"))
    frappe.get_doc(
        {
            "doctype": CYCLE_DOCTYPE,
            "document": doc.name,
            "cycle_year": str(getdate(start).year),
            "scheduled_start": start,
            "due_on": due_on,
            "reviewer": reviewer or doc.document_owner,
            "cycle_status": CYCLE_OPENED,
        }
    ).insert(ignore_permissions=True)
    return review_context(doc)


@frappe.whitelist(methods=["POST"])
def conclude_review(cycle: str, outcome: str, outcome_notes: str) -> dict:
    """Conclude an open review with its outcome, and roll the next review date on.

    The document's next review date is derived only when it is empty, so a
    concluded review would otherwise leave the document showing as overdue for
    the review just finished. It is written directly: the document is in force
    and not editable, and a review date is scheduling, not content.
    """
    from consilium.policy import lifecycle

    row = frappe.db.get_value(CYCLE_DOCTYPE, cycle, ["document", "is_open"], as_dict=True)
    if not row:
        frappe.throw(_("Review cycle {0} does not exist.").format(cycle))
    doc = _load(row.document)
    lifecycle.authorise(doc, "conclude_review_cycle")
    if not int(row.is_open or 0):
        frappe.throw(_("Review cycle {0} is already closed.").format(cycle), title=_("Already Concluded"))
    if outcome not in _options(CYCLE_DOCTYPE, "outcome"):
        frappe.throw(_("{0} is not a review outcome.").format(outcome), title=_("Unknown Outcome"))
    if not (outcome_notes or "").strip():
        frappe.throw(_("A concluded review records what was found."), title=_("Notes Required"))
    record = frappe.get_doc(CYCLE_DOCTYPE, cycle)
    record.cycle_status = CYCLE_CONCLUDED
    record.outcome = outcome
    record.outcome_notes = outcome_notes.strip()
    record.save(ignore_permissions=True)
    months = int(doc.review_frequency_months or 0)
    if months:
        frappe.db.set_value(DOCTYPE, doc.name, "next_review_on", add_months(getdate(nowdate()), months))
    return review_context(frappe.get_doc(DOCTYPE, doc.name))


@frappe.whitelist(methods=["POST"])
def record_scan(
    document: str,
    period_covered: str,
    summary: str,
    impact_assessment: str,
    coverage_areas=None,
    sources=None,
    scan_date: str | None = None,
) -> dict:
    """Record what the owner read, and what they concluded (E14-S1..S3).

    The controller insists on at least one source and one coverage area and
    derives the due date; an impact that triggers review opens the cycle.
    """
    from consilium.policy import lifecycle

    doc = _load(document)
    lifecycle.authorise(doc, "record_horizon_scan")
    if impact_assessment not in _options(SCAN_DOCTYPE, "impact_assessment"):
        frappe.throw(_("{0} is not an impact assessment.").format(impact_assessment), title=_("Unknown Impact"))
    areas = frappe.parse_json(coverage_areas) if isinstance(coverage_areas, str) else (coverage_areas or [])
    rows = frappe.parse_json(sources) if isinstance(sources, str) else (sources or [])
    frappe.get_doc(
        {
            "doctype": SCAN_DOCTYPE,
            "document": doc.name,
            "scanned_by": frappe.session.user,
            "scan_date": scan_date or nowdate(),
            "period_covered": period_covered,
            "summary": summary,
            "impact_assessment": impact_assessment,
            "coverage_areas": [{"coverage_area": area} for area in areas if area],
            "sources": [
                {
                    "source_type": row.get("source_type"),
                    "reference": row.get("reference"),
                    "reviewed_on": row.get("reviewed_on") or None,
                    "notes": row.get("notes"),
                }
                for row in rows
                if row.get("reference")
            ],
        }
    ).insert(ignore_permissions=True)
    return review_context(doc)
