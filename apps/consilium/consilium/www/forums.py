"""Context for the forum inventory screen.

The screen itself reads every record through the REST API so that permissions
are applied by the server on each request. This module supplies only what the
shell needs and the two facts the page cannot ask for later without a round
trip: whether the viewer may raise a formation request, and the select options
the framework already holds for the record's own fields.
"""

import frappe

no_cache = 1


def _select_options(fieldname: str) -> list[str]:
	"""The option list the DocType itself declares, so the filters cannot drift."""
	field = frappe.get_meta("Governance Forum").get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.page_title = "Forum inventory"
	context.page_description = (
		"Every governance forum on record, with the attributes the inventory is "
		"accountable for. Open a forum to see its membership, linkages and decisions."
	)
	context.active_nav = "governance"
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Forum inventory"},
	]
	context.user_display = frappe.session.user
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	context.status_options = _select_options("compliance_status")
	context.cadence_options = _select_options("cadence")
	return context
