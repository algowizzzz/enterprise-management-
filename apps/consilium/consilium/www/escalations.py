"""Context for the escalation register.

Escalations carry a record-level restriction: a sensitive matter is invisible
to anyone without the right to see it, on every read path (see
``consilium/escalation/sensitivity.py``). That restriction lives in the
permission engine, so the only safe way to show this register is the way the
forum inventory already works — every row read in the browser over the REST
API, with the permission hooks applied to each request. Nothing here reads a
matter; this module supplies the shell, the select options the DocType
declares, and whether the viewer may raise a matter at all.
"""

import frappe

no_cache = 1

DOCTYPE = "Escalation Matter"


def _select_options(fieldname: str) -> list[str]:
	"""The option list the DocType itself declares, so the filters cannot drift."""
	field = frappe.get_meta(DOCTYPE).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def _has_desk_access() -> bool:
	"""A website user cannot use the workspace, so the link would only refuse them."""
	if frappe.session.user == "Guest":
		return False
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def get_context(context):
	context.no_cache = 1
	context.page_title = "Escalation register"
	context.page_description = (
		"Matters raised for a decision above the level where they arose — how severe, "
		"how old, where they have gone and whether they are still open."
	)
	context.active_nav = "escalations"
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Escalation register"},
	]
	context.user_display = frappe.session.user
	context.can_raise = _has_desk_access() and bool(frappe.has_permission(DOCTYPE, "create"))
	context.queue_rows = _queue_size()
	context.status_options = _select_options("status")
	context.severity_options = _select_options("severity")
	return context


def _queue_size() -> int:
	"""How many lines the "Waiting on you" panel will hold, or 0 to leave it out.

	The panel is filled by the page script; knowing here whether it will have
	anything lets the page draw it (with placeholder lines) from the start,
	instead of inserting it above the register once the page has painted and
	pushing everything down. The same method the script calls, so the same
	permission rules decide.
	"""
	if frappe.session.user == "Guest":
		return 0
	try:
		from consilium.escalation.resolution import my_escalation_queue

		queue = my_escalation_queue()
	except Exception:
		return 0
	groups = [rows for rows in queue.values() if rows]
	return len(groups) + sum(len(rows) for rows in groups)
