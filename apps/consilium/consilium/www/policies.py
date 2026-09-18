"""Context for the governing document inventory.

The same shape as the forum inventory, for the same reason: every record on the
screen is read in the browser over the REST API, so the permission engine
decides on each request what the viewer may see. This module supplies only what
the shell needs before any request is made — the select options the DocType
already declares, so the filters cannot drift from the schema, and whether the
viewer may start a new document at all.
"""

import frappe

no_cache = 1

DOCTYPE = "Governing Document"


def _select_options(fieldname: str) -> list[str]:
	"""The option list the DocType itself declares, so the filters cannot drift."""
	field = frappe.get_meta(DOCTYPE).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def _has_desk_access() -> bool:
	"""Whether the workspace behind the portal is open to this viewer at all.

	A website user can hold no DocType permission that would make the desk
	useful, so offering them a link into it only produces a refusal page.
	"""
	if frappe.session.user == "Guest":
		return False
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def get_context(context):
	context.no_cache = 1
	context.page_title = "Policy inventory"
	context.page_description = (
		"Every governing document on record — policies, standards, procedures and the "
		"rest — with where each stands in its lifecycle and when it is next reviewed."
	)
	context.active_nav = "policies"
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Policy inventory"},
	]
	context.user_display = frappe.session.user
	context.can_create = _has_desk_access() and bool(frappe.has_permission(DOCTYPE, "create"))
	context.phase_options = _select_options("lifecycle_phase")
	context.handling_options = _select_options("handling_classification")
	return context
