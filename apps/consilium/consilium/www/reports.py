"""Context for the management reporting page.

Every figure on the page is counted in the browser, over the REST API and the
modules' own whitelisted analysis endpoints, so each number is a count of the
records the viewer may read — the sensitive-escalation restriction included. A
report that counted on the server with its own query would show one person a
total that the inventory behind it then refused to list.

The coverage-gap matrix (risk category by owning group, O-3) is counted the
same way, in the browser over the REST list, so each cell's number is exactly
what the inventory it links to will list for this viewer.

This module supplies only what does not change per request and cannot be
asked for cheaply later: the readable labels of the document fields the
metadata check reports by fieldname, and whether the workspace is open to the
viewer (the time-limit clocks are listed there, not on the portal).
"""

import frappe

no_cache = 1


def _field_labels(doctype: str) -> dict[str, str]:
	"""Fieldname to label, so "missing: document_owner" reads as a sentence."""
	return {df.fieldname: df.label for df in frappe.get_meta(doctype).fields if df.label}


def get_context(context):
	context.no_cache = 1
	context.page_title = "Management reporting"
	context.page_description = (
		"Where forums, governing documents and escalations stand today. Every number "
		"opens the records behind it."
	)
	context.active_nav = "reports"
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Management reporting"},
	]
	context.user_display = frappe.session.user
	context.document_field_labels = _field_labels("Governing Document")
	context.desk_access = frappe.session.user != "Guest" and (
		frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"
	)
	return context
