"""DEMONSTRATION data for the personal inbox (CS-10) and import batch review (CS-11).

    from deploy.demo_additions import inbox_imports
    inbox_imports.run(frappe)     # inside a connected site; the caller commits

Builds on records ``deploy/demo_data.py`` has already made and changes nothing
else. Idempotent: each step looks for what it would create and skips it when it
is there.

The inbox needs very little new data: the organisation already holds four
attestation campaigns (92 tasks, a third of them open), open approval steps,
overdue policy reviews, escalations under review and open action plans, and the
inbox is a view over those. Two things are added so that every kind of entry has
something to show:

* **A delegation of attestation.** The chief operating officer, on leave,
  delegates attestation of forum records to the head of operational risk for a
  month. The COO's open inventory tasks therefore also appear in the deputy's
  inbox, marked "acting for", and answering one records the delegation on the
  task.
* **An import batch awaiting review.** A file of escalation matters exported from
  another team's issue register, uploaded by the governance lead through the
  same path the portal uses, and validated. Four rows are valid; three are
  refused — an escalation type the taxonomy does not know, a risk type code
  with a typo, and a row with no description — so the review screen has both
  outcomes to show. Nothing is committed: the batch waits for a decision.

Every person and record here is fictitious.
"""

from __future__ import annotations

DEPUTY = "head.operational.risk@demo.example"
ON_LEAVE = "chief.operating.officer@demo.example"
IMPORTER = "risk.governance.lead@demo.example"
BATCH_REFERENCE = "ISSUE-REGISTER-EXPORT-2026-09"
FILE_NAME = "issue-register-export-2026-09.csv"
PROFILE_SYSTEM = "ESC_FILE"
PROFILE_TARGET = "Escalation Matter"

HEADER = [
    "external_id", "escalation_title", "escalation_type", "identification_date", "escalation_date",
    "description", "tier_1_risk_type", "identified_by", "organizational_level", "accountable_executive",
    "escalation_trigger", "severity", "impacted_entity_type", "impacted_entity",
]

ROWS = [
    ["ISS-40112", "Payments reconciliation break exceeded tolerance for three days", "LIMIT_BREACH",
     "2026-09-02", "2026-09-04", "Unreconciled items on the payments suspense account exceeded the daily "
     "tolerance on three consecutive days.", "PROCESS", "head.operational.risk@demo.example", "OPERATING_GROUP",
     "chief.operating.officer@demo.example", "Tolerance exceeded for three consecutive days.", "Medium", "", ""],
    ["ISS-40127", "Vendor failed to deliver the quarterly assurance report", "CONTROL_FAIL",
     "2026-09-05", "2026-09-08", "A critical supplier missed the contractual deadline for its quarterly "
     "control assurance report.", "VENDOR_FAIL", "head.technology.risk@demo.example", "LINE_OF_BUSINESS",
     "chief.information.officer@demo.example", "Contractual assurance deliverable missed.", "Low", "", ""],
    ["ISS-40131", "Access recertification not completed for a trading application", "CONTROL_FAIL",
     "2026-09-06", "2026-09-09", "The semi-annual access recertification for one trading application was "
     "not completed by its due date.", "TECHNOLOGY", "head.technology.risk@demo.example", "BUSINESS_UNIT",
     "chief.information.officer@demo.example", "Recertification overdue.", "Medium", "", ""],
    ["ISS-40140", "Complaint volumes rose sharply after a product change", "EMERGING_RISK",
     "2026-09-10", "2026-09-11", "Complaints about a repriced savings product tripled in the fortnight "
     "after the change.", "PROCESS", "chief.compliance.officer@demo.example", "LINE_OF_BUSINESS",
     "head.retail.banking@demo.example", "Complaint volume trigger.", "High", "", ""],
    # Refused: the issue register uses a category this taxonomy does not hold.
    ["ISS-40144", "Model inventory entry missing for a pricing tool", "MODEL_GAP",
     "2026-09-11", "2026-09-12", "A pricing tool in production has no entry in the model inventory.",
     "PROCESS", "head.model.risk@demo.example", "BUSINESS_UNIT", "chief.risk.officer@demo.example",
     "Inventory completeness check.", "Medium", "", ""],
    # Refused: a typo in the risk type code.
    ["ISS-40152", "Batch job overran and delayed the morning liquidity report", "INCIDENT",
     "2026-09-12", "2026-09-12", "An overnight batch overran by four hours and the liquidity report was "
     "issued late.", "TECH_OUTGAE", "head.technology.risk@demo.example", "OPERATING_GROUP",
     "chief.financial.officer@demo.example", "Regulatory report issued late.", "High", "", ""],
    # Refused: the description, which the profile requires, is empty.
    ["ISS-40158", "Third-party exit plan not tested", "AUDIT_FIND",
     "2026-09-14", "2026-09-15", "", "THIRD_PARTY", "head.internal.audit@demo.example", "OPERATING_GROUP",
     "chief.operating.officer@demo.example", "Audit finding.", "Medium", "", ""],
]


def _csv() -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(ROWS)
    return buffer.getvalue()


def _delegation(frappe) -> str:
    from frappe.utils import add_days, nowdate

    existing = frappe.db.get_value(
        "Authority Delegation",
        {"delegator": ON_LEAVE, "delegate": DEPUTY, "scope_doctype": "Governance Forum"},
        "name",
    )
    if existing:
        return f"delegation {existing} present"
    if not (frappe.db.exists("User", ON_LEAVE) and frappe.db.exists("User", DEPUTY)):
        return "delegation skipped (personas missing)"
    doc = frappe.get_doc(
        {
            "doctype": "Authority Delegation",
            "delegator": ON_LEAVE,
            "delegate": DEPUTY,
            "scope_type": "DocType",
            "scope_doctype": "Governance Forum",
            "valid_from": add_days(nowdate(), -3),
            "valid_to": add_days(nowdate(), 28),
            "reason": "Annual leave during the inventory attestation window. DEMONSTRATION RECORD.",
            "delegated_actions": [{"delegable_action": "ATTEST"}],
        }
    ).insert(ignore_permissions=True)
    doc.db_set("owner", ON_LEAVE, update_modified=False)
    return f"delegation {doc.name} made"


def _batch(frappe) -> str:
    existing = frappe.db.get_value("Import Batch", {"batch_reference": BATCH_REFERENCE}, "name")
    if existing:
        return f"batch {existing} present"
    profile = frappe.db.get_value(
        "Import Profile", {"source_system": PROFILE_SYSTEM, "target_doctype": PROFILE_TARGET, "is_active": 1}, "name"
    )
    if not profile:
        return "batch skipped (no escalation import profile)"
    if not frappe.db.exists("User", IMPORTER):
        return "batch skipped (persona missing)"

    from consilium.consilium_core import importing

    # Uploaded as the governance lead, through the portal's own path, so the
    # batch carries the same provenance (file, hash, importer) a real upload does.
    previous = frappe.session.user
    frappe.set_user(IMPORTER)
    try:
        context = importing.upload_batch(profile, FILE_NAME, _csv(), batch_reference=BATCH_REFERENCE)
    finally:
        frappe.set_user(previous)
    batch = context["batch"]
    return (f"batch {batch['name']} staged: {batch['valid_count']} valid, "
            f"{batch['warning_count']} warnings, {batch['error_count']} refused")


def run(frappe) -> str:
    return "; ".join([_delegation(frappe), _batch(frappe)])
