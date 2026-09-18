"""Regulatory updates (O-7): record a change, find what it touches, suggest, accept.

    GET  .../ai.regulatory.recent                    requirements changed lately
    GET  .../ai.regulatory.overview   requirement     one requirement: change, citing records,
                                                      rule-based candidates, AI suggestions
    POST .../ai.regulatory.record_change  requirement, values
    POST .../ai.regulatory.ai_suggest     requirement
    POST .../ai.regulatory.decide         service_request, document, decision, accepted_value?
    POST .../ai.regulatory.ensure_import_profile

**Recording a change.** A regulatory change is a change to a ``Regulatory
Requirement``: by hand (``record_change`` here, or the desk), or by file
through Core's import pipeline with the profile ``ensure_import_profile``
creates. Every route saves the requirement, and the requirement's own
controller then tells the owner of every document and forum that cites it
(``notify_citing_owners``). That fan-out is not repeated here: this module
only calls it by saving.

**Matching, with no model.** The documents and forums that *cite* the
requirement are the directly affected ones (``citing_records``, the
controller's own query). Beyond them, a document that does not cite it but
shares its jurisdiction or uses its distinctive words is a *candidate*, and
within a citing document the sections that use those words are the likely
places to look. Both are word-overlap heuristics, and the page says so.

**Suggestions, with a model.** With AI on, ``ai_suggest`` sends the change
and the candidates (as tokens, with titles only in summary mode) and asks
for a plain-language summary and, per document, the sections likely
affected. The model may only name documents it was sent. Its answer is
stored where every AI answer is stored — the ``AI Service Request`` — and
each suggestion is shown with Accept and Reject.

**Acceptance.** Nothing the model wrote reaches a record until a person with
write access to that document accepts it (``decide``). Accepting writes the
suggestion's note, as the person left it, into the document's regulatory
references — a new citation row if the document did not cite the
requirement, or appended to the obligation summary of the row that does —
and records an ``AI Suggestion Acceptance`` saying who, when, what was
suggested, what was written, whether it was edited, and against which
version. Rejecting records the same row with no accepted value, so a
suggestion is decided once and the decision is on file either way.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import frappe
from frappe import _
from frappe.utils import add_days, cstr, nowdate

from consilium.consilium_core.ai import client, common, guard

CAPABILITY = "regulatory"
REQUIREMENT = "Regulatory Requirement"
DOCUMENT = "Governing Document"
ACCEPTANCE = "AI Suggestion Acceptance"
PROFILE_TITLE = "Regulatory changes — file import"
IMPORT_SYSTEM = "REGULATORY-FEED"

STOPWORDS = set("""
a about above after again all also an and any are as at be been before being below between both but by can could
did do does doing down during each few for from further had has have having here how if in into is it its itself
just may more most must no nor not now of off on once only or other our out over own same shall should so some
such than that the their them then there these they this those through to too under until up upon very was were
what when where which while who whom why will with within without would you your per any all rule rules
requirement requirements regulation regulations section sections article articles paragraph new amended amendment
risk risks policy policies standard standards procedure procedures framework governance management compliance
document documents control controls guideline guidelines guidance include includes including across
""".split())


def _requirement(requirement: str):
	common.require_signed_in()
	if not requirement or not frappe.db.exists(REQUIREMENT, requirement):
		raise frappe.DoesNotExistError(_("No regulatory requirement {0}.").format(requirement))
	doc = frappe.get_doc(REQUIREMENT, requirement)
	if not frappe.has_permission(REQUIREMENT, "read", doc=doc):
		raise frappe.PermissionError(_("You may not read {0}.").format(requirement))
	return doc


def _controller():
	from consilium.consilium_core.doctype.regulatory_requirement import regulatory_requirement

	return regulatory_requirement


# ------------------------------------------------------------ the change


def last_change(requirement: str) -> dict | None:
	"""The most recent substantive change, from the framework's change log."""
	substantive = set(_controller().SUBSTANTIVE_FIELDS)
	for version in frappe.get_all("Version", filters={"ref_doctype": REQUIREMENT, "docname": requirement},
	                              fields=["name", "data", "owner", "creation"], order_by="creation desc", limit_page_length=20):
		data = common.loads(version.data, {}) or {}
		changed = [{"field": f, "old": cstr(o), "new": cstr(n)} for f, o, n in data.get("changed") or [] if f in substantive]
		if changed:
			meta = frappe.get_meta(REQUIREMENT)
			for c in changed:
				c["label"] = _(meta.get_label(c["field"]))
			return {"on": str(version.creation), "by": version.owner, "changes": changed}
	return None


def words(*texts: str) -> list[str]:
	"""The distinctive words of a text: lower-case, four letters or more, no stopwords."""
	out = []
	for text in texts:
		for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", text or ""):
			w = w.lower().strip("-")
			if w not in STOPWORDS and len(w) >= 4:
				out.append(w)
	return out


def keywords(req, change: dict | None = None) -> list[str]:
	texts = [req.regulatory_requirement_name, req.summary, req.description]
	if change:
		texts += [c["new"] for c in change["changes"]]
	counts = Counter(words(*texts))
	return [w for w, _n in counts.most_common(25)]


def section_hits(body: str, terms: list[str], limit: int = 3) -> list[dict]:
	"""Headings of a body under which the terms occur, with how often. Pure."""
	from consilium.consilium_core.ai.impact import HEADING

	if not body or not terms:
		return []
	term_set = set(terms)
	current, hits = _("(opening text)"), {}
	for line in body.splitlines():
		if HEADING.match(line) and len(line.strip()) >= 4:
			current = line.strip().lstrip("#").strip()
			continue
		found = [w for w in words(line) if w in term_set]
		if found:
			entry = hits.setdefault(current, {"section": current, "hits": 0, "terms": set()})
			entry["hits"] += len(found)
			entry["terms"] |= set(found)
	ranked = sorted(hits.values(), key=lambda e: -e["hits"])[:limit]
	return [{"section": e["section"], "hits": e["hits"], "terms": sorted(e["terms"])[:8]} for e in ranked]


def matching(req, change: dict | None = None) -> dict:
	"""Citing records and rule-based candidates, over what the viewer may read."""
	terms = keywords(req, change)
	citing = []
	cited_docs = set()
	for rec in _controller().citing_records(req.name):
		if not frappe.has_permission(rec["doctype"], "read", doc=rec["name"]):
			continue
		entry = {"doctype": rec["doctype"], "name": rec["name"], "label": rec["label"],
		         "href": common.href(rec["doctype"], rec["name"]), "sections": []}
		if rec["doctype"] == DOCUMENT:
			cited_docs.add(rec["name"])
		citing.append(entry)

	docs = [d for d in common.readable(DOCUMENT, fields=["name", "document_name", "document_abstract", "body_text", "retired_on"])
	        if not d.retired_on]
	vocab = {d.name: Counter(words(d.document_name, d.document_abstract, d.body_text)) for d in docs}
	# A word many documents use tells nothing about which
	# document a change reaches; it is dropped once there are enough documents
	# to judge by.
	if len(docs) >= 4:
		df = Counter(w for counts in vocab.values() for w in counts)
		terms = [t for t in terms if df.get(t, 0) / len(docs) <= 0.4]
	term_set = set(terms)
	jurisdiction_docs = set(frappe.get_all("Document Jurisdiction", filters={"parenttype": DOCUMENT, "jurisdiction": req.jurisdiction},
	                                       pluck="parent")) if req.jurisdiction else set()
	for entry in citing:
		if entry["doctype"] == DOCUMENT:
			entry["sections"] = section_hits(frappe.db.get_value(DOCUMENT, entry["name"], "body_text") or "", terms)
	candidates = []
	for d in docs:
		if d.name in cited_docs:
			continue
		found = Counter({w: n for w, n in vocab[d.name].items() if w in term_set})
		score = len(found) + (2 if d.name in jurisdiction_docs else 0)
		if len(found) >= 3 or (d.name in jurisdiction_docs and len(found) >= 2):
			candidates.append({"doctype": DOCUMENT, "name": d.name, "label": f"{d.document_name} ({d.name})",
			                   "href": common.href(DOCUMENT, d.name), "score": score,
			                   "same_jurisdiction": d.name in jurisdiction_docs,
			                   "terms": [w for w, _n in found.most_common(8)],
			                   "sections": section_hits(d.body_text or "", terms)})
	candidates.sort(key=lambda c: -c["score"])
	return {"terms": terms, "citing": citing, "candidates": candidates[:10]}


# ---------------------------------------------------------- suggestions


def _parse_suggestions(text: str, links: dict[str, dict]) -> dict:
	"""The model's JSON answer, reduced to documents the platform sent. Pure-ish.

	Raises ``AIServiceError`` when there is no JSON object in the answer: an
	answer the platform cannot map is not shown.
	"""
	start, end = (text or "").find("{"), (text or "").rfind("}")
	if start < 0 or end <= start:
		raise client.AIServiceError("the answer was not the JSON object asked for")
	try:
		data = json.loads(text[start:end + 1])
	except ValueError as e:
		raise client.AIServiceError("the answer's JSON could not be read") from e
	if not isinstance(data, dict):
		raise client.AIServiceError("the answer's JSON had an unexpected shape")
	out, seen = [], set()
	for item in data.get("suggestions") or []:
		if not isinstance(item, dict):
			continue
		tok = (guard.tokens_in(str(item.get("document") or "")) or [None])[0]
		info = links.get(tok) if tok else None
		if not info or info["doctype"] != DOCUMENT or tok in seen:
			continue  # a record the platform did not send, or one already suggested
		seen.add(tok)
		sections = [guard._clip(s, 120) for s in (item.get("sections") or []) if isinstance(s, str) and s.strip()][:5]
		out.append({"token": tok, "document": info["name"], "title": info["label"], "href": info.get("href"),
		            "sections": sections, "reason": guard._clip(str(item.get("reason") or ""), 500)})
	return {"summary": guard._clip(str(data.get("summary") or ""), 1500), "suggestions": out[:10]}


def suggested_note(req, suggestion: dict, on: str | None = None) -> str:
	"""The text that accepting a suggestion would write. Machine-generated in
	its sections and reason; the framing is fixed."""
	parts = [_("Affected by the change to {0} recorded {1}.").format(req.name, on or nowdate())]
	if suggestion.get("sections"):
		parts.append(_("Sections: {0}.").format("; ".join(suggestion["sections"])))
	if suggestion.get("reason"):
		parts.append(suggestion["reason"])
	return " ".join(parts)


def _readable_token_map() -> dict[str, dict]:
	names = common.readable(DOCUMENT, pluck="name")
	return {guard.token(DOCUMENT, n): {"doctype": DOCUMENT, "name": n, "label": n, "href": common.href(DOCUMENT, n)}
	        for n in names}


def stored_suggestions(req, limit: int = 5) -> list[dict]:
	"""Earlier AI answers for this requirement, re-read from the audit, with
	each suggestion's decision. Only documents the viewer may read are shown."""
	rows = frappe.get_all(client.SERVICE_REQUEST, filters={
		"capability": guard.capability_name(CAPABILITY), "subject_doctype": REQUIREMENT,
		"subject_name": req.name, "status": "Succeeded"},
		fields=["name", "requested_on", "requested_by", "response_payload"], order_by="requested_on desc",
		limit_page_length=limit)
	if not rows:
		return []
	tokens = _readable_token_map()
	titles = {r.name: r.document_name for r in common.readable(DOCUMENT, fields=["name", "document_name"])}
	out = []
	for row in rows:
		try:
			parsed = _parse_suggestions(row.response_payload, tokens)
		except client.AIServiceError:
			continue
		decisions = {d.subject_name: d for d in frappe.get_all(ACCEPTANCE, filters={"ai_service_request": row.name},
		                                                       fields=["subject_name", "accepted_value", "accepted_by", "accepted_on",
		                                                               "edited_before_accept", "suggested_value"])}
		for s in parsed["suggestions"]:
			s["title"] = f"{titles.get(s['document'], s['document'])} ({s['document']})"
			s["note"] = suggested_note(req, s, str(row.requested_on)[:10])
			d = decisions.get(s["document"])
			s["decision"] = None if not d else {
				"accepted": bool(d.accepted_value), "by": d.accepted_by, "on": str(d.accepted_on),
				"edited": bool(d.edited_before_accept), "value": d.accepted_value}
			s["may_decide"] = not d and bool(frappe.has_permission(DOCUMENT, "write", doc=s["document"]))
		out.append({"service_request": row.name, "requested_on": str(row.requested_on), "requested_by": row.requested_by,
		            "summary": parsed["summary"], "suggestions": parsed["suggestions"]})
	return out


# ------------------------------------------------------------------ views


def overview_of(req) -> dict:
	change = last_change(req.name)
	match = matching(req, change)
	return {
		"requirement": {f: cstr(req.get(f)) or None for f in (
			"name", "regulatory_requirement_code", "regulatory_requirement_name", "citation", "regulator",
			"jurisdiction", "effective_date", "last_change_on", "summary", "description", "is_active")},
		"change": change,
		"terms": match["terms"],
		"citing": match["citing"],
		"candidates": match["candidates"],
		"ai_runs": stored_suggestions(req),
		"may_edit": bool(frappe.has_permission(REQUIREMENT, "write", doc=req)),
		"editable_fields": list(_controller().SUBSTANTIVE_FIELDS),
		"ai": guard.availability(CAPABILITY),
		"note": _("Only records you may read are listed. Candidates and sections are found by shared words and "
		          "jurisdiction, a heuristic: check them."),
	}


@frappe.whitelist(methods=["GET"])
def overview(requirement: str) -> dict:
	return overview_of(_requirement(requirement))


@frappe.whitelist(methods=["GET"])
def recent(days: int | str = 365) -> dict:
	"""Requirements whose substance changed in the window, newest first, with
	how many readable records cite each — plus every other active requirement,
	so the page doubles as the place a change is recorded."""
	common.require_signed_in()
	since = add_days(nowdate(), -common.as_int(days, 365))
	rows = common.readable(REQUIREMENT, fields=["name", "regulatory_requirement_name", "citation", "regulator",
	                                            "jurisdiction", "last_change_on", "is_active"], order_by="last_change_on desc")
	doc_cites = Counter(frappe.get_all("Document Regulatory Reference", filters={"parenttype": DOCUMENT}, pluck="regulatory_requirement"))
	forum_cites = Counter(frappe.get_all("Forum Regulatory Requirement", filters={"parenttype": "Governance Forum"}, pluck="regulatory_requirement"))
	out = []
	for r in rows:
		out.append({"name": r.name, "title": r.regulatory_requirement_name, "citation": r.citation, "regulator": r.regulator,
		            "jurisdiction": r.jurisdiction, "last_change_on": str(r.last_change_on) if r.last_change_on else None,
		            "recent": bool(r.last_change_on and str(r.last_change_on) >= str(since)),
		            "active": bool(r.is_active), "documents": doc_cites.get(r.name, 0), "forums": forum_cites.get(r.name, 0),
		            "href": common.href(REQUIREMENT, r.name)})
	out.sort(key=lambda r: r["last_change_on"] or "", reverse=True)
	out.sort(key=lambda r: not r["recent"])  # stable: recent first, each part newest first
	return {"requirements": out, "may_create": bool(frappe.has_permission(REQUIREMENT, "create")),
	        "import_profile": frappe.db.get_value("Import Profile", {"profile_title": PROFILE_TITLE, "is_active": 1}, "name"),
	        "ai": guard.availability(CAPABILITY)}


@frappe.whitelist(methods=["POST"])
def record_change(requirement: str, values=None) -> dict:
	"""Save a change to a requirement's substance, as its editor.

	The requirement's controller dates the change and notifies the owners of
	everything that cites it; this only saves, with the caller's permissions.
	"""
	req = _requirement(requirement)
	req.check_permission("write")
	values = common.loads(values, {}) if not isinstance(values, dict) else values
	allowed = set(_controller().SUBSTANTIVE_FIELDS)
	unknown = sorted(set(values) - allowed)
	if unknown:
		frappe.throw(_("These fields cannot be changed here: {0}.").format(", ".join(unknown)))
	before = {f: cstr(req.get(f)) for f in values}
	req.update(values)
	if all(cstr(req.get(f)) == before[f] for f in values):
		frappe.throw(_("Nothing changed."), title=_("No Change"))
	req.save()
	out = overview_of(req)
	# Told by the requirement's own controller on that save, not by this module.
	out["citing_notified"] = len(_controller().citing_records(req.name))
	return out


SYSTEM = """You help a compliance team respond to a change in a regulatory requirement, inside an enterprise governance, risk and policy platform.
You are given the requirement, what changed, and the governing documents the platform considers affected: those that cite the requirement and rule-based candidates that do not.
Answer with a single JSON object and nothing else, in this shape:
{"summary": "<plain-language summary of the change and what it demands, at most 90 words>",
 "suggestions": [{"document": "<token, e.g. D-1a2b3c4d>", "sections": ["<section heading or area likely affected>"], "reason": "<why, at most 40 words>"}]}
Suggest only documents from the list given, at most one entry per document, most affected first, at most 8. Leave out documents you judge unaffected. Section names must come from the headings given when headings are given."""


def build_payload(req, overview_data: dict) -> guard.Payload:
	p = guard.Payload()
	r = overview_data["requirement"]
	p.line(f"Requirement {r['regulatory_requirement_code'] or r['name']}: {r['regulatory_requirement_name']}; citation {r['citation'] or 'none'}; "
	       f"regulator {r['regulator'] or 'not recorded'}; jurisdiction {r['jurisdiction'] or 'not recorded'}; effective {r['effective_date'] or 'not recorded'}.")
	if r["summary"]:
		p.line("Requirement summary (public reference text): " + guard._clip(r["summary"], 1200))
	change = overview_data["change"]
	if change:
		p.line(f"What changed on {change['on'][:10]}:")
		for c in change["changes"]:
			p.line(f"- {c['label']}: {guard._clip(c['old'], 400) or '(empty)'} -> {guard._clip(c['new'], 400) or '(empty)'}")
	else:
		p.line("No earlier value is on record; treat the requirement as newly recorded.")
	p.line("Distinctive words of the requirement: " + ", ".join(overview_data["terms"][:20]))
	docs = {d.name: d for d in frappe.get_all(DOCUMENT, filters={"name": ["in", [c["name"] for c in overview_data["citing"] + overview_data["candidates"]
	                                                                           if c["doctype"] == DOCUMENT] or common.NONE]},
	                                         fields=["name", "document_name", "document_abstract", "document_type", "primary_risk_category",
	                                                 "handling_classification", "confidential", "body_text"])}
	from consilium.consilium_core.ai.impact import sections

	def add(entry, cites: bool):
		d = docs.get(entry["name"])
		if not d:
			return
		heads = [h for _i, h in sections(d.body_text or "")][:25]
		tags = {"cites the requirement": "yes" if cites else "no", "type": d.document_type, "risk category": d.primary_risk_category,
		        "rule-based matching words": entry.get("terms") or [], "same jurisdiction": "yes" if entry.get("same_jurisdiction") else None}
		if p.summary and heads:
			tags["headings"] = [guard._clip(h, 80) for h in heads]
		elif heads:
			tags["number of headings"] = len(heads)
		p.record(DOCUMENT, d.name, guard.classification_of(DOCUMENT, d), title=d.document_name, summary=d.document_abstract,
		         tags=tags, href=entry["href"])

	p.line("Documents citing the requirement:")
	for c in overview_data["citing"]:
		if c["doctype"] == DOCUMENT:
			add(c, True)
	p.line(f"Forums citing the requirement: {sum(1 for c in overview_data['citing'] if c['doctype'] != DOCUMENT)} (not listed).")
	p.line("Rule-based candidate documents that do not cite it:")
	for c in overview_data["candidates"]:
		add(c, False)
	return p


@frappe.whitelist(methods=["POST"])
def ai_suggest(requirement: str) -> dict:
	"""Ask for a summary and per-document suggestions. Stores nothing but the
	audit row; every suggestion waits there for a person's decision."""
	req = _requirement(requirement)
	data = overview_of(req)
	payload = build_payload(req, data)
	result = guard.run(CAPABILITY, system=SYSTEM, payload=payload, subject={"doctype": REQUIREMENT, "name": req.name},
	                   subject_classification=guard.PUBLIC,
	                   accept=lambda text: _parse_suggestions(text, payload.links))
	data = overview_of(req)
	data["ai_result"] = {"used": result["used"], "status": result["status"], "notice": result["notice"],
	                     "service_request": result["service_request"], "withheld": result["withheld"], "mode": result.get("mode")}
	return data


@frappe.whitelist(methods=["POST"])
def decide(service_request: str, document: str, decision: str, accepted_value: str | None = None) -> dict:
	"""Accept or reject one suggestion. Accepting writes into the document."""
	common.require_signed_in()
	if decision not in ("accept", "reject"):
		frappe.throw(_("Decide with accept or reject."))
	if not frappe.db.exists(client.SERVICE_REQUEST, service_request):
		raise frappe.DoesNotExistError(_("No such AI request."))
	row = frappe.get_doc(client.SERVICE_REQUEST, service_request)
	if row.capability != guard.capability_name(CAPABILITY) or row.subject_doctype != REQUIREMENT or row.status != "Succeeded":
		frappe.throw(_("That request did not produce regulatory suggestions."))
	req = _requirement(row.subject_name)
	doc = frappe.get_doc(DOCUMENT, document) if frappe.db.exists(DOCUMENT, document) else None
	if not doc or not frappe.has_permission(DOCUMENT, "write", doc=doc):
		raise frappe.PermissionError(_("You may not change {0}, so you may not decide its suggestion.").format(document))

	parsed = _parse_suggestions(row.response_payload, {guard.token(DOCUMENT, document): {
		"doctype": DOCUMENT, "name": document, "label": document, "href": None}})
	suggestion = next((s for s in parsed["suggestions"] if s["document"] == document), None)
	if not suggestion:
		frappe.throw(_("The AI request made no suggestion about {0}.").format(document))
	if frappe.db.exists(ACCEPTANCE, {"ai_service_request": service_request, "subject_doctype": DOCUMENT, "subject_name": document}):
		frappe.throw(_("This suggestion has already been decided."), title=_("Already Decided"))

	suggested = suggested_note(req, suggestion, str(row.requested_on)[:10])
	accepted = None
	target = "regulatory_references"
	if decision == "accept":
		accepted = (accepted_value if accepted_value is not None else suggested).strip()
		if not accepted:
			frappe.throw(_("An accepted note cannot be empty; reject the suggestion instead."))
		existing = next((r for r in doc.get("regulatory_references") or [] if r.regulatory_requirement == req.name), None)
		if existing:
			target = "regulatory_references.obligation_summary"
			existing.obligation_summary = (existing.obligation_summary + "\n\n" if existing.obligation_summary else "") + accepted
		else:
			doc.append("regulatory_references", {"regulatory_requirement": req.name, "citation": req.citation,
			                                     "jurisdiction": req.jurisdiction, "obligation_summary": accepted})
		doc.save()

	frappe.get_doc({
		"doctype": ACCEPTANCE, "ai_service_request": service_request,
		"subject_doctype": DOCUMENT, "subject_name": document, "target_fieldname": target,
		"suggested_value": suggested,
		# A rejection is recorded with no accepted value: decided, and nothing written.
		"accepted_value": accepted,
		"accepted_by": frappe.session.user, "accepted_on": frappe.utils.now_datetime(),
		"edited_before_accept": 1 if accepted is not None and accepted != suggested else 0,
		"applied_to_version": doc.current_version if accepted is not None else None,
	}).insert(ignore_permissions=True)
	return overview_of(req)


@frappe.whitelist(methods=["POST"])
def ensure_import_profile() -> dict:
	"""The Core import profile for regulatory changes, created once.

	Keyed on the requirement code and set to update: a row naming an existing
	requirement changes it (and the controller notifies its citers); a row
	naming a new one creates it.
	"""
	if not frappe.has_permission("Import Profile", "create"):
		raise frappe.PermissionError(_("Only an administrator may set up import profiles."))
	return {"name": ensure_profile()}


def ensure_profile() -> str:
	existing = frappe.db.get_value("Import Profile", {"profile_title": PROFILE_TITLE}, "name")
	if existing:
		return existing
	if not frappe.db.exists("External System", IMPORT_SYSTEM):
		frappe.get_doc({"doctype": "External System", "system_code": IMPORT_SYSTEM, "title": "Regulatory change feed (file)",
		                "description": "Delimited files of regulatory changes, imported by hand.", "is_active": 1}).insert(ignore_permissions=True)
	mappings = [
		("Code", "regulatory_requirement_code", "Trim", 1),
		("Name", "regulatory_requirement_name", "Trim", 1),
		("Citation", "citation", "Trim", 0),
		("Regulator", "regulator", "Trim", 0),
		("Effective Date", "effective_date", "Date Parse", 0),
		("Summary", "summary", "None", 0),
		("Description", "description", "None", 0),
	]
	return frappe.get_doc({
		"doctype": "Import Profile", "profile_title": PROFILE_TITLE, "source_system": IMPORT_SYSTEM,
		"target_doctype": REQUIREMENT, "key_strategy": "Natural Key", "natural_key_fieldname": "regulatory_requirement_code",
		"on_missing_required": "Reject Row", "on_unknown_taxonomy": "Reject Row", "on_duplicate_key": "Update", "is_active": 1,
		"mappings": [{"source_column": c, "target_fieldname": f, "transform": t, "is_required": r} for c, f, t, r in mappings],
	}).insert(ignore_permissions=True).name
