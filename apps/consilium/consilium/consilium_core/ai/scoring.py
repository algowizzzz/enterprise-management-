"""Automated governance risk assessment (O-7): a rules-based score per forum and per policy.

    GET  /api/method/consilium.consilium_core.ai.scoring.assess
    POST /api/method/consilium.consilium_core.ai.scoring.ai_rationale

Each score is a sum of points from named factors, each factor with a weight
and, for counted factors, a cap. There are three kinds of factor:

* **flag** — present or not (a review is overdue): ``weight`` points;
* **count** — how many (open violations): ``weight`` per item, at most ``cap``;
* **share** — a proportion missing (attestations not completed on time):
  ``weight × share``.

The weights are configuration, not code: ``Assistant Settings`` carries an
optional JSON block that overrides any factor's ``weight`` or ``cap`` and the
band thresholds. The page shows, for every score, each factor's evidence,
weight, cap and points, so any number can be recomputed by hand.

Compliance is read from the forum's semantic flag (``requires_review``), not
from its status label, so a renamed state does not change a score. Open items
are read from ``is_open``. A factor whose records the viewer may not read is
marked unavailable and scores nothing for that viewer, rather than being
counted behind their back.

With AI on, the highest-scoring records' factor breakdowns — numbers and
tokens, titles only in summary mode — are sent for a short rationale.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_months, getdate

from consilium.consilium_core.ai import common, guard

CAPABILITY = "scores"
FORUM = "Governance Forum"
DOCUMENT = "Governing Document"

DEFAULT_WEIGHTS = {
	"forum": {
		"compliance_not_confirmed": {"kind": "flag", "weight": 20, "label": "Compliance not confirmed (the forum's compliance review is outstanding)"},
		"review_overdue": {"kind": "flag", "weight": 15, "label": "Forum review date has passed"},
		"attestation_incomplete": {"kind": "share", "weight": 15, "label": "Share of due attestations not completed"},
		"open_escalations": {"kind": "count", "weight": 4, "cap": 16, "label": "Open escalations routed to the forum"},
		"breached_slas": {"kind": "count", "weight": 5, "cap": 15, "label": "Open routed escalations past their time limit"},
		"missing_metadata": {"kind": "count", "weight": 3, "cap": 15, "label": "Missing charter, quorum rule, officers or cadence"},
		"delegation_gaps": {"kind": "count", "weight": 5, "cap": 15, "label": "Seats or officers held by disabled users, or delegates with no authority on record"},
	},
	"policy": {
		"review_overdue": {"kind": "flag", "weight": 20, "label": "Document review date has passed"},
		"no_approving_forum": {"kind": "flag", "weight": 10, "label": "No approving forum recorded"},
		"attestation_incomplete": {"kind": "share", "weight": 15, "label": "Share of due attestations not completed"},
		"open_violations": {"kind": "count", "weight": 8, "cap": 24, "label": "Open violations"},
		"open_escalations": {"kind": "count", "weight": 5, "cap": 15, "label": "Open escalations arising from its violations"},
		"breached_slas": {"kind": "count", "weight": 5, "cap": 15, "label": "Time limits breached on its reviews and violations"},
		"adverse_monitoring": {"kind": "count", "weight": 5, "cap": 15, "label": "Adverse monitoring results in the last 12 months"},
		"missing_metadata": {"kind": "count", "weight": 3, "cap": 15, "label": "Required metadata missing"},
		"delegation_gaps": {"kind": "count", "weight": 5, "cap": 10, "label": "Accountable people disabled, or a delegate with no authority on record"},
	},
	"bands": {"Critical": 75, "High": 50, "Medium": 25, "Low": 0},
}

ADVERSE_OUTCOMES = ("Not Effective", "Partially Effective", "Not Performed")


# --------------------------------------------------------------- the weights


def weights(raw: str | dict | None = None) -> tuple[dict, list[str]]:
	"""Defaults merged with the configured overrides, and any problems found.

	An unreadable or out-of-range override is ignored and reported rather than
	failing the page: a typo in a setting should not take the assessment down.
	"""
	merged = copy.deepcopy(DEFAULT_WEIGHTS)
	problems: list[str] = []
	if raw is None:
		raw = guard.settings().get("risk_score_weights")
	data = common.loads(raw, None) if raw else {}
	if raw and data is None:
		return merged, [_("The configured weights are not valid JSON; the defaults are used.")]
	for subject in ("forum", "policy"):
		for factor, override in (data.get(subject) or {}).items():
			if factor not in merged[subject] or not isinstance(override, dict):
				problems.append(_("Unknown factor {0}.{1} ignored.").format(subject, factor))
				continue
			for key in ("weight", "cap"):
				if key in override:
					value = override[key]
					if isinstance(value, int | float) and 0 <= value <= 100:
						merged[subject][factor][key] = value
					else:
						problems.append(_("{0}.{1}.{2} must be a number from 0 to 100.").format(subject, factor, key))
	bands = data.get("bands") or {}
	for band, value in bands.items():
		if band in merged["bands"] and isinstance(value, int | float):
			merged["bands"][band] = value
		else:
			problems.append(_("Band {0} ignored.").format(band))
	return merged, problems


def points(spec: dict, evidence) -> float:
	"""The points one factor contributes. Pure."""
	if evidence is None:
		return 0.0
	if spec["kind"] == "flag":
		return float(spec["weight"]) if evidence else 0.0
	if spec["kind"] == "share":
		return round(float(spec["weight"]) * max(0.0, min(1.0, float(evidence))), 1)
	return float(min(spec.get("cap", 1e9), spec["weight"] * int(evidence)))


def band(score: float, bands: dict) -> str:
	for name, floor in sorted(bands.items(), key=lambda kv: -kv[1]):
		if score >= floor:
			return name
	return "Low"


def score(subject: str, evidence: dict, cfg: dict) -> dict:
	"""Combine evidence into a score with its full working. Pure."""
	factors, total = [], 0.0
	for key, spec in cfg[subject].items():
		value = evidence.get(key)
		p = points(spec, value["value"] if value else None)
		total += p
		factors.append({"factor": key, "label": _(spec["label"]), "kind": spec["kind"], "weight": spec["weight"],
		                "cap": spec.get("cap"), "evidence": value["value"] if value else None,
		                "detail": value.get("detail") if value else None,
		                "available": value is not None, "points": p})
	total = round(total, 1)
	return {"score": total, "band": band(total, cfg["bands"]), "factors": factors}


# ------------------------------------------------------------- the evidence


def _attestation_shares(doctype: str, names: list[str]) -> dict[str, dict] | None:
	if not common.can_read("Attestation Task"):
		return None
	today = common.today()
	due = defaultdict(lambda: [0, 0])  # name -> [due, not completed]
	for t in common.readable("Attestation Task", filters={"subject_doctype": doctype, "subject_name": ["in", names or common.NONE],
	                                                      "due_on": ["<=", str(today)]},
	                         fields=["subject_name", "is_open"]):
		due[t.subject_name][0] += 1
		due[t.subject_name][1] += 1 if int(t.is_open or 0) else 0
	return {n: {"value": (v[1] / v[0]) if v[0] else 0.0,
	            "detail": _("{0} of {1} due attestations not completed").format(v[1], v[0]) if v[0] else _("none due")}
	        for n, v in due.items()}


def _disabled_users(users) -> set[str]:
	users = {u for u in users if u}
	if not users:
		return set()
	return set(frappe.get_all("User", filters={"name": ["in", list(users)], "enabled": 0}, pluck="name"))


def _active_delegations() -> set[tuple[str, str]]:
	# The open-ended end date is tested here, not in the query: an "is set"
	# filter on a date column is rejected by PostgreSQL.
	today = common.today()
	return {(d.delegator, d.delegate) for d in frappe.get_all(
		"Authority Delegation", filters={"is_active": 1, "valid_from": ["<=", str(today)]},
		fields=["delegator", "delegate", "valid_to"]) if not d.valid_to or getdate(d.valid_to) >= today}


def forum_evidence(forums: list) -> dict[str, dict]:
	today = common.today()
	names = [f.name for f in forums]
	chartered = set(frappe.get_all("Committee Charter", filters={"forum": ["in", names or common.NONE]}, pluck="forum"))
	attest = _attestation_shares(FORUM, names)

	matters_by_forum = defaultdict(list)
	if common.can_read("Escalation Matter"):
		links = frappe.get_all("Escalation Forum Link", filters={"parenttype": "Escalation Matter", "governance_forum": ["in", names or common.NONE]},
		                       fields=["parent", "governance_forum"])
		readable = {m.name: m for m in common.readable("Escalation Matter", filters={"is_open": 1, "name": ["in", [l.parent for l in links] or common.NONE]},
		                                              fields=["name", "threshold_breached"])}
		for link in links:
			if link.parent in readable:
				matters_by_forum[link.governance_forum].append(readable[link.parent])

	seats = defaultdict(list)
	for m in frappe.get_all("Forum Membership", filters={"forum": ["in", names or common.NONE]},
	                        fields=["forum", "member", "delegate", "delegate_to", "authority_delegation", "end_date"]):
		if m.end_date and getdate(m.end_date) < today:
			continue
		seats[m.forum].append(m)
	disabled = _disabled_users([s.member for rows in seats.values() for s in rows]
	                           + [u for f in forums for u in (f.committee_chair, f.secretary, f.forum_owner)])
	active_authority = set(frappe.get_all("Authority Delegation", filters={"is_active": 1}, pluck="name"))

	out = {}
	for f in forums:
		ev = {}
		ev["compliance_not_confirmed"] = {"value": bool(int(f.requires_review or 0)), "detail": f.compliance_status}
		ev["review_overdue"] = {"value": bool(f.next_review_on and getdate(f.next_review_on) < today),
		                        "detail": str(f.next_review_on) if f.next_review_on else _("no review date")}
		if attest is not None:
			ev["attestation_incomplete"] = attest.get(f.name, {"value": 0.0, "detail": _("none due")})
		if common.can_read("Escalation Matter"):
			open_m = matters_by_forum.get(f.name, [])
			ev["open_escalations"] = {"value": len(open_m), "detail": None}
			ev["breached_slas"] = {"value": sum(1 for m in open_m if int(m.threshold_breached or 0)), "detail": None}
		missing = []
		if f.name not in chartered:
			missing.append(_("charter"))
		if not f.quorum_rule_type or (f.quorum_rule_type != "All Voting Members" and not float(f.quorum_value or 0)):
			missing.append(_("quorum rule"))
		for field, label in (("committee_chair", _("chair")), ("secretary", _("secretary")), ("forum_owner", _("owner")), ("cadence", _("cadence"))):
			if not f.get(field):
				missing.append(label)
		ev["missing_metadata"] = {"value": len(missing), "detail": ", ".join(missing) or None}
		gaps = []
		for field, label in (("committee_chair", _("chair")), ("secretary", _("secretary")), ("forum_owner", _("owner"))):
			if f.get(field) in disabled:
				gaps.append(_("{0} disabled").format(label))
		for s in seats.get(f.name, []):
			if s.member in disabled:
				gaps.append(_("a seat held by a disabled user"))
			if s.delegate and (not s.delegate_to or getdate(s.delegate_to) >= today) and s.authority_delegation not in active_authority:
				gaps.append(_("a delegate with no active authority"))
		ev["delegation_gaps"] = {"value": len(gaps), "detail": "; ".join(gaps) or None}
		out[f.name] = ev
	return out


def policy_evidence(docs: list) -> dict[str, dict]:
	from consilium.policy import metadata

	today = common.today()
	names = [d.name for d in docs]
	attest = _attestation_shares(DOCUMENT, names)
	violations = common.readable("Policy Violation", filters={"document": ["in", names or common.NONE]},
	                             fields=["name", "document", "is_open", "resulting_escalation"]) if common.can_read("Policy Violation") else None
	open_v = Counter(v.document for v in violations or [] if int(v.is_open or 0))
	escalations = Counter()
	if violations is not None and common.can_read("Escalation Matter"):
		by_violation = {v.name: v.document for v in violations}
		for m in common.readable("Escalation Matter", filters={"is_open": 1, "source_policy_violation": ["in", list(by_violation) or common.NONE]},
		                         fields=["source_policy_violation"]):
			escalations[by_violation[m.source_policy_violation]] += 1
	breaches = None
	if common.can_read("SLA Clock"):
		cycles = {c.name: c.document for c in frappe.get_all("Document Review Cycle", filters={"document": ["in", names or common.NONE]},
		                                                     fields=["name", "document"])}
		subjects = dict(cycles)
		subjects.update({v.name: v.document for v in violations or []})
		breaches = Counter(subjects[c.subject_name] for c in common.readable(
			"SLA Clock", filters={"subject_name": ["in", list(subjects) or common.NONE]},
			fields=["subject_name", "breached_on"]) if c.breached_on and c.subject_name in subjects)
	adverse = None
	if common.can_read("Monitoring Result"):
		since = str(add_months(today, -12))
		adverse = Counter(r.document for r in common.readable(
			"Monitoring Result", filters={"document": ["in", names or common.NONE], "performed_on": [">=", since],
			                              "outcome": ["in", list(ADVERSE_OUTCOMES)]}, fields=["document"]))
	delegations = _active_delegations()
	people = [u for d in docs for u in (d.document_owner, d.document_approver, d.document_delegate, d.document_sponsor, d.key_contact)]
	disabled = _disabled_users(people)

	out = {}
	for d in docs:
		ev = {}
		ev["review_overdue"] = {"value": bool(int(d.is_active or 0) and d.next_review_on and getdate(d.next_review_on) < today),
		                        "detail": str(d.next_review_on) if d.next_review_on else _("no review date")}
		ev["no_approving_forum"] = {"value": not d.approving_forum, "detail": None}
		if attest is not None:
			ev["attestation_incomplete"] = attest.get(d.name, {"value": 0.0, "detail": _("none due")})
		if violations is not None:
			ev["open_violations"] = {"value": open_v.get(d.name, 0), "detail": None}
			if common.can_read("Escalation Matter"):
				ev["open_escalations"] = {"value": escalations.get(d.name, 0), "detail": None}
		if breaches is not None:
			ev["breached_slas"] = {"value": breaches.get(d.name, 0), "detail": None}
		if adverse is not None:
			ev["adverse_monitoring"] = {"value": adverse.get(d.name, 0), "detail": None}
		try:
			missing = metadata.missing_fields(frappe.get_doc(DOCUMENT, d.name))
		except Exception:
			missing = []
		ev["missing_metadata"] = {"value": len(missing), "detail": ", ".join(missing[:8]) or None}
		gaps = [f"{label} disabled" for field, label in (("document_owner", "owner"), ("document_approver", "approver"),
		                                                 ("document_delegate", "delegate"), ("document_sponsor", "sponsor"),
		                                                 ("key_contact", "key contact")) if d.get(field) in disabled]
		if d.document_delegate and d.document_owner and (d.document_owner, d.document_delegate) not in delegations:
			gaps.append(_("delegate has no active authority from the owner"))
		ev["delegation_gaps"] = {"value": len(gaps), "detail": "; ".join(gaps) or None}
		out[d.name] = ev
	return out


# ------------------------------------------------------------------- the API


def assessment() -> dict:
	cfg, problems = weights()
	forums = common.readable(FORUM, filters={"is_active": 1}, fields=[
		"name", "forum_name", "requires_review", "compliance_status", "next_review_on", "quorum_rule_type", "quorum_value",
		"committee_chair", "secretary", "forum_owner", "cadence", "confidential"])
	docs = [d for d in common.readable(DOCUMENT, fields=[
		"name", "document_name", "is_active", "is_editable", "retired_on", "next_review_on", "approving_forum", "document_owner",
		"document_approver", "document_delegate", "document_sponsor", "key_contact", "handling_classification", "confidential"])
		if not d.retired_on]
	f_ev, p_ev = forum_evidence(forums), policy_evidence(docs)
	forum_scores = [{"doctype": FORUM, "name": f.name, "title": f.forum_name, "href": common.href(FORUM, f.name),
	                 **score("forum", f_ev[f.name], cfg)} for f in forums]
	policy_scores = [{"doctype": DOCUMENT, "name": d.name, "title": d.document_name, "href": common.href(DOCUMENT, d.name),
	                  **score("policy", p_ev[d.name], cfg)} for d in docs]
	forum_scores.sort(key=lambda s: -s["score"])
	policy_scores.sort(key=lambda s: -s["score"])
	return {
		"forums": forum_scores, "policies": policy_scores,
		"weights": cfg, "weight_problems": problems,
		# In plain words: the page shows this behind "How is this worked out?".
		"method": _("Each score adds up points from the factors listed for it. A yes-or-no factor adds its full "
		            "weight when it applies; a counted factor adds its weight for each item, up to a limit; a "
		            "proportion adds its weight in proportion. {0}.").format(
			"; ".join(_("{0} from {1} points").format(k, v)
			          for k, v in sorted(cfg["bands"].items(), key=lambda kv: -kv[1]))),
		"ai": guard.availability(CAPABILITY),
		"note": _("Scored over the records you may read. A factor marked unavailable reads records your role cannot see, "
		          "and scores nothing for you."),
	}


@frappe.whitelist(methods=["GET"])
def assess() -> dict:
	common.require_signed_in()
	return assessment()


SYSTEM = """You explain rules-based governance risk scores for committees (forums) and policies in an enterprise governance, risk and policy platform. Each score is the sum of named factors; you are given each factor's evidence and points.
Write, in plain text with no headings or tables, at most 170 words: one sentence on the overall picture, then one bullet ("- ") per record given, most at risk first, naming the record by token, the one or two factors driving its score and the most useful next step.
Do not re-score or dispute the numbers; explain them."""


def build_payload(result: dict, top: int = 8) -> guard.Payload:
	p = guard.Payload()
	p.classification = guard.INTERNAL
	docs = {d.name: d for d in frappe.get_all(DOCUMENT, filters={"name": ["in", [s["name"] for s in result["policies"][:top]] or common.NONE]},
	                                          fields=["name", "handling_classification", "confidential"])}
	forums = {f.name: f for f in frappe.get_all(FORUM, filters={"name": ["in", [s["name"] for s in result["forums"][:top]] or common.NONE]},
	                                            fields=["name", "confidential"])}
	for heading, rows, doctype, facts in (("Forums, highest score first:", result["forums"][:top], FORUM, forums),
	                                      ("Policies, highest score first:", result["policies"][:top], DOCUMENT, docs)):
		p.line(heading)
		for s in rows:
			driving = [f"{f['factor']}={f['points']}" for f in s["factors"] if f["points"]]
			p.record(doctype, s["name"], guard.classification_of(doctype, facts.get(s["name"]) or {}), title=s["title"],
			         tags={"score": s["score"], "band": s["band"], "points by factor": driving or ["none"]}, href=s["href"])
	return p


@frappe.whitelist(methods=["POST"])
def ai_rationale() -> dict:
	common.require_signed_in()
	result = assessment()
	payload = build_payload(result)
	outcome = guard.run(CAPABILITY, system=SYSTEM, payload=payload,
	                    accept=lambda text: guard.narrative_blocks(text, payload.links))
	return {"assessment": result, "ai": {"used": outcome["used"], "status": outcome["status"], "notice": outcome["notice"],
	                                     "service_request": outcome["service_request"], "blocks": outcome["value"],
	                                     "withheld": outcome["withheld"], "mode": outcome.get("mode")}}
