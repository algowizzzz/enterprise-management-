"""Per-person dashboard layouts for the Insights pages (O-3).

The management reporting page (and the two analysis pages beside it) used to
draw the same sections, in the same order, for everyone. A chief risk officer
who reads escalations first and never looks at document families had to scroll
past everything else every time. O-3 asks for a customisable dashboard; this is
the smallest version that is honest about it: a viewer chooses which sections
and which dimensions inside them are shown, puts them in the order they want,
and saves that as their own layout. "Reset to default" returns the page to what
it ships as.

**What is stored.** One ``Dashboard Layout`` row per person per page, holding the
section keys in order, each with a shown flag and its dimension keys in order.
Nothing else: no figure, no filter, no record name. The row is a preference, so
it grants nothing — the page still draws only what the permission checks let it
draw, and the figures are still counted over the records the viewer may read.

**Why a registry here rather than reading the page.** The sections a page has
are named below, each with the record types a viewer must be able to read to
see it. The customise panel is offered only what this module returns, so a
section the viewer cannot read is never offered, even if a template bug drew
it; and a saved layout that names a section the viewer can no longer read (a
role was taken away) simply loses it when read back. Sections and dimensions
are identified by the id of their heading element in the page, which is also
how the script finds them.

**Reset keeps the row.** Resetting clears the layout rather than deleting the
row. A preference is not a governed record, but the platform deletes nothing as
a matter of course, and keeping the row costs nothing: the next save reuses it.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

DOCTYPE = "Dashboard Layout"


def _dim(heading: str, label: str) -> dict:
	return {"key": heading, "label": label}


#: Every customisable page: its sections in their default order. ``any_of``
#: lists the record types of which the viewer must be able to read at least
#: one for the section to be offered; ``None`` means the page's own access
#: decides (its figures are permission-filtered already).
PAGES: dict[str, list[dict]] = {
	"reports": [
		{"key": "headline-heading", "label": "The headline", "any_of": None, "dimensions": []},
		{"key": "forums-heading", "label": "Governance forums", "any_of": ["Governance Forum"], "dimensions": [
			_dim("forum-status-heading", "By compliance status"),
			_dim("forum-type-heading", "Active forums by type"),
		]},
		{"key": "forum-service-heading", "label": "Forum time limits", "any_of": ["Governance Forum"],
		 "dimensions": [
			_dim("forum-service-reviews-heading", "Reviews and attestation"),
			_dim("forum-service-formation-heading", "Formation requests"),
			_dim("forum-service-late-heading", "Forums past a time limit"),
		]},
		{"key": "coverage-heading", "label": "Coverage gaps",
		 "any_of": ["Governance Forum", "Governing Document"], "dimensions": []},
		{"key": "documents-heading", "label": "Governing documents", "any_of": ["Governing Document"],
		 "dimensions": [
			_dim("doc-phase-heading", "By lifecycle phase"),
			_dim("doc-type-heading", "By document type"),
			_dim("doc-group-heading", "By owning operating group"),
			_dim("doc-handling-heading", "By handling classification"),
			_dim("missing-heading", "Required metadata missing"),
			_dim("families-heading", "Document families"),
			_dim("monitoring-heading", "Monitoring outcomes"),
			_dim("violations-heading", "Open violations, by severity"),
			_dim("open-violations-heading", "Open violations"),
			_dim("exceptions-heading", "Exceptions"),
			_dim("dispositions-heading", "Review and retirement dispositions"),
		]},
		{"key": "escalations-heading", "label": "Escalations", "any_of": ["Escalation Matter"], "dimensions": [
			_dim("esc-severity-heading", "Open, by severity"),
			_dim("esc-age-heading", "Open, by age"),
			_dim("esc-type-heading", "Open, by type"),
			_dim("esc-level-heading", "Open, by organisational level"),
			_dim("sla-heading", "Time-limit clocks"),
			_dim("analysis-heading", "Volumes, durations and outcomes"),
		]},
	],
	"governance-gaps": [
		{"key": "gaps-heading", "label": "Governance gaps", "any_of": None, "dimensions": []},
		{"key": "risk-heading", "label": "Governance risk assessment", "any_of": None, "dimensions": []},
	],
	"emerging-risks": [
		{"key": "rising-heading", "label": "Rising", "any_of": None, "dimensions": []},
		{"key": "indicators-heading", "label": "Leading indicators", "any_of": None, "dimensions": []},
		{"key": "all-heading", "label": "Every series", "any_of": None, "dimensions": []},
	],
}


def _require_user() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		raise frappe.PermissionError(_("Sign in to arrange a dashboard."))
	return user


def _require_page(page: str) -> list[dict]:
	sections = PAGES.get((page or "").strip())
	if sections is None:
		frappe.throw(_("{0} is not a dashboard that can be arranged.").format(page), title=_("Unknown Page"))
	return sections


def _readable(section: dict, can) -> bool:
	doctypes = section.get("any_of")
	return not doctypes or any(can(doctype) for doctype in doctypes)


def available_sections(page: str, user: str | None = None) -> list[dict]:
	"""The page's sections this person may see, in the default order."""
	user = user or frappe.session.user
	cache: dict[str, bool] = {}

	def can(doctype: str) -> bool:
		if doctype not in cache:
			try:
				cache[doctype] = bool(frappe.has_permission(doctype, "read", user=user))
			except Exception:
				cache[doctype] = False
		return cache[doctype]

	return [
		{"key": s["key"], "label": _(s["label"]),
		 "dimensions": [{"key": d["key"], "label": _(d["label"])} for d in s["dimensions"]]}
		for s in _require_page(page) if _readable(s, can)
	]


def default_layout(sections: list[dict]) -> list[dict]:
	return [
		{"key": s["key"], "shown": True, "dimensions": [{"key": d["key"], "shown": True} for d in s["dimensions"]]}
		for s in sections
	]


def _parse(value) -> list:
	if not value:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			return []
	return value if isinstance(value, list) else []


def normalise(layout, sections: list[dict]) -> list[dict]:
	"""A layout reduced to what the page offers this person, and completed.

	Unknown or unreadable keys are dropped; a section or dimension the saved
	layout does not mention (added to the page since, or newly readable) is
	appended in its default position at the end, shown. So a saved layout never
	hides something new by accident and never reveals something it should not.
	"""
	offered = {s["key"]: s for s in sections}
	out, seen = [], set()
	for entry in _parse(layout):
		if not isinstance(entry, dict):
			continue
		key = entry.get("key")
		if key not in offered or key in seen:
			continue
		seen.add(key)
		dims_offered = [d["key"] for d in offered[key]["dimensions"]]
		dims, dim_seen = [], set()
		for dim in entry.get("dimensions") or []:
			if isinstance(dim, dict) and dim.get("key") in dims_offered and dim["key"] not in dim_seen:
				dim_seen.add(dim["key"])
				dims.append({"key": dim["key"], "shown": bool(dim.get("shown", True))})
		dims += [{"key": d, "shown": True} for d in dims_offered if d not in dim_seen]
		out.append({"key": key, "shown": bool(entry.get("shown", True)), "dimensions": dims})
	for section in sections:
		if section["key"] not in seen:
			out.append({"key": section["key"], "shown": True,
				"dimensions": [{"key": d["key"], "shown": True} for d in section["dimensions"]]})
	return out


def _row(user: str, page: str) -> str | None:
	return frappe.db.get_value(DOCTYPE, {"user": user, "page": page}, "name")


def layout_for(page: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	sections = available_sections(page, user)
	name = _row(user, page)
	stored = frappe.db.get_value(DOCTYPE, name, ["layout", "is_customised"], as_dict=True) if name else None
	customised = bool(stored and int(stored.is_customised or 0) and stored.layout)
	return {
		"page": page,
		"sections": sections,
		"default": default_layout(sections),
		"layout": normalise(stored.layout, sections) if customised else default_layout(sections),
		"customised": customised,
	}


@frappe.whitelist(methods=["GET"])
def get_layout(page: str) -> dict:
	"""The viewer's layout for a page, with what they may arrange on it."""
	_require_user()
	return layout_for(page)


@frappe.whitelist(methods=["POST"])
def save_layout(page: str, layout) -> dict:
	"""Save the viewer's own layout. Only ever the caller's row."""
	user = _require_user()
	sections = available_sections(page, user)
	clean = normalise(layout, sections)
	if not any(entry["shown"] for entry in clean):
		frappe.throw(_("Keep at least one section on the page."), title=_("Nothing Shown"))
	value = json.dumps(clean)
	name = _row(user, page)
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.layout = value
		doc.is_customised = 1
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": DOCTYPE, "user": user, "page": page, "layout": value, "is_customised": 1}).insert(
			ignore_permissions=True
		)
	return layout_for(page, user)


@frappe.whitelist(methods=["POST"])
def reset_layout(page: str) -> dict:
	"""Back to the page's default. The row is kept, cleared (see the module notes)."""
	user = _require_user()
	_require_page(page)
	name = _row(user, page)
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		doc.layout = None
		doc.is_customised = 0
		doc.save(ignore_permissions=True)
	return layout_for(page, user)
