"""Predictive analytics for emerging risks (O-7): trends and leading indicators.

    GET  /api/method/consilium.consilium_core.ai.trends.analyse   months?
    POST /api/method/consilium.consilium_core.ai.trends.ai_commentary   months?

The deterministic part is ordinary statistics, in pure Python, over four
event streams the platform already records:

=====================  ===================  ==========================================
stream                 dated by             grouped by
=====================  ===================  ==========================================
escalations            identification date  risk type (tier 1), escalation type, org unit*
policy violations      identified on        risk category (of the document), org unit,
                                            violation type
adverse monitoring     performed on         risk category, owning group (of the document)
SLA breaches           breached on          the kind of record that breached
=====================  ===================  ==========================================

\\* an escalation names its units through its impacted entities.

For every (stream, dimension, value) series of monthly counts it computes the
month-over-month change, the least-squares **slope** over the last six
months, and the **z-score** of the latest month against the months before it.
A series is **rising** when either

* its latest month stands out: z ≥ 2 with at least 2 events that month; or
* it climbs steadily: slope ≥ 0.5 events/month over six months, with the last
  three months above the six-month mean and at least 4 events in them.

Those thresholds are constants below, named and documented; they are meant to
be read, not tuned in secret. **Leading indicators** are the precursors a
governance office watches: repeat breaches (a matter breached more than once, a
document violated twice within 90 days, a control found ineffective twice
running) and overdue actions (action plans, review cycles, remediation tasks
and attestations past their dates).

Every count is over records the viewer may read, through the permitted query,
so the page never shows a trend built from records it would not list. With AI
on, the series that are rising and the indicators — as numbers and taxonomy
names, never record text, and never including a sensitive escalation — are
sent for a short narrative of emerging themes.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, get_first_day, getdate, nowdate

from consilium.consilium_core.ai import common, guard

CAPABILITY = "trends"

Z_THRESHOLD = 2.0
Z_MIN_LATEST = 2
SLOPE_WINDOW = 6
SLOPE_THRESHOLD = 0.5
SLOPE_MIN_RECENT = 4
REPEAT_VIOLATION_DAYS = 90

ADVERSE_OUTCOMES = ("Not Effective", "Partially Effective", "Not Performed")


# ---------------------------------------------------------------- statistics


def slope(values: list[float]) -> float:
	"""Least-squares slope of values against 0..n-1. Pure."""
	n = len(values)
	if n < 2:
		return 0.0
	mean_x, mean_y = (n - 1) / 2, sum(values) / n
	den = sum((i - mean_x) ** 2 for i in range(n))
	return sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values)) / den if den else 0.0


def zscore(history: list[float], latest: float) -> float | None:
	"""How far the latest value sits from the history, in standard deviations.

	A flat history (standard deviation 0) has no scale; any rise above it is
	reported as a z of 3 so it is not silently dropped, and no rise as 0.
	"""
	if len(history) < 3:
		return None
	mean = statistics.fmean(history)
	sd = statistics.pstdev(history)
	if sd == 0:
		return 3.0 if latest > mean else 0.0
	return (latest - mean) / sd


def classify(values: list[int]) -> dict:
	"""Trend facts for one monthly series (oldest first). Pure; tested directly."""
	latest = values[-1] if values else 0
	previous = values[-2] if len(values) > 1 else 0
	window = values[-SLOPE_WINDOW:]
	s = slope(window)
	z = zscore(values[:-1], latest)
	mean_w = statistics.fmean(window) if window else 0
	recent = values[-3:]
	steady = (s >= SLOPE_THRESHOLD and all(v >= mean_w for v in recent) and sum(recent) >= SLOPE_MIN_RECENT)
	spike = z is not None and z >= Z_THRESHOLD and latest >= Z_MIN_LATEST
	reasons = []
	if spike:
		reasons.append(_("latest month is {0:.1f} standard deviations above the months before").format(z))
	if steady:
		reasons.append(_("rising by {0:.1f} a month over the last {1} months").format(s, len(window)))
	return {
		"latest": latest, "previous": previous,
		"mom_change": latest - previous,
		"mom_pct": round((latest - previous) / previous * 100, 1) if previous else None,
		"slope": round(s, 3), "z": round(z, 2) if z is not None else None,
		"total": sum(values), "rising": bool(spike or steady), "reasons": reasons,
	}


# -------------------------------------------------------------------- events


def _months(months: int) -> tuple[list[str], str]:
	keys = common.month_keys(months)
	start = str(get_first_day(add_months(getdate(nowdate()), -(months - 1))))
	return keys, start


def _doc_facts(names) -> dict:
	names = list({n for n in names if n})
	if not names:
		return {}
	return {r.name: r for r in frappe.get_all("Governing Document", filters={"name": ["in", names]},
	                                          fields=["name", "primary_risk_category", "owning_operating_group",
	                                                  "handling_classification", "confidential"])}


def events(start: str) -> list[dict]:
	"""Every dated event in the window as {stream, month, dims, shareable}.

	``shareable`` is False for anything that may never leave: a sensitive
	escalation, or an event on a document above the classification ceiling.
	"""
	out = []
	matters = common.readable("Escalation Matter", filters={"escalation_identification_date": [">=", start]},
	                          fields=["name", "escalation_identification_date", "tier_1_risk_type", "escalation_type", "sensitive"])
	units = defaultdict(list)
	for row in frappe.get_all("Escalation Impacted Entity", filters={
			"parenttype": "Escalation Matter", "parent": ["in", [m.name for m in matters] or common.NONE],
			"entity_doctype": "Organization Unit"}, fields=["parent", "entity_value"]):
		units[row.parent].append(row.entity_value)
	for m in matters:
		dims = {"risk type": m.tier_1_risk_type, "escalation type": m.escalation_type}
		out.append({"stream": "escalations", "month": common.month_key(m.escalation_identification_date), "dims": dims,
		            "units": units.get(m.name) or [], "shareable": not int(m.sensitive or 0)})

	violations = common.readable("Policy Violation", filters={"identified_on": [">=", start]},
	                             fields=["name", "document", "identified_on", "business_unit", "violation_type"])
	results = common.readable("Monitoring Result", filters={"performed_on": [">=", start], "outcome": ["in", list(ADVERSE_OUTCOMES)]},
	                          fields=["name", "document", "performed_on", "outcome"])
	docs = _doc_facts([v.document for v in violations] + [r.document for r in results])
	for v in violations:
		d = docs.get(v.document) or {}
		out.append({"stream": "violations", "month": common.month_key(v.identified_on),
		            "dims": {"risk category": d.get("primary_risk_category"), "violation type": v.violation_type},
		            "units": [v.business_unit] if v.business_unit else [],
		            "shareable": guard.may_leave(guard.classification_of("Governing Document", d))})
	for r in results:
		d = docs.get(r.document) or {}
		out.append({"stream": "adverse monitoring", "month": common.month_key(r.performed_on),
		            "dims": {"risk category": d.get("primary_risk_category")},
		            "units": [d.get("owning_operating_group")] if d.get("owning_operating_group") else [],
		            "shareable": guard.may_leave(guard.classification_of("Governing Document", d))})

	for c in common.readable("SLA Clock", filters={"breached_on": [">=", start]}, fields=["name", "subject_doctype", "breached_on"]):
		out.append({"stream": "SLA breaches", "month": common.month_key(c.breached_on),
		            "dims": {"record kind": c.subject_doctype}, "units": [], "shareable": True})
	return out


def series(evts: list[dict], keys: list[str], *, shareable_only: bool = False) -> list[dict]:
	index = {k: i for i, k in enumerate(keys)}
	buckets: dict[tuple, list[int]] = {}

	def bump(stream, dim, value, month):
		if not value or month not in index:
			return
		buckets.setdefault((stream, dim, value), [0] * len(keys))[index[month]] += 1

	for e in evts:
		if shareable_only and not e["shareable"]:
			continue
		bump(e["stream"], "all", "all", e["month"])
		for dim, value in e["dims"].items():
			bump(e["stream"], dim, value, e["month"])
		for unit in e["units"]:
			bump(e["stream"], "org unit", unit, e["month"])
	out = []
	for (stream, dim, value), counts in buckets.items():
		out.append({"stream": stream, "dimension": dim, "value": value, "counts": counts, **classify(counts)})
	out.sort(key=lambda s: (not s["rising"], -(s["z"] or 0), -s["slope"], -s["total"]))
	return out


# ---------------------------------------------------------------- indicators


def indicators() -> list[dict]:
	today = common.today()
	out = []

	def add(kind, label, rows, href=None):
		out.append({"kind": kind, "label": label, "count": len(rows), "items": rows[:15], "href": href,
		            "shareable_count": sum(1 for r in rows if not r.get("_sensitive"))})

	repeat_matters = common.readable("Escalation Matter", filters={"breach_count": [">=", 2]},
	                                 fields=["name", "escalation_title", "breach_count", "sensitive"])
	add("repeat_breach", _("Escalations that breached their time limit more than once"),
	    [{"name": m.name, "label": m.escalation_title, "detail": _("{0} breaches").format(m.breach_count),
	      "href": common.href("Escalation Matter", m.name), "_sensitive": int(m.sensitive or 0)} for m in repeat_matters])

	since = str(add_days(today, -REPEAT_VIOLATION_DAYS))
	per_doc = Counter(v.document for v in common.readable("Policy Violation", filters={"identified_on": [">=", since]},
	                                                     fields=["document"]) if v.document)
	titles = {r.name: r.document_name for r in common.readable("Governing Document", filters={"name": ["in", list(per_doc) or common.NONE]},
	                                                          fields=["name", "document_name"])}
	add("repeat_violation", _("Documents violated more than once in {0} days").format(REPEAT_VIOLATION_DAYS),
	    [{"name": d, "label": titles.get(d, d), "detail": _("{0} violations").format(n), "href": common.href("Governing Document", d)}
	     for d, n in per_doc.most_common() if n >= 2 and d in titles])

	runs = defaultdict(list)
	for r in common.readable("Monitoring Result", fields=["monitoring_activity", "outcome", "performed_on", "document"],
	                         order_by="performed_on desc"):
		runs[r.monitoring_activity].append(r)
	repeat_controls = []
	activity_titles = {a.name: a.activity_title for a in common.readable(
		"Monitoring Activity", filters={"name": ["in", list(runs) or common.NONE]}, fields=["name", "activity_title"])}
	for activity, rows in runs.items():
		if len(rows) >= 2 and all(r.outcome in ADVERSE_OUTCOMES for r in rows[:2]):
			repeat_controls.append({"name": activity, "label": activity_titles.get(activity) or activity,
			                        "detail": _("last two results adverse"),
			                        "href": common.href("Governing Document", rows[0].document)})
	add("repeat_control", _("Controls found ineffective twice running"), repeat_controls)

	add("overdue_action_plans", _("Action plans past their end date"),
	    [{"name": a.name, "label": a.action_plan_name, "detail": str(a.end_date), "href": common.href("Escalation Matter", a.escalation_matter),
	      "_sensitive": int(a.sensitive or 0)}
	     for a in common.readable("Action Plan", filters={"is_open": 1, "end_date": ["<", str(today)]},
	                              fields=["name", "action_plan_name", "end_date", "escalation_matter", "sensitive"])])
	cycles = common.readable("Document Review Cycle", filters={"is_open": 1, "due_on": ["<", str(today)]},
	                         fields=["name", "document", "due_on"])
	cycle_titles = {r.name: r.document_name for r in common.readable(
		"Governing Document", filters={"name": ["in", [c.document for c in cycles] or common.NONE]}, fields=["name", "document_name"])}
	add("overdue_reviews", _("Document review cycles open past due"),
	    [{"name": c.name, "label": cycle_titles.get(c.document) or c.document, "detail": _("due {0}").format(c.due_on),
	      "href": common.href("Governing Document", c.document)} for c in cycles])
	add("overdue_remediation", _("Metadata remediation tasks past due"),
	    [{"name": t.name, "label": f"{t.subject_doctype} {t.subject_name}", "detail": str(t.due_on)}
	     for t in common.readable("Metadata Remediation Task", filters={"is_open": 1, "due_on": ["<", str(today)]},
	                              fields=["name", "subject_doctype", "subject_name", "due_on"])])
	add("overdue_attestations", _("Attestations past due"),
	    [{"name": t.name, "label": f"{t.subject_doctype} {t.subject_name}", "detail": str(t.due_on)}
	     for t in common.readable("Attestation Task", filters={"is_open": 1, "due_on": ["<", str(today)]},
	                              fields=["name", "subject_doctype", "subject_name", "due_on"])])
	return out


# ------------------------------------------------------------------- the API


def analysis(months: int = 12) -> dict:
	months = min(36, max(6, common.as_int(months, 12)))
	keys, start = _months(months)
	evts = events(start)
	all_series = series(evts, keys)
	labels = _labels(all_series)
	for s in all_series:
		s["label"] = labels.get((s["dimension"], s["value"]), s["value"])
	return {
		"months": keys,
		"series": all_series[:80],
		"rising": [s for s in all_series if s["rising"]],
		"totals": {s["stream"]: s["counts"] for s in all_series if s["dimension"] == "all"},
		"indicators": [{**i, "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in i["items"]]}
		               for i in indicators()],
		"method": {
			"z_threshold": Z_THRESHOLD, "z_min_latest": Z_MIN_LATEST, "slope_window": SLOPE_WINDOW,
			"slope_threshold": SLOPE_THRESHOLD, "slope_min_recent": SLOPE_MIN_RECENT,
			"text": _("Rising means: the latest month is at least {0} standard deviations above the earlier months with at "
			          "least {1} events, or the count has risen by at least {2} a month over the last {3} months with the "
			          "last three months above that period's mean and at least {4} events in them.").format(
				Z_THRESHOLD, Z_MIN_LATEST, SLOPE_THRESHOLD, SLOPE_WINDOW, SLOPE_MIN_RECENT),
		},
		"visible": {dt: common.can_read(dt) for dt in ("Escalation Matter", "Policy Violation", "Monitoring Result", "SLA Clock")},
		"ai": guard.availability(CAPABILITY),
		"note": _("Counted over the records you may read."),
	}


def _labels(all_series) -> dict:
	"""Display names for taxonomy values: reference data readable by everyone."""
	out = {}
	lookups = {"risk type": ("Risk Type", "risk_type_name"), "risk category": ("Risk Category", "risk_category_name"),
	           "escalation type": ("Escalation Type", "escalation_type_name"), "org unit": ("Organization Unit", "org_unit_name")}
	for dim, (doctype, field) in lookups.items():
		values = [s["value"] for s in all_series if s["dimension"] == dim]
		if values:
			for r in frappe.get_all(doctype, filters={"name": ["in", values]}, fields=["name", field]):
				out[(dim, r.name)] = r.get(field) or r.name
	return out


@frappe.whitelist(methods=["GET"])
def analyse(months: int | str = 12) -> dict:
	common.require_signed_in()
	return analysis(common.as_int(months, 12))


SYSTEM = """You are a risk analyst reviewing monthly counts of governance events in an enterprise: escalations, policy violations, adverse control-monitoring results and service-level breaches, grouped by risk type, risk category, organisation unit and similar.
Some series have been flagged as rising by fixed statistical rules, and some leading indicators (repeat breaches, overdue actions) are counted.
Write, in plain text with no headings or tables, at most 170 words: two or three sentences on the emerging themes, then up to 5 bullet points ("- ") each naming a theme, the evidence (the series or indicator) and what to look at next.
Say plainly when the numbers are too small to support a conclusion. Use only the numbers given."""


def build_payload(months: int) -> guard.Payload:
	"""Counts over shareable events only: a sensitive escalation is not even counted."""
	keys, start = _months(months)
	evts = events(start)
	shareable = series(evts, keys, shareable_only=True)
	labels = _labels(shareable)
	p = guard.Payload()
	p.classification = guard.INTERNAL
	p.line(f"Months, oldest first: {', '.join(keys)}.")
	withheld = sum(1 for e in evts if not e["shareable"])
	if withheld:
		p.withheld += withheld
	p.line("Totals per stream (monthly counts):")
	for s in shareable:
		if s["dimension"] == "all":
			p.line(f"- {s['stream']}: {s['counts']}")
	rising = [s for s in shareable if s["rising"] and s["dimension"] != "all"][:20]
	p.line("Series flagged as rising:" if rising else "No series is flagged as rising.")
	for s in rising:
		label = labels.get((s["dimension"], s["value"]), s["value"])
		p.line(f"- {s['stream']} by {s['dimension']} = {label}: counts {s['counts']}; slope {s['slope']}; z {s['z']}; "
		       f"month-over-month {s['mom_change']:+d}")
	top = [s for s in shareable if not s["rising"] and s["dimension"] != "all"][:10]
	if top:
		p.line("Other large series, for context:")
		for s in top:
			p.line(f"- {s['stream']} by {s['dimension']} = {labels.get((s['dimension'], s['value']), s['value'])}: total {s['total']}, latest {s['latest']}")
	p.line("Leading indicators (counts):")
	for i in indicators():
		p.line(f"- {i['label']}: {i['shareable_count']}")
	return p


@frappe.whitelist(methods=["POST"])
def ai_commentary(months: int | str = 12) -> dict:
	common.require_signed_in()
	months = min(36, max(6, common.as_int(months, 12)))
	result = analysis(months)
	payload = build_payload(months)
	outcome = guard.run(CAPABILITY, system=SYSTEM, payload=payload,
	                    accept=lambda text: guard.narrative_blocks(text, payload.links))
	return {"analysis": result, "ai": {"used": outcome["used"], "status": outcome["status"], "notice": outcome["notice"],
	                                   "service_request": outcome["service_request"], "blocks": outcome["value"],
	                                   "withheld": outcome["withheld"], "mode": outcome.get("mode")}}
