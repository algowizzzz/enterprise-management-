"""Governance gap detection (O-6).

    GET  /api/method/consilium.consilium_core.ai.gaps.detect
    POST /api/method/consilium.consilium_core.ai.gaps.ai_commentary

"Real-time" here means computed from the records as they are at the moment
of asking: there is no batch and no cache, so a forum given a charter a
second ago is no longer a gap. The rules, each a plain query over records the
viewer may read:

* **coverage** — a risk category and an operating group (units at the
  Operating Group or Corporate Support level, as on the reports page) that no
  active forum covers. A parent category counts as covered when one of its
  sub-categories is. The full matrix is on ``/reports#coverage``; this lists
  only the empty cells so they can be worked through.
* **forums** without a charter, without a usable quorum rule, or without a
  pathway (no parent forum, no upstream link and no written escalation
  protocol: nobody to escalate to).
* **policies** in force or in draft with no approving forum; whose review
  date has passed; or with a review cycle open past its due date.
* **regulatory requirements** that are active and cited by no document and no
  forum.
* **escalation types** that no active rule of an active escalation matrix can
  route — a rule routes a type when its condition names the type, or does not
  constrain the type at all (a general rule), and it leads somewhere (a forum
  route or a role).

Each gap carries a severity (a fixed rule, written next to it) and a link. The
AI layer (optional) is asked to prioritise and comment; it sees the gap kinds,
counts, taxonomy names and record tokens, and the titles only in summary mode.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate

from consilium.consilium_core.ai import common, guard

CAPABILITY = "gaps"
FORUM = "Governance Forum"
DOCUMENT = "Governing Document"
GROUP_LEVELS = ("Operating Group", "Corporate Support")

SEVERITY = {"High": 3, "Medium": 2, "Low": 1}


def _gap(kind: str, severity: str, text: str, *, doctype: str | None = None, name: str | None = None,
         title: str | None = None, rule: str | None = None, **extra) -> dict:
	return {"kind": kind, "severity": severity, "text": text, "doctype": doctype, "name": name,
	        "title": title, "href": common.href(doctype, name) if doctype and name else extra.pop("href", None),
	        "rule": rule, **extra}


# ------------------------------------------------------------------ coverage


def coverage_gaps(forums: list) -> list[dict]:
	categories = common.readable("Risk Category", filters={"is_active": 1},
	                             fields=["name", "risk_category_name", "parent_risk_category"], order_by="lft asc")
	groups = common.readable("Organization Unit", filters={"is_active": 1, "unit_level": ["in", list(GROUP_LEVELS)]},
	                         fields=["name", "org_unit_name"], order_by="lft asc")
	parent_of = {c.name: c.parent_risk_category for c in categories}
	covered = set()
	for f in forums:
		if not (int(f.is_active or 0) and f.primary_risk_category and f.owning_operating_group):
			continue
		cat, guard_n = f.primary_risk_category, 0
		# The forum covers its category and, through it, every ancestor.
		while cat and guard_n < 20:
			covered.add((cat, f.owning_operating_group))
			cat, guard_n = parent_of.get(cat), guard_n + 1
	out = []
	for c in categories:
		for g in groups:
			if (c.name, g.name) not in covered:
				out.append(_gap(
					"coverage", "Medium" if c.parent_risk_category else "High",
					_("No active forum covers {0} for {1}.").format(c.risk_category_name or c.name, g.org_unit_name or g.name),
					title=f"{c.risk_category_name or c.name} × {g.org_unit_name or g.name}",
					rule=_("High for a top-level category, Medium for a sub-category."),
					category=c.name, group=g.name, href="/reports#coverage",
				))
	return out


# -------------------------------------------------------------------- forums


def forum_gaps(forums: list) -> list[dict]:
	names = [f.name for f in forums if int(f.is_active or 0)]
	chartered = set(frappe.get_all("Committee Charter", filters={"forum": ["in", names or common.NONE]}, pluck="forum"))
	upstream = set(frappe.get_all("Forum Link", filters={"parenttype": FORUM, "parent": ["in", names or common.NONE],
	                                                     "direction": "Upstream"}, pluck="parent"))
	out = []
	for f in forums:
		if not int(f.is_active or 0):
			continue
		title = f.forum_name or f.name
		if f.name not in chartered:
			out.append(_gap("forum_charter", "High", _("{0} has no charter.").format(title), doctype=FORUM, name=f.name, title=title,
			                rule=_("High: a forum without a charter has no recorded mandate.")))
		quorum_ok = bool(f.quorum_rule_type) and (f.quorum_rule_type == "All Voting Members" or float(f.quorum_value or 0) > 0)
		if not quorum_ok:
			out.append(_gap("forum_quorum", "High", _("{0} has no usable quorum rule.").format(title), doctype=FORUM, name=f.name,
			                title=title, rule=_("High: without a quorum rule no decision can be shown to be valid.")))
		if not (f.parent_forum or f.name in upstream or (f.escalation_protocol or "").strip()):
			out.append(_gap("forum_pathway", "Medium", _("{0} has no escalation pathway: no parent forum, no upstream link and no written protocol.").format(title),
			                doctype=FORUM, name=f.name, title=title, rule=_("Medium: matters it cannot resolve have nowhere recorded to go.")))
	return out


# ------------------------------------------------------------------ policies


def policy_gaps() -> list[dict]:
	today = common.today()
	docs = common.readable(DOCUMENT, fields=["name", "document_name", "approving_forum", "next_review_on",
	                                         "is_active", "is_editable", "retired_on", "document_owner"])
	out = []
	for d in docs:
		if d.retired_on:
			continue
		title = d.document_name or d.name
		live = int(d.is_active or 0) or int(d.is_editable or 0)
		if live and not d.approving_forum:
			out.append(_gap("policy_forum", "High" if int(d.is_active or 0) else "Medium",
			                _("{0} has no approving forum.").format(title), doctype=DOCUMENT, name=d.name, title=title,
			                rule=_("High when in force, Medium while in draft.")))
		if int(d.is_active or 0) and d.next_review_on and getdate(d.next_review_on) < today:
			days = (today - getdate(d.next_review_on)).days
			out.append(_gap("policy_review", "High" if days > 90 else "Medium",
			                _("{0} was due for review on {1} ({2} days ago).").format(title, d.next_review_on, days),
			                doctype=DOCUMENT, name=d.name, title=title, days_overdue=days,
			                rule=_("High when more than 90 days overdue, otherwise Medium.")))
	for c in common.readable("Document Review Cycle", filters={"is_open": 1, "due_on": ["<", str(today)]},
	                         fields=["name", "document", "due_on"]):
		out.append(_gap("review_cycle", "Medium", _("A review cycle of {0} is open past its due date {1}.").format(c.document, c.due_on),
		                doctype=DOCUMENT, name=c.document, title=c.document, cycle=c.name,
		                rule=_("Medium: the review was started but not concluded in time.")))
	return out


# ---------------------------------------------------------------- regulatory


def regulatory_gaps() -> list[dict]:
	requirements = common.readable("Regulatory Requirement", filters={"is_active": 1},
	                               fields=["name", "regulatory_requirement_name", "citation"])
	cited = set(frappe.get_all("Document Regulatory Reference", filters={"parenttype": DOCUMENT}, pluck="regulatory_requirement"))
	cited |= set(frappe.get_all("Forum Regulatory Requirement", filters={"parenttype": FORUM}, pluck="regulatory_requirement"))
	return [
		_gap("regulatory_uncited", "Medium",
		     _("{0} is cited by no governing document and no forum.").format(r.regulatory_requirement_name or r.name),
		     doctype="Regulatory Requirement", name=r.name, title=r.regulatory_requirement_name or r.name,
		     rule=_("Medium: an obligation nobody has said how they meet."))
		for r in requirements if r.name not in cited
	]


# ---------------------------------------------------------------- escalation


def escalation_route_gaps() -> list[dict]:
	from consilium.escalation import routing

	types = common.readable("Escalation Type", filters={"is_active": 1}, fields=["name", "escalation_type_name"])
	if not types:
		return []
	specific, general = set(), False
	for matrix_name in routing.active_matrices():
		matrix = frappe.get_doc("Escalation Matrix", matrix_name)
		routed_rules = {r.rule_code for r in matrix.get("routes") or [] if r.governance_forum}
		for rule in matrix.get("rules") or []:
			if not int(rule.is_active or 0):
				continue
			if not (rule.rule_code in routed_rules or rule.route_to_role):
				continue  # a rule that leads nowhere routes nothing
			condition = routing._loads(rule.condition) or {}
			expected = condition.get("escalation_type")
			if expected is None:
				general = True
			elif isinstance(expected, list):
				specific |= set(expected)
			else:
				specific.add(str(expected))
	out = []
	for t in types:
		if t.name in specific:
			continue
		title = t.escalation_type_name or t.name
		if general:
			out.append(_gap("escalation_general_only", "Low", _("{0} is routed only by a general rule, not one written for it.").format(title),
			                title=title, name=t.name, rule=_("Low: it will be routed, but by a rule that does not know it.")))
		else:
			out.append(_gap("escalation_unrouted", "High", _("No active escalation matrix rule routes {0}.").format(title),
			                title=title, name=t.name, rule=_("High: a matter of this type has no destination.")))
	return out


# ------------------------------------------------------------------- summary


KIND_LABELS = {
	"coverage": "Coverage: risk category × operating group",
	"forum_charter": "Forums without a charter",
	"forum_quorum": "Forums without a quorum rule",
	"forum_pathway": "Forums without a pathway",
	"policy_forum": "Policies without an approving forum",
	"policy_review": "Policies overdue for review",
	"review_cycle": "Review cycles open past due",
	"regulatory_uncited": "Regulatory requirements cited by nobody",
	"escalation_unrouted": "Escalation types with no route",
	"escalation_general_only": "Escalation types routed only generally",
}


def detection() -> dict:
	forums = common.readable(FORUM, fields=["name", "forum_name", "is_active", "primary_risk_category", "owning_operating_group",
	                                        "quorum_rule_type", "quorum_value", "parent_forum", "escalation_protocol", "confidential"])
	# Coverage is judged over forums; someone who may read none would see every
	# cell as a gap, which says nothing about coverage and much that is false.
	coverage = coverage_gaps(forums) if common.can_read(FORUM) else []
	gaps = (coverage + forum_gaps(forums) + policy_gaps() + regulatory_gaps() + escalation_route_gaps())
	gaps.sort(key=lambda g: (-SEVERITY[g["severity"]], g["kind"], g.get("title") or ""))
	by_kind = {}
	for g in gaps:
		by_kind.setdefault(g["kind"], {"kind": g["kind"], "label": _(KIND_LABELS.get(g["kind"], g["kind"])), "count": 0, "high": 0})
		by_kind[g["kind"]]["count"] += 1
		by_kind[g["kind"]]["high"] += 1 if g["severity"] == "High" else 0
	return {
		"generated_on": str(frappe.utils.now_datetime()),
		"gaps": gaps,
		"summary": sorted(by_kind.values(), key=lambda k: (-k["high"], -k["count"])),
		"counts": {s: sum(1 for g in gaps if g["severity"] == s) for s in SEVERITY},
		"visible": {"forums": common.can_read(FORUM), "documents": common.can_read(DOCUMENT),
		            "escalation_types": common.can_read("Escalation Type")},
		"ai": guard.availability(CAPABILITY),
		"note": _("Counted over the records you may read, at the moment you opened the page."),
	}


@frappe.whitelist(methods=["GET"])
def detect() -> dict:
	common.require_signed_in()
	return detection()


SYSTEM = """You review governance gaps found by rule-based checks in an enterprise governance, risk and policy platform: risk areas no committee covers, committees missing a charter, quorum or escalation pathway, policies without an approving committee or overdue for review, regulatory requirements nobody cites, escalation types with no route.
Write, in plain text with no headings or tables, at most 180 words:
- first, one or two sentences on the overall picture;
- then up to 6 bullet points ("- "), most urgent first, each naming the gap (by token where one is given) and the first action to take.
Use only the facts given."""


def build_payload(result: dict) -> guard.Payload:
	p = guard.Payload()
	p.line("Gap counts by kind (kind: total, of which high severity):")
	for k in result["summary"]:
		p.line(f"- {k['label']}: {k['count']}, high {k['high']}")
	coverage = [g for g in result["gaps"] if g["kind"] == "coverage"]
	if coverage:
		per_category = {}
		for g in coverage:
			per_category.setdefault(g["title"].split(" × ")[0], []).append(g["title"].split(" × ")[-1])
		p.line("Coverage gaps, by risk category (operating groups with no forum):")
		for category, groups in per_category.items():
			p.line(f"- {category}: {len(groups)} group(s) — {', '.join(groups[:8])}")
	p.line("Other gaps, most severe first (at most 40):")
	docs, forums = {}, {}
	doc_names = [g["name"] for g in result["gaps"] if g["doctype"] == DOCUMENT and g["name"]]
	if doc_names:
		docs = {r.name: r for r in frappe.get_all(DOCUMENT, filters={"name": ["in", doc_names]},
		                                          fields=["name", "handling_classification", "confidential"])}
	forum_names = [g["name"] for g in result["gaps"] if g["doctype"] == FORUM and g["name"]]
	if forum_names:
		forums = {r.name: r for r in frappe.get_all(FORUM, filters={"name": ["in", forum_names]}, fields=["name", "confidential"])}
	for g in [g for g in result["gaps"] if g["kind"] != "coverage"][:40]:
		kind = f"{g['severity']} {g['kind']}"
		if g["doctype"] == DOCUMENT:
			p.record(DOCUMENT, g["name"], guard.classification_of(DOCUMENT, docs.get(g["name"]) or {}), title=g["title"],
			         tags={"gap": kind}, href=g["href"])
		elif g["doctype"] == FORUM:
			p.record(FORUM, g["name"], guard.classification_of(FORUM, forums.get(g["name"]) or {}), title=g["title"],
			         tags={"gap": kind}, href=g["href"])
		else:
			# Taxonomy (risk categories, units, requirement and escalation type names) is reference data, not record content.
			p.line(f"- {kind}: {g['title']}")
	return p


@frappe.whitelist(methods=["POST"])
def ai_commentary() -> dict:
	common.require_signed_in()
	result = detection()
	payload = build_payload(result)
	outcome = guard.run(CAPABILITY, system=SYSTEM, payload=payload,
	                    accept=lambda text: guard.narrative_blocks(text, payload.links))
	return {"detection": result, "ai": {"used": outcome["used"], "status": outcome["status"], "notice": outcome["notice"],
	                                    "service_request": outcome["service_request"], "blocks": outcome["value"],
	                                    "withheld": outcome["withheld"], "mode": outcome.get("mode")}}
