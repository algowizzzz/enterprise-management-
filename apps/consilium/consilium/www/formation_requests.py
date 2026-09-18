"""Context for the governance office's formation queue.

Formation requests used to stop at submission: nothing on the portal could
evaluate, return, approve or reject one, so no forum could be created by the
route the process intends. This is the office's way in. The list itself is read
over the REST interface, so the server applies permissions on every request;
this module supplies only the shell, the select options the DocType declares,
and whether the viewer may record compliance reviews (which decides whether the
second list, of forums awaiting review, links to the review screen).
"""

import frappe

from consilium.governance import formation, lifecycle

no_cache = 1


def _options(doctype: str, fieldname: str) -> list[str]:
	"""The option list the DocType itself declares, so the filters cannot drift."""
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.page_title = "Formation requests"
	context.page_description = (
		"Requests to create, change or retire a forum, and where each one stands. "
		"Open a request to evaluate it, put questions to its originator or decide it."
	)
	context.active_nav = "governance"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Forum inventory", "url": "/forums"},
		{"label": "Formation requests"},
	]
	context.can_read = frappe.has_permission("Committee Formation Request", "read")
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	roles = set(frappe.get_roles())
	context.is_office = bool(
		roles & {formation.GOVERNANCE_OFFICE, formation.DESIGNATED_AUTHORITY, *formation.SUPERUSER_ROLES}
	)
	context.can_review_forums = lifecycle.may_record_review()
	context.can_read_forums = frappe.has_permission("Governance Forum", "read")
	context.state_options = _options("Committee Formation Request", "workflow_state")
	context.request_types = _options("Committee Formation Request", "request_type")
	return context
