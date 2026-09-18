#!/usr/bin/env python3
"""Load DEMONSTRATION data into a site.

    cd .bench/sites
    FRAPPE_BENCH_ROOT=<bench> ../../.venv/bin/python ../../deploy/demo_data.py --site <site>
    ... --dry-run      run everything, report, then roll the whole run back

**This is not reference data.** ``deploy/seed.py`` loads the generic taxonomy a
site needs in order to work at all. This script builds on top of it a fictitious
regulated financial-services group — personas, a committee hierarchy with
meetings and votes, a policy library at every lifecycle phase, escalations at
every stage — so that every portal page and desk list reads like a system that
has been live for about eighteen months. None of it describes a real
organisation or person: every name is a role title or a generic label.

Everything is driven through the platform's own domain functions (formation,
compliance review, voting, charters, the policy lifecycle and its gates, the
escalation approval path, the attestation engine), not by writing state fields,
so the data carries the same audit trail a real user would leave behind.

Idempotent. Records are matched on natural keys (a forum's name, a meeting's
reference, a document's name, an escalation's title, ...) and skipped when they
already exist, so a second run creates nothing. Each section is committed on its
own; a failure in one section is rolled back to that section's savepoint and the
others still load.

Dates are relative to an **anchor** — the date of the first run, remembered in
the site defaults under ``consilium_demo_data_anchor`` — so the history stays
consistent across re-runs and still looks current on a fresh site. The platform
stamps "now" on everything it writes, so the final section back-dates creation,
modification and decision timestamps to the dates the story says they happened.

How to recognise, and remove, demonstration data
------------------------------------------------
* Every persona is a System User whose email ends in ``@demo.example``; the
  first name is the role title and the last name is ``(Demo)``. No password is
  set, so none of them can sign in until an administrator gives them one —
  ``deploy/demo_logins.py`` does that for a demonstration site, writing random
  passwords to a file outside the repository.
* Every record this script creates is **owned** by one of those personas
  (``owner LIKE '%@demo.example'``). Records the platform writes as a side
  effect — approval decisions, document versions, votes, SLA clocks,
  notification dispatches, classification assessments, external references,
  ToDos, comments and version-log rows — point at a demo record through
  ``subject_doctype``/``subject_name``, ``motion``, ``reference_name`` or
  ``docname``, and the final sweep gives them a demo owner as well.
* Taxonomy rows added here (organisation units, legal and material entities,
  regulatory requirements) carry ``external_code = 'DEMO'`` as well.
* The anchor date lives in ``tabDefaultValue`` under
  ``consilium_demo_data_anchor``.

The platform refuses to delete forums, seats, votes and document versions — by
design, they are the audit record — so removal is a database operation, not a
desk one. On a copy of the site, for each table ``t`` of the Consilium modules
plus ``User``, ``Has Role``, ``User Group``, ``Contact``, ``ToDo``, ``Comment``
and ``Version``::

    DELETE FROM "tab<t>" WHERE owner LIKE '%@demo.example';

then delete child rows whose ``parent`` no longer exists, and the anchor
default. Reference data from ``seed.py`` and records other people created are
untouched because nobody else's records have a demo owner.

Records other engineers are using are deliberately left alone:
CFR-2026-00001, CFR-2026-00002, FRM-2026-00002, GDOC-00001, ESC-2026-00001 and
anything named ``test``. A forum already named "Operational Risk Committee"
(FRM-2026-00001 on the development site) is reused as the demo's operational
risk committee rather than duplicated: its seats, meetings and reviews are demo
records; the forum row itself keeps its owner. On a fresh site there is no such
forum and the demo creates it like any other.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import traceback
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

DOMAIN = "demo.example"
ANCHOR_KEY = "consilium_demo_data_anchor"
DEMO_CODE = "DEMO"

#: Personas were provisioned when the platform went live, about eighteen months
#: before the anchor.
GO_LIVE = -560

#: The forum the brief says to reuse rather than duplicate.
EXISTING_ORC = "FRM-2026-00001"


def U(key: str | None) -> str | None:
    """A persona's email from its key."""
    return f"{key}@{DOMAIN}" if key else None


# =============================================================== the context


class Ctx:
    """What a run carries between sections: the anchor, counters, and the
    timestamps to write once every save is done."""

    def __init__(self, frappe, anchor: date, dry_run: bool):
        self.frappe = frappe
        self.anchor = anchor
        self.dry_run = dry_run
        self.created: Counter = Counter()
        self.existing: Counter = Counter()
        self.section_created: Counter = Counter()
        self.stamps: list[tuple] = []
        self.notes: list[str] = []
        self.failures: list[tuple[str, str]] = []
        self.protected_documents: list[str] | None = None

    # ------------------------------------------------------------ dates

    def day(self, offset: int) -> date:
        return self.anchor + timedelta(days=offset)

    def d(self, offset: int | None) -> str | None:
        return None if offset is None else str(self.day(offset))

    def weekday(self, offset: int) -> date:
        """A meeting falls on a working day: move forward off a weekend."""
        value = self.day(offset)
        while value.weekday() >= 5:
            value += timedelta(days=1)
        return value

    def ts(self, offset: int, hhmm: str = "10:00") -> str:
        return f"{self.day(offset)} {hhmm}:00"

    # ------------------------------------------------------- bookkeeping

    def made(self, doctype: str, n: int = 1) -> None:
        self.created[doctype] += n
        self.section_created[doctype] += n

    def had(self, doctype: str, n: int = 1) -> None:
        self.existing[doctype] += n

    def stamp(self, doctype: str, name: str, when: str | date | None, by: str | None = None, **fields):
        """Record a back-dating to apply at the end of the run.

        Applied last, because a document saved after its ``modified`` was
        rewritten would be refused as stale.
        """
        if name:
            self.stamps.append((doctype, name, str(when) if when else None, by, fields))


# ============================================================ small helpers


def find(frappe, doctype: str, filters) -> str | None:
    return frappe.db.get_value(doctype, filters, "name")


def ensure(ctx: Ctx, doctype: str, key_filters, values: dict, *, by: str, when=None,
           ignore_permissions: bool = True):
    """Insert a record unless its natural key already exists. Returns (name, created)."""
    frappe = ctx.frappe
    name = find(frappe, doctype, key_filters)
    if name:
        ctx.had(doctype)
        return name, False
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=ignore_permissions)
    ctx.made(doctype)
    ctx.stamp(doctype, doc.name, when, by)
    return doc.name, True


@contextmanager
def acting_as(frappe, user: str):
    """Do something as a persona, through the platform's own permission checks,
    then give the session back to whoever had it."""
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)


def forum_by_name(frappe, forum_name: str) -> str | None:
    return find(frappe, "Governance Forum", {"forum_name": forum_name})


@contextmanager
def role_holder_first(frappe, user: str, role: str, ctx: Ctx):
    """Make ``user`` the holder a role-based formation step resolves to.

    ``formation._assignee`` gives a role-based step to whichever ``Has Role`` row
    the database returns first (``limit=1`` under the framework's default
    ``modified desc`` order), so with several holders the choice is arbitrary.
    The demo's personas are back-dated to go-live precisely so that they do
    *not* win that race against people already using the site; for the demo's
    own formation requests the Risk Governance Office Lead is brought to the
    front for the duration of the call and put back afterwards.
    """
    go_live = f"{ctx.day(GO_LIVE)} 09:00:00"
    # The framework's clock, not the database's: PostgreSQL's now() is in the
    # session time zone, which need not be the one the framework stamps in.
    frappe.db.sql(
        """UPDATE "tabHas Role" SET "modified" = %s WHERE "parent" = %s AND "role" = %s""",
        (frappe.utils.now(), user, role),
    )
    try:
        yield
    finally:
        frappe.db.sql(
            """UPDATE "tabHas Role" SET "modified" = %s WHERE "parent" = %s AND "role" = %s""",
            (go_live, user, role),
        )


# =========================================================== reference data
#
# Additions to the generic taxonomy that a group of this shape needs: lines of
# business and business units under the enterprise, subsidiaries, the entities
# designated material, and the regulatory instruments forums and documents
# cite. All generic; all tagged external_code = DEMO.

ORG_UNITS = [
    # code, name, parent, level, is_group
    ("PCB", "Personal and Commercial Banking", "ENTERPRISE", "Line of Business", 1),
    ("WEALTH", "Wealth Management", "ENTERPRISE", "Line of Business", 1),
    ("CAPMKTS", "Capital Markets", "ENTERPRISE", "Line of Business", 1),
    ("PCB_RETAIL", "Retail Lending", "PCB", "Business Unit", 0),
    ("PCB_CARDS", "Cards and Payments", "PCB", "Business Unit", 0),
    ("PCB_COMMERCIAL", "Commercial Banking", "PCB", "Business Unit", 0),
    ("WEALTH_PRIVATE", "Private Wealth", "WEALTH", "Business Unit", 0),
    ("WEALTH_AM", "Asset Management", "WEALTH", "Business Unit", 0),
    ("CM_MARKETS", "Global Markets", "CAPMKTS", "Business Unit", 0),
    ("CM_TREASURY", "Corporate Treasury", "CAPMKTS", "Business Unit", 0),
    ("TECH_INFRA", "Technology Infrastructure", "TECH", "Business Unit", 0),
    ("TECH_SECURITY", "Information Security", "TECH", "Business Unit", 0),
]

LEGAL_ENTITIES = [
    # code, name, material
    ("BANK_SUB", "Principal Banking Subsidiary", 1),
    ("DEALER_SUB", "Securities Dealer Subsidiary", 1),
    ("INSURANCE_SUB", "Insurance Subsidiary", 1),
    ("ASSET_MGMT_SUB", "Asset Management Subsidiary", 0),
    ("INTL_BRANCH", "International Branch Operations", 0),
]

MATERIAL_ENTITIES = [
    # code, name, legal entity, designation basis, designated (days from anchor)
    ("ME_BANK", "Principal Banking Subsidiary (material)", "BANK_SUB",
     "Deposit-taking and payment functions critical to the domestic economy; resolution-planning designation.", -900),
    ("ME_DEALER", "Securities Dealer Subsidiary (material)", "DEALER_SUB",
     "Market-making and clearing activity above the resolution-planning threshold.", -900),
    ("ME_INSURANCE", "Insurance Subsidiary (material)", "INSURANCE_SUB",
     "Policyholder liabilities above the group materiality threshold.", -700),
]

REGULATORY_REQUIREMENTS = [
    # code, name, regulator, jurisdiction, citation, summary
    ("REQ_CORP_GOV", "Corporate Governance Guideline", "National prudential regulator", "NATIONAL",
     "Guideline CG-1", "Board and committee structure, mandates, independence and oversight of risk."),
    ("REQ_OP_RESILIENCE", "Operational Resilience Guideline", "National prudential regulator", "NATIONAL",
     "Guideline OR-2", "Identification of critical operations, impact tolerances, mapping and scenario testing."),
    ("REQ_THIRD_PARTY", "Third-Party Risk Management Guideline", "National prudential regulator", "NATIONAL",
     "Guideline TP-3", "Risk-based management of third-party arrangements across their lifecycle, including exit."),
    ("REQ_MODEL_RISK", "Model Risk Management Guideline", "National prudential regulator", "NATIONAL",
     "Guideline MR-4", "Model inventory, tiering, independent validation, monitoring and governance."),
    ("REQ_TECH_CYBER", "Technology and Cyber Risk Management Guideline", "National prudential regulator",
     "NATIONAL", "Guideline TC-5", "Technology governance, cyber security, incident management and resilience."),
    ("REQ_CAPITAL", "Capital Adequacy Requirements", "National prudential regulator", "NATIONAL",
     "Requirements CA-6", "Minimum capital, buffers and internal capital adequacy assessment."),
    ("REQ_LIQUIDITY", "Liquidity Adequacy Requirements", "National prudential regulator", "NATIONAL",
     "Requirements LA-7", "Liquidity coverage, net stable funding and intraday liquidity management."),
    ("REQ_AML", "Anti-Money Laundering and Anti-Terrorist Financing Regulations", "Financial intelligence unit",
     "NATIONAL", "Regulations AML-8", "Customer due diligence, transaction monitoring, reporting and record keeping."),
    ("REQ_PRIVACY", "Personal Information Protection Legislation", "Data protection authority", "NATIONAL",
     "Act PI-9", "Consent, safeguarding, breach notification and individual access to personal information."),
    ("REQ_REG_REPORTING", "Regulatory Returns Filing Requirements", "National prudential regulator", "NATIONAL",
     "Manual RR-10", "Content, accuracy and deadlines of periodic prudential returns."),
    ("REQ_CONDUCT", "Market Conduct and Consumer Protection Framework", "Financial consumer agency",
     "NATIONAL", "Framework MC-11", "Fair treatment of customers, complaint handling and sales practices."),
    ("REQ_RECORDS", "Records Retention Regulations", "National prudential regulator", "NATIONAL",
     "Regulations RK-12", "Minimum retention periods and accessibility of books and records."),
]

RETENTION_CLASSES = [
    # code, title, months, trigger, disposition, worm, legal basis
    ("GOV-FORUM", "Governance forum records", 120, "Disbandment", "Archive Permanently", 0,
     "Corporate governance records retained for ten years after a forum is disbanded."),
    ("GOV-MINUTES", "Minutes and decisions", 1200, "Creation", "Archive Permanently", 1,
     "Minutes of the board and its committees are kept permanently."),
    ("POL-DOCUMENT", "Governing documents", 84, "Retirement", "Review", 0,
     "Seven years after retirement, then reviewed for permanent archive."),
    ("ESC-MATTER", "Escalation matters", 84, "Closure", "Review", 0,
     "Seven years after closure, in line with the records retention regulations."),
    ("ATTESTATION", "Attestations", 84, "Creation", "Destroy", 0,
     "Seven years from the attestation date."),
]

NOTIFICATION_CHANNELS = [
    # code, title, type, adapter, fallback
    ("IN_APP", "In-app notification", "In App", "in_app", "RECORD"),
    ("WEEKLY_DIGEST", "Weekly digest", "Digest", "record_only", "RECORD"),
]

EXTERNAL_SYSTEMS = [
    ("GRC_PLATFORM", "External GRC platform (issue management)",
     "The issue-management platform matters are handed to when they are tracked outside Consilium."),
    ("RISK_REGISTER", "Enterprise risk register",
     "The register of enterprise risks and risk-appetite statements that forums and escalations cite."),
]

BUSINESS_CALENDAR = ("HEAD_OFFICE", "Head office business calendar")

SLA_DEFINITIONS = [
    # code, title, hours, calendar
    ("ESC-HIGH", "High-severity escalation: resolve within two working weeks", 80.0, "Business Hours"),
    ("ESC-MEDIUM", "Medium-severity escalation: resolve within six working weeks", 240.0, "Business Hours"),
    ("ESC-LOW", "Low-severity escalation: resolve within thirty days", 720.0, "24x7"),
]

DOCUMENT_TEMPLATES = [
    # title, document type, action, naming pattern, sections
    ("Policy — new issue", "POLICY", "New", "<Subject> Policy", [
        ("Purpose and scope", "Why the policy exists and who it applies to.", 1),
        ("Policy statements", "The mandatory requirements, one per paragraph.", 1),
        ("Roles and responsibilities", "Accountabilities across the three lines.", 1),
        ("Exceptions", "How an exemption or deviation is requested and approved.", 1),
        ("Related documents", "Framework above, standards and procedures below.", 0),
    ]),
    ("Standard — new issue", "STANDARD", "New", "<Subject> Standard", [
        ("Scope", "The policy this standard implements.", 1),
        ("Requirements", "Specific, testable minimum requirements.", 1),
        ("Metrics and monitoring", "How compliance with the standard is measured.", 1),
    ]),
    ("Procedure — new issue", "PROCEDURE", "New", "<Process> Procedure", [
        ("Trigger", "What starts the procedure.", 1),
        ("Steps", "Numbered steps with the role that performs each.", 1),
        ("Records", "What evidence each step leaves behind.", 1),
    ]),
    ("Policy — periodic review", "POLICY", "Review", "<Subject> Policy — review <year>", [
        ("Horizon scan summary", "Changes found since the last review.", 1),
        ("Proposed changes", "Marked-up changes with their classification.", 1),
        ("Recommendation", "No change, minor update, major update or retire.", 1),
    ]),
    ("Framework — new issue", "FRAMEWORK", "New", "<Subject> Framework", [
        ("Principles", "The principles every document beneath the framework follows.", 1),
        ("Structure", "The governance structure and document hierarchy.", 1),
        ("Risk taxonomy", "The taxonomy the framework applies.", 1),
    ]),
]

GUIDE_ARTICLES = [
    # slug, title, category, module, order, body
    ("guide-getting-started", "Setting up a governance forum", "Getting Started", "Governance", 10, """
<p>Every forum on the inventory exists because a <strong>formation request</strong> was raised, evaluated
by the Risk Governance Office against the five formation criteria and approved by its delegating
authority. That is why each forum can say who asked for it, why, and who sponsors it.</p>
<ol>
<li><strong>Search the inventory.</strong> The duplicate check runs on submission; most rejected requests
overlap a forum that already exists.</li>
<li><strong>Name the delegating authority and sponsor.</strong> Both approve the request.</li>
<li><strong>Draft the mandate and escalation route.</strong> The office will challenge them.</li>
<li><strong>Expect a compliance review</strong> once the forum has a chair, a secretary and a charter.</li>
</ol>
<p>Questions: the Risk Governance Office Lead.</p>"""),
    ("guide-forum-types", "Forum types in this group", "Forum Types", "Governance", 20, """
<p>The <strong>Board</strong> reserves the matters listed in its mandate and delegates the rest to its
committees and to the Executive Committee. <strong>Board committees</strong> oversee on the Board's
behalf. The <strong>Executive Committee</strong> and the <strong>Executive Risk Committee</strong> decide
within their delegations; <strong>management committees</strong> decide within their risk domains.</p>
<p><strong>Councils</strong> and <strong>working groups</strong> coordinate and recommend. If a working
group finds itself taking decisions, raise a modify request to make it a committee.</p>"""),
    ("guide-templates", "Templates in use", "Templates", "Policy", 30, """
<p>Start a new governing document from the template for its type and action. The Enterprise Policy
Office will return a draft that does not follow the template's mandatory sections.</p>
<p>Escalations use the template for their escalation type: an incident needs a response owner and its
escalation date, a limit breach needs a reassessment frequency on any risk acceptance.</p>"""),
    ("guide-decision-authority", "Where decisions are taken", "Decision Authority", "Governance", 40, """
<p>A decision stands when three things are true: the forum holds the authority, the sitting was quorate
under the forum's own quorum rule, and the motion and its outcome are recorded with the votes cast.</p>
<table><thead><tr><th>Matter</th><th>Decided by</th></tr></thead><tbody>
<tr><td>Risk appetite</td><td>Board, on the Board Risk Committee's recommendation</td></tr>
<tr><td>Frameworks and enterprise policies</td><td>Board Risk Committee</td></tr>
<tr><td>Risk acceptances above appetite</td><td>Executive Risk Committee</td></tr>
<tr><td>Domain policies and standards</td><td>The owning management committee</td></tr>
</tbody></table>"""),
    ("guide-escalation-protocol", "How to escalate", "Escalation Protocol", "Escalation", 50, """
<p>Raise an escalation when a <strong>threshold</strong> is crossed: a limit breached, an impact tolerance
exceeded, a regulatory deadline missed, a material entity affected. The escalation matrix proposes the
severity and the forums; the service level starts when the matter is opened.</p>
<p>A matter closes only with a recorded outcome and a completed response template. A matter handed to
the external issue-management platform keeps its reference here.</p>"""),
    ("guide-policy-lifecycle", "The policy lifecycle", "Policy Lifecycle", "Policy", 60, """
<p>Draft, review, approval, publication, implementation, retirement. Publication is refused until every
step of the routed approval path is decided, a version is in the chain and applicability is recorded,
because applicability is what decides who is told.</p>"""),
]

# ================================================================ personas
#
# Role titles, not names. Each maps to the access roles the permission rows on
# the DocTypes actually use. Nobody gets a password.

PERSONAS = [
    ("board.chair", "Chair of the Board", ["Governance Viewer"]),
    ("director.risk", "Independent Director, Risk Committee Chair", ["Governance Viewer"]),
    ("director.audit", "Independent Director, Audit Committee Chair", ["Governance Viewer"]),
    ("chief.executive", "Chief Executive Officer", ["Governance Viewer", "Forum Owner", "Escalation Reviewer"]),
    ("chief.risk.officer", "Chief Risk Officer", [
        "Head of Risk Governance", "Forum Owner", "Policy Owner", "Escalation Owner",
        "Escalation Reviewer", "Sensitive Escalation Access", "Governance Viewer"]),
    ("chief.compliance.officer", "Chief Compliance Officer", [
        "Compliance Reviewer", "Policy Owner", "Forum Owner", "Escalation Owner",
        "Escalation Reviewer", "Sensitive Escalation Access"]),
    ("chief.information.officer", "Chief Information Officer", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("chief.operating.officer", "Chief Operating Officer", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("chief.financial.officer", "Chief Financial Officer", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("general.counsel", "General Counsel", [
        "Policy Reviewer", "Escalation Reviewer", "Sensitive Escalation Access", "Governance Viewer"]),
    ("head.operational.risk", "Head of Operational Risk", [
        "Policy Owner", "Forum Owner", "Escalation Owner", "Escalation Reviewer"]),
    ("head.technology.risk", "Head of Technology Risk", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("head.model.risk", "Head of Model Risk", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("treasurer", "Treasurer", ["Policy Owner", "Forum Owner", "Escalation Owner"]),
    ("head.retail.banking", "Head of Personal and Commercial Banking", [
        "Policy Owner", "Escalation Owner", "Governance Viewer"]),
    ("head.internal.audit", "Head of Internal Audit", ["Consilium Audit", "Governance Viewer"]),
    ("internal.auditor", "Internal Auditor", ["Consilium Audit"]),
    ("risk.governance.lead", "Risk Governance Office Lead", [
        "Risk Governance Office", "Committee Secretary", "Taxonomy Administrator", "Consilium Administrator"]),
    ("risk.governance.analyst", "Risk Governance Analyst", ["Risk Governance Office", "Governance Viewer"]),
    ("committee.secretary", "Committee Secretary", ["Committee Secretary", "Governance Viewer"]),
    ("policy.office.lead", "Enterprise Policy Office Lead", ["Enterprise Policy Office", "Policy Reviewer"]),
    ("second.line.reviewer", "Second Line Reviewer", [
        "Policy Reviewer", "Compliance Reviewer", "Escalation Reviewer"]),
    ("records.manager", "Records Manager", ["Records Manager", "Governance Viewer"]),
]

USER_GROUPS = [
    ("Executive Risk Committee Members", ["chief.risk.officer", "chief.financial.officer",
                                          "chief.operating.officer", "chief.information.officer",
                                          "chief.compliance.officer", "general.counsel"]),
    ("Risk Management Function", ["chief.risk.officer", "head.operational.risk", "head.technology.risk",
                                  "head.model.risk", "second.line.reviewer", "risk.governance.lead",
                                  "risk.governance.analyst"]),
    ("Technology and Operations Leadership", ["chief.information.officer", "chief.operating.officer",
                                              "head.technology.risk"]),
    ("Compliance Function", ["chief.compliance.officer", "second.line.reviewer", "general.counsel"]),
    ("Business Line Leadership", ["head.retail.banking", "treasurer", "chief.financial.officer"]),
]


# ================================================================ sections


def section_reference(ctx: Ctx) -> None:
    """Taxonomy additions, retention classes, channels, calendar, service levels."""
    frappe = ctx.frappe
    admin = U("risk.governance.lead")
    when = ctx.ts(GO_LIVE, "09:30")

    for code, name, parent, level, is_group in ORG_UNITS:
        ensure(ctx, "Organization Unit", code, {
            "org_unit_code": code, "org_unit_name": name, "parent_org_unit": parent,
            "unit_level": level, "is_group": is_group, "is_active": 1, "external_code": DEMO_CODE,
        }, by=admin, when=when)

    for code, name, material in LEGAL_ENTITIES:
        ensure(ctx, "Legal Entity", code, {
            "legal_entity_code": code, "legal_entity_name": name, "is_material_entity": material,
            "is_active": 1, "external_code": DEMO_CODE,
            "description": "A subsidiary of the parent entity.",
        }, by=admin, when=when)

    for code, name, entity, basis, designated in MATERIAL_ENTITIES:
        ensure(ctx, "Material Entity", code, {
            "material_entity_code": code, "material_entity_name": name, "legal_entity": entity,
            "designation_basis": basis, "designated_on": ctx.d(designated), "is_active": 1,
            "external_code": DEMO_CODE,
        }, by=admin, when=when)

    for index, (code, name, regulator, jurisdiction, citation, summary) in enumerate(REGULATORY_REQUIREMENTS):
        ensure(ctx, "Regulatory Requirement", code, {
            "regulatory_requirement_code": code, "regulatory_requirement_name": name,
            "regulator": regulator, "jurisdiction": jurisdiction, "citation": citation,
            "summary": summary, "description": summary, "is_active": 1, "sort_order": index * 10,
            "external_code": DEMO_CODE, "effective_date": ctx.d(-1500),
            "last_change_on": ctx.d(-200 - index * 37),
        }, by=admin, when=when)

    for code, title, months, trigger, action, worm, basis in RETENTION_CLASSES:
        ensure(ctx, "Retention Class", code, {
            "class_code": code, "title": title, "retention_period_months": months,
            "trigger_event": trigger, "disposition_action": action, "requires_worm": worm,
            "legal_basis": basis, "is_active": 1,
        }, by=U("records.manager"), when=when)

    for code, title, kind, adapter, fallback in NOTIFICATION_CHANNELS:
        ensure(ctx, "Notification Channel", code, {
            "channel_code": code, "title": title, "channel_type": kind, "adapter": adapter,
            "fallback_channel": fallback, "is_active": 1,
        }, by=admin, when=when)

    for code, title, description in EXTERNAL_SYSTEMS:
        ensure(ctx, "External System", code, {
            "system_code": code, "title": title, "description": description, "is_active": 1,
        }, by=admin, when=when)

    code, title = BUSINESS_CALENDAR
    year = ctx.anchor.year
    holidays = sorted(
        f"{y}-{md}" for y in (year - 1, year, year + 1) for md in ("01-01", "07-01", "12-25", "12-26")
    )
    ensure(ctx, "Business Calendar", code, {
        "calendar_code": code, "title": title, "day_start": "08:30:00", "day_end": "17:30:00",
        "holidays": json.dumps(holidays), "is_active": 1,
    }, by=admin, when=when)

    for sla_code, sla_title, hours, calendar in SLA_DEFINITIONS:
        ensure(ctx, "SLA Definition", sla_code, {
            "sla_code": sla_code, "title": sla_title, "target_doctype": "Escalation Matter",
            "measure": "Total Open Time", "target_hours": hours, "warning_threshold_pct": 75,
            "calendar": calendar, "business_calendar": code if calendar == "Business Hours" else None,
            "is_active": 1,
        }, by=admin, when=when)

    for title, doc_type, action, pattern, sections in DOCUMENT_TEMPLATES:
        # required_fields is deliberately left empty: it feeds the metadata gate
        # for every document of the type, including ones other people own.
        ensure(ctx, "Document Template", title, {
            "template_title": title, "document_type": doc_type, "action": action,
            "naming_convention_pattern": pattern, "is_active": 1,
            "sections": [
                {"section_title": s, "guidance": g, "is_mandatory": m, "sequence": i + 1}
                for i, (s, g, m) in enumerate(sections)
            ],
        }, by=U("policy.office.lead"), when=when)

    for slug, title, category, module, order, body in GUIDE_ARTICLES:
        ensure(ctx, "Guide Article", slug, {
            "slug": slug, "title": title, "category": category, "applies_to_module": module,
            "display_order": order, "body": body.strip(), "is_published": 1,
        }, by=admin, when=ctx.ts(-40, "11:00"))


def section_users(ctx: Ctx) -> None:
    """Personas and the user groups notification and applicability resolve through."""
    frappe = ctx.frappe
    go_live = f"{ctx.day(GO_LIVE)} 09:00:00"
    for key, title, roles in PERSONAS:
        email = U(key)
        if frappe.db.exists("User", email):
            ctx.had("User")
            continue
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": title,
            "last_name": "(Demo)",
            "user_type": "System User",
            "send_welcome_email": 0,
            "enabled": 1,
            "roles": [{"role": role} for role in roles if frappe.db.exists("Role", role)],
        })
        user.flags.no_welcome_mail = True
        user.insert(ignore_permissions=True)
        ctx.made("User")
        ctx.stamp("User", email, go_live, U("risk.governance.lead"))
        # Provisioned at go-live. This also keeps these role rows *older* than
        # those of people already testing on the site, so a role-based step that
        # picks the newest holder keeps picking the person it picked before.
        frappe.db.sql(
            """UPDATE "tabHas Role" SET "creation" = %s, "modified" = %s, "owner" = %s
               WHERE "parent" = %s AND "parenttype" = 'User'""",
            (go_live, go_live, U("risk.governance.lead"), email),
        )

    for group, members in USER_GROUPS:
        ensure(ctx, "User Group", group, {
            "__newname": group,
            "user_group_members": [{"user": U(m)} for m in members],
        }, by=U("risk.governance.lead"), when=go_live)


# ============================================================ forum tree
#
# Board -> Board Risk Committee, Audit Committee, Executive Committee;
# Executive Committee -> Executive Risk Committee, Asset-Liability Committee,
# Conduct and Culture Council (and the Data Governance Council, which the
# formation section brings into being); Executive Risk Committee -> the
# operational, technology, model and credit risk committees; the Operational
# Risk Committee -> the Third-Party Risk Working Group and the Outsourcing
# Oversight Forum it replaced, which is disbanded.
#
# key: (abbreviation, spec). ``parent`` and ``links`` name other keys and must
# already exist, so the list runs top-down.

FORUMS = [
    ("BOARD", "BOD", dict(
        forum_name="Board of Directors", forum_type="BOARD", cadence="Quarterly",
        description="Sets the group's strategy and risk appetite, oversees management and holds the "
                    "matters reserved to the Board. Delegates the remainder to its committees and to the "
                    "Executive Committee.",
        sponsor="board.chair", compliance_contact="chief.compliance.officer",
        primary_risk_category="STRATEGIC", owning_operating_group="ENTERPRISE",
        responsibilities=["OVERSIGHT_AND_DECISION"], legal_entities=["PARENT"], jurisdictions=["NATIONAL"],
        regulatory=[("REQ_CORP_GOV", "Board composition, mandate and oversight of risk management.")],
        escalation_protocol="Matters reach the Board through the Board Risk Committee or the Audit "
                            "Committee, or directly from the Chief Executive Officer where urgent.",
        escalation_threshold="A breach of Board-approved risk appetite, or an event that threatens "
                             "capital, liquidity or licence.",
        quorum_rule_type="Percentage", quorum_value=50, quorum_requires_chair=1,
        established=-3650, next_review=150, retention="GOV-MINUTES")),
    ("BRC", "BRC", dict(
        forum_name="Board Risk Committee", forum_type="BOARD_CTTE", cadence="Quarterly", parent="BOARD",
        description="Oversees the enterprise risk management framework, recommends risk appetite to the "
                    "Board and challenges management's assessment of the principal risks.",
        sponsor="board.chair", compliance_contact="chief.compliance.officer",
        primary_risk_category="STRATEGIC", owning_operating_group="RISK",
        responsibilities=["OVERSIGHT"], risk_types=["FINANCIAL", "TECHNOLOGY", "REGULATORY", "THIRD_PARTY"],
        jurisdictions=["NATIONAL"],
        regulatory=[("REQ_CORP_GOV", "A board-level risk committee of independent directors.")],
        links=[("BOARD", "Reports To", "Reports after every meeting.")],
        escalation_protocol="The Chief Risk Officer escalates within five business days of a risk "
                            "appetite breach; the chair decides whether the Board is convened.",
        escalation_threshold="Any breach of a Board-level risk appetite limit.",
        quorum_rule_type="Count", quorum_value=2, quorum_requires_chair=1,
        established=-2900, next_review=95, retention="GOV-MINUTES")),
    ("AC", "AC", dict(
        forum_name="Audit Committee", forum_type="BOARD_CTTE", cadence="Quarterly", parent="BOARD",
        description="Oversees financial reporting, internal control, the internal audit function and the "
                    "external auditor.",
        sponsor="board.chair", compliance_contact="chief.compliance.officer",
        primary_risk_category="COMPLIANCE", owning_operating_group="AUDIT",
        responsibilities=["OVERSIGHT"], jurisdictions=["NATIONAL"],
        regulatory=[("REQ_CORP_GOV", "An audit committee of independent directors.")],
        links=[("BOARD", "Reports To", None)],
        escalation_protocol="The Head of Internal Audit has unrestricted access to the chair.",
        escalation_threshold="A high-rated audit finding overdue by more than 90 days.",
        quorum_rule_type="Count", quorum_value=2, quorum_requires_chair=1,
        established=-2900, next_review=40, retention="GOV-MINUTES")),
    ("EXCO", "EXCO", dict(
        forum_name="Executive Committee", forum_type="EXEC_CTTE", cadence="Monthly", parent="BOARD",
        description="Runs the group within the authority delegated by the Board: strategy execution, "
                    "resource allocation and the most significant management decisions.",
        sponsor="chief.executive", compliance_contact="second.line.reviewer",
        primary_risk_category="STRATEGIC", owning_operating_group="ENTERPRISE",
        responsibilities=["DECISION_MAKING"], legal_entities=["PARENT", "BANK_SUB"],
        links=[("BOARD", "Reports To", "Monthly report from the Chief Executive Officer.")],
        escalation_protocol="Unresolved matters go to the Board through the Chief Executive Officer.",
        escalation_threshold="A decision outside the Executive Committee's delegated limits.",
        quorum_rule_type="Percentage", quorum_value=60, quorum_requires_chair=1,
        established=-2500, next_review=210, retention="GOV-MINUTES")),
    ("ERC", "ERC", dict(
        forum_name="Executive Risk Committee", forum_type="EXEC_CTTE", cadence="Monthly", parent="EXCO",
        description="The senior management forum for enterprise risk: monitors the risk profile against "
                    "appetite, approves enterprise risk policies and decides on escalated risk acceptances.",
        sponsor="chief.executive", compliance_contact="chief.compliance.officer",
        primary_risk_category="STRATEGIC", owning_operating_group="RISK",
        responsibilities=["OVERSIGHT_AND_DECISION"],
        risk_types=["FINANCIAL", "PROCESS", "REGULATORY", "TECHNOLOGY", "THIRD_PARTY", "PEOPLE"],
        legal_entities=["BANK_SUB", "DEALER_SUB", "INSURANCE_SUB"], jurisdictions=["NATIONAL", "REGIONAL"],
        links=[("EXCO", "Reports To", "Monthly risk report."),
               ("BRC", "Escalates To", "Risk appetite breaches and material-entity matters.")],
        escalation_protocol="Escalate to the Board Risk Committee within five business days of a risk "
                            "appetite breach, with the proposed treatment and accountable executive.",
        escalation_threshold="A breach of risk appetite, an impact on a material entity, or a risk "
                             "acceptance above the committee's delegated limit.",
        quorum_rule_type="Percentage", quorum_value=50, quorum_requires_chair=1,
        established=-1800, next_review=120, retention="GOV-MINUTES")),
    ("ORC", "ORC", dict(
        # Reused, not duplicated, where a forum of this name already exists (see
        # the module docstring); on a fresh site it is created like the others.
        forum_name="Operational Risk Committee", forum_type="MGMT_CTTE", cadence="Monthly",
        primary_risk_category="OPERATIONAL", owning_operating_group="RISK",
        reuse_existing=True, parent="ERC", sponsor="chief.risk.officer",
        compliance_contact="second.line.reviewer",
        description="Oversees operational risk appetite, loss events and key risk indicators across the "
                    "enterprise, and approves the operational risk policy suite.",
        responsibilities=["OVERSIGHT_AND_DECISION"], risk_types=["PROCESS", "TECHNOLOGY", "THIRD_PARTY", "PEOPLE"],
        business_units=["PCB_RETAIL", "PCB_CARDS", "TECH_INFRA"],
        links=[("ERC", "Reports To", "Monthly operational risk profile.")],
        escalation_protocol="Escalate to the Executive Risk Committee when a key risk indicator is red for "
                            "two consecutive months or a single loss exceeds the reporting threshold.",
        escalation_threshold="Operational loss above the enterprise reporting threshold, or an impact "
                             "tolerance exceeded for a critical operation.",
        quorum_rule_type="Percentage", quorum_value=50,
        quorum_requires_chair=1, established=-540, next_review=200, retention="GOV-FORUM")),
    ("TCRC", "TCRC", dict(
        forum_name="Technology and Cyber Risk Committee", forum_type="MGMT_CTTE", cadence="Monthly",
        parent="ERC",
        description="Oversees technology and cyber risk: the security posture, material incidents, "
                    "technology resilience and the remediation of control gaps.",
        sponsor="chief.operating.officer", compliance_contact="second.line.reviewer",
        primary_risk_category="TECHNOLOGY", owning_operating_group="TECH",
        responsibilities=["OVERSIGHT_AND_DECISION"], risk_types=["TECH_CYBER", "TECH_OUTAGE", "PROCESS_CHANGE"],
        business_units=["TECH_INFRA", "TECH_SECURITY"],
        regulatory=[("REQ_TECH_CYBER", "Governance of technology and cyber risk at management level.")],
        links=[("ERC", "Reports To", None), ("ORC", "Informs", "Shares technology incident data.")],
        escalation_protocol="Severity-one incidents are reported to the Executive Risk Committee chair "
                            "within 24 hours.",
        escalation_threshold="A severity-one incident, or a critical vulnerability unremediated past its "
                             "service level.",
        quorum_rule_type="Count", quorum_value=3, quorum_requires_chair=0,
        established=-520, next_review=60, retention="GOV-FORUM")),
    ("MRC", "MRC", dict(
        forum_name="Model Risk Committee", forum_type="MGMT_CTTE", cadence="Quarterly", parent="ERC",
        description="Approves models for use, oversees model validation and monitoring, and decides on "
                    "model limitations and overlays.",
        sponsor="chief.risk.officer", compliance_contact="chief.compliance.officer",
        primary_risk_category="MODEL", owning_operating_group="RISK",
        responsibilities=["DECISION_MAKING"], risk_types=["FIN_MODEL"],
        regulatory=[("REQ_MODEL_RISK", "Model approval and oversight by a designated committee.")],
        links=[("ERC", "Reports To", None)],
        escalation_protocol="Tier-one model failures are escalated to the Executive Risk Committee.",
        escalation_threshold="A tier-one model failing validation or back-testing tolerance.",
        quorum_rule_type="Count", quorum_value=3, quorum_requires_chair=1,
        established=-510, next_review=-35, retention="GOV-FORUM")),
    ("CRC", "CRC", dict(
        forum_name="Credit Risk Committee", forum_type="MGMT_CTTE", cadence="Monthly", parent="ERC",
        description="Approves credit risk policy, sector and concentration limits and large exposures "
                    "within delegated authority.",
        sponsor="chief.risk.officer", compliance_contact="second.line.reviewer",
        primary_risk_category="CREDIT", owning_operating_group="ENTERPRISE", owning_line_of_business="PCB",
        responsibilities=["DECISION_MAKING"], risk_types=["FIN_LIMIT"],
        business_units=["PCB_RETAIL", "PCB_COMMERCIAL"],
        links=[("ERC", "Reports To", None)],
        escalation_protocol="Limit excesses above delegated authority go to the Executive Risk Committee.",
        escalation_threshold="A concentration or single-name limit exceeded by more than 5 per cent.",
        quorum_rule_type="Count", quorum_value=3, quorum_requires_chair=1,
        established=-500, next_review=180, retention="GOV-FORUM")),
    ("ALCO", "ALCO", dict(
        forum_name="Asset-Liability Committee", forum_type="MGMT_CTTE", cadence="Monthly", parent="EXCO",
        description="Manages the balance sheet: liquidity, funding, interest-rate risk in the banking "
                    "book and capital allocation.",
        sponsor="chief.financial.officer", compliance_contact="second.line.reviewer",
        primary_risk_category="LIQUIDITY", owning_operating_group="ENTERPRISE", owning_line_of_business="CAPMKTS",
        responsibilities=["DECISION_MAKING"], business_units=["CM_TREASURY"], legal_entities=["BANK_SUB"],
        regulatory=[("REQ_LIQUIDITY", "Liquidity risk management and the contingency funding plan."),
                    ("REQ_CAPITAL", "Internal capital adequacy assessment.")],
        links=[("EXCO", "Reports To", None), ("ERC", "Informs", "Liquidity and capital metrics.")],
        escalation_protocol="Early-warning indicator breaches go to the Executive Committee the same day.",
        escalation_threshold="Liquidity coverage below the management trigger.",
        quorum_rule_type="Count", quorum_value=3, quorum_requires_chair=1,
        established=-2000, next_review=75, retention="GOV-MINUTES")),
    ("CCC", "CCC", dict(
        forum_name="Conduct and Culture Council", forum_type="COUNCIL", cadence="Quarterly", parent="EXCO",
        description="Coordinates the conduct risk programme, reviews culture indicators and complaint "
                    "trends, and recommends actions to the Executive Committee.",
        sponsor="chief.executive", compliance_contact="second.line.reviewer",
        primary_risk_category="CONDUCT", owning_operating_group="COMPLIANCE",
        responsibilities=["OVERSIGHT"], risk_types=["PEOPLE_CONDUCT"],
        links=[("EXCO", "Reports To", None)],
        escalation_protocol="Recommendations go to the Executive Committee; systemic conduct issues to "
                            "the Executive Risk Committee.",
        escalation_threshold="A complaint trend up more than 25 per cent quarter on quarter.",
        quorum_rule_type="Count", quorum_value=2, quorum_requires_chair=0,
        established=-150, next_review=210, retention="GOV-FORUM")),
    ("LEGACY", "OOF", dict(
        forum_name="Outsourcing Oversight Forum", forum_type="WORKING_GRP", cadence="Quarterly", parent="ORC",
        description="Coordinated oversight of material outsourcing arrangements.",
        sponsor="chief.operating.officer", compliance_contact="second.line.reviewer",
        primary_risk_category="THIRDPARTY", owning_operating_group="RISK",
        responsibilities=["OVERSIGHT"], risk_types=["TP_SERVICE"],
        links=[("ORC", "Reports To", None)],
        escalation_protocol="Issues to the Operational Risk Committee.",
        escalation_threshold="A material outsourcing arrangement rated high risk.",
        quorum_rule_type="Count", quorum_value=2, quorum_requires_chair=0,
        established=-1500, next_review=None, retention="GOV-FORUM")),
    ("TPRWG", "TPRWG", dict(
        forum_name="Third-Party Risk Working Group", forum_type="WORKING_GRP", cadence="Monthly", parent="ORC",
        description="Coordinates third-party risk assessments, exit plans and the register of material "
                    "arrangements for the Operational Risk Committee.",
        sponsor="chief.operating.officer", compliance_contact="second.line.reviewer",
        primary_risk_category="THIRDPARTY", owning_operating_group="RISK",
        responsibilities=["OVERSIGHT"], risk_types=["TP_SERVICE", "TP_CONCENTRATION"],
        regulatory=[("REQ_THIRD_PARTY", "Oversight of material third-party arrangements.")],
        links=[("ORC", "Reports To", "Monthly third-party risk dashboard.")],
        escalation_protocol="Arrangements rated high risk go to the Operational Risk Committee.",
        escalation_threshold="A critical provider missing a service level twice in a quarter.",
        quorum_rule_type="Count", quorum_value=2, quorum_requires_chair=0,
        established=-170, next_review=190, retention="GOV-FORUM")),
]

#: Mandate as rewritten after the first review — the watched-field change that
#: sends the working group back for re-review.
TPRWG_NEW_MANDATE = (
    "Coordinates third-party risk assessments, exit plans and the register of material arrangements, and "
    "now also approves concentration assessments for cloud and critical technology providers."
)
TCRC_NEW_MANDATE = (
    "Oversees technology and cyber risk and, from this year, the operational resilience of critical "
    "operations: impact tolerances, mapping and scenario testing."
)

#: forum key -> seats: (persona or None, role, start, options)
#: options: votes=0 / quorum=0 to override the role default, end=(offset, reason),
#: position="title" for a by-position seat, delegate=(persona, from, to)
MEMBERSHIPS = {
    "BOARD": [
        ("board.chair", "CHAIR", -3650, {}),
        ("chief.executive", "FORUM_OWNER", -3000, {}),
        ("director.risk", "VOTING_MEMBER", -2900, {}),
        ("director.audit", "VOTING_MEMBER", -2900, {}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
        (None, "VOTING_MEMBER", -120, {"position": "Independent Director (vacancy)"}),
    ],
    "BRC": [
        ("director.risk", "CHAIR", -2900, {}),
        ("director.audit", "VOTING_MEMBER", -2900, {}),
        ("board.chair", "VOTING_MEMBER", -2900, {}),
        ("chief.risk.officer", "FORUM_OWNER", -1800, {"votes": 0}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
        ("head.internal.audit", "OBSERVER", -1800, {}),
    ],
    "AC": [
        ("director.audit", "CHAIR", -2900, {}),
        ("director.risk", "VOTING_MEMBER", -2900, {}),
        ("head.internal.audit", "FORUM_OWNER", -1800, {"votes": 0}),
        ("chief.financial.officer", "NON_VOTING_MEMBER", -1800, {}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
    ],
    "EXCO": [
        ("chief.executive", "CHAIR", -2500, {}),
        ("chief.operating.officer", "FORUM_OWNER", -2000, {}),
        ("chief.risk.officer", "VOTING_MEMBER", -1800, {}),
        ("chief.financial.officer", "VOTING_MEMBER", -1800, {}),
        ("chief.information.officer", "VOTING_MEMBER", -1400, {}),
        ("general.counsel", "VOTING_MEMBER", -1400, {}),
        ("chief.compliance.officer", "VOTING_MEMBER", -1400, {}),
        ("head.retail.banking", "VOTING_MEMBER", -900, {}),
        ("treasurer", "VOTING_MEMBER", GO_LIVE, {"end": (-250, "Role Change")}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
    ],
    "ERC": [
        ("chief.risk.officer", "CHAIR", -1800, {}),
        ("head.operational.risk", "FORUM_OWNER", -1200, {}),
        ("chief.financial.officer", "VOTING_MEMBER", -1800, {}),
        ("chief.operating.officer", "VOTING_MEMBER", -1800, {"delegate": ("head.retail.banking", -93, -87)}),
        ("chief.information.officer", "VOTING_MEMBER", -1400, {}),
        ("chief.compliance.officer", "VOTING_MEMBER", -1400, {}),
        ("general.counsel", "VOTING_MEMBER", -1400, {}),
        ("treasurer", "VOTING_MEMBER", -900, {}),
        ("head.model.risk", "RISK_OWNER", -900, {}),
        ("head.technology.risk", "RISK_OWNER", -900, {}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
        ("head.internal.audit", "OBSERVER", -900, {}),
    ],
    "ORC": [
        ("head.operational.risk", "CHAIR", -540, {}),
        ("chief.operating.officer", "FORUM_OWNER", -540, {}),
        ("head.technology.risk", "VOTING_MEMBER", -540, {}),
        ("chief.information.officer", "VOTING_MEMBER", -540, {}),
        ("head.retail.banking", "VOTING_MEMBER", -540, {}),
        ("chief.compliance.officer", "VOTING_MEMBER", -540, {}),
        ("head.model.risk", "VOTING_MEMBER", -540, {"end": (-210, "Role Change")}),
        ("second.line.reviewer", "NON_VOTING_MEMBER", -200, {}),
        ("committee.secretary", "SECRETARY", -540, {"votes": 0, "quorum": 0}),
        (None, "RISK_OWNER", -60, {"position": "Head of Business Continuity"}),
    ],
    "TCRC": [
        ("chief.information.officer", "CHAIR", -520, {}),
        ("head.technology.risk", "FORUM_OWNER", -520, {}),
        ("chief.operating.officer", "VOTING_MEMBER", -520, {}),
        ("head.operational.risk", "VOTING_MEMBER", -520, {}),
        ("second.line.reviewer", "NON_VOTING_MEMBER", -520, {}),
        ("committee.secretary", "SECRETARY", -520, {"votes": 0, "quorum": 0}),
    ],
    "MRC": [
        ("head.model.risk", "CHAIR", -210, {}),
        ("chief.risk.officer", "CHAIR", -510, {"end": (-211, "Role Change")}),
        ("chief.financial.officer", "FORUM_OWNER", -510, {}),
        ("treasurer", "VOTING_MEMBER", -510, {}),
        ("head.retail.banking", "VOTING_MEMBER", -510, {}),
        ("second.line.reviewer", "NON_VOTING_MEMBER", -510, {}),
        ("risk.governance.analyst", "SECRETARY", -510, {"votes": 0, "quorum": 0}),
    ],
    "CRC": [
        ("chief.risk.officer", "CHAIR", -500, {}),
        ("head.retail.banking", "FORUM_OWNER", -500, {}),
        ("chief.financial.officer", "VOTING_MEMBER", -500, {}),
        ("treasurer", "VOTING_MEMBER", -500, {}),
        ("head.model.risk", "VOTING_MEMBER", -500, {}),
        ("committee.secretary", "SECRETARY", -500, {"votes": 0, "quorum": 0}),
    ],
    "ALCO": [
        ("chief.financial.officer", "CHAIR", -2000, {}),
        ("treasurer", "FORUM_OWNER", -900, {}),
        ("chief.risk.officer", "VOTING_MEMBER", -1800, {}),
        ("head.retail.banking", "VOTING_MEMBER", -900, {}),
        ("chief.executive", "VOTING_MEMBER", -2000, {}),
        ("risk.governance.analyst", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
    ],
    "CCC": [
        ("chief.compliance.officer", "CHAIR", -150, {}),
        ("general.counsel", "FORUM_OWNER", -150, {}),
        ("head.retail.banking", "VOTING_MEMBER", -150, {}),
        ("chief.operating.officer", "VOTING_MEMBER", -150, {}),
        ("committee.secretary", "SECRETARY", -150, {"votes": 0, "quorum": 0}),
    ],
    "LEGACY": [
        ("chief.operating.officer", "CHAIR", -1500, {}),
        ("head.operational.risk", "FORUM_OWNER", -1500, {}),
        ("head.technology.risk", "VOTING_MEMBER", -1500, {}),
        ("committee.secretary", "SECRETARY", GO_LIVE, {"votes": 0, "quorum": 0}),
    ],
    "TPRWG": [
        ("chief.operating.officer", "CHAIR", -170, {}),
        ("head.operational.risk", "FORUM_OWNER", -170, {}),
        ("head.technology.risk", "VOTING_MEMBER", -170, {}),
        ("chief.information.officer", "VOTING_MEMBER", -170, {}),
        ("risk.governance.analyst", "SECRETARY", -170, {"votes": 0, "quorum": 0}),
    ],
}


FORUM_SPECS = {key: (abbr, spec) for key, abbr, spec in FORUMS}

#: The forum the formation section creates. Not in FORUMS: it comes into being
#: only by approving its formation request.
DGC_NAME = "Data Governance Council"


def forum_of(ctx: Ctx, key: str) -> str | None:
    """The record name of a demo forum, by its key."""
    if key == "DGC":
        return forum_by_name(ctx.frappe, DGC_NAME)
    abbr, spec = FORUM_SPECS[key]
    return forum_by_name(ctx.frappe, spec["forum_name"])


def abbr_of(key: str) -> str:
    return "DGC" if key == "DGC" else FORUM_SPECS[key][0]


def _forum_values(ctx: Ctx, spec: dict) -> dict:
    values = {
        "description": spec["description"],
        "sponsor": U(spec.get("sponsor")),
        "compliance_contact": U(spec.get("compliance_contact")),
        "governance_responsibilities": [
            {"governance_responsibility": r} for r in spec.get("responsibilities", [])
        ],
        "risk_types": [{"risk_type": r} for r in spec.get("risk_types", [])],
        "business_units": [{"business_unit": b} for b in spec.get("business_units", [])],
        "legal_entities": [{"legal_entity": e} for e in spec.get("legal_entities", [])],
        "jurisdictions": [{"jurisdiction": j} for j in spec.get("jurisdictions", [])],
        "regulatory_required": 1 if spec.get("regulatory") else 0,
        "regulatory_requirements": [
            {"regulatory_requirement": code, "obligation_summary": summary, "jurisdiction": "NATIONAL"}
            for code, summary in spec.get("regulatory", [])
        ],
        "parent_forum": forum_of(ctx, spec["parent"]) if spec.get("parent") else None,
        "upstream_links": [
            {"linked_forum": forum_of(ctx, target), "relationship_type": kind, "notes": notes}
            for target, kind, notes in spec.get("links", [])
        ],
        "escalation_protocol": spec.get("escalation_protocol"),
        "escalation_threshold": spec.get("escalation_threshold"),
        "quorum_requires_chair": spec.get("quorum_requires_chair", 0),
        "established_on": ctx.d(spec.get("established")),
        "next_review_on": ctx.d(spec.get("next_review")),
        "retention_class": spec.get("retention"),
    }
    for field in ("forum_name", "forum_type", "cadence", "primary_risk_category",
                  "owning_operating_group", "owning_line_of_business", "quorum_rule_type", "quorum_value"):
        if field in spec:
            values[field] = spec[field]
    return values


#: Entries in the enterprise risk register that forums oversee and matters cite.
RISK_REGISTER = {
    "ERC": [("ERR-001", "Enterprise risk profile against appetite", "STRATEGIC"),
            ("ERR-014", "Concentration in commercial real estate lending", "CREDIT")],
    "ORC": [("ERR-021", "Failure of a critical third-party service", "THIRDPARTY"),
            ("ERR-022", "Change-induced outage of core platforms", "TECHNOLOGY")],
}


def _risk_references(ctx: Ctx, key: str, forum: str) -> list[dict]:
    rows = []
    for external_key, label, category in RISK_REGISTER.get(key, []):
        name, _created = ensure(ctx, "External Reference", {
            "external_system": "RISK_REGISTER", "external_key": external_key,
            "subject_doctype": "Governance Forum", "subject_name": forum,
        }, {
            "subject_doctype": "Governance Forum", "subject_name": forum,
            "external_system": "RISK_REGISTER", "external_key": external_key,
            "external_type": "Enterprise risk", "label": label, "last_seen_on": ctx.d(-3),
        }, by=U("risk.governance.analyst"), when=ctx.ts(-300))
        rows.append({"external_reference": name, "risk_category": category,
                     "assessment_summary": label, "linked_on": ctx.d(-300)})
    return rows


def section_forums(ctx: Ctx) -> None:
    """The forum tree, created top-down so parents and link targets exist."""
    frappe = ctx.frappe
    by = U("risk.governance.lead")
    for key, abbr, spec in FORUMS:
        existing = forum_of(ctx, key)
        if existing and spec.get("reuse_existing"):
            _update_existing_orc(ctx, key, spec, existing)
            continue
        if existing:
            ctx.had("Governance Forum")
            continue
        doc = frappe.get_doc({"doctype": "Governance Forum", **_forum_values(ctx, spec)})
        doc.insert(ignore_permissions=True)
        ctx.made("Governance Forum")
        if key in RISK_REGISTER:
            for row in _risk_references(ctx, key, doc.name):
                doc.append("risk_references", row)
            doc.save(ignore_permissions=True)
        created = max(spec.get("established") or GO_LIVE, GO_LIVE)
        ctx.stamp("Governance Forum", doc.name, ctx.ts(created, "09:15"), by)


def _update_existing_orc(ctx: Ctx, key: str, spec: dict, name: str) -> None:
    """Fill in an operational risk committee that already exists.

    Only once: the parent link is the marker, so on a second run — and for the
    committee this script itself created on a fresh site — nothing changes.
    Changing its mandate and parent are watched fields, so the save sends the
    draft forum to Pending and raises a re-review ToDo — the compliance review
    section then clears it.
    """
    frappe = ctx.frappe
    doc = frappe.get_doc("Governance Forum", name)
    if doc.parent_forum:
        ctx.had("Governance Forum")
        return
    values = _forum_values(ctx, spec)
    for field in ("forum_name", "forum_type", "cadence", "primary_risk_category",
                  "owning_operating_group", "quorum_rule_type", "quorum_value"):
        values.pop(field, None)
    doc.update(values)
    for row in _risk_references(ctx, key, doc.name):
        doc.append("risk_references", row)
    doc.save(ignore_permissions=True)
    ctx.notes.append(f"{doc.name} (existing) filled in; its owner is left as it was.")


def section_memberships(ctx: Ctx) -> None:
    """Dated seats: chairs, secretaries, owners, voters, a vacancy, ended seats, a delegate."""
    frappe = ctx.frappe
    for key, seats in MEMBERSHIPS.items():
        forum = forum_of(ctx, key)
        if not forum:
            raise RuntimeError(f"forum {key} is missing; run the forums section first")
        _seat_forum(ctx, forum, seats)


def _seat_forum(ctx: Ctx, forum: str, seats: list) -> None:
    frappe = ctx.frappe
    for persona, role, start, opts in seats:
        key = {"forum": forum, "forum_role": role, "start_date": ctx.d(start)}
        if opts.get("position"):
            key["position_title"] = opts["position"]
        else:
            key["member"] = U(persona)
        if find(frappe, "Forum Membership", key):
            ctx.had("Forum Membership")
            continue
        values = {
            "doctype": "Forum Membership",
            "forum": forum,
            "seat_type": "Position" if opts.get("position") else "Person",
            "member": U(persona),
            "position_title": opts.get("position"),
            "forum_role": role,
            "start_date": ctx.d(start),
            "appointed_by": U("risk.governance.lead"),
        }
        if opts.get("end"):
            end, reason = opts["end"]
            values.update(end_date=ctx.d(end), end_reason=reason)
        if opts.get("delegate"):
            delegate, frm, to = opts["delegate"]
            values.update(delegate=U(delegate), delegate_from=str(ctx.weekday(frm)),
                          delegate_to=str(ctx.weekday(to)), delegate_votes=1,
                          notes="Standing delegate while the member is on leave.")
        if opts.get("position"):
            values["notes"] = "Seat held by position; vacant pending appointment."
        doc = frappe.get_doc(values).insert(ignore_permissions=True)
        if "votes" in opts or "quorum" in opts:
            # A role's defaults are applied on insert and a zero is read as
            # "not given", so a non-voting secretary is set by an ordinary edit.
            doc.reload()
            doc.votes = opts.get("votes", doc.votes)
            doc.counts_toward_quorum = opts.get("quorum", doc.counts_toward_quorum)
            doc.save(ignore_permissions=True)
        ctx.made("Forum Membership")
        ctx.stamp("Forum Membership", doc.name, ctx.ts(max(start, GO_LIVE), "08:45"),
                  U("committee.secretary"))


# ================================================================ glossary

GLOSSARY = [
    # term, definition, synonyms, enforce, action, days
    ("Risk Appetite", "The aggregate level and types of risk the group is willing to accept, within its "
     "risk capacity, to achieve its strategic objectives.", ["Appetite"], 1, "publish", -500),
    ("Risk Tolerance", "The acceptable variation around a risk appetite measure before escalation is "
     "required.", [], 0, "publish", -500),
    ("Key Risk Indicator", "A metric that signals a change in the likelihood or impact of a risk, with "
     "thresholds that trigger escalation.", ["KRI"], 1, "publish", -480),
    ("Three Lines of Defence", "The model under which the first line owns and manages risk, the second line "
     "oversees and challenges, and the third line provides independent assurance.",
     ["Three Lines Model", "3LOD"], 1, "publish", -480),
    ("Effective Challenge", "Critical, informed and independent questioning of a first-line assessment by "
     "people with the competence and authority to change it.", [], 0, "publish", -460),
    ("Critical Operation", "An operation whose disruption could threaten the group's viability, its "
     "customers or the stability of the financial system.", ["Critical Business Service"], 1, "publish", -300),
    ("Impact Tolerance", "The maximum tolerable disruption to a critical operation, expressed as a "
     "duration.", [], 1, "supersede", -300),
    ("Material Third-Party Arrangement", "An arrangement with a third party whose failure would materially "
     "affect the group's operations, customers, finances or compliance.",
     ["Material Outsourcing Arrangement"], 1, "publish", -280),
    ("Model", "A quantitative method that applies statistical, economic or mathematical theory to "
     "transform input data into estimates used in decisions.", [], 0, "publish", -260),
    ("Politically Exposed Person", "An individual entrusted with a prominent public function, and their "
     "family members and close associates.", ["PEP"], 1, "publish", -240),
    ("Operational Resilience", "The ability to deliver critical operations through disruption: to prevent, "
     "adapt, respond, recover and learn.", [], 0, "propose", -20),
]

#: The second definition Impact Tolerance was superseded with.
IMPACT_TOLERANCE_V2 = (
    "The maximum tolerable disruption to a critical operation, expressed as a duration and, where "
    "relevant, a volume of affected customers or transactions, beyond which the group's viability or "
    "customers would be harmed."
)

#: A term scoped to a single document; created after the library exists.
SCOPED_TERM = ("Emergency Change", "A change deployed outside the standard approval cycle to restore "
               "service or close a critical vulnerability, approved retrospectively within two business "
               "days.", "CHANGE")


# =========================================================== policy library
#
# key -> spec. ``target`` is the phase the lifecycle is driven to, always
# through configured workflow actions and their gates; ``approvals`` (for a
# document still in review) is how many routed steps are already decided.

BODY = (
    "<h3>{name}</h3><p><strong>Purpose.</strong> {abstract}</p>"
    "<p><strong>Scope.</strong> Applies across the group unless an authorised exemption says otherwise.</p>"
    "<p><strong>Requirements.</strong> See the numbered statements in the approved rendition.</p>"
)

DOCUMENTS = [
    ("ERM", dict(
        document_name="Enterprise Risk Management Framework", document_type="FRAMEWORK", target="Implemented",
        document_abstract="Sets the principles, risk taxonomy, three-lines accountabilities and governance "
                          "structure within which every risk policy of the group sits.",
        owner="chief.risk.officer", approver="chief.executive", sponsor="board.chair",
        liaison="risk.governance.lead", key_contact="head.operational.risk",
        group="RISK", lod="2LOD", category="STRATEGIC",
        risk_types=["FINANCIAL", "PROCESS", "REGULATORY", "TECHNOLOGY", "THIRD_PARTY", "PEOPLE"],
        legal_entities=["PARENT", "BANK_SUB", "DEALER_SUB", "INSURANCE_SUB"], jurisdictions=["NATIONAL"],
        forum="BRC", regulatory=[("REQ_CORP_GOV", "Section 4", "A board-approved risk management framework.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Risk Management Function")],
        effective=-420, review_months=24, next_review=310, created=-520, retention="POL-DOCUMENT",
        glossary=["Risk Appetite", "Three Lines of Defence", "Effective Challenge"],
        versions=[("1.0", "Framework re-issued on the platform at go-live.", -520),
                  ("2.0", "Annual refresh: risk taxonomy aligned to the new tier-two risk types.", -440)])),
    ("RAF", dict(
        document_name="Risk Appetite Framework", document_type="FRAMEWORK", target="Published",
        document_abstract="Defines how risk appetite is set, cascaded into limits and key risk indicators, "
                          "monitored and escalated when breached.",
        owner="chief.risk.officer", approver="chief.executive", sponsor="board.chair",
        liaison="risk.governance.lead", group="RISK", lod="2LOD", category="STRATEGIC", parent="ERM",
        risk_types=["FINANCIAL", "REGULATORY"], forum="BOARD",
        applicability=[("Role", "Forum Owner", None, None), ("Organization Unit", "ENTERPRISE", None, None)],
        effective=-60, review_months=12, next_review=300, created=-150, retention="POL-DOCUMENT",
        glossary=["Risk Appetite", "Risk Tolerance", "Key Risk Indicator"],
        versions=[("3.0", "Refreshed appetite statements and new concentration metrics.", -120)])),
    ("ORM", dict(
        document_name="Operational Risk Management Policy", document_type="POLICY", target="Implemented",
        document_abstract="Requirements for identifying, assessing, monitoring and reporting operational "
                          "risk, including loss-event capture and risk and control self-assessment.",
        owner="head.operational.risk", approver="chief.risk.officer", sponsor="chief.operating.officer",
        liaison="policy.office.lead", group="RISK", lod="2LOD", category="OPERATIONAL", parent="ERM",
        risk_types=["PROCESS", "TECHNOLOGY", "THIRD_PARTY"], forum="ORC",
        applicability=[("Organization Unit", "ENTERPRISE", None, "Risk Management Function"),
                       ("Role", "Policy Owner", None, None)],
        effective=-380, review_months=12, next_review=-15, created=-470, retention="POL-DOCUMENT",
        glossary=["Key Risk Indicator", "Three Lines of Defence"],
        versions=[("4.0", "Loss-event thresholds lowered; near-miss reporting made mandatory.", -420)])),
    ("INFOSEC", dict(
        document_name="Information Security Policy", document_type="POLICY", target="Implemented",
        reopen=("5.0-draft", "Redraft for the technology and cyber guideline update: identity, cloud and "
                             "third-party access controls.", -12),
        document_abstract="Mandatory controls protecting the confidentiality, integrity and availability of "
                          "information and systems.",
        owner="chief.information.officer", approver="chief.risk.officer", sponsor="chief.operating.officer",
        liaison="head.technology.risk", delegate="head.technology.risk", group="TECH", lod="1LOD",
        category="CYBER", risk_types=["TECH_CYBER"], forum="TCRC", confidential=0,
        regulatory=[("REQ_TECH_CYBER", "Section 3", "Information security controls proportionate to risk.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Technology and Operations Leadership")],
        effective=-330, review_months=12, next_review=35, created=-400, retention="POL-DOCUMENT",
        versions=[("4.0", "Annual review; multi-factor authentication extended to all remote access.", -360)])),
    ("TPRM", dict(
        document_name="Outsourcing and Third-Party Risk Policy", document_type="POLICY", target="Review",
        approvals=1,
        document_abstract="Risk-based management of third-party arrangements from due diligence to exit, "
                          "including concentration risk and the register of material arrangements.",
        owner="chief.operating.officer", approver="chief.risk.officer", sponsor="chief.executive",
        liaison="policy.office.lead", group="RISK", lod="1LOD", category="THIRDPARTY", parent="ORM",
        risk_types=["TP_SERVICE", "TP_CONCENTRATION"], forum="ORC", material=["ME_BANK", "ME_DEALER"],
        regulatory=[("REQ_THIRD_PARTY", "Sections 2-6", "Lifecycle management of third-party arrangements.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Risk Management Function")],
        effective=30, review_months=12, created=-45, retention="POL-DOCUMENT",
        glossary=["Material Third-Party Arrangement"],
        versions=[("1.0-consultation", "Consultation draft replacing the vendor management standard.", -45),
                  ("1.0", "Consultation comments addressed; exit-plan requirements added.", -20)])),
    ("MRM", dict(
        document_name="Model Risk Management Policy", document_type="POLICY", target="Approved",
        intake="INT-MRM",
        document_abstract="Model inventory, risk tiering, independent validation, ongoing monitoring and the "
                          "approval of models, overlays and limitations.",
        owner="head.model.risk", approver="chief.risk.officer", sponsor="chief.financial.officer",
        liaison="policy.office.lead", group="RISK", lod="2LOD", category="MODEL", parent="ERM",
        risk_types=["FIN_MODEL"], forum="MRC",
        regulatory=[("REQ_MODEL_RISK", "Sections 1-5", "Enterprise model risk management.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Risk Management Function")],
        effective=20, review_months=12, created=-80, retention="POL-DOCUMENT", glossary=["Model"],
        versions=[("1.0", "First issue as a policy; replaces the model validation standard.", -70)])),
    ("BCM", dict(
        document_name="Business Continuity and Operational Resilience Standard", document_type="STANDARD",
        target="Published",
        document_abstract="Minimum requirements for business impact analysis, impact tolerances, recovery "
                          "planning and annual scenario testing of critical operations.",
        owner="chief.operating.officer", approver="head.operational.risk", sponsor="chief.risk.officer",
        liaison="policy.office.lead", group="RISK", lod="1LOD", category="OPERATIONAL", parent="ORM",
        risk_types=["TECH_OUTAGE", "TP_SERVICE"], forum="ORC", material=["ME_BANK"],
        regulatory=[("REQ_OP_RESILIENCE", "Sections 2-4", "Critical operations, tolerances and testing.")],
        applicability=[("Organization Unit", "PCB", None, "Business Line Leadership"),
                       ("Organization Unit", "TECH", None, "Technology and Operations Leadership")],
        effective=-100, review_months=12, next_review=265, created=-190, retention="POL-DOCUMENT",
        glossary=["Critical Operation", "Impact Tolerance"],
        versions=[("2.0", "Impact tolerances set for all critical operations.", -160)])),
    ("RECORDS", dict(
        document_name="Records Management and Retention Standard", document_type="STANDARD",
        target="Implemented",
        document_abstract="Classification, retention, legal hold and disposition of records in every medium.",
        owner="records.manager", approver="general.counsel", sponsor="chief.operating.officer",
        liaison="policy.office.lead", group="COMPLIANCE", lod="1LOD", category="COMPLIANCE",
        risk_types=["REG_DATA"], forum="ORC",
        regulatory=[("REQ_RECORDS", "Schedule 1", "Minimum retention periods.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Compliance Function")],
        effective=-300, review_months=24, next_review=430, created=-360, retention="POL-DOCUMENT",
        versions=[("3.0", "Retention schedule aligned to the platform's retention classes.", -340)])),
    ("CODE", dict(
        document_name="Code of Conduct Policy", document_type="POLICY", target="Implemented",
        document_abstract="The standards of behaviour expected of every employee and director, including "
                          "conflicts of interest, gifts and entertainment and speaking up.",
        owner="chief.compliance.officer", approver="chief.executive", sponsor="board.chair",
        liaison="policy.office.lead", group="COMPLIANCE", lod="2LOD", category="CONDUCT", training=1,
        risk_types=["PEOPLE_CONDUCT"], forum="CCC",
        regulatory=[("REQ_CONDUCT", "Part 2", "Standards of conduct and fair treatment of customers.")],
        applicability=[("Organization Unit", "ENTERPRISE", None, None), ("Role", "Policy Owner", None, None)],
        effective=-400, review_months=12, next_review=-35, created=-450, retention="POL-DOCUMENT",
        versions=[("7.0", "Speak-up channels and non-retaliation strengthened.", -430)])),
    ("AML", dict(
        document_name="Anti-Money Laundering Policy", document_type="POLICY", target="Published",
        document_abstract="Customer due diligence, enhanced due diligence, transaction monitoring, suspicious "
                          "transaction reporting and record keeping.",
        owner="chief.compliance.officer", approver="general.counsel", sponsor="chief.executive",
        liaison="policy.office.lead", group="COMPLIANCE", lod="2LOD", category="FINCRIME",
        risk_types=["REGULATORY"], forum="ERC", material=["ME_BANK", "ME_DEALER"],
        handling="Confidential", confidential=1,
        regulatory=[("REQ_AML", "Parts 1-4", "An anti-money laundering compliance programme.")],
        applicability=[("Organization Unit", "PCB", None, "Business Line Leadership"),
                       ("Organization Unit", "WEALTH", None, None),
                       ("Legal Entity", "INTL_BRANCH", None, None)],
        effective=-200, review_months=12, next_review=165, created=-260, retention="POL-DOCUMENT",
        glossary=["Politically Exposed Person"],
        versions=[("9.0", "Enhanced due diligence triggers extended to high-risk jurisdictions.", -230)])),
    ("PRIVACY", dict(
        document_name="Customer Data Privacy Procedure", document_type="PROCEDURE", target="Review",
        intake="INT-PRIV", approvals=0,
        document_abstract="Steps for handling customer personal information: collection, consent, access "
                          "requests, correction and breach response.",
        owner="head.retail.banking", approver="chief.compliance.officer", sponsor="chief.operating.officer",
        liaison="policy.office.lead", group="ENTERPRISE", lob="PCB", business_units=["PCB_RETAIL", "PCB_CARDS"],
        lod="1LOD", category="DATA", parent="RECORDS", risk_types=["REG_DATA"],
        regulatory=[("REQ_PRIVACY", "Sections 5-10", "Safeguarding and breach notification.")],
        applicability=[("Organization Unit", "PCB", None, "Business Line Leadership")],
        effective=45, review_months=12, created=-30, retention="POL-DOCUMENT",
        versions=[("1.0", "First issue, following the misdirected-correspondence incident.", -28)])),
    ("CHANGE", dict(
        document_name="Change Management Procedure", document_type="PROCEDURE", target="Implemented",
        document_abstract="How changes to production systems are assessed, approved by the change advisory "
                          "board, implemented and reviewed, including emergency changes.",
        owner="chief.information.officer", approver="head.technology.risk", sponsor="chief.operating.officer",
        liaison="policy.office.lead", group="TECH", lod="1LOD", category="TECHNOLOGY", parent="ORM",
        risk_types=["PROCESS_CHANGE", "TECH_OUTAGE"], forum="TCRC",
        applicability=[("Organization Unit", "TECH", None, "Technology and Operations Leadership")],
        effective=-250, review_months=12, next_review=115, created=-300, retention="POL-DOCUMENT",
        versions=[("2.0", "Emergency change path and retrospective approval defined.", -280)])),
    ("VENDOR", dict(
        document_name="Vendor Management Standard", document_type="STANDARD", target="Retired",
        superseded_by="TPRM", retire_after=["ONBOARD"],
        document_abstract="Minimum requirements for selecting, contracting and monitoring vendors. "
                          "Superseded by the outsourcing and third-party risk policy.",
        owner="chief.operating.officer", approver="head.operational.risk", sponsor="chief.risk.officer",
        liaison="policy.office.lead", group="RISK", lod="1LOD", category="THIRDPARTY",
        risk_types=["TP_SERVICE"], forum="ORC",
        applicability=[("Organization Unit", "ENTERPRISE", None, None)],
        effective=-1400, review_months=24, created=-540, retention="POL-DOCUMENT",
        versions=[("3.2", "Migrated to the platform at go-live.", -540)])),
    ("ONBOARD", dict(
        document_name="Supplier Onboarding Procedure", document_type="PROCEDURE", target="Published",
        document_abstract="Steps to onboard a new supplier: due diligence, risk rating, contract checks and "
                          "register entry.",
        owner="head.operational.risk", approver="chief.operating.officer", sponsor="chief.operating.officer",
        liaison="policy.office.lead", group="RISK", lod="1LOD", category="THIRDPARTY", parent="VENDOR",
        risk_types=["TP_SERVICE"],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Risk Management Function")],
        effective=-500, review_months=12, next_review=-140, created=-530, retention="POL-DOCUMENT",
        versions=[("1.4", "Migrated to the platform at go-live.", -530)])),
    ("AIUSE", dict(
        document_name="Artificial Intelligence Use Standard", document_type="STANDARD", target="Draft",
        intake="INT-AI",
        document_abstract="Requirements for the approved use of artificial intelligence: use-case "
                          "registration, risk tiering, human oversight, data protection and monitoring.",
        owner="head.technology.risk", approver="chief.risk.officer", sponsor="chief.information.officer",
        liaison="policy.office.lead", group="TECH", lod="2LOD", category="TECHNOLOGY",
        risk_types=["TECH_CYBER", "FIN_MODEL"],
        applicability=[("Organization Unit", "ENTERPRISE", None, "Technology and Operations Leadership")],
        effective=90, review_months=12, created=-15, retention="POL-DOCUMENT",
        versions=[("0.1", "Working draft for the technology risk working session.", -10)])),
]

DOC_SPECS = dict(DOCUMENTS)

#: Order the lifecycle phases are driven through. Configuration names the
#: actions; this is only the order the demo walks them.
PHASE_ORDER = ["Draft", "Review", "Approved", "Published", "Implemented"]

INTAKES = [
    # key, type, subject doc, proposed type, proposed name, requester, justification, effective, parties,
    # category, answers (None = not yet classified), fulfils (doc key), created
    ("INT-MRM", "Create", None, "POLICY", "Model Risk Management Policy", "head.model.risk",
     "The model validation standard no longer covers the model inventory, tiering and use of overlays that "
     "the model risk guideline expects; a policy is needed.", 20,
     ["chief.risk.officer", "policy.office.lead"], "MODEL",
     {"q_scope": "enterprise", "q_obligation": "yes", "q_control": "yes"}, "MRM", -90),
    ("INT-PRIV", "Create", None, "PROCEDURE", "Customer Data Privacy Procedure", "head.retail.banking",
     "Branch and contact-centre staff need step-by-step handling of customer personal information after "
     "the misdirected-correspondence incident.", 45, ["chief.compliance.officer"], "DATA",
     {"q_scope": "local", "q_obligation": "no", "q_control": "no"}, "PRIVACY", -32),
    ("INT-AI", "Create", None, "STANDARD", "Artificial Intelligence Use Standard", "head.technology.risk",
     "Business lines are piloting generative tools with no standard governing their approval or use.", 90,
     ["chief.information.officer", "chief.compliance.officer", "general.counsel"], "TECHNOLOGY",
     {"q_scope": "enterprise", "q_obligation": "no", "q_control": "yes"}, "AIUSE", -18),
    ("INT-AML-CHG", "Change", "AML", None, None, "chief.compliance.officer",
     "Update the enhanced due diligence refresh cycle following the internal audit finding.", 60,
     ["general.counsel"], "FINCRIME", {"q_scope": "local", "q_obligation": "no", "q_control": "no"}, None, -8),
    ("INT-CLIMATE", "Create", None, "STANDARD", "Climate Risk Management Standard", "chief.risk.officer",
     "Supervisory expectations on climate risk require a standard for scenario analysis and disclosure.",
     180, ["chief.financial.officer"], "CLIMATE", None, None, -3),
    ("INT-ONBOARD-RET", "Retire", "ONBOARD", None, None, "head.operational.risk",
     "The supplier onboarding procedure sits under a retired standard; its steps move into the "
     "third-party policy's procedures.", 60, ["policy.office.lead"], "THIRDPARTY", None, None, -6),
]

#: Documents other engineers are working with on the development site; never
#: matched, never touched. Only where they exist and are not the demo's own: on
#: a fresh site these names are the first documents the demo itself creates.
PROTECTED_DOCUMENTS = ["GDOC-00001", "GDOC-00002"]


def _protected_documents(ctx: Ctx) -> list[str]:
    """The protected names that belong to someone else, worked out once per run,
    before this run has created anything."""
    if ctx.protected_documents is None:
        ctx.protected_documents = [
            name for name in PROTECTED_DOCUMENTS
            if (owner := ctx.frappe.db.get_value("Governing Document", name, "owner"))
            and not owner.endswith(f"@{DOMAIN}")
        ] or [""]
    return ctx.protected_documents


def doc_of(ctx: Ctx, key: str) -> str | None:
    return find(ctx.frappe, "Governing Document", {
        "document_name": DOC_SPECS[key]["document_name"], "name": ["not in", _protected_documents(ctx)],
    })


def term_of(ctx: Ctx, term: str) -> str | None:
    return find(ctx.frappe, "Glossary Term", {"term": term, "scope_level": "Enterprise"})


def section_glossary(ctx: Ctx) -> None:
    """Enterprise terms, put in force through the glossary's own publish, one superseded."""
    frappe = ctx.frappe
    from consilium.policy import glossary

    epo = U("policy.office.lead")
    for term, definition, synonyms, enforce, action, days in GLOSSARY:
        if term_of(ctx, term):
            ctx.had("Glossary Term")
            continue
        doc = frappe.get_doc({
            "doctype": "Glossary Term", "term": term, "definition": definition, "scope_level": "Enterprise",
            "term_status": "Proposed", "enforce_usage": enforce,
            "synonyms": [{"synonym": s} for s in synonyms],
        }).insert(ignore_permissions=True)
        ctx.made("Glossary Term")
        last = days
        if action in ("publish", "supersede"):
            glossary.publish(doc.name, approved_by=epo, change_summary="Definition agreed by the Enterprise "
                                                                       "Policy Office and put in force.")
            _stamp_versions(ctx, "Glossary Term", doc.name, [days + 2])
            ctx.stamp("Glossary Term", doc.name, None, None, approved_on=ctx.d(days + 2))
            last = days + 2
        if action == "supersede":
            glossary.supersede(doc.name, IMPACT_TOLERANCE_V2, approved_by=epo,
                               change_summary="Extended to volume-based tolerances after the resilience "
                                              "guideline update.")
            _stamp_versions(ctx, "Glossary Term", doc.name, [days + 2, -90])
            ctx.stamp("Glossary Term", doc.name, None, None, approved_on=ctx.d(-90))
            last = -90
        ctx.stamp("Glossary Term", doc.name, ctx.ts(days, "14:00"), epo)
        ctx.stamp("Glossary Term", doc.name, None, None, modified=ctx.ts(last, "15:00"))


def _stamp_versions(ctx: Ctx, doctype: str, name: str, days: list[int], by: str | None = None) -> None:
    """Back-date a subject's version chain, oldest first, to the given days."""
    rows = ctx.frappe.get_all("Document Version", filters={"subject_doctype": doctype, "subject_name": name},
                              pluck="name", order_by="version_number asc")
    for version, day in zip(rows, days, strict=False):
        ctx.stamp("Document Version", version, ctx.ts(day, "16:00"), by)


def _document_values(ctx: Ctx, spec: dict) -> dict:
    terms = [term_of(ctx, t) for t in spec.get("glossary", [])]
    roles = [
        {"role": "DOC_OWNER", "user": U(spec["owner"]), "is_primary": 1, "from_date": ctx.d(spec["created"])},
        {"role": "DOC_APPROVER", "user": U(spec["approver"]), "from_date": ctx.d(spec["created"])},
        {"role": "MONITOR", "user": U("second.line.reviewer"), "from_date": ctx.d(spec["created"])},
        {"role": "PARTNER", "user_group": "Compliance Function"},
    ]
    return {
        "document_name": spec["document_name"],
        "document_type": spec["document_type"],
        "document_abstract": spec["document_abstract"],
        "document_owner": U(spec["owner"]),
        "document_approver": U(spec["approver"]),
        "document_sponsor": U(spec.get("sponsor")),
        "document_liaison": U(spec.get("liaison")),
        "document_delegate": U(spec.get("delegate")),
        "key_contact": U(spec.get("key_contact")),
        "accountability_roles": roles,
        "owning_operating_group": spec["group"],
        "owning_line_of_business": spec.get("lob"),
        "owning_business_units": [{"organization_unit": b} for b in spec.get("business_units", [])],
        "legal_entities": [{"legal_entity": e} for e in spec.get("legal_entities", [])],
        "jurisdictions": [{"jurisdiction": j} for j in spec.get("jurisdictions", ["NATIONAL"])],
        "line_of_defence": spec.get("lod"),
        "primary_risk_category": spec["category"],
        "risk_types": [{"risk_type": r} for r in spec.get("risk_types", [])],
        "material_entity_impact": 1 if spec.get("material") else 0,
        "material_entities": [{"material_entity": m} for m in spec.get("material", [])],
        "parent_document": doc_of(ctx, spec["parent"]) if spec.get("parent") else None,
        "approving_forum": forum_of(ctx, spec["forum"]) if spec.get("forum") else None,
        "applicability": [
            {"scope_type": kind, "scope_value": value, "scope_label": label, "notification_group": group}
            for kind, value, label, group in spec.get("applicability", [])
        ],
        "regulatory_required": 1 if spec.get("regulatory") else 0,
        "regulatory_references": [
            {"regulatory_requirement": code, "citation": citation, "jurisdiction": "NATIONAL",
             "obligation_summary": obligation, "last_verified_on": ctx.d(-30)}
            for code, citation, obligation in spec.get("regulatory", [])
        ],
        "confidential": spec.get("confidential", 0),
        "handling_classification": spec.get("handling", "Internal"),
        "training_required": spec.get("training", 0),
        "effective_on": ctx.d(spec.get("effective")),
        "next_review_on": ctx.d(spec.get("next_review")),
        "review_frequency_months": spec.get("review_months"),
        "retention_class": spec.get("retention"),
        "glossary_terms": [{"glossary_term": t, "context_note": "Used as defined in the enterprise glossary."}
                           for t in terms if t],
    }


def _perform(ctx: Ctx, name: str, action: str) -> None:
    """Take a configured lifecycle action — after checking its gates, so that a
    missing precondition is reported plainly instead of written to the refusal log."""
    from consilium.policy import lifecycle

    doc = ctx.frappe.get_doc("Governing Document", name)
    entry = next((a for a in lifecycle.available_actions(doc) if a["action"] == action), None)
    if not entry:
        raise RuntimeError(f"{name}: action {action!r} is not configured from {doc.lifecycle_phase}")
    frappe = ctx.frappe
    frappe.db.savepoint("demo_gate")
    try:
        failures = lifecycle.check_gates(doc, "lifecycle_phase", entry["next_state"])
    except Exception as exc:
        # A gate whose own query fails. The only one that does is "Publication
        # Record Required", which asks PostgreSQL whether a date equals '' (see
        # the report). Its precondition is evaluated correctly below and, if
        # it holds, the configured transition is applied through the framework.
        frappe.db.rollback(save_point="demo_gate")
        failures = _gates_by_hand(ctx, doc, entry["next_state"])
        if failures:
            raise RuntimeError(f"{name}: {action} blocked by gates: {' | '.join(failures)}") from exc
        from frappe.model.workflow import apply_workflow

        apply_workflow(doc, action)
        note = (f"lifecycle gate query failed on PostgreSQL for '{action}'; precondition verified by the "
                f"demo script and the transition applied with apply_workflow")
        if note not in ctx.notes:
            ctx.notes.append(note)
        return
    if failures:
        raise RuntimeError(f"{name}: {action} blocked by gates: {' | '.join(failures)}")
    lifecycle.perform(doc, action)


def _gates_by_hand(ctx: Ctx, doc, next_state: str) -> list[str]:
    """The gates for a state, with the publication check written as PostgreSQL accepts it."""
    from consilium.policy import lifecycle

    failures = []
    for row in lifecycle.gates_for(doc.doctype, "lifecycle_phase", next_state):
        if row["gate"] == "Publication Record Required":
            published = ctx.frappe.db.sql(
                """SELECT count(*) FROM "tabDocument Publication"
                   WHERE "document" = %s AND "docstatus" < 2 AND "withdrawn_on" IS NULL""",
                (doc.name,),
            )[0][0]
            if not published:
                failures.append(f"{row['gate']}: no publication record exists")
            continue
        passed, reason = lifecycle.GATES[row["gate"]](doc)
        if not passed:
            failures.append(f"{row['gate']}: {reason}")
    return failures


def _decide_route(ctx: Ctx, name: str, how_many: int | None, day: int) -> None:
    """Instantiate the routed approval path and decide the first ``how_many`` steps."""
    from consilium.consilium_core import approvals
    from consilium.policy import routing

    frappe = ctx.frappe
    routing.instantiate(frappe.get_doc("Governing Document", name))
    rows = frappe.get_all("Approval Decision",
                          filters={"subject_doctype": "Governing Document", "subject_name": name, "is_open": 1},
                          fields=["name", "assigned_to", "approval_step"], order_by="step_sequence asc, creation asc")
    for index, row in enumerate(rows):
        ctx.stamp("Approval Decision", row["name"], ctx.ts(day - 10, "09:00"), U("policy.office.lead"))
        if how_many is not None and index >= how_many:
            continue
        approvals.record_decision(row["name"], "Approved", acting_user=row["assigned_to"],
                                  comments=f"{row['approval_step']}: approved as drafted.")
        ctx.stamp("Approval Decision", row["name"], None, None, decided_on=ctx.ts(day - 7 + index, "15:30"))


def _drive(ctx: Ctx, key: str, name: str) -> None:
    """Walk a document through its lifecycle to the target phase."""
    from consilium.policy import publication

    frappe = ctx.frappe
    spec = DOC_SPECS[key]
    target = "Published" if spec["target"] == "Retired" else spec["target"]
    reach = PHASE_ORDER.index(target)
    effective = spec.get("effective") or 0
    approve_day = min(effective, spec["versions"][-1][2] + 20) if reach >= 2 else -5

    if reach >= 1 or spec.get("approvals") is not None:
        _perform(ctx, name, "Submit for Review")
    if reach >= 2:
        _decide_route(ctx, name, None, approve_day)
        _perform(ctx, name, "Record Approval")
    elif spec.get("approvals") is not None:
        _decide_route(ctx, name, spec["approvals"], -3)
    if reach >= 3:
        _perform(ctx, name, "Publish")
        confidential = spec.get("handling") == "Confidential" or spec.get("confidential")
        record = publication.record_publication(
            name,
            audience_type="Targeted Groups" if confidential else "All Employees",
            audiences=[{"audience_kind": "User Group", "audience_value": "Business Line Leadership"},
                       {"audience_kind": "User Group", "audience_value": "Compliance Function"}]
            if confidential else None,
            view_only=1 if confidential else 0,
        )
        ctx.made("Document Publication")
        ctx.stamp("Document Publication", record.name, ctx.ts(effective - 1, "08:00"), U("policy.office.lead"),
                  published_on=ctx.ts(effective - 1, "08:00"), published_by=U("policy.office.lead"))
    if reach >= 4:
        doc = frappe.get_doc("Governing Document", name)
        doc.implementation_confirmed_by = U(spec["owner"])
        doc.implementation_confirmed_on = ctx.d(effective + 60)
        doc.implementation_verified_by = U("second.line.reviewer")
        doc.implementation_verified_on = ctx.d(effective + 90)
        doc.save(ignore_permissions=True)
        _perform(ctx, name, "Confirm Implementation")
    if spec.get("reopen"):
        label, summary, day = spec["reopen"]
        _perform(ctx, name, "Reopen for Change")
        publication.upload_version(name, change_summary=summary, version_label=label,
                                   body_text=BODY.format(name=spec["document_name"], abstract=summary))


def _create_document(ctx: Ctx, key: str) -> str | None:
    """Create one document (through its intake request where it has one) and drive it."""
    from consilium.policy import intake, publication

    frappe = ctx.frappe
    spec = DOC_SPECS[key]
    existing = doc_of(ctx, key)
    if existing:
        ctx.had("Governing Document")
        return existing

    values = _document_values(ctx, spec)
    if spec.get("intake"):
        request = _intake(ctx, next(row for row in INTAKES if row[0] == spec["intake"]))
        name = intake.create_document(request, **values)
        _stop_intake_clock(ctx, request, spec["created"])
    else:
        name = frappe.get_doc({"doctype": "Governing Document", **values}).insert(ignore_permissions=True).name
    ctx.made("Governing Document")

    days = []
    for label, summary, day in spec["versions"]:
        publication.upload_version(name, change_summary=summary, version_label=label,
                                   body_text=BODY.format(name=spec["document_name"], abstract=spec["document_abstract"]))
        days.append(day)
    if spec.get("reopen"):
        days.append(spec["reopen"][2])
    _drive(ctx, key, name)
    _stamp_versions(ctx, "Governing Document", name, days, U(spec["owner"]))

    last = max([spec["created"], *(d for d in days), min(spec.get("effective") or 0, 0)])
    ctx.stamp("Governing Document", name, ctx.ts(spec["created"], "10:30"), U(spec["owner"]))
    ctx.stamp("Governing Document", name, None, None, modified=ctx.ts(last, "17:00"))
    return name


def _intake(ctx: Ctx, row) -> str:
    """An intake request, classified through Core's engine when the answers are in."""
    from consilium.consilium_core import sla
    from consilium.policy import intake

    frappe = ctx.frappe
    (key, kind, subject, proposed_type, proposed_name, requester, justification, effective, parties,
     category, answers, _fulfils, created) = row
    existing = find(frappe, "Document Intake Request",
                    {"request_type": kind, "business_justification": justification})
    if existing:
        ctx.had("Document Intake Request")
        return existing
    doc = frappe.get_doc({
        "doctype": "Document Intake Request", "request_type": kind,
        "subject_document": doc_of(ctx, subject) if subject else None,
        "proposed_document_type": proposed_type, "proposed_document_name": proposed_name,
        "requester": U(requester), "business_justification": justification,
        "proposed_effective_date": ctx.d(effective),
        "parties_to_engage": [{"party": U(p)} for p in parties],
        "primary_risk_category": category, "workflow_state": "Requested",
    }).insert(ignore_permissions=True)
    ctx.made("Document Intake Request")
    ctx.stamp("Document Intake Request", doc.name, ctx.ts(created, "09:40"), U(requester))
    if answers:
        assessment = intake.classify(doc.name, answers)
        ctx.stamp("Classification Assessment", assessment.name, ctx.ts(created + 1, "11:00"),
                  U("policy.office.lead"), evaluated_on=ctx.ts(created + 1, "11:00"),
                  evaluated_by=U("policy.office.lead"))
        clock = frappe.db.get_value("Document Intake Request", doc.name, "sla_clock")
        if clock:
            # The clock starts when the request is classified; the platform
            # stamps "now", so it is re-based on the story's date through the
            # same target calculation Core uses.
            started = ctx.ts(created + 1, "11:00")
            definition = frappe.get_doc("SLA Definition", frappe.db.get_value("SLA Clock", clock, "sla_definition"))
            ctx.stamp("SLA Clock", clock, started, None, started_on=started,
                      target_on=sla.target_datetime(definition, started))
    return doc.name


def _stop_intake_clock(ctx: Ctx, request: str, created: int) -> None:
    """A fulfilled request has met its service level. ``create_document`` does
    not stop the clock itself, so it is stopped here through Core."""
    from consilium.consilium_core import sla

    clock = ctx.frappe.db.get_value("Document Intake Request", request, "sla_clock")
    if clock and ctx.frappe.db.get_value("SLA Clock", clock, "is_open"):
        stopped = ctx.ts(created, "12:00")
        sla.stop_clock(clock, stopped_on=ctx.frappe.utils.now())
        ctx.stamp("SLA Clock", clock, None, None, stopped_on=stopped, status="Met", breached_on=None)


def section_policy_library(ctx: Ctx) -> None:
    """Governing documents at every phase, their versions, approvals and publications."""
    frappe = ctx.frappe
    from consilium.policy import glossary

    for key, _spec in DOCUMENTS:
        _create_document(ctx, key)

    # Retirement comes last: the standard's child procedure has to exist before
    # its parent leaves force, which is what raises the child's remediation task.
    for key, spec in DOCUMENTS:
        if spec["target"] != "Retired":
            continue
        name = doc_of(ctx, key)
        doc = frappe.get_doc("Governing Document", name)
        if not doc.is_active:
            continue
        doc.superseded_by = doc_of(ctx, spec["superseded_by"])
        doc.save(ignore_permissions=True)
        _perform(ctx, name, "Retire")
        ctx.stamp("Governing Document", name, None, None, modified=ctx.ts(-25, "17:00"), retired_on=ctx.d(-25))

    for row in INTAKES:
        if not row[11]:
            _intake(ctx, row)

    term, definition, doc_key = SCOPED_TERM
    scope_doc = doc_of(ctx, doc_key)
    if not find(frappe, "Glossary Term", {"term": term, "scope_document": scope_doc}):
        created = frappe.get_doc({
            "doctype": "Glossary Term", "term": term, "definition": definition, "scope_level": "Document",
            "scope_document": scope_doc, "term_status": "Proposed", "enforce_usage": 1,
        }).insert(ignore_permissions=True)
        glossary.publish(created.name, approved_by=U("policy.office.lead"),
                         change_summary="Scoped to the change management procedure.")
        ctx.made("Glossary Term")
        ctx.stamp("Glossary Term", created.name, ctx.ts(-270, "10:00"), U("policy.office.lead"),
                  approved_on=ctx.d(-270))
        _stamp_versions(ctx, "Glossary Term", created.name, [-270])

# ======================================================== policy oversight

HORIZON_SCANS = [
    # doc, scanned_by, day, period, areas, sources [(type, reference, day)], summary, impact, findings
    ("ERM", "chief.risk.officer", -200, "First half of the year", ["REG_CHANGE", "ESG", "GEOPOLITICAL"],
     [("Regulatory Publication", "Prudential regulator annual supervisory priorities letter", -210),
      ("Peer Forum", "Industry chief risk officers' roundtable summary", -205)],
     "No change to the framework's principles is required; climate expectations are tracked separately.",
     "No Change",
     [("Supervisory focus on climate scenario analysis", "ESG", "REQ_CORP_GOV", "Low", "Monitor",
       "chief.risk.officer", 60, "Raised")]),
    ("INFOSEC", "head.technology.risk", -40, "Last two quarters", ["CYBER", "AI_GOV", "THIRD_PARTY"],
     [("Regulatory Publication", "Technology and cyber risk guideline, revised edition", -45),
      ("Technology", "National cyber agency advisory on identity-based attacks", -42),
      ("Subject Matter Expert", "Security architecture review of cloud identity", -41)],
     "The revised guideline tightens identity and third-party access requirements; the policy needs a "
     "major update, now in drafting.",
     "Review Triggered",
     [("Revised identity and access requirements", "CYBER", "REQ_TECH_CYBER", "High", "Update Required",
       "chief.information.officer", 45, "In Hand"),
      ("Use of generative tools with customer data", "AI_GOV", None, "Medium", "Review Triggered",
       "head.technology.risk", 90, "Raised")]),
    ("TPRM", "chief.operating.officer", -70, "Trailing twelve months", ["THIRD_PARTY", "OP_RESIL", "REG_CHANGE"],
     [("Consultation", "Consultation on third-party risk management guideline amendments", -75),
      ("Industry Report", "Industry survey of cloud concentration", -72)],
     "Exit planning and concentration requirements are now expected for all critical providers; the "
     "vendor standard is replaced by a policy.",
     "Immediate Update Required",
     [("Exit plans required for all critical providers", "THIRD_PARTY", "REQ_THIRD_PARTY", "High",
       "Update Required", "chief.operating.officer", -10, "Concluded")]),
    ("AML", "chief.compliance.officer", -95, "Last six months", ["REG_CHANGE", "GEOPOLITICAL"],
     [("Regulatory Publication", "Financial intelligence unit guidance on beneficial ownership", -100),
      ("Geopolitical", "Updated sanctions and high-risk jurisdiction lists", -98)],
     "Enhanced due diligence refresh cycle should shorten for high-risk customers.",
     "Review Triggered",
     [("Beneficial ownership verification guidance", "REG_CHANGE", "REQ_AML", "Medium", "Review Triggered",
       "chief.compliance.officer", 30, "In Hand")]),
    ("BCM", "chief.operating.officer", -120, "Last year", ["OP_RESIL", "CYBER"],
     [("Regulatory Publication", "Operational resilience guideline implementation notes", -125)],
     "Tolerances and testing requirements remain aligned; no change.", "No Change", []),
]

REVIEW_CYCLES = [
    # doc, year offset, start, due, reviewer, status, outcome, notes
    ("ORM", -1, -400, -330, "head.operational.risk", "Concluded", "Minor Update",
     "Loss thresholds lowered; otherwise unchanged."),
    ("CODE", 0, -60, -20, "chief.compliance.officer", "Underway", None,
     "Annual review running late: awaiting the speak-up channel statistics."),
    ("ERM", 0, 60, 150, "chief.risk.officer", "Planned", None, "Biennial review."),
    ("RECORDS", -1, -380, -320, "records.manager", "Concluded", "No Change", "No change required."),
    ("ONBOARD", 0, -40, 20, "head.operational.risk", "Underway", "Retire",
     "Parent standard retired; steps move under the third-party policy."),
]

MONITORING = [
    # doc, title, description, frequency, responsible, control ref, results
    ("AML", "Alert disposition quality assurance",
     "Sample of closed transaction-monitoring alerts re-performed by quality assurance.", "Monthly",
     "second.line.reviewer", "AML-C-07",
     [("Month -3", -95, "Effective", "Sample of 60 alerts; no disposition errors."),
      ("Month -2", -65, "Partially Effective", "Four of 60 alerts closed without documented rationale."),
      ("Month -1", -35, "Not Effective", "Backlog of aged alerts; sample could not be completed.")]),
    ("CODE", "Annual code of conduct attestation completion",
     "Completion rate of the annual code of conduct attestation by all staff.", "Annual",
     "chief.compliance.officer", "COC-C-01",
     [("Prior year", -300, "Effective", "99.2 per cent completion within the window.")]),
    ("INFOSEC", "Privileged access review",
     "Quarterly recertification of privileged access to production systems.", "Quarterly",
     "head.technology.risk", "ISP-C-12",
     [("Quarter -3", -250, "Effective", "All privileged accounts recertified."),
      ("Quarter -2", -160, "Effective", "Two dormant accounts removed."),
      ("Quarter -1", -70, "Not Performed", None)]),
    ("CHANGE", "Change success rate", "Share of production changes implemented without incident.", "Quarterly",
     "head.technology.risk", "CHG-C-03",
     [("Quarter -2", -150, "Effective", "98.7 per cent success."),
      ("Quarter -1", -55, "Partially Effective", "One emergency change caused a major outage.")]),
    ("BCM", "Critical operation recovery test",
     "Semi-annual recovery test of each critical operation against its impact tolerance.", "Semi Annual",
     "chief.operating.officer", "BCM-C-02",
     [("Half-year -1", -130, "Effective", "All tests within tolerance.")]),
]

VIOLATIONS = [
    # key, doc, type, severity, occurred, identified, responsible, BU, description, corrective, status, resolved
    ("V-CHANGE", "CHANGE", "Control", "High", -41, -40, "chief.information.officer", "TECH_INFRA",
     "An emergency change to the core banking platform was deployed without change advisory board approval "
     "and without a tested back-out plan.",
     "Technical enforcement of the change freeze; retrospective approval within two days.", "Remediating", None),
    ("V-AML", "AML", "Regulatory", "Medium", -150, -110, "head.retail.banking", "PCB_RETAIL",
     "Enhanced due diligence was not refreshed within twelve months for 38 high-risk customers.",
     "Refresh completed for all 38 customers; system reminder introduced.", "Under Investigation", None),
    ("V-CODE", "CODE", "Conduct", "Low", -240, -230, "head.retail.banking", "PCB_COMMERCIAL",
     "Gifts and entertainment register not maintained by one commercial banking team for a quarter.",
     "Register reconstructed and team retrained.", "Resolved", -180),
    ("V-INFOSEC", "INFOSEC", "Control", "Medium", -70, -66, "head.technology.risk", "TECH_SECURITY",
     "Quarterly privileged access review not performed.", None, "Logged", None),
    ("V-RECORDS", "RECORDS", "Data", "High", -310, -300, "records.manager", None,
     "Suspected early destruction of loan files; investigation showed files had been migrated, not destroyed.",
     None, "Dismissed", -270),
]

IMPLEMENTATION_PLANS = [
    # doc, title, owner, sizing, training, target, status, verified, tasks [(title, user, due, status, done)]
    ("ORM", "Operational risk policy v4 rollout", "head.operational.risk", "Medium", 1, -300, "Concluded", -290,
     [("Update loss-event capture thresholds", "head.operational.risk", -350, "Done", -352),
      ("Train first-line risk coordinators", "second.line.reviewer", -320, "Done", -318)]),
    ("CODE", "Code of conduct v7 implementation", "chief.compliance.officer", "High", 1, -200, "Concluded", -190,
     [("Launch speak-up channel", "chief.compliance.officer", -380, "Done", -385),
      ("Annual attestation campaign", "chief.compliance.officer", -320, "Done", -318)]),
    ("BCM", "Impact tolerance testing programme", "chief.operating.officer", "High", 0, 60, "Underway", None,
     [("Map critical operations to supporting resources", "head.operational.risk", -60, "Done", -58),
      ("Scenario test payments processing", "head.technology.risk", 15, "Doing", None),
      ("Scenario test customer onboarding", "head.retail.banking", 45, "To Do", None)]),
    ("CHANGE", "Emergency change controls", "chief.information.officer", "Medium", 1, -10, "Underway", None,
     [("Enforce freeze windows in the deployment pipeline", "head.technology.risk", -10, "Doing", None),
      ("Retrain release managers", "chief.information.officer", 20, "To Do", None)]),
]

EXEMPTIONS = [
    # doc, type, scope type, value, label, justification, requested by, from, to, conditions, authorised by
    ("AML", "Exemption", "Legal Entity", "INTL_BRANCH", None,
     "The international branch applies the host-country regime, which is at least equivalent.",
     "chief.compliance.officer", -180, 185, "Annual equivalence assessment by compliance.", "general.counsel"),
    ("INFOSEC", "Deviation", "Organization Unit", "CM_MARKETS", None,
     "Trading desk terminals cannot enforce the screen-lock timeout during market hours.",
     "head.technology.risk", -30, 150, "Physical access controls on the trading floor.", None),
]


#: How each violation reached the status the story gives it, from Logged.
VIOLATION_PATHS = {
    "Logged": [],
    "Under Investigation": ["Under Investigation"],
    "Remediating": ["Under Investigation", "Remediating"],
    "Resolved": ["Under Investigation", "Remediating", "Resolved"],
    "Dismissed": ["Under Investigation", "Dismissed"],
}

#: The statement closing a violation requires.
VIOLATION_CLOSING_NOTES = {
    "Resolved": "Corrective actions completed and verified; closed after second-line review of the evidence.",
    "Dismissed": "Dismissed after second-line review of the evidence: no breach of the standard occurred.",
}


def section_policy_oversight(ctx: Ctx) -> None:
    """Horizon scans and findings, review cycles, monitoring, violations, plans, exemptions."""
    frappe = ctx.frappe
    from consilium.policy import monitoring

    for (doc_key, scanner, day, period, areas, sources, summary, impact, findings) in HORIZON_SCANS:
        document = doc_of(ctx, doc_key)
        key = {"document": document, "scan_date": ctx.d(day)}
        if find(frappe, "Horizon Scan", key):
            ctx.had("Horizon Scan")
            continue
        scan = frappe.get_doc({
            "doctype": "Horizon Scan", "document": document, "scanned_by": U(scanner), "scan_date": ctx.d(day),
            "period_covered": period, "coverage_areas": [{"coverage_area": a} for a in areas],
            "sources": [{"source_type": t, "reference": r, "reviewed_on": ctx.d(d)} for t, r, d in sources],
            "summary": summary, "impact_assessment": impact,
        }).insert(ignore_permissions=True)
        ctx.made("Horizon Scan")
        ctx.stamp("Horizon Scan", scan.name, ctx.ts(day, "15:00"), U(scanner))
        cycle = frappe.db.get_value("Horizon Scan", scan.name, "resulting_review_cycle")
        if cycle:
            ctx.made("Document Review Cycle")
            ctx.stamp("Document Review Cycle", cycle, ctx.ts(day, "15:05"), U(scanner))
        for title, area, requirement, assessed, action, owner, due, status in findings:
            finding = frappe.get_doc({
                "doctype": "Horizon Scan Finding", "horizon_scan": scan.name, "finding_title": title,
                "coverage_area": area, "regulatory_requirement": requirement,
                "impacted_documents": [{"governing_document": document}], "assessed_impact": assessed,
                "action_taken": action, "finding_owner": U(owner), "due_on": ctx.d(due),
                "finding_status": status, "description": summary,
            }).insert(ignore_permissions=True)
            ctx.made("Horizon Scan Finding")
            ctx.stamp("Horizon Scan Finding", finding.name, ctx.ts(day, "15:30"), U(scanner))

    for doc_key, year_offset, start, due, reviewer, status, outcome, notes in REVIEW_CYCLES:
        document = doc_of(ctx, doc_key)
        year = str(ctx.anchor.year + year_offset)
        if find(frappe, "Document Review Cycle", {"document": document, "cycle_year": year,
                                                  "triggered_by_horizon_scan": ["is", "not set"]}):
            ctx.had("Document Review Cycle")
            continue
        cycle = frappe.get_doc({
            "doctype": "Document Review Cycle", "document": document, "cycle_year": year,
            "scheduled_start": ctx.d(start), "due_on": ctx.d(due), "reviewer": U(reviewer),
            "cycle_status": status, "outcome": outcome, "outcome_notes": notes,
        }).insert(ignore_permissions=True)
        ctx.made("Document Review Cycle")
        ctx.stamp("Document Review Cycle", cycle.name, ctx.ts(start, "09:00"), U("policy.office.lead"))

    violations = {}
    for (key, doc_key, kind, severity, occurred, identified, responsible, unit, description, corrective,
         status, resolved) in VIOLATIONS:
        document = doc_of(ctx, doc_key)
        existing = find(frappe, "Policy Violation", {"document": document, "description": description})
        if existing:
            ctx.had("Policy Violation")
            violations[key] = existing
            continue
        # A violation is logged open, to be investigated (the controller refuses
        # one recorded as already closed), and then moved on through the policy
        # office's own entry point, which is where the platform checks who may
        # move it and that closing it carries a resolution note.
        doc = frappe.get_doc({
            "doctype": "Policy Violation", "document": document, "violation_type": kind, "severity": severity,
            "occurred_on": ctx.d(occurred), "identified_on": ctx.d(identified),
            "responsible_party": U(responsible), "business_unit": unit, "description": description,
            "violation_status": "Logged",
        }).insert(ignore_permissions=True)
        for step in VIOLATION_PATHS[status]:
            with acting_as(frappe, U("policy.office.lead")):
                monitoring.update_violation(
                    doc.name, step,
                    resolution_note=VIOLATION_CLOSING_NOTES.get(step) if step == status else None,
                    corrective_actions=corrective if step == status else None,
                )
        violations[key] = doc.name
        ctx.made("Policy Violation")
        # The platform dates a resolution the day it is recorded; the story says when.
        ctx.stamp("Policy Violation", doc.name, ctx.ts(identified, "13:00"), U("second.line.reviewer"),
                  **({"resolved_on": ctx.d(resolved)} if resolved else {}))

    for doc_key, title, description, frequency, responsible, control, results in MONITORING:
        document = doc_of(ctx, doc_key)
        if find(frappe, "Monitoring Activity", {"document": document, "activity_title": title}):
            ctx.had("Monitoring Activity")
            continue
        activity = frappe.get_doc({
            "doctype": "Monitoring Activity", "document": document, "activity_title": title,
            "description": description, "frequency": frequency, "responsible": U(responsible),
            "control_reference": control, "is_active": 1, "next_due_on": ctx.d(results[0][1]),
        }).insert(ignore_permissions=True)
        ctx.made("Monitoring Activity")
        ctx.stamp("Monitoring Activity", activity.name, ctx.ts(results[0][1] - 30, "09:00"), U(responsible))
        for period, day, outcome, findings in results:
            violation = None
            if outcome == "Not Effective" and doc_key == "AML":
                violation = violations.get("V-AML")
            if outcome == "Not Performed" and doc_key == "INFOSEC":
                violation = violations.get("V-INFOSEC")
            result = frappe.get_doc({
                "doctype": "Monitoring Result", "monitoring_activity": activity.name, "period_label": period,
                "performed_by": U(responsible), "performed_on": ctx.d(day), "outcome": outcome,
                "findings": findings, "resulting_violation": violation,
            }).insert(ignore_permissions=True)
            ctx.made("Monitoring Result")
            ctx.stamp("Monitoring Result", result.name, ctx.ts(day, "16:00"), U(responsible))

    for doc_key, title, owner, sizing, training, target, status, verified, tasks in IMPLEMENTATION_PLANS:
        document = doc_of(ctx, doc_key)
        if find(frappe, "Implementation Plan", {"document": document, "plan_title": title}):
            ctx.had("Implementation Plan")
            continue
        plan = frappe.get_doc({
            "doctype": "Implementation Plan", "document": document, "plan_title": title, "plan_owner": U(owner),
            "impact_people": "Awareness for affected staff; targeted training where marked.",
            "impact_process": "Procedures updated to the new requirements.",
            "impact_technology": "Configuration changes where controls are automated.",
            "impact_data": "No new data collected.", "impact_sizing": sizing, "training_required": training,
            "working_groups": [{"user_group": "Risk Management Function"}],
            "target_completion": ctx.d(target), "plan_status": status,
            "verified_by": U("second.line.reviewer") if verified else None, "verified_on": ctx.d(verified),
            "tasks": [{"task_title": t, "assigned_to": U(u), "due_on": ctx.d(due), "task_status": s,
                       "completed_on": ctx.d(done)} for t, u, due, s, done in tasks],
        }).insert(ignore_permissions=True)
        ctx.made("Implementation Plan")
        ctx.stamp("Implementation Plan", plan.name, ctx.ts(tasks[0][2] - 20, "10:00"), U(owner))

    for (doc_key, kind, scope_type, value, label, justification, requester, start, end, conditions,
         authoriser) in EXEMPTIONS:
        document = doc_of(ctx, doc_key)
        if find(frappe, "Applicability Exemption", {"document": document, "justification": justification}):
            ctx.had("Applicability Exemption")
            continue
        exemption = frappe.get_doc({
            "doctype": "Applicability Exemption", "document": document, "exemption_type": kind,
            "scope_type": scope_type, "scope_value": value, "scope_label": label, "justification": justification,
            "requested_by": U(requester), "valid_from": ctx.d(start), "valid_to": ctx.d(end),
            "conditions": conditions, "exemption_status": "Requested",
        }).insert(ignore_permissions=True)
        if authoriser:
            exemption.authorise(approved_by=U(authoriser))
            ctx.stamp("Applicability Exemption", exemption.name, None, None, approved_on=ctx.d(start - 5))
        ctx.made("Applicability Exemption")
        ctx.stamp("Applicability Exemption", exemption.name, ctx.ts(start - 12, "11:00"), U(requester))

    # Remediation tasks the retirement raised: stamp them with the retirement date.
    for task in frappe.get_all("Metadata Remediation Task", filters={"trigger_name": doc_of(ctx, "VENDOR")},
                               pluck="name"):
        ctx.stamp("Metadata Remediation Task", task, ctx.ts(-25, "17:05"), U("policy.office.lead"))

# ======================================================= meetings and votes

H, S, C, A = "Held", "Scheduled", "Cancelled", "Adjourned"

MEETINGS = {
    "BOARD": [(-455, H), (-365, H), (-270, H), (-180, H), (-88, H), (4, S)],
    "BRC": [(-460, H), (-370, H), (-275, H), (-185, H), (-95, H), (12, S)],
    "AC": [(-360, H), (-180, H), (-96, H), (25, S)],
    "EXCO": [(-120, H), (-89, H), (-59, H), (-28, H), (6, S)],
    "ERC": [(-210, H), (-180, H), (-150, H), (-120, C), (-90, H), (-60, H), (-30, H), (10, S), (40, S)],
    "ORC": [(-150, H), (-120, H), (-90, H), (-58, A), (-35, H), (-7, H), (20, S)],
    "TCRC": [(-180, H), (-120, H), (-63, H), (-33, H), (14, S)],
    "MRC": [(-400, H), (-300, H), (-200, H), (-100, H), (-20, H), (70, S)],
    "CRC": [(-95, H), (-64, H), (-34, H), (8, S)],
    "ALCO": [(-92, H), (-61, H), (-31, C), (-26, H), (9, S)],
    "CCC": [(30, S)],
    "LEGACY": [(-400, H), (-250, H)],
    "TPRWG": [(-140, H), (-110, H), (-80, H), (-50, H), (-21, H), (12, S)],
}

#: Who was away. A member away with a standing delegate is represented by them.
ABSENT = {
    ("ERC", -90): ["chief.operating.officer"],
    ("ERC", -150): ["general.counsel"],
    ("ORC", -58): ["head.technology.risk", "chief.information.officer", "head.retail.banking",
                   "chief.compliance.officer", "chief.operating.officer", "second.line.reviewer"],
    ("MRC", -100): ["treasurer"],
    ("EXCO", -59): ["general.counsel"],
    ("TCRC", -120): ["chief.operating.officer"],
}

#: Non-members who attended as guests.
GUESTS = {"BRC": ["chief.executive"], "ERC": ["risk.governance.lead"], "ORC": ["risk.governance.analyst"]}

MOTIONS = [
    # forum, meeting day, text, subject document, outcome (None = still open), positions
    ("BRC", -460, "Recommend the Enterprise Risk Management Framework v2.0 to the Board for approval.",
     "ERM", "Carried", {}),
    ("BOARD", -455, "Approve the Enterprise Risk Management Framework v2.0.", "ERM", "Carried", {}),
    ("AC", -180, "Approve the internal audit plan for the coming year.", None, "Carried", {}),
    ("ERC", -180, "Approve the Anti-Money Laundering Policy v9.0.", "AML", "Carried", {}),
    ("TCRC", -180, "Approve the Information Security Policy v4.0.", "INFOSEC", "Carried", {}),
    ("ORC", -150, "Approve the Business Continuity and Operational Resilience Standard v2.0.", "BCM",
     "Carried", {}),
    ("MRC", -300, "Approve the challenger model for retail mortgage probability of default for use.", None,
     "Carried", {}),
    ("MRC", -100, "Approve an interim management overlay on the small-business credit scorecard.", None,
     "Carried", {"head.retail.banking": "Recused"}),
    ("BRC", -95, "Recommend the refreshed Risk Appetite Framework v3.0 to the Board.", "RAF", "Carried",
     {"director.audit": "Abstain"}),
    ("ALCO", -92, "Approve the contingency funding plan and its early-warning indicators.", None, "Carried", {}),
    ("ERC", -90, "Approve the enterprise stress-testing scenarios for the capital plan.", None, "Carried", {}),
    ("ORC", -90, "Set the impact tolerance for payments processing at four hours.", None, "Carried",
     {"head.retail.banking": "Against"}),
    ("BOARD", -88, "Approve the Risk Appetite Framework v3.0, including the new concentration metrics.", "RAF",
     "Carried", {}),
    ("CRC", -64, "Approve a higher sector sub-limit for commercial real estate lending.", None, "Not Carried",
     {"chief.financial.officer": "Against", "treasurer": "Against", "head.model.risk": "Against"}),
    ("TCRC", -63, "Accept the risk of operating the end-of-life database platform until its migration completes.",
     None, "Not Carried", {"head.operational.risk": "Against", "chief.operating.officer": "Against"}),
    ("ERC", -60, "Endorse the operational resilience self-assessment for the Board Risk Committee.", None,
     "Deferred", {}),
    ("EXCO", -59, "Approve the establishment of a Data Governance Council, subject to formation approval.",
     None, "Carried", {}),
    ("ORC", -58, "Approve an exception to the change freeze for the year-end release.", None, "Inquorate", {}),
    ("TPRWG", -50, "Adopt the exit-plan template for critical providers.", None, "Carried", {}),
    ("ORC", -35, "Lower the payments processing impact tolerance to two hours.", None, "Not Carried",
     {"chief.information.officer": "Against", "head.technology.risk": "Against",
      "chief.compliance.officer": "Against", "chief.operating.officer": "Against"}),
    ("ERC", -30, "Accept a temporary exceedance of the commercial real estate concentration limit, to at most "
                 "13.5 per cent of capital for two quarters, conditional on the reduction plan.", None, "Carried",
     {"chief.compliance.officer": "Against", "general.counsel": "Abstain"}),
    ("ALCO", -26, "Extend the interest-rate hedging programme by twelve months.", None, "Deferred", {}),
    ("MRC", -20, "Approve the Model Risk Management Policy for publication.", "MRM", "Deferred", {}),
    ("ERC", 10, "Approve the Outsourcing and Third-Party Risk Policy.", "TPRM", None, {}),
]

#: The motion the risk acceptance on the concentration breach cites as its approval.
CRE_MOTION = ("ERC", -30)


def meeting_ref(ctx: Ctx, key: str, day: int) -> str:
    return f"{abbr_of(key)}-{ctx.weekday(day).isoformat()}"


def _officers_on(ctx: Ctx, forum: str, on_date) -> dict:
    from consilium.governance import membership

    out = {}
    for seat in membership.members_as_at(forum, on_date):
        flags = membership.role_defaults(seat["forum_role"])
        if flags.get("is_chair_role") and seat["member"]:
            out["chair"] = seat["member"]
        if flags.get("is_secretary_role") and seat["member"]:
            out["secretary"] = seat["member"]
    return out


def _attendance(ctx: Ctx, key: str, forum: str, day: int) -> list[dict]:
    from consilium.governance import membership

    on = ctx.weekday(day)
    away = {U(p) for p in ABSENT.get((key, day), [])}
    rows = []
    for seat in membership.members_as_at(forum, on):
        if not seat["member"]:
            continue
        present = seat["member"] not in away
        rows.append({"membership": seat["name"], "attendee": seat["member"], "attended_as": "Member",
                     "present": 1 if present else 0})
        if not present and membership.delegate_active_on(seat, on):
            rows.append({"membership": seat["name"], "attendee": seat["delegate"], "attended_as": "Delegate",
                         "present": 1})
    for guest in GUESTS.get(key, []):
        rows.append({"attendee": U(guest), "attended_as": "Guest", "present": 1})
    return rows


def ensure_meetings(ctx: Ctx, key: str, schedule: list) -> None:
    """One forum's meetings, their attendance and, for all but the latest sitting, approved minutes."""
    from consilium.governance import meetings

    frappe = ctx.frappe
    forum = forum_of(ctx, key)
    held_days = [day for day, status in schedule if status == H]
    for day, status in schedule:
        reference = meeting_ref(ctx, key, day)
        if find(frappe, "Forum Meeting", {"forum": forum, "meeting_reference": reference}):
            ctx.had("Forum Meeting")
            continue
        on = ctx.weekday(day)
        officers = _officers_on(ctx, forum, on)
        values = {
            "doctype": "Forum Meeting", "forum": forum, "meeting_reference": reference,
            "scheduled_on": f"{on} 09:30:00", "status": status,
            "location": "Head office, boardroom 1" if key in ("BOARD", "BRC", "AC") else "Head office, room 4.12",
            "chaired_by": officers.get("chair"), "secretary": officers.get("secretary"),
        }
        if status in (H, A):
            values["held_on"] = f"{on} 09:30:00"
            values["attendance"] = _attendance(ctx, key, forum, day)
        meeting = frappe.get_doc(values).insert(ignore_permissions=True)
        ctx.made("Forum Meeting")
        ctx.stamp("Forum Meeting", meeting.name, ctx.ts(day - 21, "12:00"), officers.get("secretary")
                  or U("committee.secretary"))
        if status == H and day != max(held_days) and day < 0:
            body = (f"<p>Minutes of the {reference} sitting. Quorum confirmed. The committee received the "
                    f"risk report, considered the items on the agenda and recorded the motions below. "
                    f"Actions are tracked in the action log.</p>")
            # Through the minutes API, which versions them as a charter is
            # versioned and points the meeting at the latest version.
            version = meetings.record_minutes(meeting, body, change_summary="Minutes approved at the next sitting.")
            ctx.stamp("Document Version", version.name, ctx.ts(day + 25, "16:00"), officers.get("secretary"))


def ensure_motion(ctx: Ctx, index: int, spec) -> None:
    """Open a motion (writing entitlement as at the decision date), cast the
    ballots of those present, and record the outcome, which freezes quorum."""
    from consilium.consilium_core import versioning
    from consilium.governance import voting

    frappe = ctx.frappe
    key, day, text, subject, outcome, positions = spec
    forum = forum_of(ctx, key)
    on = ctx.weekday(day)
    sequence = sum(1 for other in MOTIONS[:index] if other[0] == key) + 1
    reference = f"{abbr_of(key)}-{on.year}-M{sequence:02d}"
    if find(frappe, "Forum Motion", {"forum": forum, "motion_reference": reference}):
        ctx.had("Forum Motion")
        return
    meeting = find(frappe, "Forum Meeting", {"forum": forum, "meeting_reference": meeting_ref(ctx, key, day)})
    officers = _officers_on(ctx, forum, on)
    attendance = frappe.get_all("Meeting Attendance", filters={"parent": meeting, "parenttype": "Forum Meeting"},
                                fields=["membership", "attendee", "attended_as", "present"]) if meeting else []
    present_seats = [row["membership"] for row in attendance if row["membership"] and row["present"]]
    seconder = next((row["attendee"] for row in attendance
                     if row["present"] and row["attendee"] != officers.get("chair") and row["membership"]), None)
    subject_name = doc_of(ctx, subject) if subject else None
    current = versioning.current_version("Governing Document", subject_name) if subject_name else None
    motion = frappe.get_doc({
        "doctype": "Forum Motion", "forum": forum, "meeting": meeting, "motion_reference": reference,
        "motion_text": text, "decision_date": str(on),
        "subject_doctype": "Governing Document" if subject_name else None, "subject_name": subject_name,
        "based_on_version": current.name if current else None,
        "proposed_by": officers.get("chair"), "seconded_by": seconder, "voting_mode": "In Meeting",
    }).insert(ignore_permissions=True)
    ctx.made("Forum Motion")
    voting.open_motion(motion)
    entitled = voting.entitlement(motion.name)
    ctx.made("Forum Vote", len(entitled))
    stamp_time = f"{on} 11:00:00"
    for row in entitled:
        ctx.stamp("Forum Vote", row["name"], stamp_time, None)
    if outcome is None:
        ctx.stamp("Forum Motion", motion.name, ctx.ts(day - 14, "10:00"), officers.get("secretary"),
                  opened_on=ctx.ts(day - 14, "10:00"))
        return
    if outcome != "Deferred":
        delegates = {row["membership"]: row["attendee"] for row in attendance
                     if row["attended_as"] == "Delegate" and row["present"]}
        members_present = {row["membership"] for row in attendance
                           if row["attended_as"] == "Member" and row["present"]}
        for row in entitled:
            voter_key = row["voter"].split("@")[0]
            position = positions.get(voter_key, "For")
            if row["membership"] in members_present:
                voting.cast_vote(motion.name, row["membership"], position)
            elif row["membership"] in delegates:
                voting.cast_vote(motion.name, row["membership"], position, as_delegate=True,
                                 rationale="Cast by the standing delegate.")
            if row["membership"] in members_present or row["membership"] in delegates:
                ctx.stamp("Forum Vote", row["name"], stamp_time, None, cast_on=stamp_time)
    voting.record_outcome(motion.name, outcome, recorded_by=officers.get("secretary"),
                          present_memberships=present_seats)
    ctx.stamp("Forum Motion", motion.name, ctx.ts(day - 7, "10:00"), officers.get("secretary"),
              opened_on=f"{on} 10:45:00", closed_on=f"{on} 11:30:00",
              modified=f"{on} 11:30:00")


def section_meetings(ctx: Ctx) -> None:
    """Sittings of every forum, then the motions decided at them."""
    for key, schedule in MEETINGS.items():
        ensure_meetings(ctx, key, schedule)
    for index, spec in enumerate(MOTIONS):
        ensure_motion(ctx, index, spec)

# ================================================= charters and compliance

CHARTERS = [
    # forum, title, effective, next review, versions [(label, summary, day)], challenge, evidence day
    ("BOARD", "Board of Directors Mandate", -455, 270, [("2025", "Mandate re-approved without change.", -470)],
     ("Cleared", "Consistent with the corporate governance guideline.", -465), -455),
    ("BRC", "Board Risk Committee Charter", -460, 265, [("3.0", "Annual review; climate risk oversight added.", -480)],
     ("Cleared", "Mandate and reporting lines confirmed.", -470), -460),
    ("AC", "Audit Committee Charter", -360, 5, [("4.1", "Annual review; no change.", -370)],
     ("Cleared", "No challenge.", -365), -360),
    ("EXCO", "Executive Committee Terms of Reference", -400, 330,
     [("2.0", "Delegated limits aligned to the Board's reserved matters.", -410)],
     ("Cleared", "Delegated limits reconcile to the Board mandate.", -405), -400),
    ("ERC", "Executive Risk Committee Charter", -150, 215,
     [("1.0", "Charter migrated at go-live.", -500),
      ("2.0", "Risk acceptance authority and escalation to the Board Risk Committee made explicit.", -165)],
     ("Cleared", "Risk acceptance limits now explicit; challenge cleared.", -160), -150),
    ("ORC", "Operational Risk Committee Charter", -480, 250,
     [("1.0", "First charter on the platform.", -495)],
     ("Cleared", "Clear escalation threshold; cleared.", -490), -480),
    # Version 1.0 was cleared at go-live; the 2.0 draft and the challenge on it
    # come much later, with the mandate change (LATER_CHARTER_VERSIONS).
    ("TCRC", "Technology and Cyber Risk Committee Charter", -490, -40,
     [("1.0", "First charter on the platform.", -500)],
     ("Cleared", "Clear mandate and escalation route for technology and cyber risk; cleared.", -495), -490),
    ("MRC", "Model Risk Committee Charter", -470, -35, [("2.0", "Model tiering authority added.", -480)],
     ("Cleared", "Consistent with the model risk guideline.", -475), -470),
    ("CRC", "Credit Risk Committee Charter", -470, 260, [("1.0", "Charter migrated at go-live.", -480)],
     ("Cleared", "No challenge.", -475), -470),
    ("ALCO", "Asset-Liability Committee Charter", -380, 350, [("5.0", "Contingency funding plan ownership.", -390)],
     ("Cleared", "No challenge.", -385), -380),
    ("CCC", "Conduct and Culture Council Terms of Reference", None, None,
     [("0.9", "Draft terms of reference for the new council.", -120)], None, None),
    ("TPRWG", "Third-Party Risk Working Group Terms of Reference", -160, 200,
     [("1.0", "Terms of reference for the successor to the outsourcing oversight forum.", -168)],
     ("Cleared", "Clear succession from the disbanded forum; cleared.", -165), -160),
]

#: Charter versions taken after the forum's first compliance review, with the
#: challenge on each. A forum is recorded Compliant only while the challenge on
#: its charter is cleared, so a later draft is published — reopening the
#: challenge — at the point in the story where it happened: just before the
#: review it triggers, not with the charter's first version.
LATER_CHARTER_VERSIONS = {
    "TCRC": [("2.0-draft", "Draft extending the mandate to operational resilience of critical operations.", -50,
              ("Changes Requested", "The draft extends the mandate to operational resilience but gives the "
                                    "committee no authority to set impact tolerances, and no escalation route "
                                    "for a tolerance breach. Clarify both before approval.", -45))],
}

COMPLIANT_NOTE = ("Charter, membership, quorum rule and escalation route reviewed against the governance "
                  "standard. No exceptions.")

REVIEWS = {
    # forum: [(review type, decision, day, reviewer, comments, questions, triggered fields)]
    "BOARD": [("Initial", "Compliant", -450, "chief.compliance.officer", COMPLIANT_NOTE, None, None)],
    "BRC": [("Initial", "Compliant", -450, "chief.compliance.officer", COMPLIANT_NOTE, None, None)],
    "AC": [("Initial", "Compliant", -350, "chief.compliance.officer", COMPLIANT_NOTE, None, None)],
    "EXCO": [("Initial", "Compliant", -395, "second.line.reviewer", COMPLIANT_NOTE, None, None)],
    "ERC": [("Initial", "Compliant", -490, "chief.compliance.officer", COMPLIANT_NOTE, None, None)],
    "ORC": [("Triggered By Change", "Compliant", -470, "second.line.reviewer",
             "Re-reviewed after the parent forum and mandate were recorded. Compliant.", None,
             ["parent_forum", "description"])],
    "TCRC": [("Initial", "Compliant", -480, "second.line.reviewer", COMPLIANT_NOTE, None, None),
             ("Triggered By Change", "Non-Compliant", -44, "second.line.reviewer",
              "The mandate now covers operational resilience, but the charter has not been approved for it "
              "and the risk governance office has requested changes. The committee is operating outside an "
              "approved mandate.", None, ["description"])],
    "MRC": [("Initial", "Compliant", -465, "chief.compliance.officer", COMPLIANT_NOTE, None, None)],
    "CRC": [("Initial", "Compliant", -465, "second.line.reviewer", COMPLIANT_NOTE, None, None)],
    "ALCO": [("Initial", "Compliant", -375, "second.line.reviewer", COMPLIANT_NOTE, None, None)],
    "CCC": [("Initial", "Returned To Creator", -100, "second.line.reviewer", None,
             "1. Which decisions, if any, may the council take without the Executive Committee?\n"
             "2. Who owns the conduct risk appetite metrics the council reviews?\n"
             "3. The terms of reference are unapproved: when will they go to the Executive Committee?", None)],
    "LEGACY": [("Initial", "Compliant", -520, "second.line.reviewer", COMPLIANT_NOTE, None, None)],
    "TPRWG": [("Initial", "Compliant", -155, "second.line.reviewer", COMPLIANT_NOTE, None, None)],
}

#: Mandates rewritten after their first review — watched-field changes.
MANDATE_CHANGES = {"TCRC": (TCRC_NEW_MANDATE, -50), "TPRWG": (TPRWG_NEW_MANDATE, -12)}


def section_charters(ctx: Ctx) -> None:
    """Charters in Core's version chain, with the risk governance office's challenge."""
    frappe = ctx.frappe
    from consilium.governance import charters

    for key, title, effective, review, versions, challenge, evidence_day in CHARTERS:
        if find(frappe, "Committee Charter", {"charter_title": title}):
            ctx.had("Committee Charter")
            continue
        forum = forum_of(ctx, key)
        chair = frappe.db.get_value("Governance Forum", forum, "committee_chair")
        charter = frappe.get_doc({
            "doctype": "Committee Charter", "charter_title": title, "forum": forum,
            "effective_from": ctx.d(effective), "next_charter_review_on": ctx.d(review),
            "approval_evidence": [{
                "evidence_type": "Meeting Minutes", "provided_by": U("committee.secretary"),
                "dated_on": ctx.d(evidence_day),
                "description": "Charter approved at the sitting; extract of minutes attached to the meeting record.",
            }] if evidence_day else [],
        }).insert(ignore_permissions=True)
        ctx.made("Committee Charter")
        for label, summary, day in versions:
            body = (f"<h3>{title}</h3><p>{summary}</p><p><strong>Purpose.</strong> "
                    f"{frappe.db.get_value('Governance Forum', forum, 'description')}</p>")
            charters.publish_version(charter.name, summary, body_text=body, version_label=label)
        _stamp_versions(ctx, "Committee Charter", charter.name, [v[2] for v in versions], chair)
        if challenge:
            _challenge_charter(ctx, charter.name, challenge)
        ctx.stamp("Committee Charter", charter.name, ctx.ts(versions[0][2], "10:00"), U("committee.secretary"))


def _challenge_charter(ctx: Ctx, charter: str, challenge: tuple) -> None:
    """The risk governance office records its challenge outcome, as itself,
    through the forum page's own entry point (which checks the challenge role)."""
    from consilium.governance import charters

    status, comments, day = challenge
    with acting_as(ctx.frappe, U("risk.governance.lead")):
        charters.record_charter_challenge(charter, status, comments=comments)
    ctx.stamp("Committee Charter", charter, None, None, rgo_reviewed_on=ctx.ts(day, "14:00"),
              modified=ctx.ts(day, "14:00"))


def _later_charter_versions(ctx: Ctx, key: str, forum: str) -> None:
    """A new charter draft taken by the secretary, which reopens the challenge,
    then the risk governance office's outcome on it."""
    frappe = ctx.frappe
    from consilium.governance import charters

    charter = frappe.db.get_value("Committee Charter", {"forum": forum}, "name", order_by="creation asc")
    if not charter:
        return
    taken = set(frappe.get_all("Document Version", pluck="version_label",
                               filters={"subject_doctype": "Committee Charter", "subject_name": charter}))
    for label, summary, day, challenge in LATER_CHARTER_VERSIONS.get(key, []):
        if label in taken:
            continue
        title = frappe.db.get_value("Committee Charter", charter, "charter_title")
        body = (f"<h3>{title}</h3><p>{summary}</p><p><strong>Purpose.</strong> "
                f"{frappe.db.get_value('Governance Forum', forum, 'description')}</p>")
        with acting_as(frappe, U("committee.secretary")):
            charters.publish_charter_version(charter, summary, body_text=body, version_label=label)
        version = frappe.db.get_value("Document Version", {"subject_doctype": "Committee Charter",
                                                           "subject_name": charter, "version_label": label})
        ctx.stamp("Document Version", version, ctx.ts(day, "16:00"), U("committee.secretary"))
        if challenge:
            _challenge_charter(ctx, charter, challenge)


def section_compliance(ctx: Ctx) -> None:
    """Compliance reviews through the lifecycle's own review record; mandate changes
    that send forums back for review; and one forum disbanded through its plan."""
    frappe = ctx.frappe
    from consilium.governance import lifecycle

    for key, reviews in REVIEWS.items():
        forum = forum_of(ctx, key)
        done = frappe.get_all("Forum Compliance Review",
                              filters={"forum": forum, "reviewer": ["like", f"%@{DOMAIN}"]}, pluck="name")
        if done:
            ctx.had("Forum Compliance Review", len(done))
            continue
        for review_type, decision, day, reviewer, comments, questions, fields in reviews:
            if key in MANDATE_CHANGES and review_type != "Initial":
                _change_mandate(ctx, key, forum)
            if key in LATER_CHARTER_VERSIONS and review_type != "Initial":
                _later_charter_versions(ctx, key, forum)
            review = lifecycle.record_review(forum, decision, review_type=review_type, reviewer=U(reviewer),
                                             comments=comments, returned_questions=questions,
                                             triggered_by_fields=fields)
            ctx.made("Forum Compliance Review")
            ctx.stamp("Forum Compliance Review", review.name, ctx.ts(day, "15:00"), U(reviewer),
                      decided_on=ctx.ts(day, "15:00"))
        if key in MANDATE_CHANGES and all(r[0] == "Initial" for r in reviews):
            _change_mandate(ctx, key, forum)
        last = max([r[2] for r in reviews] + [MANDATE_CHANGES.get(key, (None, -9999))[1]])
        if frappe.db.get_value("Governance Forum", forum, "owner") != "Administrator":
            ctx.stamp("Governance Forum", forum, None, None, modified=ctx.ts(last, "15:05"))

    _disband(ctx, "LEGACY", successor="TPRWG", effective=-150)


def _change_mandate(ctx: Ctx, key: str, forum: str) -> None:
    """Rewrite a forum's mandate. It is a watched field, so the forum goes back to review."""
    doc = ctx.frappe.get_doc("Governance Forum", forum)
    new_mandate, _day = MANDATE_CHANGES[key]
    if doc.description == new_mandate:
        return
    doc.description = new_mandate
    doc.save(ignore_permissions=True)


def _disband(ctx: Ctx, key: str, *, successor: str, effective: int) -> None:
    """G-11: a plan, the named approvals as Core decisions, then execution."""
    from consilium.consilium_core import approvals
    from consilium.governance import lifecycle

    frappe = ctx.frappe
    forum = forum_of(ctx, key)
    if find(frappe, "Disbandment Plan", {"forum": forum}):
        ctx.had("Disbandment Plan")
        return
    plan = frappe.get_doc({
        "doctype": "Disbandment Plan", "forum": forum, "trigger_scenario": "Mandate Complete",
        "successor_forum": forum_of(ctx, successor), "effective_on": ctx.d(effective),
        "records_disposition_note": "Minutes and papers transfer to the successor working group's record; "
                                    "retained under the governance forum records class for ten years.",
        "approvals": [
            {"approver_role": "Delegating Authority", "approver": U("chief.risk.officer"), "required": 1},
            {"approver_role": "Sponsor", "approver": U("chief.operating.officer"), "required": 1},
            {"approver_role": "Chair", "approver": U("head.operational.risk"), "required": 0},
        ],
    }).insert(ignore_permissions=True)
    ctx.made("Disbandment Plan")
    for index, name in enumerate(plan.raise_approvals()):
        assignee = frappe.db.get_value("Approval Decision", name, "assigned_to")
        approvals.record_decision(name, "Approved", acting_user=assignee,
                                  comments="The successor working group has taken over the mandate.")
        ctx.stamp("Approval Decision", name, ctx.ts(effective - 20, "10:00"), U("risk.governance.lead"),
                  decided_on=ctx.ts(effective - 12 + index, "16:00"))
    plan.reload()
    plan.save(ignore_permissions=True)
    lifecycle.execute_disbandment(plan.name, effective_on=ctx.d(effective))
    ctx.stamp("Disbandment Plan", plan.name, ctx.ts(effective - 25, "11:00"), U("risk.governance.lead"),
              executed_on=ctx.ts(effective, "09:00"))
    ctx.stamp("Governance Forum", forum, None, None, modified=ctx.ts(effective, "09:00"))

# ======================================================= formation requests

PASS_ALL = [
    ("Gap In Coverage", "Pass", "No forum covers this ground today."),
    ("Duplication", "Pass", "Duplicate check found no forum with the same type and risk category."),
    ("Escalation Pathway", "Pass", "Escalates through the named parent forum."),
    ("Framework Alignment", "Pass", "Aligned to the enterprise risk management framework."),
    ("Resource Feasibility", "Pass", "Secretariat and members confirmed."),
]

FORMATION = [
    ("DGC", "approved", dict(
        forum_name=DGC_NAME, forum_type="COUNCIL", requester="chief.information.officer",
        delegating_authority="chief.executive", sponsor="chief.operating.officer", category="DATA",
        cadence="Quarterly", parent="EXCO", group="ENTERPRISE", timeline=-40, first_meeting=25, created=-110,
        rationale="Data ownership, quality and lineage decisions are taken in five different places, and the "
                  "privacy incident showed nobody owns cross-business data standards.",
        purpose_scope="Coordinates data ownership, data quality standards and the data lineage of critical "
                      "reports across the group; recommends data policies to the Executive Committee.",
        responsibilities="Maintain the register of data owners; approve data quality thresholds for critical "
                         "reports; escalate unresolved data ownership disputes to the Executive Committee.")),
    ("ORSC", "pending_approval", dict(
        forum_name="Operational Resilience Steering Committee", forum_type="MGMT_CTTE",
        requester="chief.operating.officer", delegating_authority="chief.risk.officer",
        sponsor="chief.executive", category="OPERATIONAL", cadence="Monthly", parent="ERC", group="RISK",
        timeline=45, first_meeting=60, created=-35,
        rationale="The operational resilience guideline requires tolerances to be set and tested by a "
                  "forum with authority over the critical operations; no single forum holds it today.",
        purpose_scope="Sets impact tolerances for critical operations, approves the scenario testing "
                      "programme and tracks remediation of vulnerabilities found in testing.",
        responsibilities="Approve impact tolerances; approve and review scenario tests; escalate tolerance "
                         "breaches to the Executive Risk Committee.")),
    ("AIGC", "returned", dict(
        forum_name="Artificial Intelligence Governance Council", forum_type="COUNCIL",
        requester="head.technology.risk", delegating_authority="chief.executive",
        sponsor="chief.information.officer", category="TECHNOLOGY", cadence="Monthly", parent="EXCO",
        group="TECH", timeline=60, first_meeting=75, created=-20,
        rationale="Business lines are piloting generative tools; use cases need a common approval route.",
        purpose_scope="Registers and approves artificial intelligence use cases and monitors their risks.",
        responsibilities="Approve high-risk use cases; maintain the use-case register.",
        questions="1. How does the council relate to the Model Risk Committee, which already approves models?\n"
                  "2. Would a working group under the Technology and Cyber Risk Committee be enough?\n"
                  "3. Who is the delegating authority for use-case approvals above the council's limit?")),
    ("CRWG", "evaluation", dict(
        forum_name="Climate Risk Working Group", forum_type="WORKING_GRP", requester="chief.risk.officer",
        delegating_authority="chief.executive", sponsor="chief.financial.officer", category="CLIMATE",
        cadence="Monthly", parent="ERC", group="RISK", timeline=90, first_meeting=100, created=-12,
        rationale="Supervisory expectations on climate scenario analysis need a coordinating forum.",
        purpose_scope="Coordinates climate scenario analysis, data and disclosures across risk and finance.",
        responsibilities="Run the climate scenario programme; recommend climate metrics to the Executive "
                         "Risk Committee.")),
    ("RPWG", "rejected", dict(
        forum_name="Retail Pricing Review Working Group", forum_type="WORKING_GRP",
        requester="head.retail.banking", delegating_authority="chief.executive",
        sponsor="chief.operating.officer", category="CONDUCT", cadence="Monthly", parent="CCC",
        group="ENTERPRISE", lob="PCB", timeline=-30, first_meeting=-20, created=-75,
        rationale="Pricing changes for retail products need a conduct review before launch.",
        purpose_scope="Reviews retail pricing changes for fair-value and conduct risk before launch.",
        responsibilities="Review pricing proposals; recommend to the product committee.",
        reason="Duplicates the Conduct and Culture Council's remit. The council's terms of reference are being "
               "extended to cover product fair-value reviews instead.")),
    ("PIF", "draft", dict(
        forum_name="Payments Innovation Forum", forum_type="ADVISORY", requester="head.retail.banking",
        delegating_authority="chief.operating.officer", sponsor="chief.information.officer", category="STRATEGIC",
        cadence="Bi-Monthly", parent="EXCO", group="ENTERPRISE", lob="PCB", timeline=120, first_meeting=130,
        created=-2,
        rationale="New payment schemes need a single place to assess their risk and opportunity.",
        purpose_scope="Advises on new payment schemes and their risks.",
        responsibilities="Advise the Executive Committee on payment scheme participation.")),
]

DGC_SEATS = [
    ("chief.information.officer", "CHAIR", -38, {}),
    ("records.manager", "FORUM_OWNER", -38, {}),
    ("chief.compliance.officer", "VOTING_MEMBER", -38, {}),
    ("head.retail.banking", "VOTING_MEMBER", -38, {}),
    ("risk.governance.analyst", "SECRETARY", -38, {"votes": 0, "quorum": 0}),
]


def section_formation(ctx: Ctx) -> None:
    """New formation requests at every stage, through the formation module's transitions."""
    frappe = ctx.frappe
    for key, stage, spec in FORMATION:
        if find(frappe, "Committee Formation Request", {"forum_name": spec["forum_name"]}):
            ctx.had("Committee Formation Request")
            continue
        _formation_request(ctx, key, stage, spec)
    if forum_of(ctx, "DGC"):
        _complete_dgc(ctx)


def _formation_request(ctx: Ctx, key: str, stage: str, spec: dict) -> None:
    from consilium.governance import formation

    frappe = ctx.frappe
    rgo_lead, analyst = U("risk.governance.lead"), U("risk.governance.analyst")
    created = spec["created"]
    request = frappe.get_doc({
        "doctype": "Committee Formation Request", "requester": U(spec["requester"]), "request_type": "Create",
        "is_new_committee": 1, "rationale": spec["rationale"], "purpose_scope": spec["purpose_scope"],
        "proposed_responsibilities": spec["responsibilities"],
        "delegating_authority": U(spec["delegating_authority"]), "proposed_timeline": ctx.d(spec["timeline"]),
        "first_meeting_date": ctx.d(spec["first_meeting"]), "forum_name": spec["forum_name"],
        "forum_type": spec["forum_type"], "primary_risk_category": spec["category"], "cadence": spec["cadence"],
        "jurisdictions": [{"jurisdiction": "NATIONAL"}], "parent_forum": forum_of(ctx, spec["parent"]),
        "owning_operating_group": spec["group"], "owning_line_of_business": spec.get("lob"),
        "forum_sponsor": U(spec["sponsor"]), "workflow_state": "Draft",
    }).insert(ignore_permissions=True)
    ctx.made("Committee Formation Request")
    name = request.name
    ctx.stamp("Committee Formation Request", name, ctx.ts(created, "10:00"), U(spec["requester"]))
    last = created
    if stage == "draft":
        return

    formation.submit(name)
    last = created + 1
    if stage == "returned":
        formation.start_evaluation(name)
        formation.return_to_originator(name, spec["questions"], by=rgo_lead)
        ctx.stamp("Committee Formation Request", name, None, None, returned_on=ctx.ts(created + 6, "15:00"),
                  modified=ctx.ts(created + 6, "15:00"))
        return

    formation.start_evaluation(name)
    if stage == "evaluation":
        formation.record_findings(name, [
            {"criterion": "Gap In Coverage", "assessment": "Pass",
             "comments": "Climate scenario work has no coordinating forum."},
            {"criterion": "Duplication", "assessment": "Pass", "comments": "No overlap found."},
        ], by=analyst)
        ctx.stamp("Committee Formation Request", name, None, None, modified=ctx.ts(created + 4, "16:00"))
        return

    if stage == "rejected":
        formation.record_findings(name, [
            {"criterion": c, "assessment": "Fail" if c == "Duplication" else a,
             "comments": "Overlaps the Conduct and Culture Council's mandate." if c == "Duplication" else note}
            for c, a, note in PASS_ALL
        ], completeness_confirmed=1, by=analyst)
        formation.reject(name, spec["reason"])
        ctx.stamp("Committee Formation Request", name, None, None, decided_on=ctx.d(created + 20),
                  modified=ctx.ts(created + 20, "12:00"))
        return

    formation.record_findings(name, [{"criterion": c, "assessment": a, "comments": n} for c, a, n in PASS_ALL],
                              completeness_confirmed=1, by=analyst)
    with role_holder_first(frappe, rgo_lead, "Risk Governance Office", ctx):
        raised = formation.raise_approval_steps(name)
    steps = {frappe.db.get_value("Approval Decision", d, "approval_step"): d for d in raised}
    for decision in raised:
        assignee = frappe.db.get_value("Approval Decision", decision, "assigned_to")
        if not str(assignee).endswith(f"@{DOMAIN}"):
            raise RuntimeError(f"{name}: approval step {decision} resolved to {assignee}, not a demo persona")
        ctx.stamp("Approval Decision", decision, ctx.ts(created + 8, "09:00"), rgo_lead)

    def decide(step: str, day: int, comments: str) -> None:
        decision = steps[step]
        assignee = frappe.db.get_value("Approval Decision", decision, "assigned_to")
        formation.record_step_decision(name, decision, "Approved", comments=comments, acting_user=assignee)
        ctx.stamp("Approval Decision", decision, None, None, decided_on=ctx.ts(created + day, "14:00"))

    decide("Risk Governance Office Evaluation", 10, "Evaluation complete; all criteria pass.")
    if stage == "pending_approval":
        decide("Sponsor Endorsement", 14, "Endorsed.")
        ctx.stamp("Committee Formation Request", name, None, None, modified=ctx.ts(created + 14, "14:00"))
        return

    decide("Delegating Authority Approval", 30, "Approved by the Executive Committee on the motion carried.")
    authorisation = formation.authorise_bypass(
        name, steps["Sponsor Endorsement"],
        "The sponsor endorsed the council at the Executive Committee sitting, where the motion was carried; "
        "the system endorsement could not be recorded while the sponsor was on leave.",
        approved_by=U("chief.risk.officer"))
    ctx.stamp("Exception Authorisation", authorisation.name, ctx.ts(created + 31, "11:00"), U("chief.risk.officer"),
              requested_by=rgo_lead, approved_on=ctx.ts(created + 31, "11:00"))
    ctx.stamp("Approval Decision", steps["Sponsor Endorsement"], None, None,
              decided_on=ctx.ts(created + 31, "11:00"))
    formation.approve(name)
    forum = frappe.db.get_value("Committee Formation Request", name, "created_forum")
    ctx.made("Governance Forum")
    ctx.stamp("Committee Formation Request", name, None, None, decided_on=ctx.d(created + 32),
              modified=ctx.ts(created + 32, "10:00"))
    ctx.stamp("Governance Forum", forum, ctx.ts(created + 32, "10:00"), rgo_lead)


def _complete_dgc(ctx: Ctx) -> None:
    """The council the approved request created: its seats, charter and first sitting."""
    frappe = ctx.frappe
    forum = forum_of(ctx, "DGC")
    doc = frappe.get_doc("Governance Forum", forum)
    if not doc.compliance_contact:
        doc.compliance_contact = U("second.line.reviewer")
        doc.retention_class = "GOV-FORUM"
        doc.governance_responsibilities = []
        doc.append("governance_responsibilities", {"governance_responsibility": "OVERSIGHT"})
        doc.escalation_threshold = "A data ownership dispute unresolved after two sittings."
        doc.quorum_value = 3
        doc.save(ignore_permissions=True)
    _seat_forum(ctx, forum, DGC_SEATS)
    title = "Data Governance Council Terms of Reference"
    if not find(frappe, "Committee Charter", {"charter_title": title}):
        from consilium.governance import charters

        request = frappe.db.get_value("Governance Forum", forum, "formation_request")
        charter = frappe.get_doc({"doctype": "Committee Charter", "charter_title": title, "forum": forum,
                                  "formation_request": request}).insert(ignore_permissions=True)
        charters.publish_version(charter.name, "Draft terms of reference from the approved request.",
                                 body_text=f"<h3>{title}</h3><p>{doc.description}</p>", version_label="0.1")
        ctx.made("Committee Charter")
        ctx.stamp("Committee Charter", charter.name, ctx.ts(-36, "10:00"), U("risk.governance.analyst"))
        _stamp_versions(ctx, "Committee Charter", charter.name, [-36])
    ensure_meetings(ctx, "DGC", [(25, S)])

# ==================================================== escalation configuration

MATRIX_CODE = "ENTERPRISE-ESC"

#: Tier-one risk types the matrix is scoped to. Deliberately not every type on
#: the site: matters other people raise against other types are not rerouted.
MATRIX_SCOPE = ["FINANCIAL", "PEOPLE", "PROCESS", "REGULATORY", "TECHNOLOGY", "THIRD_PARTY"]

MATRIX_RULES = [
    # code, priority, condition, severity, route role, sla, description, routes [(forum, role)], groups
    ("R10-APPETITE", 10, {"risk_appetite_breach": True}, "High", "Head of Risk Governance", "ESC-HIGH",
     "A breach of Board-approved risk appetite.",
     [("ERC", "Decision"), ("BRC", "Oversight")], ["Executive Risk Committee Members"]),
    ("R20-MATERIAL", 20, {"material_entity_impact": True}, "High", "Head of Risk Governance", "ESC-HIGH",
     "An impact on a material entity.", [("ERC", "Decision"), ("BRC", "Informed")],
     ["Executive Risk Committee Members"]),
    ("R30-PRIVACY", 30, {"tier_1_risk_type": "REGULATORY", "tier_2_risk_type": "REG_DATA"}, "High", None,
     "ESC-HIGH", "A personal-information breach.", [("ORC", "Decision"), ("ERC", "Oversight")],
     ["Compliance Function"]),
    ("R35-EMERGING", 35, {"escalation_type": "EMERGING_RISK"}, "Low", None, "ESC-LOW",
     "An emerging risk with no loss yet.", [("ORC", "Informed")], []),
    ("R40-MODEL", 40, {"tier_2_risk_type": "FIN_MODEL"}, "Medium", None, "ESC-MEDIUM",
     "A model failing validation or back-testing.", [("MRC", "Decision"), ("ERC", "Informed")],
     ["Risk Management Function"]),
    ("R45-CREDIT", 45, {"tier_2_risk_type": "FIN_LIMIT"}, "Medium", None, "ESC-MEDIUM",
     "A credit or concentration limit breach within appetite.", [("CRC", "Decision")], []),
    ("R50-TECH", 50, {"tier_1_risk_type": "TECHNOLOGY"}, "Medium", None, "ESC-MEDIUM",
     "A technology or cyber event.", [("TCRC", "Decision"), ("ORC", "Informed")],
     ["Technology and Operations Leadership"]),
    ("R55-THIRD", 55, {"tier_1_risk_type": "THIRD_PARTY"}, "Medium", None, "ESC-MEDIUM",
     "A third-party failure.", [("TPRWG", "Decision"), ("ORC", "Oversight")], []),
    ("R60-REG", 60, {"tier_1_risk_type": "REGULATORY"}, "Medium", None, "ESC-MEDIUM",
     "A regulatory breach.", [("ORC", "Decision")], ["Compliance Function"]),
    ("R70-CONDUCT", 70, {"tier_1_risk_type": "PEOPLE", "escalation_type": ["POLICY_BREACH", "INCIDENT"]},
     "Medium", None, "ESC-MEDIUM", "A conduct matter.", [("CCC", "Decision")], ["Compliance Function"]),
    ("R75-PROCESS", 75, {"tier_1_risk_type": "PROCESS"}, "Medium", None, "ESC-MEDIUM",
     "A process failure.", [("ORC", "Decision")], []),
    ("R99-DEFAULT", 999, {}, "Low", None, "ESC-LOW", "Anything else in scope.", [("ORC", "Decision")], []),
]

ESCALATION_TEMPLATES = [
    # code, title, type, scope, fields [(fieldname, when)]
    ("ESC-INCIDENT", "Incident escalation", "INCIDENT", "Escalation",
     [("escalation_date", "Always"), ("response_owner", "High Or Medium"), ("governance_forums", "High")]),
    ("AP-INCIDENT", "Incident action plan", "INCIDENT", "Action Plan", [("description", "Always")]),
    ("ESC-REGULATORY", "Regulatory matter escalation", "REG_MATTER", "Escalation",
     [("escalation_date", "Always"), ("response_owner", "Always")]),
    ("ESC-LIMIT", "Limit breach escalation", "LIMIT_BREACH", "Escalation",
     [("escalation_date", "Always"), ("response_owner", "Always")]),
    ("RA-LIMIT", "Limit breach risk acceptance", "LIMIT_BREACH", "Risk Acceptance",
     [("reassessment_frequency_months", "Always"), ("governance_forums", "Always")]),
]

DELEGATIONS = [
    # delegator, delegate, scope type, scope doctype, scope record (forum key), actions, from, to, reason
    ("chief.risk.officer", "head.operational.risk", "DocType", "Risk Acceptance", None, ["APPROVE", "REVIEW"],
     -8, 10, "Annual leave cover for the Chief Risk Officer."),
    ("chief.information.officer", "head.technology.risk", "Forum", "Governance Forum", "TCRC", ["APPROVE"],
     -300, -280, "Cover while the Chief Information Officer was on secondment."),
]


def section_escalation_config(ctx: Ctx) -> None:
    """The escalation matrix, templates per escalation type, and authority delegations."""
    frappe = ctx.frappe
    cro = U("chief.risk.officer")
    if find(frappe, "Escalation Matrix", MATRIX_CODE):
        ctx.had("Escalation Matrix")
    else:
        rules, routes, notifications = [], [], []
        for code, priority, condition, severity, role, sla_code, description, destinations, groups in MATRIX_RULES:
            rules.append({"rule_code": code, "priority": priority, "condition": json.dumps(condition),
                          "resulting_severity": severity, "route_to_role": role, "sla_definition": sla_code,
                          "is_active": 1, "rule_description": description})
            routes.extend({"rule_code": code, "governance_forum": forum_of(ctx, key), "role_in_escalation": r}
                          for key, r in destinations)
            notifications.extend({"rule_code": code, "user_group": g} for g in groups)
        matrix = frappe.get_doc({
            "doctype": "Escalation Matrix", "matrix_code": MATRIX_CODE, "title": "Enterprise escalation matrix",
            "scope_risk_types": [{"risk_type": r} for r in MATRIX_SCOPE],
            "effective_from": ctx.d(-540), "approved_by": cro, "approved_on": ctx.d(-545), "is_active": 1,
            "rules": rules, "routes": routes, "rule_notifications": notifications,
        }).insert(ignore_permissions=True)
        ctx.made("Escalation Matrix")
        ctx.stamp("Escalation Matrix", matrix.name, ctx.ts(-545, "10:00"), cro)

    for code, title, esc_type, scope, fields in ESCALATION_TEMPLATES:
        ensure(ctx, "Escalation Template", code, {
            "template_code": code, "title": title, "escalation_type": esc_type, "template_scope": scope,
            "is_active": 1,
            "template_fields": [{"fieldname": f, "is_required": 1, "required_when_severity": when,
                                 "display_order": i * 10} for i, (f, when) in enumerate(fields)],
        }, by=U("head.operational.risk"), when=ctx.ts(-540, "11:00"))

    for delegator, delegate, scope, scope_doctype, record, actions, start, end, reason in DELEGATIONS:
        ensure(ctx, "Authority Delegation",
               {"delegator": U(delegator), "delegate": U(delegate), "valid_from": ctx.d(start)}, {
                   "delegator": U(delegator), "delegate": U(delegate), "scope_type": scope,
                   "scope_doctype": scope_doctype, "scope_record": forum_of(ctx, record) if record else None,
                   "valid_from": ctx.d(start), "valid_to": ctx.d(end), "reason": reason,
                   "delegated_actions": [{"delegable_action": a} for a in actions],
               }, by=U(delegator), when=ctx.ts(start - 3, "17:00"))

# ============================================================== escalations

ESCALATIONS = [
    dict(key="E1", title="Critical payments processor outage breached its recovery time objective",
         type="INCIDENT", t1="THIRD_PARTY", t2="TP_SERVICE", identified=-300, opened=-299,
         identified_by="head.operational.risk", level="ENTERPRISE", accountable="chief.operating.officer",
         response="head.technology.risk", material=1,
         trigger="Card payments unavailable for 6 hours 40 minutes against a 4-hour recovery time objective.",
         description="The third-party card processor suffered a data-centre failure. Failover to its secondary "
                     "site did not complete, and card authorisations failed for 6 hours 40 minutes.",
         impacted=[("Material Entity", "ME_BANK", "Deposit-taking entity's card payments unavailable."),
                   ("Business Unit", "PCB_CARDS", "All card authorisations declined during the outage.")],
         status="Closed", closed=-200,
         closure=("Resolved", "Secondary processing site live and tested; exit plan revised; residual risk "
                              "accepted for the interim and since expired."),
         reviews=[(1, "second.line.reviewer", -290, -287, "Accepted", "Treatment plan is proportionate.")],
         plans=[("Establish an active secondary processing site with the provider", -295, -210,
                 "chief.operating.officer", "head.technology.risk", "Completed",
                 "Contract amendment and failover testing for an active-active secondary site."),
                ("Revise the payments processing exit plan", -290, -230, "chief.operating.officer",
                 "head.operational.risk", "Completed", "Exit plan rewritten with a tested alternative provider.")],
         acceptances=[dict(name="Accept single-site processing risk until the secondary site is live",
                           start=-285, end=-205, accountable="chief.operating.officer", months=1,
                           rationale="No alternative processor can be onboarded before the secondary site "
                                     "is live; manual fallback procedures reduce the impact.",
                           approve=("chief.risk.officer", -284), final="Expired")]),
    dict(key="E2", title="Retail mortgage probability-of-default model failed back-testing",
         type="LIMIT_BREACH", t1="FINANCIAL", t2="FIN_MODEL", identified=-75, opened=-74,
         identified_by="head.model.risk", level="LINE_OF_BUSINESS", accountable="chief.risk.officer",
         response="head.model.risk",
         trigger="Seven back-testing exceptions in the quarter against a tolerance of four.",
         description="Quarterly back-testing of the retail mortgage PD model shows systematic under-prediction "
                     "for recent vintages, driven by the rate environment.",
         impacted=[("Line of Business", "PCB", "Mortgage provisions and capital may be understated."),
                   ("Legal Entity", "BANK_SUB", None)],
         status="Under Review",
         reviews=[(1, "second.line.reviewer", -60, -55, "Challenged",
                   "The overlay's calibration evidence is thin: show the sensitivity to the rate path."),
                  (2, "second.line.reviewer", -10, None, None, None)],
         plans=[("Redevelop and validate the mortgage PD model", -60, 120, "chief.risk.officer",
                 "head.model.risk", "In Progress", "Redevelopment on recent vintages; independent validation.")],
         acceptances=[dict(name="Temporary management overlay on mortgage PD pending redevelopment",
                           start=-40, end=140, accountable="chief.risk.officer", months=3, forums=["MRC"],
                           rationale="An overlay of 12 basis points holds provisions at a prudent level "
                                     "until the redeveloped model is validated.",
                           request="chief.risk.officer", final="Pending Approval")]),
    dict(key="E3", title="Transaction-monitoring alert backlog exceeded the service standard",
         type="REG_MATTER", t1="PROCESS", t2="PROCESS_EXEC", identified=-120, opened=-119,
         identified_by="chief.compliance.officer", level="OPERATING_GROUP", accountable="chief.compliance.officer",
         response="head.retail.banking", sensitive=1, severity="High",
         trigger="4,800 alerts older than 30 days against a service standard of none.",
         description="A scenario change doubled alert volumes and investigation capacity was not increased. "
                     "Aged alerts create a risk of late suspicious-transaction reports.",
         impacted=[("Business Unit", "PCB_RETAIL", None), ("Material Entity", "ME_BANK", None)],
         status="In Progress", breach=True, violation="V-AML",
         plans=[("Clear the aged alert backlog with surge capacity", -110, -20, "chief.compliance.officer",
                 "head.retail.banking", "In Progress", "Surge team of twelve investigators for eight weeks."),
                ("Retune scenario thresholds to reduce false positives", -90, 60, "chief.compliance.officer",
                 "second.line.reviewer", "Open", "Below-the-line testing and retuning of three scenarios.")]),
    dict(key="E4", title="Customer statements sent to superseded addresses after a data migration",
         type="INCIDENT", t1="REGULATORY", t2="REG_DATA", identified=-25, opened=-25,
         identified_by="head.retail.banking", level="BUSINESS_UNIT", accountable="head.retail.banking",
         response="chief.compliance.officer", sensitive=1,
         trigger="1,240 statements mailed to prior addresses; personal information disclosed to third parties.",
         description="A customer-address migration reverted recent address changes. Statements were printed "
                     "and mailed before the defect was detected.",
         impacted=[("Business Unit", "PCB_RETAIL", "1,240 customers affected."),
                   ("Legal Entity", "BANK_SUB", None)],
         status="Pending Review",
         plans=[("Notify affected customers and the data protection authority", -24, 5, "head.retail.banking",
                 "chief.compliance.officer", "In Progress", "Notification letters and a regulator report.")]),
    dict(key="E5", title="Targeted phishing campaign against finance staff",
         type="INCIDENT", t1="TECHNOLOGY", t2="TECH_CYBER", identified=-160, opened=-160,
         identified_by="head.technology.risk", level="ENTERPRISE", accountable="chief.information.officer",
         response="head.technology.risk",
         trigger="Three credential compromises confirmed from 212 targeted messages.",
         description="A targeted campaign impersonated a supplier's invoicing portal. Three finance users "
                     "entered credentials; no payment fraud occurred.",
         impacted=[("Business Unit", "TECH_SECURITY", None)],
         status="Closed", closed=-125,
         closure=("Resolved", "Credentials reset, phishing-resistant authentication enforced for finance, "
                              "no loss."),
         plans=[("Enforce phishing-resistant multi-factor authentication for finance", -158, -125,
                 "chief.information.officer", "head.technology.risk", "Completed",
                 "Hardware keys for all finance and treasury staff.")]),
    dict(key="E6", title="Quarterly regulatory capital return submitted two business days late",
         type="REG_MATTER", t1="REGULATORY", t2="REG_REPORTING", identified=-210, opened=-210,
         identified_by="chief.financial.officer", level="ENTERPRISE", accountable="chief.financial.officer",
         response="treasurer",
         trigger="Submission two business days after the regulatory deadline.",
         description="A reconciliation break in the capital calculation delayed sign-off of the return.",
         impacted=[("Legal Entity", "BANK_SUB", None)],
         status="Closed — Tracked Externally", closed=-172, external=("GRC_PLATFORM", "ISSUE-4412"),
         closure=("Transferred Externally", "Remediation of the reconciliation process is tracked in the "
                                            "external issue-management platform.")),
    dict(key="E7", title="Commercial real estate concentration above the risk appetite limit",
         type="LIMIT_BREACH", t1="FINANCIAL", t2="FIN_LIMIT", identified=-60, opened=-59,
         identified_by="chief.risk.officer", level="ENTERPRISE", accountable="chief.risk.officer",
         response="head.retail.banking", appetite=1,
         trigger="Exposure at 13.2 per cent of capital against a 12 per cent appetite limit.",
         description="Drawdowns on committed construction facilities took commercial real estate exposure "
                     "above its appetite limit.",
         impacted=[("Line of Business", "PCB", None), ("Material Entity", "ME_BANK", None)],
         status="In Progress", breach=True, appetite_ref=("RISK_REGISTER", "RAS-CRE-01"),
         plans=[("Reduce concentration through syndication and origination limits", -45, 90,
                 "chief.risk.officer", "head.retail.banking", "In Progress",
                 "Syndicate two facilities and pause new construction lending.")],
         acceptances=[dict(name="Temporary exceedance of the commercial real estate concentration limit",
                           start=-29, end=150, accountable="chief.risk.officer", months=3, forums=["ERC"],
                           rationale="Reduction below the limit within two quarters is achievable through "
                                     "syndication; forced sales would crystallise losses.",
                           motion=CRE_MOTION, final="Approved")]),
    dict(key="E8", title="Key-person dependency in treasury liquidity operations",
         type="EMERGING_RISK", t1="PEOPLE", t2="PEOPLE_KEY", identified=-10, opened=-10,
         identified_by="treasurer", level="BUSINESS_UNIT", accountable="chief.financial.officer",
         response="treasurer",
         trigger="Two of three intraday liquidity specialists resigning within the quarter.",
         description="Intraday liquidity management depends on three specialists; two have resigned.",
         impacted=[("Business Unit", "CM_TREASURY", None)], status="Open"),
    dict(key="E9", title="Unapproved emergency change caused a four-hour core banking outage",
         type="INCIDENT", t1="PROCESS", t2="PROCESS_CHANGE", identified=-40, opened=-40,
         identified_by="head.technology.risk", level="ENTERPRISE", accountable="chief.information.officer",
         response="head.technology.risk", material=1, violation="V-CHANGE",
         trigger="Core banking unavailable for 4 hours 5 minutes; the change bypassed approval.",
         description="An emergency database change was deployed without change advisory board approval and "
                     "failed; the back-out plan had not been tested.",
         impacted=[("Material Entity", "ME_BANK", "Branch and online banking unavailable."),
                   ("Business Unit", "TECH_INFRA", None)],
         status="Under Review",
         reviews=[(1, "second.line.reviewer", -30, -26, "Accepted", "Root cause and actions are adequate.")],
         plans=[("Enforce technical change-freeze controls in the pipeline", -35, -5, "chief.information.officer",
                 "head.technology.risk", "In Progress", "Pipeline blocks deployment without an approved change."),
                ("Root-cause review of the emergency change process", -38, -20, "chief.information.officer",
                 "head.technology.risk", "Completed", "Review completed; findings adopted.")],
         acceptances=[dict(name="Continue operating the end-of-life database platform until migration",
                           start=-5, end=100, accountable="chief.information.officer", months=2,
                           rationale="Migration is scheduled; extended vendor support covers the interim.",
                           approve=("head.operational.risk", -4), request="chief.risk.officer", final="Approved")]),
    dict(key="E10", title="Rising trend in sales-practice complaints",
         type="POLICY_BREACH", t1="PEOPLE", t2="PEOPLE_CONDUCT", identified=-5, opened=-5,
         identified_by="chief.compliance.officer", level="LINE_OF_BUSINESS", accountable="head.retail.banking",
         response="chief.compliance.officer",
         trigger="Complaints up 38 per cent quarter on quarter in two regions.",
         description="Complaints about products sold without a documented needs assessment are rising in two "
                     "regions following a sales campaign.",
         impacted=[("Line of Business", "PCB", None)], status="Open"),
    dict(key="E11", title="Concentration of critical workloads with a single cloud provider",
         type="EMERGING_RISK", t1="THIRD_PARTY", t2="TP_CONCENTRATION", identified=-90, opened=-90,
         identified_by="head.technology.risk", level="ENTERPRISE", accountable="chief.information.officer",
         response="head.technology.risk",
         trigger="Seven of twelve critical operations depend on one cloud provider.",
         description="The concentration assessment found most critical workloads hosted by one provider.",
         impacted=[("Business Unit", "TECH_INFRA", None)], status="Closed", closed=-62,
         closure=("Risk Accepted", "Concentration accepted within appetite for twelve months while a "
                                   "multi-provider assessment is completed."),
         acceptances=[dict(name="Accept single-provider concentration pending the multi-provider assessment",
                           start=-66, end=300, accountable="chief.information.officer", months=6,
                           rationale="Exit plans are tested and the provider's regional redundancy is adequate.",
                           approve=("chief.risk.officer", -65), final="Approved")]),
]

PERIODS = [(-3, "Accepted"), (-2, "Accepted"), (-1, "Submitted"), (0, "Draft")]


def _violation_of(ctx: Ctx, key: str) -> str | None:
    row = next(v for v in VIOLATIONS if v[0] == key)
    return find(ctx.frappe, "Policy Violation", {"document": doc_of(ctx, row[1]), "description": row[8]})


def _motion_on(ctx: Ctx, forum_key: str, day: int) -> str | None:
    return find(ctx.frappe, "Forum Motion", {"forum": forum_of(ctx, forum_key), "decision_date": str(ctx.weekday(day))})


def _external_reference(ctx: Ctx, system: str, key: str, matter: str, label: str, day: int) -> str:
    name, _created = ensure(ctx, "External Reference", {"external_system": system, "external_key": key}, {
        "subject_doctype": "Escalation Matter", "subject_name": matter, "external_system": system,
        "external_key": key, "label": label, "last_seen_on": ctx.d(-2),
    }, by=U("risk.governance.analyst"), when=ctx.ts(day, "12:00"))
    return name


def _matter(ctx: Ctx, spec: dict) -> None:
    frappe = ctx.frappe
    if find(frappe, "Escalation Matter", {"escalation_title": spec["title"]}):
        ctx.had("Escalation Matter")
        return
    opened = spec["opened"]
    values = {
        "doctype": "Escalation Matter", "escalation_title": spec["title"], "escalation_type": spec["type"],
        "escalation_identification_date": ctx.d(spec["identified"]), "escalation_date": ctx.d(opened),
        "description": spec["description"], "tier_1_risk_type": spec["t1"], "tier_2_risk_type": spec["t2"],
        "impacted_entities": [{"entity_type": kind, "entity_value": value, "impact_note": note}
                              for kind, value, note in spec["impacted"]],
        "identified_by": U(spec["identified_by"]), "organizational_level": spec["level"],
        "accountable_executive": U(spec["accountable"]), "response_owner": U(spec.get("response")),
        "escalation_trigger": spec["trigger"], "material_entity_impact": spec.get("material", 0),
        "risk_appetite_breach": spec.get("appetite", 0), "sensitive": spec.get("sensitive", 0),
        "source_policy_violation": _violation_of(ctx, spec["violation"]) if spec.get("violation") else None,
        "status": "Open", "opened_on": ctx.ts(opened, "08:30"), "retention_class": "ESC-MATTER",
        "reviews": [{"round": rnd, "reviewer": U(reviewer), "review_line": "2LOD",
                     "received_on": ctx.ts(received, "09:00"),
                     "responded_on": ctx.ts(responded, "17:00") if responded else None,
                     "outcome": outcome, "comments": comments}
                    for rnd, reviewer, received, responded, outcome, comments in spec.get("reviews", [])],
    }
    if spec.get("severity"):
        # The accountable executive judged the matter more severe than the
        # matrix proposes: a recorded manual override.
        values.update(severity=spec["severity"], severity_source="Manual Override")
    matter = frappe.get_doc(values).insert(ignore_permissions=True)
    name = matter.name
    ctx.made("Escalation Matter")
    last = opened
    ctx.stamp("Escalation Matter", name, ctx.ts(opened, "08:30"), U(spec["identified_by"]))
    clock = frappe.db.get_value("Escalation Matter", name, "sla_clock")
    if clock:
        ctx.stamp("SLA Clock", clock, ctx.ts(opened, "08:30"), None)

    if spec.get("appetite_ref"):
        system, key = spec["appetite_ref"]
        matter = frappe.get_doc("Escalation Matter", name)
        matter.risk_appetite_reference = _external_reference(
            ctx, system, key, name, "Commercial real estate concentration appetite statement", opened)
        matter.save(ignore_permissions=True)
    if spec.get("violation"):
        violation = frappe.get_doc("Policy Violation", _violation_of(ctx, spec["violation"]))
        violation.resulting_escalation = name
        violation.save(ignore_permissions=True)

    decision_forums = [row.governance_forum for row in frappe.get_doc("Escalation Matter", name).governance_forums
                       if row.role_in_escalation == "Decision"]
    for title, start, end, accountable, owner, status, description in spec.get("plans", []):
        plan = frappe.get_doc({
            "doctype": "Action Plan", "escalation_matter": name, "action_plan_name": title,
            "start_date": ctx.d(start), "end_date": ctx.d(end), "accountable_executive": U(accountable),
            "owner_user": U(owner), "status": status, "description": description,
            "governance_forums": [{"governance_forum": f} for f in decision_forums[:1]],
        }).insert(ignore_permissions=True)
        ctx.made("Action Plan")
        extra = {"completed_on": ctx.ts(end, "17:00")} if status == "Completed" else {}
        ctx.stamp("Action Plan", plan.name, ctx.ts(start, "11:00"), U(owner),
                  **({"modified": ctx.ts(end, "17:00")} if status == "Completed" else {}), **extra)

    for acceptance in spec.get("acceptances", []):
        last = max(last, _risk_acceptance(ctx, name, acceptance))

    if spec["status"] not in ("Open",):
        matter = frappe.get_doc("Escalation Matter", name)
        if spec.get("closed") is not None:
            closed = spec["closed"]
            kind, summary = spec["closure"]
            external = None
            if spec.get("external"):
                system, key = spec["external"]
                external = _external_reference(ctx, system, key, name, "Reconciliation remediation issue", closed)
            closure = frappe.get_doc({
                "doctype": "Escalation Closure", "escalation_matter": name, "closure_type": kind,
                "closure_summary": summary, "approved_by": U(spec["accountable"]),
                "approved_on": ctx.ts(closed, "16:00"), "external_reference": external,
                "criteria_met": [
                    {"criterion": "Root cause identified and recorded", "required": 1, "met": 1,
                     "evidence_note": "Root-cause analysis attached to the incident record."},
                    {"criterion": "Actions complete, accepted or transferred", "required": 1, "met": 1},
                    {"criterion": "Lessons learned shared with the owning forum", "required": 0, "met": 1},
                ],
            }).insert(ignore_permissions=True)
            ctx.made("Escalation Closure")
            ctx.stamp("Escalation Closure", closure.name, ctx.ts(closed, "16:00"), U(spec["accountable"]))
            matter.response_template_completed = 1
            matter.external_reference = external
            matter.closed_on = ctx.ts(closed, "16:30")
            last = closed
        matter.status = spec["status"]
        matter.save(ignore_permissions=True)

    if spec.get("breach"):
        _breach(ctx, name)
    ctx.stamp("Escalation Matter", name, None, None, modified=ctx.ts(max(last, opened + 3), "17:15"))


def _risk_acceptance(ctx: Ctx, matter: str, spec: dict) -> int:
    """Draft, then approved by a forum motion or through the Core approval path."""
    from consilium.escalation import approvals

    frappe = ctx.frappe
    doc = frappe.get_doc({
        "doctype": "Risk Acceptance", "escalation_matter": matter, "risk_acceptance_name": spec["name"],
        "start_date": ctx.d(spec["start"]), "end_date": ctx.d(spec["end"]),
        "accountable_executive": U(spec["accountable"]), "rationale": spec["rationale"],
        "reassessment_frequency_months": spec["months"], "status": "Draft",
        "governance_forums": [{"governance_forum": forum_of(ctx, k)} for k in spec.get("forums", [])],
    }).insert(ignore_permissions=True)
    ctx.made("Risk Acceptance")
    name = doc.name
    day = spec["start"] - 1
    ctx.stamp("Risk Acceptance", name, ctx.ts(spec["start"] - 3, "10:00"), U(spec["accountable"]))
    if spec.get("motion"):
        doc.approval_motion = _motion_on(ctx, *spec["motion"])
        doc.status = "Approved"
        doc.save(ignore_permissions=True)
    elif spec.get("approve"):
        acting, day = spec["approve"]
        approver = spec.get("request", acting)
        decision = approvals.request_approval(name, U(approver), required_role="Head of Risk Governance")
        approvals.record_approval(name, "Approved", acting_user=U(acting),
                                  comments="Accepted for the period stated, with the reassessment cadence.")
        ctx.stamp("Approval Decision", decision.name, ctx.ts(day - 2, "09:00"), U(spec["accountable"]),
                  decided_on=ctx.ts(day, "15:00"))
        ctx.stamp("Risk Acceptance", name, None, None, approved_on=ctx.ts(day, "15:00"))
        doc.reload()
        doc.status = "Approved"
        doc.save(ignore_permissions=True)
    elif spec.get("request"):
        decision = approvals.request_approval(name, U(spec["request"]), required_role="Head of Risk Governance")
        ctx.stamp("Approval Decision", decision.name, ctx.ts(spec["start"] - 2, "09:00"), U(spec["accountable"]))
        doc.reload()
        doc.status = "Pending Approval"
        doc.save(ignore_permissions=True)
    if spec["final"] == "Expired":
        doc.reload()
        doc.status = "Expired"
        doc.save(ignore_permissions=True)
        day = spec["end"]
    return day


def _breach(ctx: Ctx, matter: str) -> None:
    """Mark an overdue clock breached and let the escalation module raise the matter.

    This is the per-clock body of the daily sweep, applied only to the demo's
    own matters so nobody else's clocks are touched.
    """
    from consilium.escalation import resolution
    from frappe.utils import get_datetime, now

    frappe = ctx.frappe
    clock_name = frappe.db.get_value("Escalation Matter", matter, "sla_clock")
    if not clock_name:
        return
    clock = frappe.get_doc("SLA Clock", clock_name)
    if not clock.is_open or get_datetime(clock.target_on) >= get_datetime(now()):
        return
    clock.status = "Breached"
    clock.breached_on = clock.target_on
    clock.save(ignore_permissions=True)
    resolution.record_breach(frappe.get_doc("Escalation Matter", matter), clock.name, clock.breached_on)


def _quarter(ctx: Ctx, offset: int) -> tuple[str, date, date]:
    start_month = 3 * ((ctx.anchor.month - 1) // 3) + 1
    index = ctx.anchor.year * 4 + (start_month - 1) // 3 + offset
    year, q = divmod(index, 4)
    start = date(year, q * 3 + 1, 1)
    nxt = date(year + (q == 3), (q * 3 + 3) % 12 + 1, 1)
    return f"{year}-Q{q + 1}", start, nxt - timedelta(days=1)


def section_escalations(ctx: Ctx) -> None:
    """Matters at every stage, with plans, acceptances, closures and periodic returns."""
    frappe = ctx.frappe
    for spec in ESCALATIONS:
        _matter(ctx, spec)

    for offset, status in PERIODS:
        label, start, end = _quarter(ctx, offset)
        if find(frappe, "Periodic Submission", {"period_label": label}):
            ctx.had("Periodic Submission")
            continue
        doc = frappe.get_doc({
            "doctype": "Periodic Submission", "period_label": label, "period_start": str(start),
            "period_end": str(end), "scope_filter": "{}", "status": "Draft",
        }).insert(ignore_permissions=True)
        ctx.made("Periodic Submission")
        by = U("risk.governance.lead")
        ctx.stamp("Periodic Submission", doc.name, f"{end} 12:00:00", by)
        if status == "Draft":
            continue
        doc.nil_return = 0 if doc.count_matters() else 1
        doc.status = "Submitted"
        doc.save(ignore_permissions=True)
        if status == "Accepted":
            doc.status = "Accepted"
            doc.save(ignore_permissions=True)
        submitted = f"{end + timedelta(days=12)} 15:00:00"
        ctx.stamp("Periodic Submission", doc.name, None, None, submitted_on=submitted, submitted_by=by,
                  modified=submitted)


# ============================================================ attestations

INVENTORY_FORUMS = ["BOARD", "BRC", "AC", "EXCO", "ERC", "ORC", "TCRC", "MRC", "CRC", "ALCO", "CCC", "TPRWG", "DGC"]
DUAL_REVIEW_FORUMS = {"ERC": "sign", "BRC": "sign", "CRC": "sign", "ALCO": "respond", "EXCO": None}
EXCEPTIONS = {
    "TCRC": ("Attested With Exceptions", "Membership is accurate; the charter is not yet approved for the "
                                         "extended mandate."),
    "CCC": ("Declined", "The council's terms of reference are not yet approved, so the record cannot be "
                        "attested as accurate."),
}


def section_attestation(ctx: Ctx) -> None:
    """Three campaigns on Core's engine: last year's inventory (closed), this year's
    inventory (open, partly answered), the dual-signed annual review, and the
    governing-document attestation."""
    frappe = ctx.frappe
    from consilium.consilium_core import attestation
    from consilium.governance import reviews

    year = ctx.anchor.year
    forums = [f for f in (forum_of(ctx, k) for k in INVENTORY_FORUMS) if f]
    by_forum = {forum_of(ctx, k): k for k in INVENTORY_FORUMS}
    attested_on: dict[str, str] = {}

    def campaign_exists(kind: str, label: str) -> str | None:
        return find(frappe, "Attestation Campaign", {"campaign_type": kind, "period_label": label})

    # Last year's inventory attestation: every seat answered, campaign closed.
    label = str(year - 1)
    if campaign_exists(reviews.INVENTORY_CAMPAIGN, label):
        ctx.had("Attestation Campaign")
    else:
        campaign = reviews.open_inventory_attestation(label, opens_on=ctx.d(-260), due_on=ctx.d(-200),
                                                      population_filter={"name": ["in", forums]})
        ctx.made("Attestation Campaign")
        result = reviews.generate(campaign)
        for index, task in enumerate(result["created"]):
            attestation.respond(task, "Attested", statement="Membership, mandate and reporting lines confirmed.")
            responded = ctx.ts(-240 + index % 25, "10:00")
            ctx.stamp("Attestation Task", task, ctx.ts(-260, "08:00"), None, responded_on=responded)
        ctx.made("Attestation Task", len(result["created"]))
        doc = frappe.get_doc("Attestation Campaign", campaign.name)
        doc.status = "Closed"
        doc.save(ignore_permissions=True)
        ctx.stamp("Attestation Campaign", campaign.name, ctx.ts(-262, "09:00"), U("risk.governance.lead"),
                  generated_on=ctx.ts(-260, "08:00"), modified=ctx.ts(-195, "17:00"))

    # This year's: open, due shortly, about two thirds answered.
    label = str(year)
    if campaign_exists(reviews.INVENTORY_CAMPAIGN, label):
        ctx.had("Attestation Campaign")
    else:
        campaign = reviews.open_inventory_attestation(label, opens_on=ctx.d(-45), due_on=ctx.d(15),
                                                      population_filter={"name": ["in", forums]})
        campaign.append("reminder_schedule", {"offset_days": -14, "channel": "IN_APP",
                                              "note": "Two weeks before the due date."})
        campaign.append("reminder_schedule", {"offset_days": -3, "channel": "IN_APP", "note": "Final reminder."})
        campaign.save(ignore_permissions=True)
        ctx.made("Attestation Campaign")
        result = reviews.generate(campaign)
        ctx.made("Attestation Task", len(result["created"]))
        for index, task in enumerate(result["created"]):
            subject = frappe.db.get_value("Attestation Task", task, "subject_name")
            key = by_forum.get(subject)
            ctx.stamp("Attestation Task", task, ctx.ts(-45, "08:00"), None)
            if key in EXCEPTIONS:
                status, statement = EXCEPTIONS[key]
                attestation.respond(task, status, statement=statement)
            elif index % 3 == 2:
                continue
            else:
                attestation.respond(task, "Attested", statement="Record confirmed as accurate.")
            responded = ctx.ts(-40 + index % 30, "11:00")
            ctx.stamp("Attestation Task", task, None, None, responded_on=responded)
            attested_on[subject] = max(attested_on.get(subject, ""), responded[:10])
        ctx.stamp("Attestation Campaign", campaign.name, ctx.ts(-46, "09:00"), U("risk.governance.lead"),
                  generated_on=ctx.ts(-45, "08:00"))
        from consilium.governance import inventory

        inventory.refresh_last_attested(campaign.name)
        for forum, day in attested_on.items():
            ctx.stamp("Governance Forum", forum, None, None, last_attested_on=day)

    # The dually-signed forum owner and compliance review.
    if campaign_exists(reviews.DUAL_CAMPAIGN, label):
        ctx.had("Attestation Campaign")
    else:
        population = [forum_of(ctx, k) for k in DUAL_REVIEW_FORUMS]
        campaign = reviews.open_annual_review(label, opens_on=ctx.d(-30), due_on=ctx.d(60),
                                              population_filter={"name": ["in", population]})
        ctx.made("Attestation Campaign")
        result = reviews.generate(campaign)
        ctx.made("Attestation Task", len(result["created"]))
        ctx.stamp("Attestation Campaign", campaign.name, ctx.ts(-31, "09:00"), U("risk.governance.lead"),
                  generated_on=ctx.ts(-30, "08:00"))
        for index, task in enumerate(result["created"]):
            row = frappe.db.get_value("Attestation Task", task, ["subject_name", "second_signatory"], as_dict=True)
            step = DUAL_REVIEW_FORUMS.get(by_forum.get(row.subject_name))
            ctx.stamp("Attestation Task", task, ctx.ts(-30, "08:00"), None)
            if not step:
                continue
            attestation.respond(task, "Attested", statement="Forum operating within its charter; membership "
                                                            "and quorum confirmed.")
            ctx.stamp("Attestation Task", task, None, None, responded_on=ctx.ts(-20 + index, "10:00"))
            if step != "sign":
                continue
            attestation.second_sign(task, user=row.second_signatory)
            review = reviews.record_annual_review(task, "Compliant",
                                                  comments="Annual review dually signed by the forum owner and "
                                                           "compliance.")
            ctx.made("Forum Compliance Review")
            ctx.stamp("Attestation Task", task, None, None, second_signed_on=ctx.ts(-15 + index, "16:00"))
            ctx.stamp("Forum Compliance Review", review.name, ctx.ts(-15 + index, "16:30"), row.second_signatory,
                      decided_on=ctx.ts(-15 + index, "16:30"))

    # Governing document attestation, to each document owner.
    if campaign_exists("Governing Document", label):
        ctx.had("Attestation Campaign")
    else:
        documents = [d for d in (doc_of(ctx, k) for k, _spec in DOCUMENTS) if d]
        campaign = frappe.get_doc({
            "doctype": "Attestation Campaign", "campaign_title": f"Governing document attestation {label}",
            "campaign_type": "Governing Document", "period_label": label, "target_doctype": "Governing Document",
            "population_filter": json.dumps({"is_active": 1, "name": ["in", documents]}),
            "participant_source": "Record Field", "participant_field": "document_owner",
            "opens_on": ctx.d(-20), "due_on": ctx.d(40), "status": "Open",
            "reminder_schedule": [{"offset_days": -7, "channel": "WEEKLY_DIGEST", "note": "Weekly digest."}],
        }).insert(ignore_permissions=True)
        ctx.made("Attestation Campaign")
        result = attestation.generate_tasks(campaign)
        ctx.made("Attestation Task", len(result["created"]))
        ctx.stamp("Attestation Campaign", campaign.name, ctx.ts(-21, "09:00"), U("policy.office.lead"),
                  generated_on=ctx.ts(-20, "08:00"))
        for index, task in enumerate(result["created"]):
            ctx.stamp("Attestation Task", task, ctx.ts(-20, "08:00"), None)
            if index % 2:
                continue
            attestation.respond(task, "Attested", statement="Document is current, owned and in force as published.")
            ctx.stamp("Attestation Task", task, None, None, responded_on=ctx.ts(-15 + index, "14:00"))

# ------------------------------------------------------------- SECTIONS-END


# ============================================================ final stamping

#: Side-effect records and the link that ties each to its subject:
#: (doctype, how the subject is named) where the second element is either
#: ("dynamic", doctype field, name field) or ("fixed", parent doctype, field).
DERIVED = [
    ("Approval Decision", ("dynamic", "subject_doctype", "subject_name")),
    ("Document Version", ("dynamic", "subject_doctype", "subject_name")),
    ("Classification Assessment", ("dynamic", "subject_doctype", "subject_name")),
    ("SLA Clock", ("dynamic", "subject_doctype", "subject_name")),
    ("Notification Dispatch", ("dynamic", "subject_doctype", "subject_name")),
    ("Exception Authorisation", ("dynamic", "subject_doctype", "subject_name")),
    ("External Reference", ("dynamic", "subject_doctype", "subject_name")),
    ("Metadata Remediation Task", ("dynamic", "subject_doctype", "subject_name")),
    ("Governance Refusal Log", ("dynamic", "subject_doctype", "subject_name")),
    ("ToDo", ("dynamic", "reference_type", "reference_name")),
    ("Comment", ("dynamic", "reference_doctype", "reference_name")),
    ("Version", ("dynamic", "ref_doctype", "docname")),
    ("Forum Vote", ("fixed", "Forum Motion", "motion")),
    ("Attestation Task", ("fixed", "Attestation Campaign", "campaign")),
    ("Document Review Cycle", ("fixed", "Governing Document", "document")),
    ("Document Publication", ("fixed", "Governing Document", "document")),
    ("Contact", ("fixed", "User", "user")),
]

SWEEP_OWNER = "risk.governance.lead"


def section_stamping(ctx: Ctx) -> None:
    """Back-date what the platform stamped 'now', then give side-effect records a demo owner."""
    frappe = ctx.frappe
    applied = 0
    for doctype, name, when, by, fields in ctx.stamps:
        values = dict(fields)
        if when:
            values.update(creation=when, modified=when)
        if by:
            values.update(owner=by, modified_by=by)
        if not values or not frappe.db.exists(doctype, name):
            continue
        # A re-run stamps records that already carry the story's dates; leaving
        # those alone is what lets a second run report that nothing changed.
        current = frappe.db.get_value(doctype, name, list(values), as_dict=True) or {}
        if all(_same(current.get(field), value) for field, value in values.items()):
            continue
        frappe.db.set_value(doctype, name, values, update_modified=False)
        applied += 1
    print(f"  back-dated {applied} records")
    print(f"  gave {_sweep_all(frappe)} side-effect records a demo owner")


def _same(current, wanted) -> bool:
    """Whether a stored value already equals the one a stamp would write."""
    if current is None or wanted is None:
        return current is None and wanted is None
    if isinstance(current, datetime):
        return current.replace(microsecond=0) == _as_datetime(wanted)
    return str(current) == str(wanted)


def _as_datetime(value) -> datetime | None:
    text = str(value)
    for pattern, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], pattern)
        except ValueError:
            continue
    return None


def _sweep_all(frappe) -> int:
    """Give every side-effect record that hangs off a demo record a demo owner."""
    owner = U(SWEEP_OWNER)
    like = f"%@{DOMAIN}"
    swept = 0
    # Repeated until nothing changes: some side effects hang off other side
    # effects (a version-log row of a vote, a dispatch about an attestation task).
    for _pass in range(4):
        found = _sweep_pass(frappe, owner, like)
        swept += found
        if not found:
            break
    return swept


def _sweep_pass(frappe, owner: str, like: str) -> int:
    swept = 0
    for doctype, link in DERIVED:
        if not frappe.db.table_exists(doctype):
            continue
        table = f"tab{doctype}"
        if link[0] == "fixed":
            _kind, parent, field = link
            swept += _sweep(frappe, table, f"tab{parent}", field, owner, like)
            continue
        _kind, dt_field, name_field = link
        for subject_doctype in frappe.db.sql_list(
            f'SELECT DISTINCT "{dt_field}" FROM "{table}" WHERE "owner" = %s AND "{dt_field}" IS NOT NULL',
            ("Administrator",),
        ):
            if not subject_doctype or not frappe.db.table_exists(subject_doctype):
                continue
            swept += _sweep(frappe, table, f"tab{subject_doctype}", name_field, owner, like,
                            extra=f' AND c."{dt_field}" = %(dt)s', dt=subject_doctype)
    return swept


def _sweep(frappe, table, parent_table, field, owner, like, extra="", dt=None) -> int:
    params = {"owner": owner, "like": like, "dt": dt}
    before = frappe.db.sql(
        f"""SELECT count(*) FROM "{table}" c WHERE c."owner" = 'Administrator'{extra}
            AND EXISTS (SELECT 1 FROM "{parent_table}" p WHERE p."name" = c."{field}"
                        AND p."owner" LIKE %(like)s)""",
        params,
    )[0][0]
    if before:
        frappe.db.sql(
            f"""UPDATE "{table}" c SET "owner" = %(owner)s WHERE c."owner" = 'Administrator'{extra}
                AND EXISTS (SELECT 1 FROM "{parent_table}" p WHERE p."name" = c."{field}"
                            AND p."owner" LIKE %(like)s)""",
            params,
        )
    return int(before)


# ==================================================================== main

SECTIONS = [
    ("reference data", section_reference),
    ("personas", section_users),
    ("forum tree", section_forums),
    ("forum membership", section_memberships),
    ("glossary", section_glossary),
    ("policy library", section_policy_library),
    ("policy oversight", section_policy_oversight),
    ("meetings and motions", section_meetings),
    ("charters", section_charters),
    ("compliance and disbandment", section_compliance),
    ("formation requests", section_formation),
    ("escalation configuration", section_escalation_config),
    ("escalations", section_escalations),
    ("attestation campaigns", section_attestation),
]

COUNTED = [
    "User", "User Group", "Organization Unit", "Legal Entity", "Material Entity", "Regulatory Requirement",
    "Retention Class", "Notification Channel", "Business Calendar", "SLA Definition", "Document Template",
    "Guide Article", "Governance Forum", "Forum Membership", "Forum Meeting", "Forum Motion", "Forum Vote",
    "Committee Charter", "Forum Compliance Review", "Disbandment Plan", "Committee Formation Request",
    "Glossary Term", "Governing Document", "Document Version", "Approval Decision", "Document Publication",
    "Document Intake Request", "Document Review Cycle", "Horizon Scan", "Horizon Scan Finding",
    "Monitoring Activity", "Monitoring Result", "Policy Violation", "Implementation Plan",
    "Applicability Exemption", "Metadata Remediation Task", "Escalation Matrix", "Escalation Template",
    "Escalation Matter", "Action Plan", "Risk Acceptance", "Escalation Closure", "Periodic Submission",
    "Authority Delegation", "Exception Authorisation", "External Reference", "SLA Clock",
    "Attestation Campaign", "Attestation Task", "Notification Dispatch",
]


#: The state each workflow-bearing record is in, reported after a run.
STATE_FIELDS = [
    ("Governance Forum", "compliance_status"),
    ("Committee Formation Request", "workflow_state"),
    ("Committee Charter", "rgo_challenge_status"),
    ("Forum Meeting", "status"),
    ("Forum Motion", "outcome"),
    ("Governing Document", "lifecycle_phase"),
    ("Document Intake Request", "workflow_state"),
    ("Policy Violation", "violation_status"),
    ("Escalation Matter", "status"),
    ("Escalation Matter", "severity"),
    ("Action Plan", "status"),
    ("Risk Acceptance", "status"),
    ("Attestation Task", "status"),
]


def _anchor(frappe, dry_run: bool) -> date:
    stored = frappe.db.get_default(ANCHOR_KEY)
    if stored:
        return datetime.strptime(str(stored)[:10], "%Y-%m-%d").date()
    today = datetime.strptime(str(frappe.utils.nowdate()), "%Y-%m-%d").date()
    frappe.db.set_default(ANCHOR_KEY, str(today))
    return today


def _counts(frappe) -> dict:
    like = f"%@{DOMAIN}"
    out = {}
    for doctype in COUNTED:
        if not frappe.db.table_exists(doctype):
            continue
        field = "name" if doctype == "User" else "owner"
        demo = frappe.db.sql(f'SELECT count(*) FROM "tab{doctype}" WHERE "{field}" LIKE %s', (like,))[0][0]
        out[doctype] = (int(demo), frappe.db.count(doctype))
    return out


def _addition_lines(result) -> list[str]:
    """An addition's report as lines: a string, a list of notes, or a dict."""
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, dict):
        return [f"{key}: {value}" for key, value in result.items()]
    if isinstance(result, (list, tuple)):
        return [str(line) for line in result]
    return [str(result)]


def _reports_failure(line: str) -> bool:
    text = line.lower()
    return text.startswith("failed") or ": failed" in text or text.startswith("error")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every section, then roll the whole run back")
    parser.add_argument("--only", help="comma-separated section titles to run (debugging)")
    args = parser.parse_args()

    import frappe
    import frappe.utils  # noqa: F401  (the anchor reads nowdate)

    frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")
    # Nothing here should leave the building: every persona is fictitious.
    frappe.flags.mute_emails = True

    ctx = Ctx(frappe, _anchor(frappe, args.dry_run), args.dry_run)
    _protected_documents(ctx)  # before anything is created: see PROTECTED_DOCUMENTS
    print(f"\nDemonstration data for {args.site} — anchor {ctx.anchor}"
          f"{' (DRY RUN: everything is rolled back)' if args.dry_run else ''}\n")

    only = {s.strip() for s in (args.only or "").split(",") if s.strip()}
    for title, fn in SECTIONS:
        if only and title not in only:
            continue
        ctx.section_created = Counter()
        frappe.db.savepoint("demo_section")
        try:
            fn(ctx)
        except Exception:
            frappe.db.rollback(save_point="demo_section")
            ctx.failures.append((title, traceback.format_exc()))
            print(f"  {title:<28} FAILED — rolled back (see below)")
            continue
        if not args.dry_run:
            frappe.db.commit()
        made = ", ".join(f"{n} {dt}" for dt, n in sorted(ctx.section_created.items())) or "nothing new"
        print(f"  {title:<28} {made}")

    frappe.db.savepoint("demo_section")
    try:
        section_stamping(ctx)
    except Exception:
        frappe.db.rollback(save_point="demo_section")
        ctx.failures.append(("stamping", traceback.format_exc()))
    if not args.dry_run:
        frappe.db.commit()

    # Additions that show features built after this script: each module in
    # deploy/demo_additions/ exposes an idempotent run(frappe). They run after
    # the organisation exists, in name order, each in its own savepoint so one
    # failing addition does not undo the others.
    additions_dir = Path(__file__).resolve().parent / "demo_additions"
    for path in sorted(additions_dir.glob("*.py")) if additions_dir.is_dir() else []:
        if path.name.startswith("_") or (only and path.stem not in only):
            continue
        spec = importlib.util.spec_from_file_location(f"demo_additions.{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        frappe.db.savepoint("demo_section")
        try:
            spec.loader.exec_module(module)
            result = module.run(frappe)
        except Exception:
            frappe.db.rollback(save_point="demo_section")
            ctx.failures.append((f"addition {path.stem}", traceback.format_exc()))
            print(f"  addition {path.stem:<19} FAILED — rolled back (see below)")
            continue
        # An addition catches a failing step so the others still load, and
        # reports it in its result; a failure reported that way is still a
        # failure of the run, not "done".
        lines = _addition_lines(result)
        failed = [line for line in lines if _reports_failure(line)]
        if failed:
            frappe.db.rollback(save_point="demo_section")
            ctx.failures.append((f"addition {path.stem}", "\n".join(failed)))
            print(f"  addition {path.stem:<19} FAILED — rolled back (see below)")
            continue
        if not args.dry_run:
            frappe.db.commit()
        print(f"  addition {path.stem:<19} " + ("\n  " + " " * 29).join(lines or ["done"]))

    # The additions leave side effects of their own (versions, clocks, dispatches);
    # they are swept here, or the next run would find them and report a change.
    frappe.db.savepoint("demo_section")
    try:
        print(f"  gave {_sweep_all(frappe)} side-effect records of the additions a demo owner")
    except Exception:
        frappe.db.rollback(save_point="demo_section")
        ctx.failures.append(("final sweep", traceback.format_exc()))
    if not args.dry_run:
        frappe.db.commit()

    print(f"\n  {sum(ctx.created.values())} records created, {sum(ctx.existing.values())} already present.")
    for note in ctx.notes:
        print(f"  note: {note}")

    print("\n  Demo-owned records / all records, by DocType:")
    for doctype, (demo, total) in _counts(frappe).items():
        print(f"    {doctype:<30} {demo:>5} / {total}")

    print("\n  Where the demo records stand:")
    for doctype, field in STATE_FIELDS:
        rows = frappe.db.sql(
            f'''SELECT COALESCE(NULLIF("{field}", ''), '(none)'), count(*) FROM "tab{doctype}"
                WHERE "owner" LIKE %s OR "name" = %s GROUP BY 1 ORDER BY 2 DESC''',
            (f"%@{DOMAIN}", EXISTING_ORC),
        )
        print(f"    {doctype + '.' + field:<44} " + ", ".join(f"{v} {n}" for v, n in rows))

    for title, trace in ctx.failures:
        print(f"\n  --- {title} failed ---\n{trace}", file=sys.stderr)

    if args.dry_run:
        frappe.db.rollback()
    frappe.destroy()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
