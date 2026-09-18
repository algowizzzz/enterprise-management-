"""Context for the guided formation request.

The screen creates a ``Committee Formation Request``. It does not create a
forum: an approved request is what does that, and the page says so before the
first field. The select options come from the DocType itself so that the form
cannot offer a value the record would refuse.
"""

import frappe

no_cache = 1


def _options(doctype: str, fieldname: str) -> list[str]:
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.page_title = "Request a new forum"
	context.page_description = (
		"A guided request. Nothing is created until it has been evaluated and approved."
	)
	context.active_nav = "forums"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Forum inventory", "url": "/forums"},
		{"label": "Request a new forum"},
	]
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	context.request_types = _options("Committee Formation Request", "request_type")
	context.cadence_options = _options("Committee Formation Request", "cadence")
	context.existing = (frappe.form_dict.get("request") or "").strip()
	return context
