"""DEMONSTRATION data for the governance gaps closed in wave 3 (G-7, G-15, E8-S5, E6-S3, E3-S2).

    from deploy.demo_additions import governance_gaps
    governance_gaps.run(frappe)       # inside a connected site; the caller commits

Builds on records ``deploy/demo_data.py`` has already made, and changes nothing
else. Idempotent: every step looks for what it would create and skips it when
it exists.

* **A charter with a pending challenge (G-7, G-15).** The Conduct and Culture
  Council's terms of reference take a version 2, published the way the forum
  page's Documents tab publishes one, so the challenge reopens and the forum
  page shows the version chain and the "not cleared" blocker.
* **A formation request blocked by its charter (G-7).** The Operational
  Resilience Steering Committee request, pending approval, gets a draft charter
  that the risk governance office has sent back with changes requested, so
  ``/formation-request`` lists the charter challenge among its approval blockers.
* **A disbandment awaiting approval (E8-S5).** The Third-Party Risk Working Group
  is to be folded into its parent, the Operational Risk Committee. The plan names
  G-11's approvers; the delegating authority has approved, the sponsor and the
  chair have not, so ``/forum-disband`` shows a plan that cannot yet be executed.
* **Scope data for the inventory filters (E6-S3, E3-S2).** Two forums are tagged
  with further business units, risk types and jurisdictions, and a legal entity
  that one forum carried is then retired — so ``/forums`` offers it under
  "Retired values" and still finds the forum, while pickers for new records no
  longer offer it.

Everything is fictitious, and records are owned by ``@demo.example`` personas
like the rest of the demonstration data.
"""

from __future__ import annotations

RGO = "risk.governance.lead@demo.example"
CRO = "chief.risk.officer@demo.example"

CHARTER_FORUM = "Conduct and Culture Council"
CHARTER_V2_LABEL = "2.0 draft"

BLOCKED_REQUEST = "Operational Resilience Steering Committee"
BLOCKED_CHARTER_TITLE = "Operational Resilience Steering Committee Terms of Reference (draft)"

DISBAND_FORUM = "Third-Party Risk Working Group"
SUCCESSOR_FORUM = "Operational Risk Committee"

RETIRED_ENTITY = ("LEASING_SUB", "Former Leasing Subsidiary")
RETIRED_CARRIER = "Asset-Liability Committee"


def _forum(frappe, forum_name: str) -> str | None:
    return frappe.db.get_value("Governance Forum", {"forum_name": forum_name}, "name")


def _as(frappe, user: str):
    """Act as a persona when it exists, so authorship reads as it would in use."""
    frappe.set_user(user if frappe.db.exists("User", user) else "Administrator")


def _charter_version(frappe, report: dict) -> None:
    from consilium.governance import charters

    forum = _forum(frappe, CHARTER_FORUM)
    charter = forum and frappe.db.get_value("Committee Charter", {"forum": forum}, "name")
    if not charter:
        report["charter_version"] = "skipped: no charter on " + CHARTER_FORUM
        return
    if frappe.db.exists("Document Version", {"subject_doctype": "Committee Charter", "subject_name": charter,
                                             "version_label": CHARTER_V2_LABEL}):
        report["charter_version"] = f"{charter} already at {CHARTER_V2_LABEL}"
        return
    _as(frappe, "committee.secretary@demo.example")
    try:
        doc = frappe.get_doc("Committee Charter", charter)
        version = charters.publish_version(
            doc,
            "Adds a standing conduct-risk dashboard to every sitting and moves the council to monthly "
            "meetings for its first year.",
            body_text=(
                "DEMONSTRATION DOCUMENT: fictitious content.\n\n"
                "1. Purpose\nThe council oversees conduct risk and the culture that drives it.\n\n"
                "2. Authority\nIt recommends; the Executive Committee decides.\n\n"
                "3. Sittings\nMonthly for the first year, then quarterly. A conduct-risk dashboard is "
                "tabled at every sitting.\n\n"
                "4. Escalation\nMatters above the conduct-risk appetite go to the Executive Committee within "
                "five business days."
            ),
            version_label=CHARTER_V2_LABEL,
        )
        charters.reopen_challenge(
            frappe.get_doc("Committee Charter", charter),
            f"Version {version.version_number} was published; the text has not yet been challenged.",
        )
    finally:
        frappe.set_user("Administrator")
    report["charter_version"] = f"{charter} v{version.version_number}, challenge reopened"


def _blocked_request(frappe, report: dict) -> None:
    from consilium.governance import charters

    request = frappe.db.get_value("Committee Formation Request", {"forum_name": BLOCKED_REQUEST}, "name")
    if not request:
        report["blocked_request"] = "skipped: no request for " + BLOCKED_REQUEST
        return
    if frappe.db.exists("Committee Charter", {"formation_request": request}):
        report["blocked_request"] = f"{request} already carries a charter"
        return
    # Drafted by the secretary, so the charter and its version carry a demo
    # owner like every other demonstration record; then challenged by the risk
    # governance office, as itself, through the entry point that checks the
    # challenge role.
    _as(frappe, "committee.secretary@demo.example")
    try:
        doc = frappe.get_doc({"doctype": "Committee Charter", "charter_title": BLOCKED_CHARTER_TITLE,
                              "formation_request": request}).insert(ignore_permissions=True)
        charters.publish_version(
            doc, "Draft terms of reference submitted with the request.",
            body_text=("DEMONSTRATION DOCUMENT: fictitious content.\n\nThe committee sets impact tolerances "
                       "for important business services and oversees their testing."),
            version_label="0.1",
        )
        _as(frappe, RGO)
        charters.record_charter_challenge(
            doc.name, charters.CHALLENGE_CHANGES_REQUESTED,
            comments="Name the delegating authority for tolerance-setting, and say how a tolerance breach is "
                     "escalated before this goes for approval.",
        )
    finally:
        frappe.set_user("Administrator")
    report["blocked_request"] = f"{request}: charter {doc.name} with changes requested"


def _disbandment(frappe, report: dict) -> None:
    from consilium.consilium_core import approvals
    from consilium.governance import lifecycle

    forum = _forum(frappe, DISBAND_FORUM)
    if not forum:
        report["disbandment"] = "skipped: no forum " + DISBAND_FORUM
        return
    existing = frappe.db.get_value("Disbandment Plan", {"forum": forum}, "name")
    if existing:
        report["disbandment"] = f"{forum} already has plan {existing}"
        return
    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        report["disbandment"] = f"skipped: {forum} is not active"
        return
    record = frappe.db.get_value("Governance Forum", forum, ["sponsor", "committee_chair"], as_dict=True)
    _as(frappe, RGO)
    try:
        plan = lifecycle.raise_disbandment(
            forum,
            trigger_scenario="Mandate Complete",
            records_disposition_note=(
                "Minutes, membership history and the working group's third-party inventory are retained under "
                "the forum's retention class. Open actions transfer to the Operational Risk Committee."
            ),
            successor_forum=_forum(frappe, SUCCESSOR_FORUM),
            approvals_rows=[
                {"approver_role": "Delegating Authority", "approver": CRO},
                {"approver_role": "Sponsor", "approver": record.sponsor or CRO},
                {"approver_role": "Chair", "approver": record.committee_chair or CRO},
            ],
        )
    finally:
        frappe.set_user("Administrator")
    authority = next(row for row in plan.approvals if row.approver_role == "Delegating Authority")
    approvals.record_decision(authority.approval_decision, "Approved",
                              comments="The working group has delivered its remit.", acting_user=CRO)
    frappe.get_doc("Disbandment Plan", plan.name).save(ignore_permissions=True)
    report["disbandment"] = f"{forum}: plan {plan.name}, 1 of 3 approvals given"


def _scope_tags(frappe, report: dict) -> None:
    """Further tags on two forums, then a retired legal entity one of them carries.

    The order is the point: the value is live when the forum is tagged with it,
    and retired afterwards, as it would be in use. Scope fields are not watched
    fields, so tagging does not send the forum back for review.
    """
    code, title = RETIRED_ENTITY
    carrier = _forum(frappe, RETIRED_CARRIER)
    if not carrier:
        report["scope"] = "skipped: no forum " + RETIRED_CARRIER
        return
    if frappe.db.exists("Legal Entity", code):
        report["scope"] = "already tagged"
        return
    # Added by the taxonomy administrator persona and tagged like the demo's
    # other taxonomy rows (external_code DEMO), so it is found and removed with them.
    _as(frappe, RGO)
    try:
        frappe.get_doc({"doctype": "Legal Entity", "legal_entity_code": code, "legal_entity_name": title,
                        "external_code": "DEMO",
                        "description": "Demonstration: a subsidiary sold and retired from the taxonomy."}
                       ).insert(ignore_permissions=True)
    finally:
        frappe.set_user("Administrator")

    tagged = []
    for forum_name, additions in (
        (RETIRED_CARRIER, {"legal_entities": ("legal_entity", [code]),
                           "jurisdictions": ("jurisdiction", frappe.get_all("Jurisdiction", pluck="name", limit=1))}),
        (SUCCESSOR_FORUM, {"risk_types": ("risk_type", frappe.get_all("Risk Type", filters={"is_active": 1},
                                                                       pluck="name", order_by="name", limit=2)),
                           "business_units": ("business_unit", frappe.get_all(
                               "Organization Unit", filters={"is_active": 1, "unit_level": "Business Unit"},
                               pluck="name", order_by="name", limit=1))}),
    ):
        name = _forum(frappe, forum_name)
        if not name:
            continue
        doc = frappe.get_doc("Governance Forum", name)
        for table, (column, values) in additions.items():
            held = {row.get(column) for row in doc.get(table)}
            for value in values:
                if value and value not in held:
                    doc.append(table, {column: value})
        doc.save(ignore_permissions=True)
        tagged.append(name)

    # Retired the way an administrator retires a value (E3-S2): the flag is
    # cleared on the record, through its controller, never deleted.
    _as(frappe, RGO)
    try:
        entity = frappe.get_doc("Legal Entity", code)
        entity.is_active = 0
        entity.save(ignore_permissions=True)
    finally:
        frappe.set_user("Administrator")
    report["scope"] = f"tagged {', '.join(tagged)}; {code} retired"


def run(frappe) -> dict:
    """Apply the additions. Returns what was done; the caller commits."""
    report: dict = {}
    if not frappe.db.exists("Governance Forum", {"forum_name": SUCCESSOR_FORUM}):
        report["skipped"] = "the demonstration forums are missing; run deploy/demo_data.py first"
        return report
    _charter_version(frappe, report)
    _blocked_request(frappe, report)
    _disbandment(frappe, report)
    _scope_tags(frappe, report)
    return report
