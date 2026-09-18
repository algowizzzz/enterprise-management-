"""Context for a single governing document's page.

The record itself is read in the browser over the REST API. What may be *done*
to it is read from ``consilium.policy.lifecycle.document_actions`` and the
panel payloads beside it, and every action posts to a checked entry point that
asks the same questions again on the way in, so the page never decides what is
allowed. The server settles here only what must be known before any request:
whether the viewer may see this document at all, whether the workspace behind
the portal is open to them, and the lifecycle phases in the order the DocType
declares them, so the phase strip follows configuration.

A viewer with no read access who is asked to decide one of the document's
approval steps still sees the page — reduced to its summary and its approval
panel — because an approver who cannot see what they approve cannot approve it.
"""

import frappe

no_cache = 1

DOCTYPE = "Governing Document"


def _has_desk_access() -> bool:
	"""A website user cannot use the workspace, so the link would only refuse them."""
	if frappe.session.user == "Guest":
		return False
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def _phases() -> list[str]:
	field = frappe.get_meta(DOCTYPE).get_field("lifecycle_phase")
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user

	if frappe.session.user == "Guest":
		# Refused before the reference is looked at, so a visitor cannot use the
		# difference between "refused" and "not found" to probe for references.
		frappe.throw("Sign in to see governing documents.", frappe.PermissionError)

	name = (frappe.form_dict.get("name") or "").strip()
	context.record_name = name
	context.found = False
	context.can_edit = False
	context.readable = False
	context.desk_access = False
	context.phases = _phases()

	crumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Policy inventory", "url": "/policies"},
	]

	if not name:
		context.page_title = "Governing document"
		context.page_description = "No document was named in the address."
		context.breadcrumbs = crumbs + [{"label": "Document"}]
		return context

	if not frappe.db.exists(DOCTYPE, name):
		context.page_title = "Governing document"
		context.page_description = "Reference {0}".format(name)
		context.breadcrumbs = crumbs + [{"label": name}]
		return context

	# Raises for a viewer with neither read access nor a part in the approval,
	# rather than rendering a shell the page then cannot fill.
	from consilium.policy import lifecycle

	doc = frappe.get_doc(DOCTYPE, name)
	context.readable = bool(frappe.has_permission(DOCTYPE, "read", doc=doc))
	if not lifecycle.may_view(doc):
		frappe.throw("You do not have access to this governing document.", frappe.PermissionError)

	title = frappe.db.get_value(DOCTYPE, name, "document_name")
	context.found = True
	# The change log records fieldnames; the page shows them as the form labels.
	context.field_labels = {df.fieldname: df.label for df in frappe.get_meta(DOCTYPE).fields if df.label}
	context.page_title = title or name
	context.page_description = "Reference {0}".format(name)
	context.desk_access = _has_desk_access()
	context.can_edit = context.desk_access and bool(frappe.has_permission(DOCTYPE, "write", doc=name))
	# The viewer the document-view page will serve a version to; it builds its
	# own checks, this page only links to it.
	context.viewer_route = "/document-view"
	context.breadcrumbs = crumbs + [{"label": title or name}]
	return context
