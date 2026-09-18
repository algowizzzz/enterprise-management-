"""Global search: the header's one box for forums, policies and escalations.

A person looking for "the credit risk committee" or "ESC-2026-00015" should not
have to know which inventory it lives in first. This endpoint asks the three
record types at once and returns the top few matches from each, grouped, for
the header to drop down.

**Every row comes from ``frappe.get_list``**, never from a direct read. That is
the whole of the security story: the list API applies the viewer's permissions
and every ``permission_query_conditions`` hook, so a confidential or restricted
governing document (``consilium.policy.handling``) and a sensitive escalation
matter (``consilium.escalation.sensitivity``) are left out for anyone not
cleared to see them — exactly as on the list pages. A record type the viewer
may not read at all is skipped, not refused, so the box still answers for the
types they can.

Matching is on the identifier, the title and, for escalations, the external
reference — the things a person types. It is deliberately not the full-text
search of ``consilium.policy.repository.search`` (which also reads every
version's body): the header asks on every keystroke and must stay fast. The
"See all" link hands the words to the list page, which runs its own, deeper
search where it has one.
"""

from __future__ import annotations

import frappe
from frappe import _

#: The shortest query worth asking the database about.
MIN_LENGTH = 2
#: Longer than any title; anything past it is noise or an attempt at a heavy query.
MAX_LENGTH = 100
DEFAULT_LIMIT = 5
MAX_LIMIT = 10

#: One entry per record type: what is matched, what is shown, where a result
#: opens and where "See all" goes. ``see_all`` is set only where the list page
#: reads ``?q=`` from its address.
SOURCES = (
	{
		"key": "forums",
		"label": "Forums",
		"doctype": "Governance Forum",
		"match": ("name", "forum_name"),
		"title": "forum_name",
		"status": "compliance_status",
		"extra": ("is_active",),
		"url": "/forum?name={0}",
		"see_all": "/forums?q={0}",
		"icon": "bi-diagram-3",
	},
	{
		"key": "policies",
		"label": "Policies",
		"doctype": "Governing Document",
		"match": ("name", "document_name"),
		"title": "document_name",
		"status": "lifecycle_phase",
		"extra": ("document_type",),
		"url": "/policy?name={0}",
		"see_all": "/policies?q={0}",
		"icon": "bi-file-earmark-text",
	},
	{
		"key": "escalations",
		"label": "Escalations",
		"doctype": "Escalation Matter",
		"match": ("name", "escalation_title", "escalation_id"),
		"title": "escalation_title",
		"status": "status",
		"extra": ("severity",),
		"url": "/escalation?name={0}",
		"see_all": "/escalations?q={0}",
		"icon": "bi-exclamation-diamond",
	},
)

#: How a status reads as a pill. Display only; nothing here decides anything.
TONES = {
	"success": {"Compliant", "Published", "Implemented", "Approved", "Closed", "Resolved"},
	"warning": {"Pending", "Review", "Under Review", "Pending Review", "In Progress", "Medium"},
	"danger": {"Non-Compliant", "Overdue", "High", "Breached", "Rejected"},
	"neutral": {"Draft", "Disbanded", "Retired", "Archived", "Low", "Cancelled"},
}


def tone_of(status: str | None) -> str:
	for tone, values in TONES.items():
		if status in values:
			return tone
	return "info"


def _like(text: str) -> str:
	"""A LIKE pattern that matches ``text`` literally, wildcards included."""
	escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{escaped}%"


def _search_one(source: dict, text: str, limit: int) -> dict | None:
	meta = frappe.get_meta(source["doctype"])
	match = [field for field in source["match"] if field == "name" or meta.has_field(field)]
	shown = [field for field in (source["title"], source["status"], *source["extra"]) if meta.has_field(field)]
	pattern = _like(text)
	# One more than is shown, so the box can say there is more without a count.
	rows = frappe.get_list(
		source["doctype"],
		fields=["name", *shown],
		or_filters=[[field, "like", pattern] for field in match],
		order_by="modified desc",
		limit_page_length=limit + 1,
	)
	results = []
	for row in rows[:limit]:
		status = row.get(source["status"]) or ""
		if source["key"] == "forums" and row.get("is_active") == 0:
			status = "Disbanded"
		detail = [row.name]
		for field in source["extra"]:
			value = row.get(field)
			if value and field != "is_active":
				detail.append(_("{0} severity").format(value) if field == "severity" else str(value))
		results.append({
			"name": row.name,
			"title": row.get(source["title"]) or row.name,
			"detail": " · ".join(detail),
			"status": status,
			"tone": tone_of(status),
			"url": source["url"].format(frappe.utils.quote(row.name, safe="")),
		})
	return {
		"key": source["key"],
		"label": _(source["label"]),
		"icon": source["icon"],
		"results": results,
		"more": len(rows) > limit,
		"see_all": source["see_all"].format(frappe.utils.quote(text, safe="")),
	}


@frappe.whitelist(methods=["GET"])
def global_search(q: str | None = None, limit: int | str | None = None) -> dict:
	"""The top matches per record type for the header search box.

	Returns ``{"query": ..., "groups": [...]}``; each group has ``key``,
	``label``, ``results`` (``name``, ``title``, ``detail``, ``status``,
	``tone``, ``url``), ``more`` and ``see_all``. A type with no match is left
	out; a query shorter than two characters returns no groups.
	"""
	if frappe.session.user == "Guest":
		# The framework already refuses a visitor on a method that does not
		# allow guests; said again here so the rule survives a hook change.
		frappe.throw(_("Sign in to search."), frappe.PermissionError)
	text = " ".join((q or "").split())[:MAX_LENGTH]
	try:
		size = int(limit or DEFAULT_LIMIT)
	except (TypeError, ValueError):
		size = DEFAULT_LIMIT
	size = max(1, min(size, MAX_LIMIT))
	groups = []
	if len(text) >= MIN_LENGTH:
		for source in SOURCES:
			if not frappe.has_permission(source["doctype"], "read"):
				continue
			group = _search_one(source, text, size)
			if group and group["results"]:
				groups.append(group)
	return {"query": text, "groups": groups}
