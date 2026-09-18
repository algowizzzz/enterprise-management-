"""Policy reporting: families, monitoring, exceptions, violations and dispositions.

P-4 asks for a family view of documents, P-12 for reporting on "document
families, parent-child relationships, upcoming and overdue reviews, monitoring
outcomes, exceptions and violations, with export", and P-22 for violations to be
"reportable for compliance monitoring and governance". The reports page already
counts the inventory by type, phase, group and handling in the browser; these
are the sections it could not count that way, because each needs a join the
REST list cannot express (a family is a walk of the lineage graph; an exception
is a Core record about a document).

**Every figure is over what the viewer may read.** The set of documents is
taken once, through ``frappe.get_list`` — the Governing Document permission
hooks, and so the confidential and restricted handling rules, included — and
every section is restricted to it. Monitoring results and violations are then
read through ``get_list`` as well, so their own DocType permissions apply on
top. Two people with different standing see different totals, and each total
is exactly what the records behind it would show them.

**Export is the same rows.** ``export`` writes the rows a section shows through
a CSV writer on the server, so a downloaded file never holds anything the
screen would not.

Nothing here compares a state name. "Open" is ``is_open``; "in force" is
``is_active``; a review that is due is a date. Outcome and status labels are
counted for display only.
"""

from __future__ import annotations

import csv
import io
import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

DOCTYPE = "Governing Document"
SECTIONS = ("families", "monitoring", "exceptions", "violations", "dispositions")

#: How far back the outcome and disposition counts look.
LOOKBACK_DAYS = 365


def _readable_documents() -> dict[str, dict]:
    rows = frappe.get_list(
        DOCTYPE,
        filters={"docstatus": ["<", 2]},
        fields=["name", "document_name", "document_owner", "lifecycle_phase", "is_active", "next_review_on",
                "parent_document"],
        limit_page_length=0,
    )
    return {row["name"]: row for row in rows}


def _may_list(doctype: str) -> bool:
    return bool(frappe.has_permission(doctype, "read"))


# ------------------------------------------------------------------ families


def families(docs: dict[str, dict]) -> list[dict]:
    """Each readable document heading a family, with the size and state of the family.

    The graph is walked with ``lineage.descendants`` (both directions of the
    lineage, cycles tolerated), and every member counted is one the viewer may
    read — a restricted child is neither counted nor named.
    """
    from consilium.policy import lineage

    today = getdate(nowdate())
    heads = set()
    for row in frappe.get_all(
        "Document Relationship",
        filters={"parenttype": DOCTYPE, "relationship_type": ["in", list(lineage.DESCENDANT_TYPES)]},
        pluck="parent",
    ):
        heads.add(row)
    heads |= {row["parent_document"] for row in docs.values() if row.get("parent_document")}
    out = []
    for head in sorted(heads):
        if head not in docs:
            continue
        members = [name for name in lineage.descendants(head) if name in docs and name != head]
        if not members:
            continue
        children = [row["document"] for row in lineage.children(head) if row["document"] in docs]
        overdue = [
            name for name in members
            if docs[name]["is_active"] and docs[name].get("next_review_on")
            and getdate(docs[name]["next_review_on"]) < today
        ]
        out.append({
            "document": head,
            "document_name": docs[head]["document_name"],
            "lifecycle_phase": docs[head]["lifecycle_phase"],
            "is_active": int(docs[head]["is_active"] or 0),
            "children": len(children),
            "members": len(members),
            "in_force": sum(1 for name in members if docs[name]["is_active"]),
            "not_in_force": sum(1 for name in members if not docs[name]["is_active"]),
            "review_overdue": len(overdue),
            # A child still in force under a head that is not is P-23's
            # remediation case: its parent link no longer points at a live parent.
            "orphaned_in_force": sum(
                1 for name in children if docs[name]["is_active"] and not docs[head]["is_active"]
            ),
        })
    out.sort(key=lambda row: (-row["members"], row["document_name"] or ""))
    return out


# ---------------------------------------------------------------- monitoring


def monitoring(docs: dict[str, dict]) -> dict:
    if not (_may_list("Monitoring Result") and _may_list("Monitoring Activity")):
        return {"available": False}
    names = list(docs) or [""]
    since = add_days(nowdate(), -LOOKBACK_DAYS)
    results = frappe.get_list(
        "Monitoring Result",
        filters={"document": ["in", names], "performed_on": [">=", since]},
        fields=["name", "document", "monitoring_activity", "period_label", "performed_on", "outcome",
                "resulting_violation"],
        order_by="performed_on desc",
        limit_page_length=0,
    )
    by_outcome: dict[str, int] = {}
    for row in results:
        by_outcome[row["outcome"] or ""] = by_outcome.get(row["outcome"] or "", 0) + 1
    activities = frappe.get_list(
        "Monitoring Activity",
        filters={"document": ["in", names], "is_active": 1},
        fields=["name", "document", "activity_title", "responsible", "next_due_on"],
        limit_page_length=0,
    )
    today = getdate(nowdate())
    overdue = [
        {**row, "document_name": docs[row["document"]]["document_name"]}
        for row in activities
        if row.get("next_due_on") and getdate(row["next_due_on"]) < today
    ]
    raising = [
        {**row, "document_name": docs[row["document"]]["document_name"]}
        for row in results if row.get("resulting_violation")
    ]
    return {
        "available": True,
        "since": str(since),
        "results": len(results),
        "by_outcome": [{"outcome": key, "count": value} for key, value in sorted(by_outcome.items())],
        "active_activities": len(activities),
        "overdue_activities": sorted(overdue, key=lambda row: str(row["next_due_on"])),
        "results_raising_violations": raising,
    }


# ---------------------------------------------------------------- exceptions


def exceptions(docs: dict[str, dict]) -> dict:
    """Formal applicability exemptions in force, and exception authorisations.

    Exception Authorisations are Core records readable only by oversight; what
    is shown here is limited to the documents the viewer may read, which is
    what the document page already shows them.
    """
    from consilium.policy import lifecycle

    names = list(docs) or [""]
    today = getdate(nowdate())
    soon = add_days(nowdate(), 30)
    exemptions = frappe.get_all(
        "Applicability Exemption",
        filters={"document": ["in", names], "is_active": 1, "docstatus": ["<", 2]},
        fields=["name", "document", "exemption_type", "scope_type", "scope_value", "scope_label", "valid_to",
                "approved_by"],
        order_by="valid_to asc",
    )
    for row in exemptions:
        row["document_name"] = docs[row["document"]]["document_name"]
        row["expiring"] = bool(row.get("valid_to") and getdate(row["valid_to"]) <= getdate(soon))
    authorisations = frappe.get_all(
        "Exception Authorisation",
        filters={"subject_doctype": DOCTYPE, "subject_name": ["in", names]},
        fields=["name", "subject_name", "exception_type", "requested_by", "approved_by", "approved_on",
                "valid_to", "creation"],
        order_by="creation desc",
    )
    rows = []
    for row in authorisations:
        expired = bool(row.get("valid_to") and getdate(row["valid_to"]) < today)
        standing = (
            _("Awaiting approval") if not row.get("approved_by")
            else _("Expired") if expired
            else _("Approved") if not lifecycle.approval_unfit(row)
            else _("Approved, but cannot excuse a gate")
        )
        rows.append({**row, "document": row["subject_name"],
                     "document_name": docs[row["subject_name"]]["document_name"], "standing": standing})
    return {
        "exemptions_in_force": exemptions,
        "exemptions_expiring": sum(1 for row in exemptions if row["expiring"]),
        "authorisations": rows,
        "authorisations_pending": sum(1 for row in authorisations if not row.get("approved_by")),
    }


# ---------------------------------------------------------------- violations


def violations(docs: dict[str, dict]) -> dict:
    if not _may_list("Policy Violation"):
        return {"available": False}
    names = list(docs) or [""]
    rows = frappe.get_list(
        "Policy Violation",
        filters={"document": ["in", names], "docstatus": ["<", 2]},
        fields=["name", "document", "violation_type", "severity", "violation_status", "is_open", "identified_on",
                "responsible_party", "resolved_on", "resulting_escalation", "external_reference"],
        order_by="identified_on asc",
        limit_page_length=0,
    )
    since = getdate(add_days(nowdate(), -90))
    open_rows = [row for row in rows if int(row["is_open"] or 0)]

    def tally(items, field):
        counts: dict[str, int] = {}
        for row in items:
            counts[row[field] or ""] = counts.get(row[field] or "", 0) + 1
        return [{"value": key, "count": value} for key, value in sorted(counts.items())]

    for row in rows:
        row["document_name"] = docs[row["document"]]["document_name"]
    return {
        "available": True,
        "total": len(rows),
        "open": len(open_rows),
        "escalated": sum(1 for row in rows if row.get("resulting_escalation")),
        "closed_last_90_days": sum(
            1 for row in rows if not int(row["is_open"] or 0) and row.get("resolved_on")
            and getdate(row["resolved_on"]) >= since
        ),
        "open_by_severity": tally(open_rows, "severity"),
        "by_status": tally(rows, "violation_status"),
        "open_violations": open_rows,
    }


# -------------------------------------------------------------- dispositions


def dispositions(docs: dict[str, dict]) -> dict:
    names = list(docs) or [""]
    since = add_days(nowdate(), -LOOKBACK_DAYS)
    rows = frappe.get_all(
        "Document Disposition",
        filters={"document": ["in", names], "decided_on": [">=", since]},
        fields=["name", "document", "disposition_kind", "version_label", "decided_by", "decided_on", "reason",
                "retention_class", "disposition_due_on", "legal_hold"],
        order_by="decided_on desc",
    )
    by_kind: dict[str, int] = {}
    for row in rows:
        row["document_name"] = docs[row["document"]]["document_name"]
        by_kind[row["disposition_kind"]] = by_kind.get(row["disposition_kind"], 0) + 1
    return {"since": str(since), "rows": rows,
            "by_kind": [{"value": key, "count": value} for key, value in sorted(by_kind.items())]}


# ----------------------------------------------------------------- endpoints


def _require_reader() -> None:
    if not frappe.has_permission(DOCTYPE, "read"):
        frappe.throw(_("Policy reporting is not open to you."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def policy_sections() -> dict:
    """Every section of the reports page's policy block, counted for this viewer."""
    _require_reader()
    docs = _readable_documents()
    return {
        "documents": len(docs),
        "families": families(docs),
        "monitoring": monitoring(docs),
        "exceptions": exceptions(docs),
        "violations": violations(docs),
        "dispositions": dispositions(docs),
    }


_EXPORT_COLUMNS = {
    "families": ["document", "document_name", "lifecycle_phase", "is_active", "children", "members", "in_force",
                 "not_in_force", "review_overdue", "orphaned_in_force"],
    "monitoring": ["document", "document_name", "activity_title", "responsible", "next_due_on"],
    "exceptions": ["kind", "name", "document", "document_name", "type", "scope", "standing", "approved_by",
                   "valid_to"],
    "violations": ["name", "document", "document_name", "violation_type", "severity", "violation_status",
                   "identified_on", "responsible_party", "resulting_escalation"],
    "dispositions": ["name", "document", "document_name", "disposition_kind", "version_label", "decided_by",
                     "decided_on", "reason", "retention_class", "disposition_due_on", "legal_hold"],
}


def section_rows(section: str, docs: dict[str, dict] | None = None) -> list[dict]:
    """The rows a section shows, flattened for a file."""
    if section not in SECTIONS:
        frappe.throw(_("Unknown section {0}. Known sections: {1}.").format(section, ", ".join(SECTIONS)))
    docs = _readable_documents() if docs is None else docs
    if section == "families":
        return families(docs)
    if section == "monitoring":
        data = monitoring(docs)
        return data.get("overdue_activities", []) if data.get("available") else []
    if section == "violations":
        data = violations(docs)
        return data.get("open_violations", []) if data.get("available") else []
    if section == "dispositions":
        return dispositions(docs)["rows"]
    data = exceptions(docs)
    rows = [
        {"kind": _("Exemption"), "name": row["name"], "document": row["document"],
         "document_name": row["document_name"], "type": row["exemption_type"],
         "scope": row.get("scope_label") or row.get("scope_value"), "standing": _("In force"),
         "approved_by": row.get("approved_by"), "valid_to": row.get("valid_to")}
        for row in data["exemptions_in_force"]
    ]
    rows += [
        {"kind": _("Exception authorisation"), "name": row["name"], "document": row["document"],
         "document_name": row["document_name"], "type": row["exception_type"], "scope": "",
         "standing": row["standing"], "approved_by": row.get("approved_by"), "valid_to": row.get("valid_to")}
        for row in data["authorisations"]
    ]
    return rows


def to_csv(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: _cell(row.get(column)) for column in columns})
    return buffer.getvalue()


def _cell(value) -> str:
    """A cell a spreadsheet will not execute: a leading = + - @ is quoted as text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


#: The system a file downloaded from the reporting page is recorded against:
#: it goes to the person who asked, not to another system (P-20).
DOWNLOAD_SYSTEM = "PORTAL_DOWNLOAD"


def _download_system() -> str:
    if not frappe.db.exists("External System", DOWNLOAD_SYSTEM):
        frappe.get_doc({"doctype": "External System", "system_code": DOWNLOAD_SYSTEM,
                        "title": "Downloaded from the portal",
                        "description": "A file a person downloaded from a reporting page for their own use.",
                        "is_active": 1}).insert(ignore_permissions=True)
    return DOWNLOAD_SYSTEM


def _log_export(section: str, rows: list[dict], columns: list[str], content: str) -> str:
    """Record the download as an Export Batch: who, when, which section, which records, the hash."""
    from consilium.consilium_core import importing

    batch, _content = importing.export_records(
        export_profile=f"Management reporting: {section}",
        target_system=_download_system(),
        source_doctype=DOCTYPE,
        fields=columns,
        filters={"section": section},
        rows=rows,
        content=content,
        extra={
            "file_format": "CSV",
            "record_names": json.dumps([row.get("name") or row.get("document") for row in rows]),
            "delivered_to": _("Downloaded by {0}").format(frappe.session.user),
        },
    )
    return batch.name


@frappe.whitelist(methods=["GET", "POST"])
def export(section: str) -> str:
    """A CSV of one section, over the records the caller may read.

    Each download is logged as an Export Batch (P-20). The reporting page asks
    with POST, so the log is committed; a GET still answers, but a GET does not
    commit, so it leaves no log — which is why the page does not use one.
    """
    _require_reader()
    rows = section_rows(section)
    columns = _EXPORT_COLUMNS.get(section, [])
    content = to_csv(rows, columns)
    if rows:
        _log_export(section, rows, columns, content)
    return content
