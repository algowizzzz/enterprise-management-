"""Policy-change impact assessment (O-6).

    GET  /api/method/consilium.consilium_core.ai.impact.assess
         document, version?, change_summary?
    POST /api/method/consilium.consilium_core.ai.impact.ai_commentary
         document, version?, change_summary?

Given a governing document and a proposed change — a new version, or a
sentence describing the change — ``assess`` works out from the data what the
change reaches, with no model:

* **lineage**: parents and ancestors (whose owners may have to approve),
  children and addenda (which may need consequential changes), and what it
  supersedes or is superseded by — read through the policy module's own
  lineage engine, so there is one definition of the graph;
* **applicability**: the scopes in force and how many people they reach —
  through the applicability engine, which is also what notifies them;
* **regulatory references** it cites, and what else cites the same
  requirements (through the regulatory requirement's own ``citing_records``);
* **forums**: the approving forum and the forums it reports to;
* **monitoring activities and controls** that test it, with their last result;
* **open violations and escalations** that reference it;
* and, when a version is named, **which sections changed**, by a line diff of
  the version text against the current one.

From those it derives a reach rating and a checklist of review points. That
is the whole feature with AI off. With AI on, ``ai_commentary`` sends the same
facts — through the gate in ``guard.py`` — and returns a short narrative and
extra review points, labelled as machine-generated. Nothing is written.

Every record listed is one the viewer may read; the page says so.
"""

from __future__ import annotations

import difflib
import re

import frappe
from frappe import _
from frappe.utils import getdate

from consilium.consilium_core.ai import common, guard

DOCTYPE = "Governing Document"
CAPABILITY = "impact"

#: A line that reads as a section heading: markdown, numbered clauses, or a
#: short line in capitals. A heuristic, stated as one on the page.
HEADING = re.compile(
	r"^\s*(?:#{1,6}\s+\S.{0,100}|(?:[Ss]ection\s+)?\d+(?:\.\d+)*[.)]?\s+[A-Z].{0,100}|[A-Z][A-Z0-9 ,&/()'-]{3,80})\s*$"
)

#: A result a monitoring activity can record that says the control did not do its job.
ADVERSE_OUTCOMES = ("Not Effective", "Partially Effective", "Not Performed")


def _load(document: str):
	common.require_signed_in()
	if not document or not frappe.db.exists(DOCTYPE, document):
		raise frappe.DoesNotExistError(_("No governing document {0}.").format(document))
	doc = frappe.get_doc(DOCTYPE, document)
	# The document's has_permission hook applies here: a restricted document
	# the viewer may not see is refused exactly as it is on its own page.
	if not frappe.has_permission(DOCTYPE, "read", doc=doc):
		raise frappe.PermissionError(_("You may not read {0}.").format(document))
	return doc


def _docs(names) -> dict[str, dict]:
	names = [n for n in set(names or []) if n]
	if not names:
		return {}
	rows = common.readable(DOCTYPE, filters={"name": ["in", names]}, fields=[
		"name", "document_name", "document_owner", "is_active", "handling_classification", "confidential",
		"lifecycle_phase", "document_type", "primary_risk_category"])
	return {row.name: row for row in rows}


def _doc_entry(row, **extra) -> dict:
	return {"name": row.name, "title": row.document_name, "owner": row.document_owner,
	        "in_force": bool(row.is_active), "href": common.href(DOCTYPE, row.name), **extra}


# ---------------------------------------------------------------- the parts


def _lineage(doc) -> dict:
	from consilium.policy import lineage

	children = lineage.children(doc.name)
	parents = lineage.parents(doc.name)
	ancestors = lineage.ancestors(doc.name)
	descendants = lineage.descendants(doc.name)
	superseded = [r.name for r in frappe.get_all(DOCTYPE, filters={"superseded_by": doc.name}, fields=["name"])]
	superseded += [r.related_document for r in frappe.get_all(
		"Document Relationship", filters={"parent": doc.name, "parenttype": DOCTYPE, "relationship_type": "Supersedes"},
		fields=["related_document"])]
	referenced_by = [r.parent for r in frappe.get_all(
		"Document Relationship", filters={"related_document": doc.name, "parenttype": DOCTYPE,
		                                  "relationship_type": "References"}, fields=["parent"])]
	seen = _docs(parents + ancestors + [c["document"] for c in children] + descendants + superseded
	             + referenced_by + ([doc.superseded_by] if doc.superseded_by else []))
	return {
		"parents": [_doc_entry(seen[n], owner_approval=any(
			r.related_document == doc.name and int(r.owner_approval_required or 0)
			for r in frappe.get_all("Document Relationship", filters={"parent": n, "parenttype": DOCTYPE},
			                        fields=["related_document", "owner_approval_required"])))
			for n in parents if n in seen],
		"ancestors": [_doc_entry(seen[n]) for n in ancestors if n in seen and n not in parents],
		"children": [_doc_entry(seen[c["document"]], relationship=c["relationship_type"])
		             for c in children if c["document"] in seen],
		"descendants": [_doc_entry(seen[n]) for n in descendants
		                if n in seen and n not in {c["document"] for c in children}],
		"supersedes": [_doc_entry(seen[n]) for n in sorted(set(superseded)) if n in seen],
		"superseded_by": _doc_entry(seen[doc.superseded_by]) if doc.superseded_by in seen else None,
		"referenced_by": [_doc_entry(seen[n]) for n in sorted(set(referenced_by)) if n in seen],
	}


def _applicability(doc) -> dict:
	from consilium.policy import applicability

	scopes = applicability.applicable_scopes(doc.name)
	try:
		reach = len(applicability.affected_parties(doc.name))
	except Exception:
		reach = None
	return {
		"scopes": [{"scope_type": s.scope_type, "scope": s.scope_label or s.scope_value,
		            "applies_to": str(s.applies_to) if s.applies_to else None,
		            "has_recipients": bool(s.notification_group) or s.scope_type == "Role"} for s in scopes],
		"people_reached": reach,
		"owning_operating_group": doc.owning_operating_group,
		"jurisdictions": [r.jurisdiction for r in doc.get("jurisdictions") or []],
		"legal_entities": [r.legal_entity for r in doc.get("legal_entities") or []],
	}


def _regulatory(doc) -> list[dict]:
	from consilium.consilium_core.doctype.regulatory_requirement.regulatory_requirement import citing_records

	out = []
	for ref in doc.get("regulatory_references") or []:
		if not ref.regulatory_requirement:
			continue
		req = frappe.db.get_value("Regulatory Requirement", ref.regulatory_requirement,
		                          ["name", "regulatory_requirement_name", "citation", "regulator", "last_change_on"],
		                          as_dict=True) or {}
		also = []
		for rec in citing_records(ref.regulatory_requirement):
			if rec["doctype"] == DOCTYPE and rec["name"] == doc.name:
				continue
			if frappe.has_permission(rec["doctype"], "read", doc=rec["name"]):
				also.append({"doctype": rec["doctype"], "name": rec["name"], "label": rec["label"],
				             "href": common.href(rec["doctype"], rec["name"])})
		stale = bool(req.get("last_change_on") and (not ref.last_verified_on
		                                           or getdate(ref.last_verified_on) < getdate(req["last_change_on"])))
		out.append({
			"requirement": ref.regulatory_requirement, "title": req.get("regulatory_requirement_name"),
			"citation": ref.citation or req.get("citation"), "regulator": req.get("regulator"),
			"last_verified_on": str(ref.last_verified_on) if ref.last_verified_on else None,
			"requirement_changed_on": str(req["last_change_on"]) if req.get("last_change_on") else None,
			"changed_since_verified": stale, "also_cited_by": also,
			"href": common.href("Regulatory Requirement", ref.regulatory_requirement),
		})
	return out


def _forums(doc) -> list[dict]:
	out, seen = [], set()

	def add(name, role):
		if not name or name in seen:
			return
		row = frappe.db.get_value("Governance Forum", name, ["name", "forum_name", "is_active", "confidential"], as_dict=True)
		if not row or not frappe.has_permission("Governance Forum", "read", doc=name):
			return
		seen.add(name)
		out.append({"name": name, "title": row.forum_name, "role": role, "active": bool(row.is_active),
		            "href": common.href("Governance Forum", name)})

	if doc.approving_forum:
		add(doc.approving_forum, _("Approves this document"))
		for link in frappe.get_all("Forum Link", filters={"parent": doc.approving_forum, "parenttype": "Governance Forum",
		                                                  "direction": "Upstream"},
		                           fields=["linked_forum", "relationship_type"]):
			add(link.linked_forum, _("Oversees the approving forum ({0})").format(link.relationship_type or _("linked")))
		parent = frappe.db.get_value("Governance Forum", doc.approving_forum, "parent_forum")
		add(parent, _("Parent of the approving forum"))
	return out


def _monitoring(doc) -> list[dict]:
	activities = common.readable("Monitoring Activity", filters={"document": doc.name}, fields=[
		"name", "activity_title", "frequency", "responsible", "next_due_on", "is_active", "control_reference"])
	results = common.readable("Monitoring Result", filters={"document": doc.name}, fields=[
		"monitoring_activity", "outcome", "performed_on"], order_by="performed_on desc")
	last = {}
	for r in results:
		last.setdefault(r.monitoring_activity, r)
	out = []
	for a in activities:
		result = last.get(a.name)
		out.append({"name": a.name, "title": a.activity_title, "control_reference": a.control_reference,
		            "frequency": a.frequency, "active": bool(a.is_active),
		            "next_due_on": str(a.next_due_on) if a.next_due_on else None,
		            "last_outcome": result.outcome if result else None,
		            "last_adverse": bool(result and result.outcome in ADVERSE_OUTCOMES),
		            "last_performed_on": str(result.performed_on) if result and result.performed_on else None})
	return out


def _violations_and_escalations(doc) -> tuple[list[dict], list[dict]]:
	violations = common.readable("Policy Violation", filters={"document": doc.name}, fields=[
		"name", "violation_type", "severity", "identified_on", "is_open", "resulting_escalation"])
	open_violations = [{"name": v.name, "type": v.violation_type, "severity": v.severity,
	                    "identified_on": str(v.identified_on) if v.identified_on else None}
	                   for v in violations if int(v.is_open or 0)]
	names = [v.name for v in violations]
	escalated = [v.resulting_escalation for v in violations if v.resulting_escalation]
	# Sensitive matters the viewer may not read are filtered out by the query itself.
	matters = common.readable("Escalation Matter", or_filters=[
		["source_policy_violation", "in", names or common.NONE], ["name", "in", escalated or common.NONE]],
		filters={"is_open": 1}, fields=["name", "escalation_title", "severity", "sensitive"])
	escalations = [{"name": m.name, "title": m.escalation_title, "severity": m.severity,
	                "href": common.href("Escalation Matter", m.name), "_sensitive": int(m.sensitive or 0)}
	               for m in matters]
	return open_violations, escalations


# ----------------------------------------------------------- the change


def sections(text: str) -> list[tuple[int, str]]:
	return [(i, line.strip().lstrip("#").strip()) for i, line in enumerate((text or "").splitlines())
	        if HEADING.match(line) and len(line.strip()) >= 4]


def _section_of(line_no: int, heads: list[tuple[int, str]]) -> str:
	current = _("(before the first heading)")
	for i, title in heads:
		if i > line_no:
			break
		current = title
	return current


def compare(old_text: str, new_text: str) -> dict:
	"""Which sections a change touches, by a line diff. Pure; tested directly."""
	old_lines, new_lines = (old_text or "").splitlines(), (new_text or "").splitlines()
	old_heads, new_heads = sections(old_text), sections(new_text)
	touched, added, removed = {}, 0, 0
	matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
	for tag, i1, i2, j1, j2 in matcher.get_opcodes():
		if tag == "equal":
			continue
		removed += i2 - i1
		added += j2 - j1
		title = _section_of(j1, new_heads) if j2 > j1 else _section_of(i1, old_heads)
		touched[title] = touched.get(title, 0) + max(i2 - i1, j2 - j1)
	old_titles, new_titles = {t for _, t in old_heads}, {t for _, t in new_heads}
	return {
		"lines_added": added, "lines_removed": removed,
		"similarity": round(matcher.ratio(), 3),
		"sections_touched": [{"section": k, "lines": v} for k, v in sorted(touched.items(), key=lambda kv: -kv[1])],
		"sections_added": sorted(new_titles - old_titles),
		"sections_removed": sorted(old_titles - new_titles),
	}


def _change(doc, version: str | None, change_summary: str | None) -> dict:
	out = {"version": None, "summary": (change_summary or "").strip()[:2000] or None, "diff": None}
	if not version:
		return out
	from consilium.policy import handling

	version_doc, owner_doc = handling.governing_version(version)
	if owner_doc.name != doc.name:
		frappe.throw(_("Version {0} belongs to another document.").format(version))
	base_text = doc.body_text or ""
	if doc.current_version and doc.current_version != version_doc.name:
		base_text = frappe.db.get_value("Document Version", doc.current_version, "body_text") or base_text
	out.update(version=version_doc.name, version_label=version_doc.version_label)
	if not out["summary"] and version_doc.change_summary:
		out["summary"] = version_doc.change_summary
	if version_doc.body_text and base_text and version_doc.name != doc.current_version:
		out["diff"] = compare(base_text, version_doc.body_text)
	elif not version_doc.body_text:
		out["diff_note"] = _("The version has no extracted text, so sections could not be compared.")
	else:
		out["diff_note"] = _("This is already the current version; there is nothing to compare it against.")
	return out


# ------------------------------------------------------- review points


def _rating(parts: dict) -> dict:
	lineage, reg = parts["lineage"], parts["regulatory"]
	score = (2 * len(lineage["children"]) + len(lineage["descendants"]) + len(lineage["parents"])
	         + 2 * len(reg) + len(parts["applicability"]["scopes"]) + len(parts["monitoring"])
	         + 2 * len(parts["open_violations"]) + 3 * len(parts["open_escalations"]))
	band = "High" if score >= 15 else "Medium" if score >= 6 else "Low"
	# ``basis`` is the rule in plain words. The panel keeps it behind "How is this
	# worked out?": printed beside the rating, a formula read as the answer.
	return {"score": score, "band": band,
	        "basis": _("Every record this document reaches adds to its reach. A child document or addendum, a "
	                   "regulatory requirement it cites and an open violation each add two points; an open "
	                   "escalation adds three; a parent, a document further down the line, each group it "
	                   "applies to and each monitoring activity add one. Fifteen points or more is High, six "
	                   "or more is Medium, and anything less is Low.")}


def review_points(doc, parts: dict) -> list[dict]:
	"""The rule-based checklist. Each point names its source, so it can be checked."""
	points = []
	lineage = parts["lineage"]
	for p in lineage["parents"]:
		if p.get("owner_approval"):
			points.append({"kind": "approval", "text": _("The owner of the parent document {0} must approve the change.").format(p["title"]),
			               "href": p["href"]})
	if lineage["children"]:
		points.append({"kind": "lineage", "text": _("{0} child or addendum document(s) sit under this one; check each for consequential changes: {1}.")
		               .format(len(lineage["children"]), ", ".join(c["title"] for c in lineage["children"][:8]))})
	if lineage["referenced_by"]:
		points.append({"kind": "lineage", "text": _("{0} document(s) refer to this one and may quote it.").format(len(lineage["referenced_by"]))})
	for reg in parts["regulatory"]:
		if reg["changed_since_verified"]:
			points.append({"kind": "regulatory", "text": _("{0} changed on {1}, after this document last verified it; re-verify the obligation.")
			               .format(reg["title"] or reg["requirement"], reg["requirement_changed_on"]), "href": reg["href"]})
	if parts["regulatory"]:
		points.append({"kind": "regulatory", "text": _("Confirm the change still meets the {0} regulatory requirement(s) cited.").format(len(parts["regulatory"]))})
	if not doc.approving_forum:
		points.append({"kind": "forum", "text": _("No approving forum is recorded, so it is not clear who must approve this change.")})
	for f in parts["forums"][:1]:
		points.append({"kind": "forum", "text": _("{0} must approve the change.").format(f["title"]), "href": f["href"]})
	scopes = parts["applicability"]
	silent = [s for s in scopes["scopes"] if not s["has_recipients"]]
	if scopes["scopes"]:
		points.append({"kind": "applicability", "text": _("The change applies across {0} scope(s), reaching {1} people through notification.")
		               .format(len(scopes["scopes"]), scopes["people_reached"] if scopes["people_reached"] is not None else "?")})
	if silent:
		points.append({"kind": "applicability", "text": _("{0} applicability scope(s) name no notification group, so nobody there would be told of the change.").format(len(silent))})
	controls = [m for m in parts["monitoring"] if m["control_reference"]]
	if controls:
		points.append({"kind": "monitoring", "text": _("Check the control references tested by monitoring still match: {0}.")
		               .format(", ".join(sorted({m["control_reference"] for m in controls})))})
	for m in parts["monitoring"]:
		if m["last_adverse"]:
			points.append({"kind": "monitoring", "text": _("Monitoring activity {0} last found the control {1}; the change may be the remediation.")
			               .format(m["title"], (m["last_outcome"] or "").lower())})
	if parts["open_violations"]:
		points.append({"kind": "violations", "text": _("{0} violation(s) of this document are still open; decide whether the change affects their remediation.").format(len(parts["open_violations"]))})
	if parts["open_escalations"]:
		points.append({"kind": "escalations", "text": _("{0} open escalation(s) arise from this document's violations.").format(len(parts["open_escalations"]))})
	change = parts["change"]
	if change.get("diff"):
		d = change["diff"]
		if d["sections_removed"]:
			points.append({"kind": "change", "text": _("Sections removed: {0}. Check nothing else refers to them.").format(", ".join(d["sections_removed"][:8]))})
		if d["sections_touched"]:
			points.append({"kind": "change", "text": _("Sections changed: {0}.").format(", ".join(s["section"] for s in d["sections_touched"][:8]))})
	if doc.next_review_on and getdate(doc.next_review_on) < common.today():
		points.append({"kind": "review", "text": _("The document's review is overdue (due {0}); the change could conclude it.").format(doc.next_review_on)})
	return points


# ---------------------------------------------------------------- the API


def assessment(doc, version: str | None = None, change_summary: str | None = None) -> dict:
	open_violations, open_escalations = _violations_and_escalations(doc)
	parts = {
		"lineage": _lineage(doc),
		"applicability": _applicability(doc),
		"regulatory": _regulatory(doc),
		"forums": _forums(doc),
		"monitoring": _monitoring(doc),
		"open_violations": open_violations,
		"open_escalations": open_escalations,
		"change": _change(doc, version, change_summary),
	}
	parts["rating"] = _rating(parts)
	parts["review_points"] = review_points(doc, parts)
	parts["document"] = {"name": doc.name, "title": doc.document_name, "classification": guard.classification_of(DOCTYPE, doc)}
	parts["versions"] = [{"name": v.name, "label": v.version_label or f"v{v.version_number}", "is_current": int(v.is_current or 0)}
	                     for v in frappe.get_all("Document Version", filters={"subject_doctype": DOCTYPE, "subject_name": doc.name},
	                                             fields=["name", "version_label", "version_number", "is_current"],
	                                             order_by="version_number desc", limit_page_length=20)]
	parts["ai"] = guard.availability(CAPABILITY)
	parts["note"] = _("Only records you may read are listed.")
	return parts


@frappe.whitelist(methods=["GET"])
def assess(document: str, version: str | None = None, change_summary: str | None = None) -> dict:
	"""The rule-based impact of a proposed change. Needs no network, writes nothing."""
	return assessment(_load(document), version, change_summary)


SYSTEM = """You assess the impact of a proposed change to a governing document (a policy, standard or procedure) in an enterprise governance, risk and policy platform.
You are given facts the platform worked out from its own records: lineage, applicability, regulatory references, approving forums, monitoring, open violations and escalations, and a rule-based checklist.
Write, in plain text with no headings and no tables:
1. A narrative of at most 120 words on what the change is likely to affect and why.
2. Then a line reading exactly "Review points:" followed by up to 6 short bullet points ("- ") that add to the checklist rather than repeat it.
Base everything only on the facts given. If the facts are thin, say so rather than speculate."""


def build_payload(doc, parts: dict) -> guard.Payload:
	p = guard.Payload()
	subject_class = guard.classification_of(DOCTYPE, doc)
	p.line("Document under change:")
	p.record(DOCTYPE, doc.name, subject_class, title=doc.document_name, summary=doc.document_abstract,
	         tags={"type": doc.document_type, "risk category": doc.primary_risk_category, "in force": "yes" if doc.is_active else "no"},
	         href=common.href(DOCTYPE, doc.name))
	change = parts["change"]
	if p.summary and change.get("summary"):
		p.line("Proposed change, as described: " + guard._clip(change["summary"], 800))
	elif change.get("summary"):
		p.line("A change description exists but is not shared under the current data-sharing mode.")
	if change.get("diff"):
		d = change["diff"]
		p.line(f"Version comparison: {d['lines_added']} lines added, {d['lines_removed']} removed, similarity {d['similarity']}.")
		if p.summary:
			p.line("Sections changed: " + "; ".join(guard._clip(s["section"], 80) for s in d["sections_touched"][:10]))
			if d["sections_removed"]:
				p.line("Sections removed: " + "; ".join(guard._clip(s, 80) for s in d["sections_removed"][:10]))
		else:
			p.line(f"{len(d['sections_touched'])} section(s) changed, {len(d['sections_removed'])} removed.")
	lin = parts["lineage"]
	names = _docs([x["name"] for key in ("parents", "ancestors", "children", "descendants", "supersedes", "referenced_by")
	               for x in lin[key]])
	for key, label in (("parents", "Parent documents"), ("children", "Child and addendum documents"),
	                   ("descendants", "Further descendants"), ("supersedes", "Documents it supersedes"),
	                   ("referenced_by", "Documents referring to it")):
		if lin[key]:
			p.line(label + ":")
			for x in lin[key]:
				row = names.get(x["name"])
				if row:
					p.record(DOCTYPE, row.name, guard.classification_of(DOCTYPE, row), title=row.document_name,
					         tags={"relationship": x.get("relationship"), "owner approval required": "yes" if x.get("owner_approval") else None},
					         href=x["href"])
	app = parts["applicability"]
	p.line(f"Applicability: {len(app['scopes'])} scope(s) in force ({', '.join(sorted({s['scope_type'] or '' for s in app['scopes']})) or 'none'}); "
	       f"people reached by notification: {app['people_reached']}.")
	if parts["regulatory"]:
		p.line("Regulatory requirements cited (public references):")
		for r in parts["regulatory"]:
			p.line(f"- {r['requirement']}: {r['title'] or ''} ({r['citation'] or 'no citation'}); regulator {r['regulator'] or 'not recorded'}; "
			       f"changed since last verified: {'yes' if r['changed_since_verified'] else 'no'}; also cited by {len(r['also_cited_by'])} other record(s).")
	for f in parts["forums"]:
		row = frappe.db.get_value("Governance Forum", f["name"], ["confidential"], as_dict=True) or {}
		p.record("Governance Forum", f["name"], guard.classification_of("Governance Forum", row), title=f["title"],
		         tags={"role": f["role"]}, href=f["href"], prefix="- forum ")
	if parts["monitoring"]:
		p.line(f"Monitoring: {len(parts['monitoring'])} activit(ies); last results: "
		       + ", ".join(m["last_outcome"] or "none yet" for m in parts["monitoring"]) + ".")
	p.line(f"Open violations: {len(parts['open_violations'])} (severities: {', '.join(v['severity'] or '?' for v in parts['open_violations']) or 'none'}).")
	# A sensitive matter is not even counted in what leaves.
	sensitive_free = [e for e in parts["open_escalations"] if not e.get("_sensitive")]
	p.line(f"Open escalations arising from its violations: {len(sensitive_free)}.")
	p.line(f"Rule-based reach rating: {parts['rating']['band']} (score {parts['rating']['score']}).")
	p.line("Rule-based checklist already shown to the reader:")
	for point in parts["review_points"]:
		text = point["text"]
		if not p.summary:
			text = point["kind"] + " point"
		p.line("- " + guard._clip(text, 240))
	return p


@frappe.whitelist(methods=["POST"])
def ai_commentary(document: str, version: str | None = None, change_summary: str | None = None) -> dict:
	"""Narrative and extra review points from the AI endpoint, if it is on.

	Returns the rule-based assessment too, so the page never loses it.
	"""
	doc = _load(document)
	parts = assessment(doc, version, change_summary)
	payload = build_payload(doc, parts)
	result = guard.run(
		CAPABILITY, system=SYSTEM, payload=payload, subject={"doctype": DOCTYPE, "name": doc.name},
		subject_classification=guard.classification_of(DOCTYPE, doc),
		accept=lambda text: guard.narrative_blocks(text, payload.links),
	)
	return {"assessment": parts, "ai": _public(result)}


def _public(result: dict) -> dict:
	return {"used": result["used"], "status": result["status"], "notice": result["notice"],
	        "service_request": result["service_request"], "blocks": result["value"],
	        "withheld": result["withheld"], "mode": result.get("mode")}
