#!/usr/bin/env python3
"""Capture the screenshots the illustrated guides in docs/guides/ use.

    cd <bench>/sites
    FRAPPE_BENCH_ROOT=<bench> <repo>/.venv/bin/python <repo>/scripts/capture_screenshots.py \\
        --site consilium.localhost --url http://consilium.localhost:8000

    # only some areas, or only shots whose name matches a pattern
    ... capture_screenshots.py --site consilium.localhost --area policies --area escalations
    ... capture_screenshots.py --site consilium.localhost --only 'forum-*'
    ... capture_screenshots.py --list          # print the shot list and exit

Why it exists. The guides are only useful if their pictures match the screens
people actually see, and the screens change every week. So the pictures are
never taken by hand: this script is the single, repeatable definition of every
picture in the guides, and re-running it refreshes them all.

How it signs in — without a password. The script opens a connection to the
site, creates an ordinary server-side session for each persona it needs with
the framework's own session machinery (``frappe.sessions.Session``, the same
object a real sign-in creates), and hands the browser nothing but that
session's ``sid`` cookie. No password is entered, typed, stored or needed —
the demonstration personas do not have one. Every session it created is deleted
again at the end, even when a capture fails.

How it drives the browser. Playwright, pointed at the Google Chrome already
installed on the machine (``channel="chrome"``). It never downloads a browser,
which matters on a locked-down workstation.

Missing screens are skipped, not fatal. The platform is still being extended;
a shot whose page does not exist yet (HTTP 404, or a workspace record type that
is not installed) is recorded as ``skipped`` in the manifest and the run goes
on. A shot that fails for another reason is recorded as ``failed`` with the
error, and the run goes on. Re-run once the screen exists.

It changes nothing. Every shot only navigates, opens tabs, types into filters
and opens dialogs. A dialog is always dismissed, never confirmed; a form is
never saved. (Signing a persona in does stamp their "last login" time — that is
what a session is.)

Output: ``docs/guides/images/<area>/<name>.png`` (1440×900 unless a shot says
otherwise) and ``docs/guides/images/manifest.json`` recording each shot, who
it was taken as, its address, its outcome and when.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "guides" / "images"

VIEWPORT = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}
# Full-page shots are cut off here so a long page does not become a 12 000
# pixel image nobody can read in a printed guide. Shots that need the lower
# part of a page scroll to it instead.
MAX_FULL_HEIGHT = 2600

# The persona each kind of work is shown as. Demonstration users only
# (@demo.example); the platform administrator for configuration screens.
PERSONA = {
	"rgo": "risk.governance.lead@demo.example",  # Risk Governance Office lead (+ Consilium Administrator)
	"analyst": "risk.governance.analyst@demo.example",  # Risk Governance Office
	"head_rg": "chief.risk.officer@demo.example",  # Head of Risk Governance
	"secretary": "committee.secretary@demo.example",
	"compliance": "second.line.reviewer@demo.example",  # Compliance / Policy / Escalation Reviewer
	"epo": "policy.office.lead@demo.example",  # Enterprise Policy Office
	"owner": "head.technology.risk@demo.example",  # Policy Owner, Forum Owner, Escalation Owner
	"esc_owner": "head.operational.risk@demo.example",
	"sensitive": "chief.compliance.officer@demo.example",  # holds Sensitive Escalation Access
	"viewer": "board.chair@demo.example",  # Governance Viewer only
	"audit": "internal.auditor@demo.example",
	"records": "records.manager@demo.example",
	"admin": "Administrator",
}
PERSONA_BASE = dict(PERSONA)
# Personas that depend on the data: whoever holds that part on this site.
PERSONA.update({
	"resp_owner": "@RESP_OWNER@",  # response owner of the breached matter
	"doc_owner": "@DOC_DRAFT_OWNER@",  # Policy Owner of the draft document
	"doc_steward": "@DOC_OVERDUE_OWNER@",  # Policy Owner of the overdue document
	"doc_approver": "@DOC_DECIDE_APPROVER@",  # assigned an open document approval step
	"attester": "@ATTESTER@",  # has open attestation tasks
	"second_signer": "@SECOND_SIGNER@",  # a counter-signature is waiting on them
	"originator": "@CFR_ORIGINATOR@",  # raised the returned formation request
	"disband_approver": "@DISBAND_APPROVER@",
	"sensitive_named": "@ESC_SENSITIVE_NAMED@",  # named on a sensitive matter
	"queue_taker": "@QUEUE_TAKER@",
	"doc_steward_review": "@DOC_REVIEW_OWNER@",  # Policy Owner of the document in review  # may take the waiting matter from its queue
})


@dataclass
class Shot:
	area: str
	name: str
	# An address, or a function of the site connection returning one (or None
	# to skip) — for records whose names differ between sites.
	route: object
	persona: str = "rgo"
	# Steps run after the page loads, each a tuple:
	#   ("click", selector)            ("click_text", text)
	#   ("fill", selector, text)       ("select", selector, value)
	#   ("press", key)                 ("wait", milliseconds)
	#   ("wait_for", selector)         ("scroll_to", selector)
	#   ("eval", javascript)           ("hover", selector)
	#   ("wait_js", javascript expression that becomes true)
	steps: list = field(default_factory=list)
	# "viewport" (what fits in 1440x900), "full" (whole page, capped), or a CSS
	# selector to photograph one element (a dialog, a panel).
	capture: str = "viewport"
	# Also take one picture per tab of a record page (".cns-tab"), named
	# <name>-tab-<tab id>.
	tabs: bool = False
	theme: str | None = None  # "dark" to show the dark theme
	viewport: dict | None = None
	desk: bool = False  # a workspace (/app) screen, which loads differently
	requires_doctype: str | None = None  # skip unless this record type exists
	requires_record: tuple | None = None  # (doctype, name) that must exist
	note: str = ""


def S(*args, **kwargs):
	return Shot(*args, **kwargs)


# ---------------------------------------------------------------------------
# The shot list. Grouped by the guide chapter that uses it.
# ---------------------------------------------------------------------------

# Records are named by what they are, not by number: the demonstration data is
# rebuilt from scratch from time to time and the numbers change. Each name
# below is a placeholder, filled in when the script runs by ``resolve_refs``,
# which finds the record with the characteristics the shot needs. A shot whose
# record cannot be found on the site is skipped, not failed.
def _ref(key):
	return f"@{key}@"


FORUM = _ref("FORUM")  # Operational Risk Committee: parent, children, re-review history
FORUM_NONCOMPLIANT = _ref("FORUM_NONCOMPLIANT")
FORUM_EXEC = _ref("FORUM_EXEC")  # Executive Risk Committee: widest linkage map
FORUM_DRAFT = _ref("FORUM_DRAFT")  # created by an approved request, awaiting its first review
FORUM_DISBANDED = _ref("FORUM_DISBANDED")
FORUM_PENDING = _ref("FORUM_PENDING")  # locked for review
FORUM_DISBANDING = _ref("FORUM_DISBANDING")  # a disbandment plan awaiting approvals
CFR_DRAFT = _ref("CFR_DRAFT")
CFR_SUBMITTED = _ref("CFR_SUBMITTED")
CFR_EVAL = _ref("CFR_EVAL")
CFR_RETURNED = _ref("CFR_RETURNED")
CFR_PENDING = _ref("CFR_PENDING")
CFR_APPROVED = _ref("CFR_APPROVED")
CFR_REJECTED = _ref("CFR_REJECTED")
DOC_REVIEW = _ref("DOC_REVIEW")  # in Review, approval steps raised
DOC_DECIDE = _ref("DOC_DECIDE")  # in Review, a step open for the Head of Risk Governance
DOC_APPROVED = _ref("DOC_APPROVED")
DOC_PUBLISHED = _ref("DOC_PUBLISHED")
DOC_CONFIDENTIAL = _ref("DOC_CONFIDENTIAL")
DOC_VERSIONS = _ref("DOC_VERSIONS")  # the longest version chain
DOC_OVERDUE = _ref("DOC_OVERDUE")  # in force, past its next review date
DOC_DRAFT = _ref("DOC_DRAFT")
DOC_MONITOR = _ref("DOC_MONITOR")  # has monitoring activities
DOC_LINEAGE = _ref("DOC_LINEAGE")  # has children
ESC_FULL = _ref("ESC_FULL")  # closed, with action plans and a risk acceptance
ESC_REVIEW = _ref("ESC_REVIEW")  # under review, a risk acceptance awaiting approval
ESC_SENSITIVE = _ref("ESC_SENSITIVE")
ESC_EXTERNAL = _ref("ESC_EXTERNAL")
ESC_BREACH = _ref("ESC_BREACH")  # in progress, time limit breached: the working actions
ESC_QUEUE = _ref("ESC_QUEUE")  # open, waiting in a role queue for an owner
ESC_SYSTEMIC = _ref("ESC_SYSTEMIC")
FORUM_ANNUAL = _ref("FORUM_ANNUAL")  # an owner-and-compliance attestation signed by both
MOTION_OPEN = _ref("MOTION_OPEN")


def resolve_refs(frappe) -> dict:
	"""Find, on this site, the record each placeholder stands for."""
	db = frappe.db
	today = frappe.utils.nowdate()

	def one(doctype, filters, field="name", order_by="name asc"):
		try:
			return db.get_value(doctype, filters, field, order_by=order_by)
		except Exception:
			return None

	def first_sql(query, *params):
		try:
			rows = db.sql(query, params)
			return rows[0][0] if rows else None
		except Exception:
			return None

	r = {}
	r["FORUM"] = one("Governance Forum", {"forum_name": "Operational Risk Committee"})
	r["FORUM_EXEC"] = one("Governance Forum", {"forum_name": "Executive Risk Committee"})
	r["FORUM_NONCOMPLIANT"] = one("Governance Forum", {"compliance_status": "Non-Compliant", "is_active": 1})
	r["FORUM_DISBANDED"] = one("Governance Forum", {"compliance_status": "Disbanded"})
	r["FORUM_PENDING"] = one("Governance Forum", {"compliance_status": "Pending", "is_active": 1})
	r["CFR_APPROVED"] = one("Committee Formation Request", {"workflow_state": "Approved", "request_type": "Create"})
	r["FORUM_DRAFT"] = one("Committee Formation Request", {"name": r["CFR_APPROVED"]}, "created_forum") if r["CFR_APPROVED"] else None
	for key, state in (("CFR_DRAFT", "Draft"), ("CFR_SUBMITTED", "Submitted"), ("CFR_EVAL", "Under Evaluation"),
			("CFR_RETURNED", "Returned To Originator"), ("CFR_PENDING", "Pending Approval"), ("CFR_REJECTED", "Rejected")):
		r[key] = one("Committee Formation Request", {"workflow_state": state})
	r["CFR_ORIGINATOR"] = one("Committee Formation Request", {"name": r["CFR_RETURNED"]}, "requester") if r["CFR_RETURNED"] else None

	open_plan = first_sql("""select subject_name from "tabApproval Decision" where subject_doctype='Disbandment Plan'
		and is_open=1 order by subject_name limit 1""")
	r["FORUM_DISBANDING"] = one("Disbandment Plan", {"name": open_plan}, "forum") if open_plan else None
	r["DISBAND_APPROVER"] = first_sql("""select assigned_to from "tabApproval Decision" where subject_doctype='Disbandment Plan'
		and is_open=1 order by name limit 1""")
	r["DISBAND_PLAN_DONE"] = one("Governance Forum", {"name": r["FORUM_DISBANDED"]}, "disbandment_plan") if r["FORUM_DISBANDED"] else None

	doc_step = """select d.subject_name, d.assigned_to from "tabApproval Decision" d join "tabGoverning Document" g
		on g.name=d.subject_name where d.subject_doctype='Governing Document' and d.is_open=1
		and g.lifecycle_phase='Review' and g.handling_classification in ('Public','Internal') order by d.subject_name"""
	try:
		steps = db.sql(doc_step)
	except Exception:
		steps = []
	head = [row for row in steps if row[1] == PERSONA_BASE["head_rg"]]
	r["DOC_DECIDE"], r["DOC_DECIDE_APPROVER"] = (head[0] if head else (steps[0] if steps else (None, None)))
	others = [row[0] for row in steps if row[0] != r["DOC_DECIDE"]]
	r["DOC_REVIEW"] = others[0] if others else one("Governing Document", {"lifecycle_phase": "Review",
		"handling_classification": ["in", ["Public", "Internal"]]})
	r["DOC_REVIEW_OWNER"] = one("Governing Document", {"name": r["DOC_REVIEW"]}, "document_owner") if r["DOC_REVIEW"] else None
	r["DOC_APPROVED"] = one("Governing Document", {"lifecycle_phase": "Approved"})
	r["DOC_PUBLISHED"] = first_sql("""select g.name from "tabGoverning Document" g left join "tabDocument Publication" p
		on p.document=g.name where g.lifecycle_phase='Published' and g.handling_classification in ('Public','Internal')
		group by g.name order by count(p.name) desc, g.name limit 1""")
	r["DOC_CONFIDENTIAL"] = one("Governing Document", {"handling_classification": "Confidential"})
	r["DOC_VERSIONS"] = first_sql("""select v.subject_name from "tabDocument Version" v join "tabGoverning Document" g
		on g.name=v.subject_name where v.subject_doctype='Governing Document' and g.handling_classification in ('Public','Internal')
		group by v.subject_name order by count(*) desc, v.subject_name limit 1""")
	r["DOC_OVERDUE"] = one("Governing Document", {"is_active": 1, "next_review_on": ["<", today]}, order_by="next_review_on asc")
	r["DOC_OVERDUE_OWNER"] = one("Governing Document", {"name": r["DOC_OVERDUE"]}, "document_owner") if r["DOC_OVERDUE"] else None
	r["DOC_DRAFT"] = one("Governing Document", {"lifecycle_phase": "Draft"})
	r["DOC_DRAFT_OWNER"] = one("Governing Document", {"name": r["DOC_DRAFT"]}, "document_owner") if r["DOC_DRAFT"] else None
	r["DOC_MONITOR"] = first_sql("""select document from "tabMonitoring Activity" group by document order by count(*) desc, document limit 1""")
	r["DOC_LINEAGE"] = first_sql("""select parent_document from "tabGoverning Document" where coalesce(parent_document,'')<>''
		group by parent_document order by count(*) desc, parent_document limit 1""")
	for key, doc in (("VER_PLAIN", r["DOC_VERSIONS"]), ("VER_CONFIDENTIAL", r["DOC_CONFIDENTIAL"])):
		r[key] = one("Governing Document", {"name": doc}, "current_version") if doc else None
	for key, state in (("INTAKE_REQUESTED", "Requested"), ("INTAKE_CLASSIFIED", "Classified"), ("INTAKE_FULFILLED", "Fulfilled")):
		r[key] = one("Document Intake Request", {"workflow_state": state, "request_type": "Create"}) or \
			one("Document Intake Request", {"workflow_state": state})

	r["ESC_FULL"] = first_sql("""select m.name from "tabEscalation Matter" m join "tabAction Plan" a on a.escalation_matter=m.name
		where m.status='Closed' and coalesce(m.sensitive,0)=0 group by m.name order by count(*) desc, m.name limit 1""")
	r["ESC_REVIEW"] = first_sql("""select m.name from "tabEscalation Matter" m join "tabRisk Acceptance" a on a.escalation_matter=m.name
		where m.status in ('Under Review','Pending Review') and a.status='Pending Approval' and coalesce(m.sensitive,0)=0
		order by m.name limit 1""")
	r["ESC_SENSITIVE"] = one("Escalation Matter", {"sensitive": 1})
	r["ESC_SENSITIVE_NAMED"] = one("Escalation Matter", {"name": r["ESC_SENSITIVE"]}, "response_owner") if r["ESC_SENSITIVE"] else None
	r["ESC_EXTERNAL"] = one("Escalation Matter", {"status": "Closed — Tracked Externally"})
	r["ESC_BREACH"] = one("Escalation Matter", {"status": "In Progress", "threshold_breached": 1, "sensitive": 0,
		"response_owner": ["is", "set"]})
	r["RESP_OWNER"] = one("Escalation Matter", {"name": r["ESC_BREACH"]}, "response_owner") if r["ESC_BREACH"] else None
	r["ESC_QUEUE"] = one("Escalation Matter", {"status": "Open", "response_owner": ["is", "not set"], "sensitive": 0})
	r["ESC_SYSTEMIC"] = one("Escalation Matter", {"systemic": 1, "sensitive": 0})
	r["ESC_ANY_OPEN"] = one("Escalation Matter", {"is_open": 1, "sensitive": 0})

	try:
		from consilium.escalation import assignment

		if r.get("ESC_QUEUE"):
			matter = frappe.get_doc("Escalation Matter", r["ESC_QUEUE"])
			takers = [u for u in assignment.queue_members(matter) if assignment.can_take(matter, u)]
			r["QUEUE_TAKER"] = takers[0] if takers else None
	except Exception:
		pass
	r["FORUM_ANNUAL"] = first_sql("""select t.subject_name from "tabAttestation Task" t join "tabAttestation Campaign" c
		on c.name=t.campaign where c.campaign_type='Forum Owner And Compliance' and t.second_signed_on is not null
		order by t.name limit 1""")
	r["MOTION_OPEN"] = one("Forum Motion", {"is_open": 1, "outcome": ["in", ["", None]]}) or one("Forum Motion", {"is_open": 1})
	r["MOTION_VOTER"] = first_sql("""select coalesce(v.voter, m.member) from "tabForum Vote" v
		left join "tabForum Membership" m on m.name=v.membership where v.motion=%s and coalesce(v.position,'Not Cast')='Not Cast'
		and coalesce(m.member,'')<>'' order by v.name limit 1""", r.get("MOTION_OPEN")) if r.get("MOTION_OPEN") else None
	r["MEETING"] = first_sql("""select name from "tabForum Meeting" where status='Held' and coalesce(minutes_version,'')<>''
		order by name limit 1""")
	r["CAMPAIGN_DOCS"] = one("Attestation Campaign", {"campaign_type": "Governing Document"})
	r["ATTESTER"] = first_sql("""select assigned_to from "tabAttestation Task" where status='Pending'
		group by assigned_to order by count(*) desc, assigned_to limit 1""")
	r["SECOND_SIGNER"] = first_sql("""select second_signatory from "tabAttestation Task" where status='Attested'
		and coalesce(second_signatory,'')<>'' and second_signed_on is null order by name limit 1""")
	r["MATRIX"] = one("Escalation Matrix", {"is_active": 1}) or one("Escalation Matrix", {})
	r["ESC_TEMPLATE"] = one("Escalation Template", {"escalation_type": "INCIDENT",
		"template_scope": ["not in", ["Action Plan", "Risk Acceptance"]]}) or one("Escalation Template", {})
	r["SLA_HIGH"] = one("SLA Definition", {"name": ["like", "%HIGH%"]}) or one("SLA Definition", {})
	r["CALENDAR"] = one("Business Calendar", {})
	r["FORMATION_ROUTE"] = one("Formation Approval Route", {"is_active": 1}) or one("Formation Approval Route", {})
	return {k: v for k, v in r.items() if v}


def fill_refs(value, refs: dict):
	"""Replace every @KEY@ in a string; None when a placeholder has no record."""
	if not isinstance(value, str) or "@" not in value:
		return value
	import re

	missing = []

	def sub(match):
		key = match.group(1)
		if key in refs:
			return refs[key]
		missing.append(key)
		return match.group(0)

	out = re.sub(r"@([A-Z][A-Z0-9_]+)@", sub, value)
	return None if missing else out


def SCROLL(selector):
	"""Bring an element to the middle of the picture (the shot fails if it is not there)."""
	return ("scroll_center", selector)

SHOTS: list[Shot] = [
	# 01 Getting started -----------------------------------------------------
	S("getting-started", "home", "/", "rgo", capture="full"),
	S("getting-started", "home-top", "/", "rgo"),
	S("getting-started", "home-viewer", "/", "viewer", note="A Governance Viewer's home page."),
	S("getting-started", "top-bar", "/", "rgo", capture="header"),
	S("getting-started", "user-menu", "/", "rgo",
		steps=[("click", "#cns-user-menu"), ("wait", 500)]),
	S("getting-started", "signed-out", "/forums", persona="guest"),
	S("getting-started", "text-size-larger", "/forums", "rgo",
		steps=[("click", '[data-cns-fontsize="increase"]'), ("click", '[data-cns-fontsize="increase"]'), ("wait", 300)]),
	S("getting-started", "dark-theme-home", "/", "rgo", theme="dark"),
	S("getting-started", "dark-theme-forum", f"/forum?name={FORUM}", "rgo", theme="dark"),
	S("getting-started", "phone-home", "/", "rgo", viewport=PHONE, capture="full"),
	S("getting-started", "phone-forums", "/forums", "rgo", viewport=PHONE),
	S("getting-started", "help-assistant-open", "/forums", "rgo",
		steps=[("click", ".cns-assistant-toggle"), ("wait_for", "#cns-assistant-panel"), ("wait", 500)]),
	S("getting-started", "help-assistant-answer", "/forums", "rgo",
		steps=[("click", ".cns-assistant-toggle"), ("wait_for", "#cns-assistant-input"),
			("fill", "#cns-assistant-input", "How do I ask for a new forum?"),
			("press", "Enter"), ("wait_js", "() => { const p = document.getElementById('cns-assistant-panel'); return p && p.getAttribute('aria-busy') !== 'true' && document.querySelector('.cns-assistant-msg-question') && document.querySelectorAll('.cns-assistant-log .cns-assistant-msg-answer, .cns-assistant-log .cns-assistant-msg-error').length > 0; }"), ("wait", 800)]),
	S("getting-started", "help-assistant-why", f"/formation-request?name={CFR_PENDING}", "secretary",
		steps=[("click", ".cns-assistant-toggle"), ("wait_for", "#cns-assistant-input"),
			("fill", "#cns-assistant-input", "Why can't I approve this?"),
			("press", "Enter"), ("wait_js", "() => { const p = document.getElementById('cns-assistant-panel'); return p && p.getAttribute('aria-busy') !== 'true' && document.querySelector('.cns-assistant-msg-question') && document.querySelectorAll('.cns-assistant-log .cns-assistant-msg-answer, .cns-assistant-log .cns-assistant-msg-error').length > 0; }"), ("wait", 800)]),
	S("getting-started", "workspace-home", "/app", "rgo", desk=True),
	S("getting-started", "workspace-governance", "/app/governance", "rgo", desk=True),
	S("getting-started", "workspace-policy", "/app/policy", "epo", desk=True),
	S("getting-started", "workspace-escalation", "/app/escalation", "esc_owner", desk=True),
	S("getting-started", "workspace-administration", "/app/consilium-administration", "admin", desk=True),
	S("getting-started", "workspace-list", "/app/governance-forum", "rgo", desk=True),
	S("getting-started", "workspace-form", f"/app/governance-forum/{FORUM}", "rgo", desk=True),
	S("getting-started", "no-access", "/formation-requests", "viewer"),

	# 02 Forums --------------------------------------------------------------
	S("forums", "inventory", "/forums", "rgo"),
	S("forums", "inventory-filters", "/forums", "rgo", capture="full"),
	S("forums", "inventory-table", "/forums", "rgo", steps=[SCROLL("#forum-table")]),
	S("forums", "inventory-overdue", "/forums?standing=overdue", "rgo"),
	S("forums", "inventory-noncompliant", "/forums?compliance_status=Non-Compliant", "rgo"),
	S("forums", "inventory-search", "/forums", "rgo",
		steps=[("fill", "#forum-table input[type=search]", "risk"), ("press", "Enter"), ("wait", 1200)]),
	S("forums", "forum", f"/forum?name={FORUM}", "rgo", tabs=True),
	S("forums", "forum-membership-as-at", f"/forum?name={FORUM_DISBANDED}", "rgo",
		steps=[("click", "#tab-members"), ("wait", 500), ("fill", "#as-at", "2026-03-01"), ("press", "Tab"), ("wait", 1200)]),
	S("forums", "forum-membership-today-disbanded", f"/forum?name={FORUM_DISBANDED}", "rgo",
		steps=[("click", "#tab-members"), ("wait", 900)]),
	S("forums", "forum-linkages-exec", f"/forum?name={FORUM_EXEC}", "rgo",
		steps=[("click", "#tab-links"), ("wait", 900)], capture="full"),
	S("forums", "forum-decisions", f"/forum?name={FORUM}", "rgo",
		steps=[("click", "#tab-decisions"), ("wait", 900)], capture="full"),
	S("forums", "forum-noncompliant", f"/forum?name={FORUM_NONCOMPLIANT}", "compliance"),
	S("forums", "forum-evidence-pack", f"/forum?name={FORUM}", "audit"),
	S("forums", "forum-record-history", f"/forum?name={FORUM}#history", "audit",
		steps=[("wait", 1500), SCROLL("text=Record history")]),
	S("forums", "forum-disbanded-header", f"/forum?name={FORUM_DISBANDED}", "rgo"),
	S("forums", "forum-viewer", f"/forum?name={FORUM}", "viewer"),
	S("forums", "forum-edit-desk", f"/app/governance-forum/{FORUM}", "rgo", desk=True),

	# 03 Forum formation -----------------------------------------------------
	S("formation", "create-forum", "/create-forum", "secretary", capture="full"),
	S("formation", "create-forum-top", "/create-forum", "secretary"),
	S("formation", "create-forum-draft-refused", "/create-forum", "secretary",
		steps=[("click", "#save-draft"), ("wait", 900)], note="Save draft on an empty form: nothing is saved."),
	S("formation", "create-forum-draft", f"/create-forum?request={CFR_DRAFT}", "rgo", capture="full"),
	S("formation", "create-forum-answer", f"/create-forum?request={CFR_RETURNED}", "rgo",
		steps=[("wait_for", "#response-card"), ("wait", 600), SCROLL("#response-card")], note="A returned request, with the governance office's questions."),
	S("formation", "create-forum-no-access", "/create-forum", "viewer"),
	S("formation", "queue", "/formation-requests", "rgo"),
	S("formation", "queue-all", "/formation-requests?stage=all", "rgo", capture="full"),
	S("formation", "request-submitted", f"/formation-request?name={CFR_SUBMITTED}", "rgo"),
	S("formation", "request-evaluation", f"/formation-request?name={CFR_EVAL}", "rgo", tabs=True),
	S("formation", "request-evaluation-form", f"/formation-request?name={CFR_EVAL}", "rgo",
		steps=[("click", "#tab-evaluation"), ("wait", 800), SCROLL("#findings-form")]),
	S("formation", "request-return-panel", f"/formation-request?name={CFR_EVAL}", "rgo",
		steps=[("click", "[data-action=return_to_originator]"), ("wait", 500), SCROLL("#action-panel, #panel-form")]),
	S("formation", "request-returned", f"/formation-request?name={CFR_RETURNED}", "rgo", tabs=True),
	S("formation", "request-originator", f"/formation-request?name={CFR_RETURNED}", "originator",
		note="The originator, who holds no raising role, follows the request and may withdraw it."),
	S("formation", "request-pending", f"/formation-request?name={CFR_PENDING}", "rgo", tabs=True),
	S("formation", "request-approve-blocked", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=[SCROLL("#action-buttons")], note="Approve stays disabled while anything stands in the way."),
	S("formation", "request-reject-panel", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=[("click", "[data-action=reject]"), ("wait", 500), SCROLL("#action-buttons")]),
	S("formation", "request-exception-panel", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=[("click", "[data-action=raise_exception]"), ("wait", 500), SCROLL("#action-buttons")]),
	S("formation", "request-approver", f"/formation-request?name={CFR_PENDING}#approval", "head_rg", capture="full",
		note="The Head of Risk Governance, who is also assigned an open step."),
	S("formation", "request-rejected", f"/formation-request?name={CFR_REJECTED}", "rgo"),
	S("formation", "request-approved", f"/formation-request?name={CFR_APPROVED}", "rgo", tabs=True),
	S("formation", "formation-approval-route", "/app/formation-approval-route/@FORMATION_ROUTE@", "admin",
		desk=True, capture="full"),

	# 04 Compliance and reviews ----------------------------------------------
	S("compliance", "forum-review", f"/forum-review?forum={FORUM_DRAFT}", "compliance", capture="full"),
	S("compliance", "forum-review-top", f"/forum-review?forum={FORUM_DRAFT}", "compliance"),
	S("compliance", "forum-review-validation", f"/forum-review?forum={FORUM_DRAFT}", "compliance",
		steps=[("click", "input[name=decision][value='Non-Compliant']"), ("click", "#record-review"), ("wait", 700),
			SCROLL("#review-errors")], note="Non-Compliant without questions or comments is not recorded."),
	S("compliance", "forum-review-disbanded", f"/forum-review?forum={FORUM_DISBANDED}", "compliance"),
	S("compliance", "forum-review-queue", "/formation-requests", "rgo", steps=[SCROLL("#review-table")]),
	S("compliance", "forum-pending-locked", f"/forum?name={FORUM_PENDING}", "rgo"),
	S("compliance", "forum-history", f"/forum?name={FORUM}#history", "compliance", capture="full"),
	S("compliance", "forum-disband", f"/forum-disband?forum={FORUM}", "rgo", capture="full"),
	S("compliance", "forum-disband-done", f"/forum-disband?forum={FORUM_DISBANDED}", "rgo", capture="full"),
	S("compliance", "forum-disband-approver", f"/forum-disband?forum={FORUM_DISBANDING}", "disband_approver", capture="full"),
	S("compliance", "forum-disband-open", f"/forum-disband?forum={FORUM_DISBANDING}", "rgo", capture="full"),
	S("compliance", "annual-review", f"/forum-review?forum={FORUM_ANNUAL}", "compliance",
		steps=[("wait_for", "#annual-review"), ("wait", 800), SCROLL("#annual-review")]),
	S("compliance", "annual-review-full", f"/forum-review?forum={FORUM_ANNUAL}", "compliance", capture="full"),
	S("compliance", "watched-field-set", "/app/watched-field-set/Governance Forum", "admin", desk=True, capture="full"),
	S("compliance", "compliance-review-list", "/app/forum-compliance-review", "rgo", desk=True),
	S("compliance", "disbandment-plan", "/app/disbandment-plan/@DISBAND_PLAN_DONE@", "rgo", desk=True, capture="full"),

	# 05 Meetings, votes, charters -------------------------------------------
	S("meetings", "forum-decisions", f"/forum?name={FORUM_EXEC}#decisions", "secretary", capture="full"),
	S("meetings", "forum-documents", f"/forum?name={FORUM_EXEC}#docs", "secretary"),
	S("meetings", "charter-card", f"/forum?name={FORUM}#docs", "rgo", capture="full"),
	S("meetings", "charter-change", f"/forum?name={FORUM}#docs", "rgo",
		steps=[("wait_for", "#charter-publish-form"), SCROLL("#charter-actions")]),
	S("meetings", "charter-challenge-form", f"/forum?name={FORUM}#docs", "rgo",
		steps=[("wait_for", "#charter-challenge-form"), SCROLL("#charter-challenge-form")]),
	S("meetings", "charter-challenge-formation", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=[("wait", 800), ("eval", "(() => { const c = document.getElementById('charter-challenge-card'); const p = c && c.closest('[role=tabpanel]'); if (p) { const t = document.getElementById(p.id.replace('panel-', 'tab-')); if (t) t.click(); } })()"),
			("wait", 800), SCROLL("#charter-challenge-card")]),
	S("meetings", "motion-put", f"/forum-motion?forum={FORUM}", "secretary", capture="full"),
	S("meetings", "motion-open", f"/forum-motion?name={MOTION_OPEN}", "secretary", capture="full"),
	S("meetings", "motion-vote", f"/forum-motion?name={MOTION_OPEN}", "@MOTION_VOTER@",
		steps=[("wait_for", "#vote-card"), SCROLL("#vote-card")]),
	S("meetings", "forum-decisions-put", f"/forum?name={FORUM}#decisions", "secretary"),
	S("meetings", "membership-list", "/app/forum-membership", "secretary", desk=True),
	S("meetings", "membership-form", "/app/forum-membership", "secretary", desk=True, capture="full",
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("meetings", "meeting-list", "/app/forum-meeting", "secretary", desk=True),
	S("meetings", "meeting-form", "/app/forum-meeting/@MEETING@", "secretary", desk=True, capture="full"),
	S("meetings", "meeting-record-minutes", "/app/forum-meeting/@MEETING@", "secretary", desk=True,
		steps=[("click", "button:has-text('minutes')"), ("wait_for", ".modal.show"), ("wait", 700)]),
	S("meetings", "motion-list", "/app/forum-motion", "secretary", desk=True),
	S("meetings", "motion-form", "/app/forum-motion", "secretary", desk=True, capture="full",
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("meetings", "vote-list", "/app/forum-vote", "secretary", desk=True),
	S("meetings", "charter-list", "/app/committee-charter", "secretary", desk=True),
	S("meetings", "charter-form", "/app/committee-charter", "secretary", desk=True, capture="full",
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),

	# 06 Policies ------------------------------------------------------------
	S("policies", "register", "/policies", "epo"),
	S("policies", "register-filters", "/policies", "epo", capture="full"),
	S("policies", "register-overdue", "/policies?standing=overdue", "epo"),
	S("policies", "register-review-phase", "/policies?lifecycle_phase=Review", "epo"),
	S("policies", "document-review", f"/policy?name={DOC_REVIEW}", "epo", tabs=True),
	S("policies", "document-review-full", f"/policy?name={DOC_REVIEW}", "epo", capture="full"),
	S("policies", "document-approved", f"/policy?name={DOC_APPROVED}", "epo", tabs=True),
	S("policies", "document-published", f"/policy?name={DOC_PUBLISHED}", "epo", tabs=True),
	S("policies", "document-reader", f"/policy?name={DOC_PUBLISHED}", "compliance",
		note="A reader with no part to play: read only."),
	S("policies", "document-confidential", f"/policy?name={DOC_CONFIDENTIAL}", "epo"),
	S("policies", "document-draft-owner", f"/policy?name={DOC_DRAFT}", "doc_owner"),
	S("policies", "lifecycle-confirm-panel", f"/policy?name={DOC_APPROVED}", "epo",
		steps=[("click", "#action-buttons [data-lifecycle]:not([disabled])"), ("wait", 600), SCROLL("#action-panel")]),
	S("policies", "lifecycle-blocked", f"/policy?name={DOC_REVIEW}", "epo", steps=[SCROLL("#action-buttons")],
		note="Record Approval is refused while the approval chain is incomplete."),
	S("policies", "correct-metadata", f"/policy?name={DOC_PUBLISHED}", "epo",
		steps=[("wait_for", "#correct-form"), SCROLL("#correct")]),
	S("policies", "impact-panel", f"/policy?name={DOC_PUBLISHED}", "epo",
		steps=[("wait_for", "#tab-details"), ("click_text", "Assess the impact"), ("wait", 2500), SCROLL("text=Review points")]),
	S("policies", "gate-exception", f"/policy?name={DOC_REVIEW}#approval", "doc_steward_review",
		steps=[("wait_for", "#exception-body"), ("wait", 800), SCROLL("#exception-body")]),
	S("policies", "lifecycle-readiness", f"/policy?name={DOC_APPROVED}#lifecycle", "epo", capture="full"),
	S("policies", "approval-raise-steps", f"/policy?name={DOC_REVIEW}#approval", "epo", capture="full"),
	S("policies", "approval-decide-step", f"/policy?name={DOC_DECIDE}#approval", "doc_approver", capture="full",
		note="The approver assigned the open step sees the decision form."),
	S("policies", "approval-bypass-form", f"/policy?name={DOC_DECIDE}#approval", "epo",
		steps=[("wait_for", "#bypass-form"), SCROLL("#bypass-form")]),
	S("policies", "versions-upload-form", f"/policy?name={DOC_DRAFT}#versions", "doc_owner",
		steps=[("wait_for", "#upload-form"), SCROLL("#upload-form")]),
	S("policies", "versions-revert-form", f"/policy?name={DOC_DRAFT}#versions", "doc_owner",
		steps=[("wait_for", "#revert-form"), SCROLL("#revert-form")]),
	S("policies", "versions-chain", f"/policy?name={DOC_VERSIONS}#versions", "epo", capture="full"),
	S("policies", "publish-form", f"/policy?name={DOC_PUBLISHED}#versions", "epo",
		steps=[("wait_for", "#publish-form"), SCROLL("#publish-form")]),
	S("policies", "publish-audience-preview", f"/policy?name={DOC_PUBLISHED}#versions", "epo",
		steps=[("wait_for", "#preview-audience"), ("click", "#preview-audience"), ("wait", 1500), SCROLL("#publish-form")]),
	S("policies", "reviews-tab", f"/policy?name={DOC_OVERDUE}#reviews", "doc_steward", capture="full"),
	S("policies", "horizon-scan-form", f"/policy?name={DOC_PUBLISHED}#reviews", "epo",
		steps=[("wait_for", "#scan-form"), SCROLL("#scan-form")]),
	S("policies", "monitoring-tab", f"/policy?name={DOC_MONITOR}#monitoring", "epo", capture="full"),
	S("policies", "monitoring-result-form", f"/policy?name={DOC_MONITOR}#monitoring", "epo",
		steps=[("wait_for", "[data-record-result]"), ("click", "[data-record-result] >> nth=0"), ("wait", 600), SCROLL("#result-form")]),
	S("policies", "violation-form", f"/policy?name={DOC_PUBLISHED}#monitoring", "epo",
		steps=[("wait_for", "#violation-form"), SCROLL("#violation-form")]),
	S("policies", "lineage-tab", f"/policy?name={DOC_LINEAGE}#lineage", "epo", capture="full"),
	S("policies", "document-viewer", "/document-view?version=@VER_PLAIN@", "epo"),
	S("policies", "document-viewer-confidential", "/document-view?version=@VER_CONFIDENTIAL@", "epo"),
	S("policies", "policy-impact", f"/policy-impact?name={DOC_REVIEW}", "epo", capture="full"),
	S("policies", "regulatory-updates", "/regulatory-updates", "epo", capture="full"),
	S("policies", "regulatory-update-one",
		lambda frappe: (lambda n: f"/regulatory-updates?requirement={n}" if n else None)(
			frappe.db.get_value("Regulatory Requirement", {}, "name", order_by="modified desc")), "epo", capture="full"),
	S("policies", "intake", "/policy-intake", "doc_owner", capture="full"),
	S("policies", "intake-top", "/policy-intake", "doc_owner"),
	S("policies", "intake-classify", "/policy-intake?name=@INTAKE_REQUESTED@", "epo", capture="full"),
	S("policies", "intake-classified", "/policy-intake?name=@INTAKE_CLASSIFIED@", "epo", capture="full"),
	S("policies", "intake-explained", "/policy-intake?name=@INTAKE_FULFILLED@", "epo", capture="full"),
	S("policies", "workflow-lifecycle", "/app/workflow/Governing Document Lifecycle", "admin", desk=True, capture="full"),
	S("policies", "lifecycle-gate-list", "/app/document-lifecycle-gate", "admin", desk=True),
	S("policies", "approval-route-list", "/app/approval-route", "admin", desk=True),
	S("policies", "glossary-list", "/app/glossary-term", "epo", desk=True),
	S("policies", "exemption-list", "/app/applicability-exemption", "epo", desk=True),
	S("policies", "template-list", "/app/document-template", "epo", desk=True),
	S("policies", "violation-list", "/app/policy-violation", "epo", desk=True),
	S("policies", "monitoring-activity-list", "/app/monitoring-activity", "epo", desk=True),
	S("policies", "new-document-desk", "/app/governing-document/new", "epo", desk=True, capture="full"),

	# 07 Escalations ---------------------------------------------------------
	S("escalations", "register", "/escalations", "esc_owner"),
	S("escalations", "register-filters", "/escalations?standing=all", "esc_owner", capture="full"),
	S("escalations", "register-high", "/escalations?severity=High&standing=all", "esc_owner"),
	S("escalations", "register-waiting-on-you", "/escalations", "head_rg"),
	S("escalations", "register-sensitive-holder", "/escalations?standing=all", "sensitive"),
	S("escalations", "matter", f"/escalation?name={ESC_FULL}", "esc_owner", tabs=True),
	S("escalations", "matter-breach", f"/escalation?name={ESC_BREACH}", "resp_owner", tabs=True),
	S("escalations", "matter-review", f"/escalation?name={ESC_REVIEW}", "compliance", tabs=True),
	S("escalations", "matter-external", f"/escalation?name={ESC_EXTERNAL}#closure", "esc_owner", capture="full"),
	S("escalations", "matter-sensitive-holder", f"/escalation?name={ESC_SENSITIVE}", "sensitive"),
	S("escalations", "matter-sensitive-refused", f"/escalation?name={ESC_SENSITIVE}", "esc_owner"),
	S("escalations", "action-move-status", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=move_status]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-add-plan", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=add_action_plan]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-risk-acceptance", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=add_risk_acceptance]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-pathway", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=change_pathway]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-record-closure", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=record_closure]"), ("wait", 600), SCROLL("#action-panel")], capture="full"),
	S("escalations", "action-close", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("click", "[data-action=close]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-record-review", f"/escalation?name={ESC_REVIEW}", "compliance",
		steps=[("click", "[data-action=record_review]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "action-decide-acceptance", f"/escalation?name={ESC_REVIEW}", "head_rg",
		steps=[("click", "[data-action=decide_approval]"), ("wait", 600), SCROLL("#action-panel")]),
	S("escalations", "take-ownership", f"/escalation?name={ESC_QUEUE}", "queue_taker",
		steps=[("wait_for", "#actions-card"), SCROLL("#actions-card")]),
	S("escalations", "time-in-status", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("wait_for", "#durations-body"), ("wait", 1200), SCROLL("#durations-heading")]),
	S("escalations", "matter-systemic", f"/escalation?name={ESC_SYSTEMIC}", "rgo"),
	S("escalations", "raise-systemic", "/raise-escalation", "esc_owner", steps=[SCROLL("#systemic")]),
	S("escalations", "evidence-pack-button", f"/escalation?name={ESC_FULL}", "audit"),
	S("escalations", "record-history", f"/escalation?name={ESC_FULL}#history", "audit",
		steps=[("wait", 1500), SCROLL("text=Record history")]),
	S("escalations", "matter-sensitive-named", f"/escalation?name={ESC_SENSITIVE}", "sensitive_named",
		note="A person named on a sensitive matter sees it without the sensitive-access role."),
	S("escalations", "matter-history", f"/escalation?name={ESC_BREACH}#history", "resp_owner", capture="full"),
	S("escalations", "raise", "/raise-escalation", "esc_owner", capture="full"),
	S("escalations", "raise-top", "/raise-escalation", "esc_owner"),
	S("escalations", "raise-proposal", "/raise-escalation", "esc_owner",
		steps=[("select", "#escalation_type", "LIMIT_BREACH"), ("select", "#tier_1_risk_type", "FINANCIAL"), ("wait", 500),
			("select", "#tier_2_risk_type", "FIN_LIMIT"), ("click", "#risk_appetite_breach"), ("wait", 1500), SCROLL("#proposal")]),
	S("escalations", "raise-validation", "/raise-escalation", "esc_owner",
		steps=[("click", "#raise-submit"), ("wait", 800), SCROLL("#form-errors")]),
	S("escalations", "matrix", "/app/escalation-matrix/@MATRIX@", "admin", desk=True, capture="full"),
	S("escalations", "template", "/app/escalation-template/@ESC_TEMPLATE@", "admin", desk=True, capture="full"),
	S("escalations", "sla-definition", "/app/sla-definition/@SLA_HIGH@", "admin", desk=True, capture="full"),
	S("escalations", "business-calendar", "/app/business-calendar/@CALENDAR@", "admin", desk=True, capture="full"),
	S("escalations", "business-calendar-list", "/app/business-calendar", "admin", desk=True),
	S("escalations", "sla-clock-list", "/app/sla-clock", "admin", desk=True),
	S("escalations", "periodic-submission-list", "/app/periodic-submission", "esc_owner", desk=True),
	S("escalations", "new-matter-desk", "/app/escalation-matter/new", "esc_owner", desk=True, capture="full"),

	# 08 Tasks and attestation -----------------------------------------------
	S("tasks", "inbox", "/tasks", "attester"),
	S("tasks", "inbox-full", "/tasks", "attester", capture="full"),
	S("tasks", "inbox-answer-form", "/tasks", "attester",
		steps=[("wait_for", "button[data-act=answer]"), ("click", "button[data-act=answer] >> nth=0"), ("wait", 600),
			SCROLL("form[id^=form-]")]),
	S("tasks", "inbox-second-signature", "/tasks", "compliance"),
	S("tasks", "inbox-overdue-filter", "/tasks?show=soon", "attester"),
	S("tasks", "inbox-empty", "/tasks", "viewer"),
	S("tasks", "inbox-queue", "/tasks", "queue_taker",
		steps=[("wait_for", "#inbox-groups"), ("wait", 800), SCROLL("text=Escalations waiting for an owner")]),
	S("tasks", "campaigns", "/attestation-campaigns", "rgo", capture="full"),
	S("tasks", "campaigns-top", "/attestation-campaigns", "rgo"),
	S("tasks", "campaigns-admin", "/attestation-campaigns", "admin", capture="full"),
	S("tasks", "campaigns-no-access", "/attestation-campaigns", "secretary"),
	S("tasks", "campaign-form", "/app/attestation-campaign/@CAMPAIGN_DOCS@", "admin", desk=True, capture="full"),
	S("tasks", "attestation-task-list", "/app/attestation-task", "admin", desk=True),

	# 09 Reports -------------------------------------------------------------
	S("reports", "reports", "/reports", "rgo", capture="full"),
	S("reports", "reports-top", "/reports", "rgo"),
	S("reports", "reports-forums", "/reports#forums", "rgo", steps=[SCROLL("#forums")]),
	S("reports", "reports-coverage", "/reports#coverage", "rgo", steps=[("wait", 1200), SCROLL("#coverage")]),
	S("reports", "reports-documents", "/reports#documents", "epo", steps=[("wait", 1200), SCROLL("#documents")]),
	S("reports", "reports-escalations", "/reports#escalations", "head_rg", steps=[("wait", 1500), SCROLL("#escalations")]),
	S("reports", "reports-analysis", "/reports", "head_rg",
		steps=[("wait", 2000), SCROLL("#analysis-period")]),
	S("reports", "reports-audit", "/reports", "audit"),
	S("reports", "governance-gaps", "/governance-gaps", "rgo", steps=[("wait", 2500)], capture="full"),
	S("reports", "emerging-risks", "/emerging-risks", "rgo", steps=[("wait", 2500)], capture="full"),

	# 10 Administration ------------------------------------------------------
	S("admin", "admin", "/admin", "admin", capture="full"),
	S("admin", "admin-top", "/admin", "admin"),
	S("admin", "admin-taxonomy-admin", "/admin", "rgo"),
	S("admin", "imports", "/imports", "admin", capture="full"),
	S("admin", "imports-top", "/imports", "admin"),
	S("admin", "imports-profile-chosen", "/imports", "admin",
		steps=[("wait_for", "#upload-profile"), ("wait_js", "() => document.querySelectorAll('#upload-profile option').length > 1"),
			("eval", "(() => { const s = document.getElementById('upload-profile'); if (s.selectedIndex < 1) { s.selectedIndex = 1; } s.dispatchEvent(new Event('change', {bubbles: true})); })()"),
			("wait", 900), SCROLL("#upload-form")]),
	S("admin", "imports-batch",
		lambda frappe: (lambda n: f"/imports?batch={n}" if n else None)(frappe.db.get_value("Import Batch", {}, "name", order_by="creation desc")),
		"admin", capture="full"),
	S("admin", "user-list", "/app/user", "admin", desk=True),
	S("admin", "user-form", "/app/user/committee.secretary@demo.example", "admin", desk=True),
	S("admin", "user-roles", "/app/user/committee.secretary@demo.example", "admin", desk=True,
		steps=[("click_text", "Roles & Permissions"), ("wait", 800)]),
	S("admin", "impersonate-dialog", "/app/user/committee.secretary@demo.example", "admin", desk=True,
		steps=[("click", "button:has-text('Impersonate')"), ("wait_for", ".modal.show"), ("wait", 500)]),
	S("admin", "role-profile-list", "/app/role-profile", "admin", desk=True),
	S("admin", "user-permission-list", "/app/user-permission", "admin", desk=True),
	S("admin", "user-permission-new", "/app/user-permission/new", "admin", desk=True),
	S("admin", "role-permissions-manager", "/app/permission-manager", "admin", desk=True),
	S("admin", "portal-branding", "/app/portal-branding", "admin", desk=True, capture="full"),
	S("admin", "assistant-settings", "/app/assistant-settings", "admin", desk=True, capture="full"),
	S("admin", "system-settings", "/app/system-settings", "admin", desk=True),
	S("admin", "guide-article-list", "/app/guide-article", "admin", desk=True),
	S("admin", "guide-article", "/app/guide-article", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("admin", "retention-class-list", "/app/retention-class", "records", desk=True),
	S("admin", "legal-hold-list", "/app/legal-hold", "records", desk=True),
	S("admin", "authority-delegation-list", "/app/authority-delegation", "admin", desk=True),
	S("admin", "refusal-log-list", "/app/governance-refusal-log", "admin", desk=True),
	S("admin", "error-log-list", "/app/error-log", "admin", desk=True),
	S("admin", "import-profile-list", "/app/import-profile", "admin", desk=True),
	S("admin", "reference-risk-category", "/app/risk-category", "rgo", desk=True),
	S("admin", "reference-risk-type", "/app/risk-type", "rgo", desk=True),
	S("admin", "reference-organization-unit", "/app/organization-unit", "rgo", desk=True),
	S("admin", "notification-channel-list", "/app/notification-channel", "admin", desk=True),
	S("admin", "notification-template-list", "/app/notification-template", "admin", desk=True,
		requires_doctype="Notification Template"),
	S("admin", "notification-template", "/app/notification-template", "admin", desk=True,
		requires_doctype="Notification Template",
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("admin", "notification-dispatch-list", "/app/notification-dispatch", "admin", desk=True),
	S("admin", "assistant-interaction-list", "/app/assistant-interaction", "admin", desk=True),

	# 11 Configuring workflows -----------------------------------------------
	S("configuring", "workflow-list", "/app/workflow", "admin", desk=True),
	S("configuring", "workflow-form", "/app/workflow/Governing Document Lifecycle", "admin", desk=True),
	S("configuring", "workflow-form-states", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[("scroll_to", "[data-fieldname=states]"), ("wait", 600)]),
	S("configuring", "workflow-form-transitions", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[("scroll_to", "[data-fieldname=transitions]"), ("wait", 600)]),
	S("configuring", "workflow-builder", "/app/workflow-builder/Governing Document Lifecycle", "admin", desk=True,
		steps=[("wait", 2500)]),
	S("configuring", "workflow-state-list", "/app/workflow-state", "admin", desk=True),
	S("configuring", "workflow-state-new", "/app/workflow-state/new", "admin", desk=True),
	S("configuring", "workflow-state-flag-list", "/app/workflow-state-flag", "admin", desk=True),
	S("configuring", "workflow-state-flag-document", "/app/workflow-state-flag?target_doctype=Governing%20Document",
		"admin", desk=True),
	S("configuring", "workflow-state-flag-form", "/app/workflow-state-flag?target_doctype=Governing%20Document",
		"admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("configuring", "workflow-state-flag-new", "/app/workflow-state-flag/new", "admin", desk=True),
	S("configuring", "lifecycle-gate-list", "/app/document-lifecycle-gate", "admin", desk=True),
	S("configuring", "lifecycle-gate-form", "/app/document-lifecycle-gate", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "approval-route-form", "/app/approval-route", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "formation-approval-route-form", "/app/formation-approval-route", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "watched-field-set-form", "/app/watched-field-set", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "escalation-matrix-form", "/app/escalation-matrix", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "sla-definition-form", "/app/sla-definition", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "escalation-template-form", "/app/escalation-template", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "classification-rule-set-form", "/app/classification-rule-set", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "business-calendar-new", "/app/business-calendar/new", "admin", desk=True, capture="full"),
	S("configuring", "notification-channel-form", "/app/notification-channel", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("configuring", "attestation-campaign-new", "/app/attestation-campaign/new", "admin", desk=True, capture="full"),
	S("configuring", "guide-article-form", "/app/guide-article", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		capture="full"),
	S("configuring", "refusal-log-list", "/app/governance-refusal-log", "admin", desk=True),
]


# Verification shots (area "verification"). These photograph the worked
# example in chapter 11 while it is set up on the demonstration site: a
# temporary "Legal Review" state and a temporary document to move through it.
# Unlike every other shot, some of them take an action (and are refused, or
# succeed on the temporary document), so they run only when asked for with
# --area verification, stage by stage, while the example is in place. When the
# example has been removed they skip, and the pictures already taken are kept.
VERIFY_DOC_TITLE = "Guide Verification Temporary Standard"


def _verification_doc(frappe, suffix=""):
	name = frappe.db.get_value("Governing Document", {"document_name": VERIFY_DOC_TITLE}, "name")
	return f"/policy?name={name}{suffix}" if name else None


def _vdoc(suffix=""):
	return lambda frappe: _verification_doc(frappe, suffix)


CONFIRM = ("click", "#action-panel button[type=submit]")

VERIFICATION: list[Shot] = [
	S("verification", "a1-review-actions", _vdoc(), "epo",
		note="The temporary document in Review, with the new action offered."),
	S("verification", "a2-refused-no-flag", _vdoc(), "epo",
		steps=[("click", "[data-lifecycle='Refer to Legal Review']"), ("wait", 400), CONFIRM,
			("wait", 3000)],
		note="Refused: the new state has no Workflow State Flag row yet."),
	S("verification", "a3-refused-no-phase", _vdoc(), "epo",
		steps=[("click", "[data-lifecycle='Refer to Legal Review']"), ("wait", 400), CONFIRM,
			("wait", 3000)],
		note="Refused: the state's flag row names no Phase."),
	S("verification", "a4-refused-by-gate", _vdoc(), "epo",
		note="The new gate is shown before anyone tries: the action would be refused today."),
	S("verification", "a4b-refused-by-gate-lifecycle", _vdoc("#lifecycle"), "epo", capture="full",
		note="The Lifecycle tab's readiness table names the gate that blocks the action."),
	S("verification", "a5-moved", _vdoc(), "epo",
		steps=[("click", "[data-lifecycle='Refer to Legal Review']"), ("wait", 400), CONFIRM,
			("wait", 3000)],
		note="The document moves into Legal Review."),
	S("verification", "a6-in-legal-review", _vdoc("#lifecycle"), "epo", capture="full"),
	S("verification", "a0-workflow-state-field", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[("eval", "(() => { const e = document.querySelector('[data-fieldname=workflow_state_field]'); if (e) e.scrollIntoView({block: 'center'}); })()"), ("wait", 600)],
		note="After the one-time switch the lifecycle runs on workflow_state."),
	S("verification", "a7-workflow-form", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[("scroll_to", "[data-fieldname=states]"), ("wait", 600)]),
	S("verification", "a7b-workflow-transitions", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[("scroll_to", "[data-fieldname=transitions]"), ("wait", 600)]),
	S("verification", "a7c-workflow-builder", "/app/workflow-builder/Governing Document Lifecycle", "admin",
		desk=True, steps=[("wait", 2500)]),
	S("verification", "a8-flag-row", "/app/workflow-state-flag?target_doctype=Governing%20Document&state_field=workflow_state&state_value=Legal%20Review",
		"admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("verification", "a8b-flag-rows-derived", "/app/workflow-state-flag?target_doctype=Governing%20Document&state_field=workflow_state",
		"admin", desk=True, note="The flag rows on workflow_state, each naming its Phase."),
	S("verification", "a10-gate-form", "/app/document-lifecycle-gate?notes=Guide%20verification", "admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)]),
	S("verification", "c1-rename-move-offered", _vdoc(), "epo",
		note="Renaming: the temporary action that carries records from the old name to the new one."),
	S("verification", "c2-rename-moved", _vdoc(), "epo",
		steps=[("click", "[data-lifecycle='Move to Legal Clearance']"), ("wait", 400), CONFIRM, ("wait", 3000)]),
	S("verification", "c3-rename-done", _vdoc("#lifecycle"), "epo", capture="full"),
	S("verification", "c4-list-old-state-empty", "/app/governing-document?workflow_state=Legal%20Review", "admin", desk=True),
	S("verification", "b1-new-workflow-form", "/app/workflow/Policy Violation Handling", "admin", desk=True,
		requires_record=("Workflow", "Policy Violation Handling"), capture="full"),
	S("verification", "b2-violation-actions",
		lambda frappe: (lambda n: f"/app/policy-violation/{n}" if n else None)(frappe.db.get_value(
			"Policy Violation", {"description": ["like", "Guide verification%"], "violation_status": "Logged"}, "name")),
		"owner", desk=True,
		steps=[("click", ".page-actions button:has-text('Actions')"), ("wait", 600)]),
	S("verification", "m1-home-guide-article", "/", "rgo", requires_record=("Guide Article", "guide-verification-temporary"),
		steps=[("wait_for", "#g1"), ("eval", "document.getElementById('guide-heading').scrollIntoView({block: 'start'})"), ("wait", 1200)],
		note="A published Guide Article replaces the home page's built-in 'Setting up a forum' section."),
	S("verification", "m2-guide-article-form", "/app/guide-article/guide-verification-temporary", "admin", desk=True,
		requires_record=("Guide Article", "guide-verification-temporary"), capture="full"),
	S("verification", "a11-refusal-log", "/app/governance-refusal-log", "admin", desk=True),
]
SHOTS.extend(VERIFICATION)


# ---------------------------------------------------------------------------
# Sessions — created server-side, never with a password.
# ---------------------------------------------------------------------------

class Sessions:
	"""One framework session per persona, created on first use and deleted at
	the end. The browser is given only the resulting ``sid`` cookie."""

	def __init__(self, frappe):
		self.frappe = frappe
		self.sids: dict[str, str] = {}

	def sid_for(self, user: str) -> str | None:
		if user == "guest":
			return None
		if user in self.sids:
			return self.sids[user]
		frappe = self.frappe
		from frappe.sessions import Session
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		# Session() reads the current request for an existing cookie and the
		# caller's address; give it an empty local request to read.
		frappe.local.request = Request(EnvironBuilder(path="/", base_url="http://" + frappe.local.site).get_environ())
		frappe.local.request_ip = "127.0.0.1"
		frappe.local.form_dict = frappe._dict()
		details = frappe.db.get_value("User", user, ["enabled", "full_name", "user_type"], as_dict=True)
		if not details or not details.enabled:
			raise RuntimeError(f"persona {user} does not exist or is disabled on this site")
		session = Session(user, resume=False, full_name=details.full_name, user_type=details.user_type)
		frappe.db.commit()
		self.sids[user] = session.sid
		return session.sid

	def close(self):
		from frappe.sessions import delete_session

		for user, sid in self.sids.items():
			try:
				delete_session(sid, user=user, reason="Logged Out")
			except Exception as exc:  # keep deleting the rest
				print(f"  could not delete the session for {user}: {exc}", file=sys.stderr)
		self.frappe.db.commit()
		self.sids.clear()


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

_SLUGS = None


_REFS = None


def refs(frappe) -> dict:
	global _REFS
	if _REFS is None:
		_REFS = resolve_refs(frappe)
	return _REFS


def resolve_route(frappe, shot: Shot) -> str | None:
	route = shot.route(frappe) if callable(shot.route) else shot.route
	return fill_refs(route, refs(frappe))


def resolve_persona(frappe, shot: Shot) -> str | None:
	return fill_refs(PERSONA.get(shot.persona, shot.persona), refs(frappe))


def route_exists(frappe, shot: Shot) -> str | None:
	"""Return a reason to skip the shot, or None."""
	if resolve_route(frappe, shot) is None:
		return "the record this shot shows does not exist on this site"
	if resolve_persona(frappe, shot) is None:
		return "nobody on this site holds the part this shot is taken as"
	if shot.requires_doctype and not frappe.db.exists("DocType", shot.requires_doctype):
		return f"record type {shot.requires_doctype} is not installed"
	if shot.requires_record and not frappe.db.exists(*shot.requires_record):
		return f"{shot.requires_record[0]} {shot.requires_record[1]} does not exist"
	if shot.desk:
		# /app/<slug>[/...] — check the record type behind the slug exists.
		parts = resolve_route(frappe, shot).split("?")[0].strip("/").split("/")
		if len(parts) >= 2 and parts[1] not in ("workflow-builder", "permission-manager", "governance",
				"policy", "escalation", "consilium-administration"):
			global _SLUGS
			if _SLUGS is None:
				_SLUGS = {n.lower().replace(" ", "-") for n in frappe.get_all("DocType", pluck="name")}
				_SLUGS |= {n.lower().replace(" ", "-") for n in frappe.get_all("Page", pluck="name")}
			if parts[1].lower() not in _SLUGS:
				return f"record type for /{'/'.join(parts[:2])} is not installed"
	return None


def run_step(page, step):
	kind = step[0]
	if kind == "click":
		page.locator(step[1]).first.click(timeout=6000)
	elif kind == "click_text":
		page.get_by_text(step[1], exact=False).first.click(timeout=6000)
	elif kind == "fill":
		page.locator(step[1]).first.fill(step[2], timeout=6000)
	elif kind == "select":
		page.locator(step[1]).first.select_option(step[2], timeout=6000)
	elif kind == "press":
		page.keyboard.press(step[1])
	elif kind == "wait":
		page.wait_for_timeout(step[1])
	elif kind == "wait_for":
		page.locator(step[1]).first.wait_for(state="visible", timeout=15000)
	elif kind == "scroll_to":
		page.locator(step[1]).first.scroll_into_view_if_needed(timeout=6000)
	elif kind == "hover":
		page.locator(step[1]).first.hover(timeout=6000)
	elif kind == "eval":
		page.evaluate(step[1])
	elif kind == "scroll_center":
		locator = page.locator(step[1]).first
		locator.wait_for(state="visible", timeout=8000)
		locator.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'instant'})")
		page.wait_for_timeout(900)
	elif kind == "wait_js":
		page.wait_for_function(step[1], timeout=30000)
	else:
		raise ValueError(f"unknown step {kind!r}")


def settle(page, shot: Shot):
	if shot.desk:
		# The workspace is a single-page application with a long-polling
		# socket; "network idle" never comes. Wait for the page body instead.
		page.wait_for_selector(".page-container, .layout-main, .workflow-builder, #page-Workspaces",
			state="visible", timeout=30000)
		page.wait_for_timeout(1800)
		# Hide the "you have unread notifications" style toasts that come and go.
		page.add_style_tag(content=".desk-alert, #alert-container { display: none !important; }")
	else:
		try:
			page.wait_for_load_state("networkidle", timeout=15000)
		except Exception:
			pass
		page.wait_for_timeout(700)


def snap(page, shot: Shot, path: Path):
	path.parent.mkdir(parents=True, exist_ok=True)
	if shot.capture == "viewport":
		page.screenshot(path=str(path))
	elif shot.capture == "full":
		height = page.evaluate("() => document.documentElement.scrollHeight")
		width = (shot.viewport or VIEWPORT)["width"]
		if height <= MAX_FULL_HEIGHT:
			page.screenshot(path=str(path), full_page=True)
		else:
			page.screenshot(path=str(path), full_page=True, clip={"x": 0, "y": 0, "width": width, "height": MAX_FULL_HEIGHT})
	elif shot.capture == "header":
		page.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": (shot.viewport or VIEWPORT)["width"], "height": 120})
	else:
		page.locator(shot.capture).first.screenshot(path=str(path))


def goto(page, url: str):
	"""Open a page, riding out a server restart.

	The platform is being worked on while the pictures are taken, and its
	development server restarts whenever code changes. A refused connection is
	retried for up to two minutes before the shot is given up."""
	deadline = time.time() + 120
	while True:
		try:
			return page.goto(url, wait_until="load", timeout=45000)
		except Exception as exc:
			if "ERR_CONNECTION_REFUSED" not in str(exc) or time.time() > deadline:
				raise
			page.wait_for_timeout(3000)


def is_missing_page(response, page) -> bool:
	if response is not None and response.status == 404:
		return True
	return False


def capture_all(frappe, base_url: str, shots: list[Shot]) -> list[dict]:
	from playwright.sync_api import sync_playwright

	sessions = Sessions(frappe)
	results = []
	try:
		with sync_playwright() as pw:
			browser = pw.chromium.launch(channel="chrome", headless=True)
			try:
				for shot in shots:
					results.extend(capture_one(frappe, browser, sessions, base_url, shot))
			finally:
				browser.close()
	finally:
		sessions.close()
	return results


def capture_one(frappe, browser, sessions: Sessions, base_url: str, shot: Shot) -> list[dict]:
	user = resolve_persona(frappe, shot) or PERSONA.get(shot.persona, shot.persona)
	record = {
		"area": shot.area, "name": shot.name, "route": None, "persona": user,
		"file": f"{shot.area}/{shot.name}.png", "theme": shot.theme or "light",
		"viewport": shot.viewport or VIEWPORT, "note": shot.note,
	}
	reason = route_exists(frappe, shot)
	if not reason:
		record["route"] = route = resolve_route(frappe, shot)
	if reason:
		print(f"  skip  {shot.area}/{shot.name}: {reason}")
		return [dict(record, status="skipped", reason=reason)]

	context = browser.new_context(viewport=shot.viewport or VIEWPORT, device_scale_factor=1,
		locale="en-GB", timezone_id=None)
	try:
		sid = sessions.sid_for(user)
		host = base_url.split("//", 1)[1].split(":")[0].split("/")[0]
		if sid:
			context.add_cookies([{"name": "sid", "value": sid, "domain": host, "path": "/"}])
		if shot.theme:
			context.add_init_script(f"try{{localStorage.setItem('cns:theme','{shot.theme}')}}catch(e){{}}")
		else:
			context.add_init_script("try{localStorage.removeItem('cns:theme');localStorage.removeItem('cns:fontsize')}catch(e){}")
		page = context.new_page()
		response = goto(page, base_url + route)
		if is_missing_page(response, page):
			print(f"  skip  {shot.area}/{shot.name}: {route} returns 404")
			return [dict(record, status="skipped", reason="page returns 404")]
		settle(page, shot)
		for step in shot.steps:
			run_step(page, step)
		out = []
		path = OUT / shot.area / f"{shot.name}.png"
		snap(page, shot, path)
		out.append(dict(record, status="captured", bytes=path.stat().st_size))
		print(f"  ok    {shot.area}/{shot.name}")
		if shot.tabs:
			tab_ids = page.eval_on_selector_all(".cns-tab", "els => els.filter(e => e.offsetParent).map(e => e.id)")
			for tab_id in tab_ids:
				tab_name = f"{shot.name}-{tab_id}"
				try:
					page.locator(f"#{tab_id}").click(timeout=6000)
					page.wait_for_timeout(700)
					page.evaluate("() => window.scrollTo(0, 0)")
					tab_path = OUT / shot.area / f"{tab_name}.png"
					snap(page, Shot(shot.area, tab_name, shot.route, capture="full"), tab_path)
					out.append(dict(record, name=tab_name, file=f"{shot.area}/{tab_name}.png", status="captured",
						bytes=tab_path.stat().st_size, note=f"tab {tab_id}"))
					print(f"  ok    {shot.area}/{tab_name}")
				except Exception as exc:
					out.append(dict(record, name=tab_name, status="failed", reason=str(exc).splitlines()[0][:300]))
					print(f"  FAIL  {shot.area}/{tab_name}: {str(exc).splitlines()[0][:200]}")
		return out
	except Exception as exc:
		message = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
		print(f"  FAIL  {shot.area}/{shot.name}: {message}")
		return [dict(record, status="failed", reason=message)]
	finally:
		context.close()


def write_manifest(results: list[dict], base_url: str, site: str, partial: bool):
	path = OUT / "manifest.json"
	earlier = {}
	if path.exists():
		for entry in json.loads(path.read_text()).get("shots", []):
			earlier[entry["file"]] = entry
	# A partial run keeps the entries it did not touch. A full run starts
	# afresh, except for the verification pictures, which it does not take.
	previous = dict(earlier) if partial else {k: v for k, v in earlier.items() if v.get("area") == "verification"}
	now = datetime.now(timezone.utc).isoformat(timespec="seconds")
	for entry in results:
		key = entry.get("file") or f"{entry['area']}/{entry['name']}.png"
		old = earlier.get(key)
		if entry["status"] in ("skipped", "failed") and (OUT / key).exists():
			# The screen (or the temporary set-up a verification shot shows) is
			# gone or broken right now, but the picture taken of it earlier is
			# still the one the guides use. Keep it, and say so.
			base = old if old and old.get("status") == "captured" else dict(
				entry, status="captured", captured_at=datetime.fromtimestamp(
					(OUT / key).stat().st_mtime, timezone.utc).isoformat(timespec="seconds"))
			base.pop("reason", None)
			previous[key] = dict(base, kept_from_earlier_run=True,
				not_refreshed_because=f"{entry['status']}: {entry.get('reason')}")
			continue
		entry["captured_at"] = now
		previous[key] = entry
	# Forget pictures of shots that are no longer defined.
	defined = {(s.area, s.name) for s in SHOTS}
	previous = {k: v for k, v in previous.items() if (v["area"], v["name"].split("-tab-")[0]) in defined}
	shots = sorted(previous.values(), key=lambda e: e["file"])
	summary = {
		"captured": sum(1 for e in shots if e["status"] == "captured" and not e.get("kept_from_earlier_run")),
		"kept_from_earlier_run": sum(1 for e in shots if e.get("kept_from_earlier_run")),
		"skipped": sum(1 for e in shots if e["status"] == "skipped"),
		"failed": sum(1 for e in shots if e["status"] == "failed"),
	}
	manifest = {
		"generated_at": now, "site": site, "server": base_url,
		"generator": "scripts/capture_screenshots.py", "summary": summary, "shots": shots,
	}
	path.write_text(json.dumps(manifest, indent=1) + "\n")
	return summary


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--site", default="consilium.localhost")
	parser.add_argument("--sites-path", default=".")
	parser.add_argument("--url", default="http://consilium.localhost:8000")
	parser.add_argument("--area", action="append", help="only this area (repeatable)")
	parser.add_argument("--only", action="append", help="only shots whose name matches this glob (repeatable)")
	parser.add_argument("--failed", action="store_true", help="only the shots the last run recorded as failed")
	parser.add_argument("--list", action="store_true", help="print the shot list and exit")
	args = parser.parse_args()

	shots = SHOTS
	if args.area:
		shots = [s for s in shots if s.area in args.area]
	else:
		shots = [s for s in shots if s.area != "verification"]
	if args.only:
		shots = [s for s in shots if any(fnmatch.fnmatch(s.name, g) for g in args.only)]
	if args.failed:
		manifest = OUT / "manifest.json"
		failed = {(e["area"], e["name"].split("-tab-")[0]) for e in json.loads(manifest.read_text())["shots"]
			if e["status"] == "failed"} if manifest.exists() else set()
		shots = [s for s in SHOTS if (s.area, s.name) in failed]
	if args.list:
		for s in shots:
			route = "(looked up when run)" if callable(s.route) else s.route
			print(f"{s.area:16} {s.name:36} {PERSONA.get(s.persona, s.persona):42} {route}")
		return 0

	import frappe

	frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
	frappe.connect()
	started = time.time()
	try:
		print(f"Capturing {len(shots)} shots from {args.url}")
		results = capture_all(frappe, args.url.rstrip("/"), shots)
	finally:
		frappe.destroy()
	summary = write_manifest(results, args.url, args.site, partial=bool(args.area or args.only or args.failed))
	print(f"\n{summary['captured']} captured, {summary['kept_from_earlier_run']} kept from an earlier run, "
		f"{summary['skipped']} skipped, {summary['failed']} failed "
		f"in {time.time() - started:.0f}s. Manifest: {OUT.relative_to(REPO)}/manifest.json")
	return 1 if summary["failed"] else 0


if __name__ == "__main__":
	raise SystemExit(main())
