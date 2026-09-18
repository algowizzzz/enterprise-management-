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
	# Numbered callouts drawn on the picture, in order: badge 1 on the first,
	# badge 2 on the second, and so on. Each is a C(...) (see below). The guide's
	# text under the picture explains ① ② ③ in the same order.
	callouts: list = field(default_factory=list)


def S(*args, **kwargs):
	return Shot(*args, **kwargs)


def C(target: str, pos: str = "tl", outline: bool = True, dx: int = 0, dy: int = 0, up: str | None = None) -> dict:
	"""One numbered callout.

	``target`` is a CSS selector, optionally suffixed ``@N`` for the N-th match
	(0-based), or ``text=Label`` for the innermost visible element whose own
	text is ``Label`` (a button, link, heading, tab or label). ``pos`` places the
	badge at a corner or side of the element: tl, tr, bl, br, l, r, t. ``outline``
	draws a highlight box round the element as well. ``dx``/``dy`` nudge the badge.
	``up`` widens the target to its nearest ancestor matching that selector (a
	menu entry rather than just its label, a table row rather than one cell).
	"""
	return {"target": target, "pos": pos, "outline": outline, "dx": dx, "dy": dy, "up": up}


# The callouts are drawn by this script, in the page, just before the picture
# is taken, and removed straight after. Nothing is added to the product: it is
# an overlay of absolutely positioned boxes on top of the page's own layout.
CALLOUT_JS = r"""
([specs, viewportOnly, maxY]) => {
  const old = document.getElementById("__guide_callouts");
  if (old) old.remove();
  const layer = document.createElement("div");
  layer.id = "__guide_callouts";
  layer.style.cssText = "position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;";
  document.body.appendChild(layer);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  };
  const find = (target) => {
    if (target.startsWith("text=")) {
      let want = target.slice(5).trim().toLowerCase(), nth = 0;
      const mm = want.match(/^(.*)@(\d+)$/);
      if (mm) { want = mm[1].trim(); nth = parseInt(mm[2], 10); }
      const pool = document.querySelectorAll("button, a, h1, h2, h3, h4, label, th, summary, legend, .cns-btn, [role=tab], .cns-card-title, .cns-menu-item-label, .cns-menu-label, span, p, li, td, option, div");
      const exact = [], prefix = [];
      for (const el of pool) {
        if (!visible(el)) continue;
        const own = (el.innerText || "").trim().replace(/\s+/g, " ").toLowerCase();
        if (own === want) exact.push(el);
        else if (own.startsWith(want) && own.length <= want.length + 120) prefix.push(el);
      }
      // innermost first: drop any element that contains another candidate
      const innermost = (list) => list.filter(el => !list.some(other => other !== el && el.contains(other)));
      const hits = innermost(exact).length ? innermost(exact) : innermost(prefix).sort((a, b) => a.innerText.length - b.innerText.length);
      return hits[nth] || null;
    }
    let index = 0, css = target;
    const m = target.match(/^(.*)@(\d+)$/);
    if (m) { css = m[1]; index = parseInt(m[2], 10); }
    const all = Array.from(document.querySelectorAll(css)).filter(visible);
    return all[index] || null;
  };
  const docW = Math.max(document.documentElement.scrollWidth, window.innerWidth);
  const missing = [];
  specs.forEach((spec, i) => {
    let el = find(spec.target);
    if (el && spec.up) el = el.closest(spec.up) || el;
    if (!el) { missing.push(spec.target); return; }
    const r = el.getBoundingClientRect();
    if (viewportOnly && (r.bottom < 0 || r.top > window.innerHeight)) { missing.push(spec.target + " (off screen)"); return; }
    if (!viewportOnly && maxY && r.top + window.scrollY > maxY - 20) { missing.push(spec.target + " (below the picture)"); return; }
    const x = r.left + window.scrollX, y = r.top + window.scrollY;
    if (spec.outline) {
      const box = document.createElement("div");
      box.style.cssText = `position:absolute;left:${x - 4}px;top:${y - 4}px;width:${r.width + 8}px;height:${r.height + 8}px;` +
        "border:3px solid #e8590c;border-radius:8px;box-shadow:0 0 0 2px rgba(255,255,255,.85);box-sizing:border-box;";
      layer.appendChild(box);
    }
    const size = 28;
    let bx, by;
    switch (spec.pos) {
      case "tr": bx = x + r.width - size / 2; by = y - size / 2; break;
      case "bl": bx = x - size / 2; by = y + r.height - size / 2; break;
      case "br": bx = x + r.width - size / 2; by = y + r.height - size / 2; break;
      case "l": bx = x - size - 8; by = y + r.height / 2 - size / 2; break;
      case "r": bx = x + r.width + 8; by = y + r.height / 2 - size / 2; break;
      case "t": bx = x + r.width / 2 - size / 2; by = y - size - 6; break;
      default: {
        // Outside the target, never on it: centred on its corner the badge hid
        // the first letters of the label it pointed at. Left of the target
        // first, then above it; each place is rejected if it would land on
        // text or a control, and the corner is the last resort.
        const firstLine = Math.min(r.height, 40);
        const places = [
          [x - size - 12, y + firstLine / 2 - size / 2],
          [x - 4, y - size - 8],
        ];
        const clear = (px, py) => {
          if (px < 2 || py < 2) return false;
          const vx = px + size / 2 - window.scrollX, vy = py + size / 2 - window.scrollY;
          if (vx < 0 || vy < 0 || vx > window.innerWidth || vy > window.innerHeight) return true;
          const hit = document.elementsFromPoint(vx, vy).find(e => !layer.contains(e));
          if (!hit || hit === el || el.contains(hit)) return !hit;
          if (/^(INPUT|TEXTAREA|SELECT|BUTTON|IMG|svg|LABEL|A|I|KBD)$/i.test(hit.tagName)) return false;
          return !Array.from(hit.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
        };
        const pick = places.find(([px, py]) => clear(px, py));
        if (pick) { bx = pick[0]; by = pick[1]; } else { bx = x - size / 2; by = y - size / 2; }
      }
    }
    bx = Math.min(Math.max(bx + (spec.dx || 0), 2), docW - size - 2);
    by = Math.max(by + (spec.dy || 0), 2);
    const badge = document.createElement("div");
    badge.textContent = String(i + 1);
    badge.style.cssText = `position:absolute;left:${bx}px;top:${by}px;width:${size}px;height:${size}px;border-radius:50%;` +
      "background:#e8590c;color:#fff;font:700 15px/28px -apple-system,'Segoe UI',Arial,sans-serif;text-align:center;" +
      "border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.35);box-sizing:content-box;";
    layer.appendChild(badge);
  });
  return missing;
}
"""


def draw_callouts(page, shot: Shot):
	if not shot.callouts:
		return
	missing = page.evaluate(CALLOUT_JS, [shot.callouts, shot.capture == "viewport",
		MAX_FULL_HEIGHT if shot.capture == "full" else 0])
	if missing:
		raise RuntimeError(f"callout target not found: {', '.join(missing)}")
	page.wait_for_timeout(150)


def clear_callouts(page):
	page.evaluate("() => { const l = document.getElementById('__guide_callouts'); if (l) l.remove(); }")


# ---------------------------------------------------------------------------
# The shot list. Grouped by the onboarding-guide chapter that uses it; the
# area is the picture's folder under docs/guides/images/.
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


def TOP(selector):
	"""Scroll an element to just below the header (the shot fails if it is not there)."""
	return ("scroll_top", selector)


def SCROLL(selector):
	"""Bring an element to the middle of the picture (the shot fails if it is not there)."""
	return ("scroll_center", selector)

PHONE_VIEW = {"width": 390, "height": 844}


def MENU(menu_id):
	"""Open one of the header's menus."""
	return [("click", f"#cns-menu-{menu_id}-btn"), ("wait", 600)]


def TAB(tab):
	"""Open a record page's tab."""
	return [("click", f"#tab-{tab}"), ("wait", 1000), ("eval", "window.scrollTo(0, 0)")]


ANSWERED = ("() => { const p = document.getElementById('cns-assistant-panel'); return p && p.getAttribute('aria-busy') !== 'true'"
	" && document.querySelector('.cns-assistant-msg-question') && document.querySelectorAll('.cns-assistant-log"
	" .cns-assistant-msg-answer, .cns-assistant-log .cns-assistant-msg-error').length > 0; }")


def ASK(question):
	"""Open the Help panel and ask it something (the AI can take a while)."""
	return [("click", ".cns-assistant-toggle"), ("wait_for", "#cns-assistant-input"),
		("fill", "#cns-assistant-input", question), ("press", "Enter"), ("wait_js", ANSWERED, 90000), ("wait", 900)]


def MENU_ITEMS(labels):
	return [C(f"text={label}", pos="l", up=".cns-menu-item") for label in labels]


def ACTION(action):
	"""Open an escalation or formation action's form."""
	return [("click", f"[data-action={action}]"), ("wait", 700), SCROLL("#action-panel")]


SHOTS: list[Shot] = [
	# 00 Welcome --------------------------------------------------------------
	S("welcome", "home-tour", "/", "rgo",
		callouts=[C(".cns-gsearch"), C("#cns-menu-mywork-btn"), C("text=Browse the forum inventory"),
			C("text=Request a new forum"), C(".cns-assistant-toggle", pos="tl")]),
	S("welcome", "home-full", "/", "rgo", capture="full"),
	S("welcome", "sign-in", "/forums", "guest", callouts=[C("text=Sign in", up="a,button")]),
	S("welcome", "home-board", "/", "viewer", callouts=[C(".cns-menubar")]),

	# 01 Finding your way -----------------------------------------------------
	S("navigation", "header", "/", "rgo", capture="header",
		callouts=[C(".cns-brand", dx=-4, dy=6), C(".cns-gsearch", dy=6), C(".cns-fontsize", dy=6), C(".cns-theme-btn", dy=6),
			C(".cns-user-btn", pos="tr", dy=6), C("#cns-menu-home-btn", dy=4), C("#cns-menu-mywork-btn", dy=4),
			C("#cns-menu-governance-btn", dy=4), C("#cns-menu-policies-btn", dy=4), C("#cns-menu-escalations-btn", dy=4),
			C("#cns-menu-insights-btn", dy=4), C("#cns-menu-admin-btn", dy=4)]),
	S("navigation", "menu-home", "/", "rgo", steps=MENU("home"),
		callouts=MENU_ITEMS(["Overview", "Forum map", "How it works"])),
	S("navigation", "menu-mywork", "/", "rgo", steps=MENU("mywork"),
		callouts=[C(".cns-nav-badge", pos="tr", outline=False)] + MENU_ITEMS(["All my tasks", "Due soon", "Approvals",
			"Reviews", "Attestations", "Escalations waiting for an owner"])),
	S("navigation", "menu-governance", "/", "rgo", steps=MENU("governance"),
		callouts=MENU_ITEMS(["Forum inventory", "Forum map", "Awaiting compliance review", "Overdue reviews",
			"Disbanded forums", "Request a new forum", "Formation requests"])),
	S("navigation", "menu-policies", "/", "rgo", steps=MENU("policies"),
		callouts=MENU_ITEMS(["Policy library", "In review", "Reviews due in 90 days", "Overdue reviews",
			"Request a policy or change", "Attestation campaigns", "Regulatory updates", "Horizon scanning"])),
	S("navigation", "menu-admin-full", "/", "admin", steps=MENU("admin"),
		callouts=MENU_ITEMS(["Administration", "Imports", "Attestation campaigns", "Branding", "Integrations",
			"Advanced configuration"])),
	S("navigation", "menu-escalations", "/", "rgo", steps=MENU("escalations"),
		callouts=MENU_ITEMS(["Escalation register", "Breached", "Awaiting review", "Closed", "Raise an escalation",
			"Escalation reporting"])),
	S("navigation", "menu-insights", "/", "rgo", steps=MENU("insights"),
		callouts=MENU_ITEMS(["Management reporting", "Coverage matrix", "Gaps and risk", "Emerging risks",
			"Regulatory updates"])),
	S("navigation", "menu-admin", "/", "rgo", steps=MENU("admin"),
		callouts=MENU_ITEMS(["Administration", "Imports", "Attestation campaigns", "Integrations",
			"Advanced configuration"])),
	S("navigation", "search", "/", "rgo",
		steps=[("click", ".cns-gsearch-input"), ("fill", ".cns-gsearch-input", "risk"), ("wait", 1800)],
		callouts=[C(".cns-gsearch-input"), C(".cns-gsearch-panel a@0", pos="l"), C("text=See all forums matching", pos="l", up="a")]),
	S("navigation", "user-menu", "/", "rgo", steps=[("click", ".cns-user-btn"), ("wait", 500)],
		callouts=[C("text=Profile", pos="l"), C("text=Sign out", pos="l")]),
	S("navigation", "page-anatomy", f"/forum?name={FORUM}", "rgo",
		callouts=[C(".cns-breadcrumb"), C(".cns-page-title"), C(".cns-page-actions"), C("#forum-summary"),
			C("[role=tablist]"), C(".cns-assistant-toggle")]),
	S("navigation", "list-filters", "/forums", "rgo",
		callouts=[C("#filter-heading", up=".cns-card"), C("#f-standing"), C("#filter-clear")]),
	S("navigation", "list-table", "/forums", "rgo", steps=[SCROLL("#forum-table .cns-dt-toolbar")],
		callouts=[C("#forum-table .cns-search"), C("text=Export CSV"), C("#forum-table .cns-dt-pagesize"),
			C("#forum-table .cns-table thead th@1"), C("#forum-table .cns-table tbody tr@0", pos="l")]),
	S("navigation", "list-empty", "/forums?q=zzzq", "rgo", steps=[SCROLL("#forum-table .cns-dt-state")],
		callouts=[C("#forum-table .cns-search"), C("#forum-table .cns-dt-state")]),
	S("navigation", "text-larger", "/forums", "rgo",
		steps=[("click", ".cns-fontsize button >> nth=1"), ("wait", 300), ("click", ".cns-fontsize button >> nth=1"), ("wait", 600)],
		callouts=[C(".cns-fontsize")]),
	S("navigation", "dark-theme", "/", "rgo", theme="dark", callouts=[C(".cns-theme-btn")]),
	S("navigation", "phone-header", "/", "rgo", viewport=PHONE_VIEW,
		callouts=[C(".cns-nav-toggle"), C(".cns-gsearch-open"), C(".cns-user-btn")]),
	S("navigation", "phone-menu", "/", "rgo", viewport=PHONE_VIEW,
		steps=[("click", ".cns-nav-toggle"), ("wait", 700)]),

	# 02 My work ----------------------------------------------------------------
	S("mywork", "all", "/tasks", "attester",
		callouts=[C("#inbox-summary"), C("#inbox-show"), C("text=Attestations to give"), C("text=Answer", pos="l"),
			C("text=Open", pos="r"), C("#inbox-refresh")]),
	S("mywork", "all-full", "/tasks", "attester", capture="full"),
	S("mywork", "due-soon", "/tasks?show=soon", "attester", callouts=[C("#inbox-show")]),
	S("mywork", "approvals", "/tasks?show=approvals", "head_rg", capture="full", callouts=[C("#inbox-show")]),
	S("mywork", "reviews", "/tasks?show=reviews", "compliance", capture="full", callouts=[C("#inbox-show")]),
	S("mywork", "answer", "/tasks?show=attestations", "attester",
		steps=[("wait_for", "button[data-act=answer]"), ("click", "button[data-act=answer] >> nth=0"), ("wait", 600),
			SCROLL("form[id^=form-]")],
		callouts=[C("form[id^=form-] input[type=radio]@0", pos="l", outline=False), C("form[id^=form-] textarea"),
			C("text=Record answer")]),
	S("mywork", "counter-sign", "/tasks?show=approvals", "second_signer", callouts=[C("text=Counter-sign", pos="l")]),
	S("mywork", "unowned", "/tasks?show=unowned", "queue_taker",
		callouts=[C("text=Take ownership", pos="l"), C("text=Open", pos="r")]),

	# 03 Governance -------------------------------------------------------------
	S("governance", "inventory", "/forums", "rgo",
		callouts=[C("text=Request a new forum"), C("#f-type"), C("#f-status"), C("#f-standing"), C("#filter-clear")]),
	S("governance", "inventory-table", "/forums", "rgo", steps=[SCROLL("#forum-table .cns-dt-toolbar")],
		callouts=[C("#forum-table .cns-search"), C("text=Export CSV"), C("#forum-table .cns-table tbody tr@0", pos="l")]),
	S("governance", "forum-map", "/#forum-map", "rgo", steps=[("wait", 1500), SCROLL("#forum-map")],
		callouts=[C("#forum-map"), C("#forum-map-list-wrap")]),
	S("governance", "forum", f"/forum?name={FORUM}", "rgo",
		callouts=[C("#forum-summary"), C("text=Edit this forum"), C("text=Annual review"), C("text=Disband this forum"),
			C("text=Back to inventory"), C("[role=tablist]")]),
	S("governance", "forum-compliance-view", f"/forum?name={FORUM_NONCOMPLIANT}", "compliance",
		callouts=[C("text=Record a compliance review")]),
	S("governance", "forum-tab-details", f"/forum?name={FORUM}", "rgo", steps=TAB("details"), capture="full",
		callouts=[C("#detail-mandate"), C("#detail-fields"), C("#detail-scope"), C("#detail-escalation")]),
	S("governance", "forum-tab-membership", f"/forum?name={FORUM}", "rgo", steps=TAB("members"),
		callouts=[C("#as-at"), C("#as-at-summary"), C("#members-table", pos="tl")]),
	S("governance", "forum-membership-past", f"/forum?name={FORUM_DISBANDED}", "rgo",
		steps=TAB("members") + [("fill", "#as-at", "2026-03-01"), ("press", "Tab"), ("wait", 1200)],
		callouts=[C("#as-at"), C("#as-at-summary")]),
	S("governance", "forum-tab-linkages", f"/forum?name={FORUM_EXEC}", "rgo", steps=TAB("links"), capture="full",
		callouts=[C("#forum-diagram"), C("#links-table")]),
	S("governance", "forum-tab-documents", f"/forum?name={FORUM}", "rgo", steps=TAB("docs"), capture="full",
		callouts=[C("#charter-heading", up=".cns-card"), C("#charter-actions-heading", up=".cns-card")]),
	S("governance", "forum-tab-decisions", f"/forum?name={FORUM}", "secretary", steps=TAB("decisions"), capture="full",
		callouts=[C("text=Put a motion"), C("#motions-table"), C("#meetings-table")]),
	S("governance", "forum-tab-escalations", f"/forum?name={FORUM}", "rgo", steps=TAB("escalations"),
		callouts=[C("#escalations-table")]),
	S("governance", "forum-tab-history", f"/forum?name={FORUM}", "audit", steps=TAB("history"), capture="full",
		callouts=[C("#reviews-table"), C("#forum-revisions-heading", up=".cns-card"), C("text=Record history", up=".cns-card"),
			C("text=Export evidence pack")]),
	S("governance", "forum-viewer", f"/forum?name={FORUM}", "viewer", callouts=[C(".cns-alert")]),
	S("governance", "forum-disbanded", f"/forum?name={FORUM_DISBANDED}", "rgo"),
	S("governance", "create-forum", "/create-forum", "secretary",
		callouts=[C("text=Before you start", up=".cns-card")]),
	S("governance", "create-forum-full", "/create-forum", "secretary", capture="full"),
	S("governance", "create-forum-buttons", "/create-forum", "secretary", steps=[SCROLL("#save-draft")],
		callouts=[C("#save-draft"), C("text=Submit for evaluation")]),
	S("governance", "formation-queue", "/formation-requests", "rgo",
		callouts=[C("text=Whose move it is"), C(".cns-table tbody tr@0", pos="l")]),
	S("governance", "formation-request", f"/formation-request?name={CFR_EVAL}", "rgo",
		callouts=[C("#request-summary"), C("#actions-card"), C("[role=tablist]")]),
	S("governance", "formation-evaluate", f"/formation-request?name={CFR_EVAL}", "rgo",
		viewport={"width": 1440, "height": 2300}, steps=[("click", "#tab-evaluation"), ("wait", 900), TOP("#findings-form")],
		callouts=[C("#findings-form select@0"), C("#findings-form textarea@0"), C("#save-findings")]),
	S("governance", "formation-return", f"/formation-request?name={CFR_EVAL}", "rgo",
		steps=ACTION("return_to_originator"), callouts=[C("#action-panel textarea"), C("#action-panel button[type=submit]")]),
	S("governance", "formation-answer", f"/create-forum?request={CFR_RETURNED}", "originator",
		steps=[("wait_for", "#response-card"), TOP("#response-card")],
		callouts=[C("#response-heading"), C("#originator_response"), C("#send-response")],
		note="The originator, who holds no raising role, answers the governance office's questions."),
	S("governance", "formation-approver", f"/formation-request?name={CFR_PENDING}", "head_rg",
		steps=[("click", "#tab-approval"), ("wait", 900), SCROLL("#step-forms")],
		callouts=[C("#steps-table"), C("#step-forms select@0"), C("#step-forms textarea@0"), C("#step-forms button[type=submit]@0")]),
	S("governance", "formation-blocked", f"/formation-request?name={CFR_PENDING}", "rgo", steps=[SCROLL("#action-buttons")],
		callouts=[C("[data-action=approve]"), C("#action-notes")]),
	S("governance", "formation-exception", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=ACTION("raise_exception"), callouts=[C("#action-panel textarea")]),
	S("governance", "formation-approved", f"/formation-request?name={CFR_APPROVED}", "rgo",
		callouts=[C("#forum-action"), C("#outcome")]),
	S("governance", "compliance-review", f"/forum-review?forum={FORUM_DRAFT}", "compliance", steps=[SCROLL("#review-form")],
		callouts=[C("#decision-group"), C("#comments"), C("#record-review")]),
	S("governance", "compliance-review-full", f"/forum-review?forum={FORUM_DRAFT}", "compliance", capture="full"),
	S("governance", "annual-review", f"/forum-review?forum={FORUM_ANNUAL}", "compliance",
		steps=[("wait_for", "#annual-review"), ("wait", 800), SCROLL("#annual-review")],
		callouts=[C("#annual-body table", pos="tl")]),
	S("governance", "meeting-minutes", "/app/forum-meeting/@MEETING@", "secretary", desk=True,
		steps=[("click", "button:has-text('minutes')"), ("wait_for", ".modal.show"), ("wait", 700)],
		callouts=[C(".modal.show .ql-editor, .modal.show [data-fieldname=minutes]"), C(".modal.show .btn-primary")]),
	S("governance", "meeting-form", "/app/forum-meeting/@MEETING@", "secretary", desk=True,
		callouts=[C("text=Correct minutes"), C("[data-fieldname=held_on]"), C("[data-fieldname=status]")]),
	S("governance", "motion-put", f"/forum-motion?forum={FORUM}", "secretary",
		callouts=[C("#propose-form input@0"), C("#propose-form input[type=date]"), C("#meeting"), C("#propose-form select@1"),
			C("#propose-form textarea"), C("text=Put the motion")]),
	S("governance", "motion-vote", f"/forum-motion?name={MOTION_OPEN}", "@MOTION_VOTER@",
		steps=[("wait_for", "#vote-card"), SCROLL("#vote-card")],
		callouts=[C("#vote-forms select@0"), C("#vote-forms textarea@0"), C("text=Cast my ballot")]),
	S("governance", "motion-outcome", f"/forum-motion?name={MOTION_OPEN}", "secretary",
		steps=[("wait_for", "#outcome-card"), SCROLL("#outcome-card")],
		callouts=[C("#outcome"), C("#casting"), C("text=Record the outcome and close the motion")]),
	S("governance", "motion-full", f"/forum-motion?name={MOTION_OPEN}", "secretary", capture="full",
		callouts=[C("#motion-summary"), C("#ballots-heading", up=".cns-card")]),
	S("governance", "charter-publish", f"/forum?name={FORUM}#docs", "rgo",
		viewport={"width": 1440, "height": 1250}, steps=[("wait_for", "#charter-publish-form"), SCROLL("#charter-publish-form")],
		callouts=[C("#publish-summary"), C("#publish-text"), C("#publish-file"), C("#publish-challenge-status"),
			C("text=Publish the version")]),
	S("governance", "charter-challenge", f"/forum?name={FORUM}#docs", "rgo",
		steps=[("wait_for", "#charter-challenge-form"), SCROLL("#charter-challenge-form")],
		callouts=[C("#challenge-status"), C("#challenge-comments"), C("text=Record the outcome")]),
	S("governance", "charter-challenge-request", f"/formation-request?name={CFR_PENDING}", "rgo",
		steps=[("click", "#tab-approval"), ("wait", 900), SCROLL("#charter-challenge-card")],
		callouts=[C("#charter-challenge select"), C("text=Record challenge outcome")]),
	S("governance", "disband-raise", f"/forum-disband?forum={FORUM}", "rgo", steps=[SCROLL("#raise-form")],
		callouts=[C("#trigger"), C("#successor"), C("#effective"), C("#disposition"), C("#approver-fields"),
			C("text=Raise the plan and ask for approval")]),
	S("governance", "disband-approver", f"/forum-disband?forum={FORUM_DISBANDING}", "disband_approver",
		steps=[SCROLL("text=Record the decision")],
		callouts=[C("text=Your decision"), C("text=Record the decision")]),
	S("governance", "disband-in-progress", f"/forum-disband?forum={FORUM_DISBANDING}", "rgo", capture="full",
		callouts=[C("text=Not ready to execute.", pos="l")]),
	S("governance", "disband-done", f"/forum-disband?forum={FORUM_DISBANDED}", "rgo", capture="full"),

	# 04 Policies ---------------------------------------------------------------
	S("policies", "library", "/policies", "epo",
		callouts=[C(".cns-page-actions"), C("#f-phase"), C("#f-standing"), C("#f-content"), C("#filter-clear")]),
	S("policies", "library-table", "/policies", "epo", steps=[SCROLL("#policy-table .cns-dt-toolbar")],
		callouts=[C("#policy-table .cns-search"), C("text=Export CSV"), C("#policy-table .cns-table tbody tr@0", pos="l")]),
	S("policies", "library-owner", "/policies", "@DOC_DECIDE_APPROVER@", callouts=[C("#my-steps-card")]),
	S("policies", "policy", f"/policy?name={DOC_PUBLISHED}", "epo",
		callouts=[C("#doc-summary"), C("text=Open in Doc AI"), C("text=Back to the library"), C("#action-buttons"),
			C("text=Correct metadata", up="button"), C("[role=tablist]")]),
	S("policies", "tab-details", f"/policy?name={DOC_PUBLISHED}", "epo", steps=TAB("details"), capture="full",
		callouts=[C("#detail-abstract"), C("#detail-fields"), C("#detail-people")]),
	S("policies", "tab-lifecycle", f"/policy?name={DOC_APPROVED}", "epo", steps=TAB("lifecycle"), capture="full",
		callouts=[C("#phase-strip"), C("#lifecycle-flags"), C("#readiness-body")]),
	S("policies", "tab-approval", f"/policy?name={DOC_REVIEW}", "epo", steps=TAB("approval"), capture="full",
		callouts=[C("#chain-body"), C("#steps-table"), C("#exception-body")]),
	S("policies", "tab-versions", f"/policy?name={DOC_VERSIONS}", "epo", steps=TAB("versions"), capture="full",
		callouts=[C("text=View", pos="l"), C("#publications-table")]),
	S("policies", "tab-reviews", f"/policy?name={DOC_OVERDUE}", "@DOC_OVERDUE_OWNER@", steps=TAB("reviews"), capture="full",
		callouts=[C("#cycles-table"), C("#horizon-body")]),
	S("policies", "tab-monitoring", f"/policy?name={DOC_MONITOR}", "epo", steps=TAB("monitoring"), capture="full",
		callouts=[C("#activities-table"), C("#results-table")]),
	S("policies", "tab-lineage", f"/policy?name={DOC_LINEAGE}", "epo", steps=TAB("lineage"), capture="full",
		callouts=[C("#lineage-list"), C("#relationships-table")]),
	S("policies", "action-confirm", f"/policy?name={DOC_APPROVED}", "epo",
		steps=[("click", "#action-buttons [data-lifecycle]:not([disabled])"), ("wait", 600), SCROLL("#action-panel")],
		callouts=[C("#action-panel textarea"), C("#action-panel button[type=submit]")]),
	S("policies", "action-blocked", f"/policy?name={DOC_REVIEW}", "epo", steps=[SCROLL("#action-buttons")],
		callouts=[C("[data-lifecycle='Record Approval']"), C("#action-notes")]),
	S("policies", "approval-decide", f"/policy?name={DOC_DECIDE}#approval", "doc_approver",
		steps=[("wait_for", "#step-forms"), SCROLL("#step-forms")],
		callouts=[C("#steps-table"), C("#step-forms select@0"), C("#step-forms textarea@0"), C("#step-forms button[type=submit]@0")]),
	S("policies", "approval-bypass", f"/policy?name={DOC_DECIDE}#approval", "epo",
		steps=[("wait_for", "#bypass-forms"), SCROLL("#bypass-forms")],
		callouts=[C("#bypass-forms select@0"), C("#bypass-forms textarea@0"), C("text=Authorise the bypass")]),
	S("policies", "gate-exception", f"/policy?name={DOC_REVIEW}#approval", "doc_steward_review",
		viewport={"width": 1440, "height": 1300}, steps=[("wait_for", "text=Ask for the exception"), ("wait", 800), TOP("#exception-body")],
		callouts=[C("text=Ask for a gate to be excused"), C("text=Valid to (optional)"), C("text=Justification"),
			C("text=Ask for the exception")]),
	S("policies", "version-upload", f"/policy?name={DOC_DRAFT}#versions", "doc_owner",
		steps=[("wait_for", "#upload-form"), SCROLL("#upload-form")],
		callouts=[C("#upload-form input[type=file]"), C("#upload-form textarea@0"), C("#upload-form button[type=submit]")]),
	S("policies", "version-revert", f"/policy?name={DOC_DRAFT}#versions", "doc_owner",
		steps=[("wait_for", "#revert-form"), SCROLL("#revert-form")],
		callouts=[C("#revert-form select"), C("#revert-form button[type=submit]")]),
	S("policies", "viewer", "/document-view?version=@VER_PLAIN@", "epo",
		callouts=[C("text=Open in Doc AI"), C(".cns-page-title")]),
	S("policies", "viewer-confidential", "/document-view?version=@VER_CONFIDENTIAL@", "epo",
		callouts=[C("text=This version", up=".cns-card"), C("text=Handling")]),
	S("policies", "doc-ai", f"/doc-ai?name={DOC_PUBLISHED}", "epo", callouts=[C(".cns-state")]),
	S("policies", "publish", f"/policy?name={DOC_PUBLISHED}#versions", "epo",
		steps=[("wait_for", "#publish-form"), SCROLL("#publish-form")],
		callouts=[C("text=Who would be notified?"), C("#publish-form select@0"), C("#publish-form input[type=checkbox]@0"),
			C("text=Add an audience"), C("text=Record the publication")]),
	S("policies", "review-cycle", f"/policy?name={DOC_OVERDUE}#reviews", "@DOC_OVERDUE_OWNER@",
		steps=[("wait_for", "#review-forms"), SCROLL("#review-forms")], callouts=[C("#review-forms")]),
	S("policies", "horizon-scan", f"/policy?name={DOC_PUBLISHED}#reviews", "epo",
		steps=[("wait_for", "#scan-form"), SCROLL("#scan-form")],
		callouts=[C("#scan-form select@0"), C("#add-source"), C("#scan-form button[type=submit]")]),
	S("policies", "monitoring-result", f"/policy?name={DOC_MONITOR}#monitoring", "epo",
		steps=[("wait_for", "[data-record-result]"), ("click", "[data-record-result] >> nth=0"), ("wait", 600),
			SCROLL("#result-form")],
		callouts=[C("#result-form select@0"), C("#result-form button[type=submit]")]),
	S("policies", "violation", f"/policy?name={DOC_PUBLISHED}#monitoring", "epo",
		steps=[("wait_for", "#violation-form"), SCROLL("#violation-form")],
		callouts=[C("#violation-form select@0"), C("#violation-form textarea@0"), C("#violation-form button[type=submit]")]),
	S("policies", "correct", f"/policy?name={DOC_PUBLISHED}", "epo", steps=[("wait_for", "#correct-form"), SCROLL("#correct")],
		callouts=[C("#correct-field"), C("#correct-value-field"), C("#correct-reason"), C("text=Record the correction")]),
	S("policies", "impact", f"/policy?name={DOC_PUBLISHED}", "epo",
		steps=[("click_text", "Assess the impact"), ("wait", 2500), SCROLL("text=Review points")],
		callouts=[C("text=Assess the impact"), C("text=How is this worked out?"), C("text=Points to review"), C("text=Who is affected")]),
	S("policies", "intake", "/policy-intake", "doc_owner",
		callouts=[C("text=Kind of request"), C("text=Why it is needed"), C("text=Raise the request")]),
	S("policies", "intake-classify", "/policy-intake?name=@INTAKE_REQUESTED@", "epo", capture="full",
		callouts=[C("text=Classify")]),
	S("policies", "intake-classified", "/policy-intake?name=@INTAKE_CLASSIFIED@", "epo", capture="full"),
	S("policies", "campaigns", "/attestation-campaigns", "rgo",
		callouts=[C("text=Open a forum campaign", up=".cns-card"), C("text=Open and generate tasks")]),
	S("policies", "campaigns-table", "/attestation-campaigns", "rgo", steps=[SCROLL(".cns-table")],
		callouts=[C(".cns-table tbody tr@0", pos="l"), C("text=Generate tasks")]),
	S("policies", "regulatory-list", "/regulatory-updates", "epo",
		callouts=[C("text=Horizon scanning"), C("text=Import changes from a file"), C(".cns-table tbody tr@0", pos="l")]),
	S("policies", "regulatory-detail", "/regulatory-updates?requirement=REQ_OP_RESILIENCE", "epo", capture="full",
		callouts=[C("text=Horizon scanning"), C("text=Most recent change"), C("text=Directly affected: records citing it"),
			C("text=Possibly affected: documents that do not cite it")]),
	S("policies", "horizon", "/horizon-scanning", "epo", callouts=[C(".cns-state")]),

	# 05 Escalations ------------------------------------------------------------
	S("escalations", "register", "/escalations", "head_rg",
		viewport={"width": 1440, "height": 1400}, callouts=[C("text=Raise an escalation"), C("#queue-card"), C("#f-standing"), C("#f-severity")]),
	S("escalations", "register-table", "/escalations", "head_rg", steps=[SCROLL("#escalation-table .cns-dt-toolbar")],
		callouts=[C("#escalation-table .cns-search"), C("text=Export CSV"), C("#escalation-table .cns-table tbody tr@0", pos="l")]),
	S("escalations", "raise", "/raise-escalation", "esc_owner", callouts=[C("text=Before you start", up=".cns-card")]),
	S("escalations", "raise-full", "/raise-escalation", "esc_owner", capture="full"),
	S("escalations", "raise-proposal", "/raise-escalation", "esc_owner",
		steps=[("select", "#escalation_type", "LIMIT_BREACH"), ("select", "#tier_1_risk_type", "FINANCIAL"), ("wait", 500),
			("select", "#tier_2_risk_type", "FIN_LIMIT"), ("click", "#risk_appetite_breach"), ("wait", 1500), SCROLL("#proposal")],
		callouts=[C("#severity"), C("#proposal"), C("#template-body")]),
	S("escalations", "raise-systemic", "/raise-escalation", "esc_owner", steps=[SCROLL("#systemic")],
		callouts=[C("#systemic", pos="l")]),
	S("escalations", "raise-errors", "/raise-escalation", "esc_owner",
		steps=[("click", "#raise-submit"), ("wait", 800), SCROLL("#form-errors")], callouts=[C("#form-errors")]),
	S("escalations", "matter", f"/escalation?name={ESC_BREACH}", "resp_owner",
		callouts=[C("#matter-summary"), C("#actions-card"), C("[role=tablist]")]),
	S("escalations", "tab-details", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=TAB("details"), capture="full",
		callouts=[C("#detail-description"), C("#detail-routing"), C("#detail-sla"), C("#durations-heading", up=".cns-card")]),
	S("escalations", "tab-impact", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=TAB("impact"), capture="full",
		callouts=[C("#entities-table"), C("#forums-table")]),
	S("escalations", "tab-response", f"/escalation?name={ESC_FULL}", "esc_owner", steps=TAB("response"), capture="full",
		callouts=[C("#plans-table"), C("#acceptances-table")]),
	S("escalations", "tab-reviews", f"/escalation?name={ESC_REVIEW}", "compliance", steps=TAB("reviews"),
		callouts=[C("#reviews-table")]),
	S("escalations", "tab-closure", f"/escalation?name={ESC_EXTERNAL}", "esc_owner", steps=TAB("closure"),
		callouts=[C("#closure-body")]),
	S("escalations", "tab-history", f"/escalation?name={ESC_FULL}", "audit", steps=TAB("history"), capture="full",
		callouts=[C("#revisions-heading", up=".cns-card"), C("text=Record history", up=".cns-card"), C("text=Export evidence pack")]),
	S("escalations", "take-ownership", f"/escalation?name={ESC_QUEUE}", "queue_taker",
		steps=[("wait_for", "#actions-card"), SCROLL("#actions-card")], callouts=[C("[data-action=take_ownership]")]),
	S("escalations", "move-status", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=ACTION("move_status"),
		callouts=[C("#action-panel select@0"), C("#action-panel button[type=submit]")]),
	S("escalations", "add-plan", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=ACTION("add_action_plan"),
		callouts=[C("#action-panel input@0"), C("#action-panel input[type=date]@0"), C("#action-panel input[type=date]@1"),
			C("#action-panel textarea"), C("#action-panel button[type=submit]")]),
	S("escalations", "risk-acceptance", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=ACTION("add_risk_acceptance"),
		callouts=[C("#action-panel input@0"), C("#action-panel textarea@0"), C("#action-panel button[type=submit]")]),
	S("escalations", "decide-acceptance", f"/escalation?name={ESC_REVIEW}", "head_rg", steps=ACTION("decide_approval"),
		callouts=[C("#action-panel select@0"), C("#action-panel select@1"), C("#action-panel textarea"),
			C("#action-panel button[type=submit]")]),
	S("escalations", "pathway", f"/escalation?name={ESC_BREACH}", "resp_owner", steps=ACTION("change_pathway"),
		callouts=[C("#pathway-rows"), C("#pathway-add"), C("#pathway-propose"), C("#action-panel button[type=submit]")]),
	S("escalations", "review-round", f"/escalation?name={ESC_REVIEW}", "compliance", steps=ACTION("record_review"),
		callouts=[C("#action-panel select@0"), C("#action-panel textarea"), C("#action-panel button[type=submit]")]),
	S("escalations", "record-closure", f"/escalation?name={ESC_BREACH}", "resp_owner",
		viewport={"width": 1440, "height": 1500}, steps=[("click", "[data-action=record_closure]"), ("wait", 700), TOP("#action-panel")],
		callouts=[C("#action-panel select@0"), C("#criteria-rows"), C("#action-panel button[type=submit]")]),
	# "Close the matter" is offered only once a closure is recorded, and a shot
	# never records one: this shows the actions before that step.
	S("escalations", "close", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("wait_for", "[data-action=record_closure]"), SCROLL("#actions-card")],
		callouts=[C("[data-action=record_closure]")]),
	S("escalations", "time-in-status", f"/escalation?name={ESC_BREACH}", "resp_owner",
		steps=[("wait_for", "#durations-body"), ("wait", 1200), SCROLL("#durations-heading")],
		callouts=[C("#durations-body table@0", pos="tl")]),
	S("escalations", "sensitive-holder", f"/escalation?name={ESC_SENSITIVE}", "sensitive"),
	S("escalations", "sensitive-named", f"/escalation?name={ESC_SENSITIVE}", "sensitive_named"),
	S("escalations", "sensitive-refused", f"/escalation?name={ESC_SENSITIVE}", "esc_owner"),
	S("escalations", "systemic", f"/escalation?name={ESC_SYSTEMIC}", "rgo", callouts=[C("#matter-summary")]),

	# 06 Insights ---------------------------------------------------------------
	S("insights", "reports", "/reports", "rgo",
		callouts=[C(".cns-analysis-nav"), C("#refresh-report"), C("#print-report"), C("#report-stamp"), C("#headline-heading", up="section")]),
	S("insights", "reports-full", "/reports", "rgo", capture="full"),
	S("insights", "coverage", "/reports#coverage", "rgo", steps=[("wait", 1200), SCROLL("#coverage")],
		callouts=[C("#coverage-subject"), C("#coverage-matrix")]),
	S("insights", "documents", "/reports#documents", "epo", steps=[("wait", 1200), SCROLL("#documents-heading")],
		callouts=[C("#bars-doc-phase")]),
	S("insights", "escalations", "/reports#escalations", "head_rg", steps=[("wait", 1500), SCROLL("#escalations")]),
	S("insights", "analysis", "/reports", "head_rg", viewport={"width": 1440, "height": 1700}, steps=[("wait", 2000), TOP("#analysis-period")],
		callouts=[C("#analysis-period"), C("text=Download@4")]),
	S("insights", "gaps", "/governance-gaps", "rgo", steps=[("wait", 2500)],
		callouts=[C(".cns-analysis-nav"), C("text=High-severity gaps", up=".cns-card, .cns-stat"), C("text=What is missing", up=".cns-card")]),
	S("insights", "gaps-ai", "/governance-gaps", "rgo",
		steps=[("wait", 2500), ("click_text", "Ask the AI service to prioritise these gaps"),
			("wait", 1500), ("wait_js", "() => !/Asking(…|\\.\\.\\.)/.test(document.body.innerText)", 150000),
			("wait", 4000), SCROLL("text=Machine-generated")],
		callouts=[C("text=Machine-generated", up=".cns-ai-box, .cns-card, section")]),
	S("insights", "emerging", "/emerging-risks", "rgo", steps=[("wait", 2500)],
		callouts=[C("#trend-months"), C("text=Rising", up=".cns-card")]),
	S("insights", "regulatory", "/regulatory-updates", "rgo"),

	# 07 The Help assistant ---------------------------------------------------
	S("assistant", "help-button", "/forums", "rgo", callouts=[C(".cns-assistant-toggle")]),
	S("assistant", "help-open", "/forums", "rgo",
		steps=[("click", ".cns-assistant-toggle"), ("wait_for", "#cns-assistant-panel"), ("wait", 600)],
		callouts=[C(".cns-assistant-starters"), C("#cns-assistant-input"), C(".cns-assistant-tools")]),
	S("assistant", "help-answer", "/forums", "secretary", steps=ASK("How do I ask for a new forum?"),
		callouts=[C(".cns-assistant-log", pos="l"), C(".cns-assistant-sources", pos="l"), C(".cns-assistant-mode", pos="l")]),
	S("assistant", "help-why", f"/formation-request?name={CFR_PENDING}", "secretary", steps=ASK("Why can't I approve this?"),
		callouts=[C(".cns-assistant-log", pos="l")]),

	# 09 Administration ---------------------------------------------------------
	S("admin", "home", "/admin", "rgo",
		callouts=[C("#people-heading", up=".cns-card"), C("#reference-table"), C("text=Add a value"), C("#refresh-counts")]),
	S("admin", "home-lower", "/admin", "rgo", viewport={"width": 1440, "height": 1300}, steps=[TOP("#guide-heading")],
		callouts=[C("#guide-heading", up=".cns-card"), C("#config-heading", up=".cns-card")]),
	S("admin", "users", "/app/user", "admin", desk=True),
	S("admin", "user-roles", "/app/user/@ATTESTER@", "admin", desk=True,
		steps=[("click", ".form-tabs .nav-link:has-text('Roles')"), ("wait", 900)]),
	S("admin", "role-profiles", "/app/role-profile", "admin", desk=True),
	S("admin", "reference-list", "/app/risk-category", "admin", desk=True),
	S("admin", "reference-value", "/app/risk-category/CLIMATE", "admin", desk=True,
		callouts=[C("[data-fieldname=risk_category_name]"), C("[data-fieldname=is_active]")]),
	S("admin", "imports", "/imports", "rgo",
		callouts=[C("#upload-profile"), C("#upload-file"), C("#upload-form button[type=submit]")]),
	S("admin", "imports-batch",
		lambda frappe: (lambda n: f"/imports?batch={n}" if n else None)(frappe.db.get_value("Import Batch", {}, "name", order_by="creation desc")),
		"rgo", capture="full", callouts=[C("#batch-metrics"), C("#action-buttons"), C("#row-table")]),
	S("admin", "branding", "/app/portal-branding", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=portal_name]"), C("[data-fieldname=logo]"), C("[data-fieldname=primary_colour]"),
			C("[data-fieldname=hero_title]")]),
	S("admin", "notification-list", "/app/notification-template", "admin", desk=True),
	S("admin", "notification-template", "/app/notification-template/policy.review.overdue-EMAIL", "admin", desk=True,
		capture="full", callouts=[C("[data-fieldname=is_active]"), C("[data-fieldname=subject]"), C("[data-fieldname=body]"),
			C("[data-fieldname=context_help]")]),
	S("admin", "time-limit", "/app/sla-definition/@SLA_HIGH@", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=target_hours]"), C("[data-fieldname=warning_threshold_pct]"), C("[data-fieldname=calendar]")]),
	S("admin", "calendar", "/app/business-calendar/@CALENDAR@", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=day_start]"), C("[data-fieldname=holidays]")]),
	S("admin", "routing-rules", "/app/escalation-matrix/@MATRIX@", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=rules]"), C("[data-fieldname=routes]"), C("[data-fieldname=rule_notifications]")]),
	S("admin", "forum-approval-route", "/app/formation-approval-route/@FORMATION_ROUTE@", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=request_type]"), C("[data-fieldname=steps]")]),
	S("admin", "policy-approval-route", "/app/approval-route/Major Change Route", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=change_classification]"), C("[data-fieldname=priority]"), C("[data-fieldname=steps]")]),
	S("admin", "campaign", "/app/attestation-campaign/@CAMPAIGN_DOCS@", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=period_label]"), C("[data-fieldname=due_on]"), C("[data-fieldname=status]"),
			C("[data-fieldname=reminder_schedule]")]),
	S("admin", "guide-article", "/app/guide-article/new", "admin", desk=True,
		callouts=[C("[data-fieldname=title]"), C("[data-fieldname=category]"), C("[data-fieldname=is_published]")]),
	S("admin", "watched-fields", "/app/watched-field-set/Governance Forum", "admin", desk=True, capture="full",
		callouts=[C("[data-fieldname=on_change_action]"), C("[data-fieldname=fields]")]),
	S("admin", "integrations", "/integrations", "admin", callouts=[C(".cns-alert")]),
	S("admin", "integration-ai", "/integrations", "admin", viewport={"width": 1440, "height": 1400}, steps=[SCROLL("#ai-heading")],
		callouts=[C("#ai-heading"), C("text=API key"), C("text=Use it for"), C("text=Test connection")]),
	S("admin", "integration-ai-sharing", "/integrations", "admin", steps=[SCROLL("text=What may be shared")],
		callouts=[C("text=What may be shared"), C("text=Highest classification that may leave"), C("text=Analysis features")]),
	S("admin", "integration-docai", "/integrations", "admin", steps=[SCROLL("#docai-heading")],
		callouts=[C("#docai-heading"), C("text=Show the Doc AI button"), C("text=Address template")]),
	S("admin", "integration-horizon", "/integrations", "admin", steps=[SCROLL("#horizon-heading")],
		callouts=[C("#horizon-heading"), C("text=Show the horizon scanning button")]),
	S("admin", "integration-email", "/integrations", "admin", viewport={"width": 1440, "height": 1350}, steps=[TOP("#email-heading")],
		callouts=[C("#email-heading"), C("text=Send notification email through"), C("text=Send a test email to me")]),
	S("admin", "integration-sso", "/integrations", "admin", viewport={"width": 1440, "height": 1100}, steps=[TOP("#sso-heading")],
		callouts=[C("#sso-heading"), C("text=Redirect URI to register"), C("text=Copy", up="button")]),
	S("admin", "refusal-log", "/app/governance-refusal-log", "admin", desk=True),
]


# Verification shots (area "verification"). These photograph the worked
# example in the onboarding guide's chapter 9 while it is set up on the
# demonstration site: a temporary "Legal Review" step and a temporary document
# to move through it (see OPERATIONS.md, appendix B and E).
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
	# The onboarding guide's chapter 9 (adding a step to the policy lifecycle).
	S("verification", "step-states", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[TOP("[data-fieldname=states]")], callouts=[C("text=Legal Review", up=".grid-row", pos="l")]),
	S("verification", "step-transitions", "/app/workflow/Governing Document Lifecycle", "admin", desk=True,
		steps=[TOP("[data-fieldname=transitions]")], callouts=[C("text=Refer to Legal Review", up=".grid-row", pos="l")]),
	S("verification", "step-flag", "/app/workflow-state-flag?target_doctype=Governing%20Document&state_field=workflow_state&state_value=Legal%20Review",
		"admin", desk=True,
		steps=[("click", ".list-row-container .list-subject a >> nth=0"), ("wait_for", ".form-layout"), ("wait", 900)],
		viewport={"width": 1440, "height": 1100},
		callouts=[C("[data-fieldname=state_value]"), C("[data-fieldname=phase]"), C("[data-fieldname=is_editable]")]),
	S("verification", "step-offered", _vdoc(), "epo", steps=[SCROLL("#action-buttons")],
		callouts=[C("[data-lifecycle='Refer to Legal Review']")]),
	S("verification", "step-in-legal-review", _vdoc(), "epo", callouts=[C("#doc-summary")]),
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
	elif kind == "scroll_top":
		locator = page.locator(step[1]).first
		locator.wait_for(state="visible", timeout=8000)
		locator.evaluate("e => { e.scrollIntoView({block: 'start', behavior: 'instant'}); window.scrollBy(0, -130); }")
		page.wait_for_timeout(700)
	elif kind == "wait_js":
		page.wait_for_function(step[1], timeout=step[2] if len(step) > 2 else 30000)
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


#: (real, stand-in) pairs replaced on every page before it is photographed.
#: The site's own AI endpoint and model are configuration, not product: a guide
#: that pictured them would name whichever provider the demonstration happened
#: to use. They are read from the site at start-up (``scrub_pairs``), so this
#: file names no provider either.
SCRUB: list[tuple[str, str]] = []

SCRUB_JS = """
(pairs) => {
  const swap = (text) => pairs.reduce((t, [a, b]) => t.split(a).join(b), text);
  document.querySelectorAll("input, textarea").forEach(el => {
    if (el.value && pairs.some(([a]) => el.value.includes(a))) el.value = swap(el.value);
  });
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (pairs.some(([a]) => n.nodeValue.includes(a))) n.nodeValue = swap(n.nodeValue);
  }
}
"""


def scrub_pairs(frappe) -> list[tuple[str, str]]:
	"""The configured AI endpoint, its host and model, each with a neutral stand-in."""
	from urllib.parse import urlsplit

	try:
		settings = frappe.get_single("Assistant Settings")
	except Exception:
		return []
	pairs = []
	endpoint = (settings.endpoint_url or "").strip()
	host = urlsplit(endpoint).hostname if endpoint else None
	if endpoint:
		pairs.append((endpoint, "https://ai-gateway.example.internal/v1/chat/completions"))
	if host:
		pairs.append((host, "ai-gateway.example.internal"))
	if (settings.model or "").strip():
		pairs.append((settings.model.strip(), "your-model-name"))
	return pairs


def snap(page, shot: Shot, path: Path):
	path.parent.mkdir(parents=True, exist_ok=True)
	if SCRUB:
		page.evaluate(SCRUB_JS, SCRUB)
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
		draw_callouts(page, shot)
		snap(page, shot, path)
		clear_callouts(page)
		out.append(dict(record, status="captured", bytes=path.stat().st_size,
			callouts=[c["target"] for c in shot.callouts]))
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
	SCRUB[:] = scrub_pairs(frappe)
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
