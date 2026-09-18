"""Context for a single forum's page.

The record itself is read in the browser over the REST API. Two things are
settled here instead, because they are decisions the server must make: whether
the viewer may see this forum at all, and whether they may change it. The page
offers an edit route only when the second is true, and the framework enforces
it again on the way in.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "forums"
	context.user_display = frappe.session.user

	name = (frappe.form_dict.get("name") or "").strip()
	context.forum = name
	context.found = False
	context.can_edit = False
	context.can_review = False

	if not name:
		context.page_title = "Forum"
		context.page_description = "No forum was named in the address."
		context.breadcrumbs = [
			{"label": "Home", "url": "/"},
			{"label": "Forum inventory", "url": "/forums"},
			{"label": "Forum"},
		]
		return context

	# Raises for a viewer without read access, rather than rendering a shell
	# the page then cannot fill.
	frappe.has_permission("Governance Forum", "read", doc=name, throw=True)

	title = frappe.db.get_value("Governance Forum", name, "forum_name")
	context.found = bool(title)
	context.page_title = title or name
	context.page_description = "Reference {0}".format(name)
	context.can_edit = frappe.has_permission("Governance Forum", "write", doc=name)
	context.can_review = frappe.has_permission("Forum Compliance Review", "create")
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Forum inventory", "url": "/forums"},
		{"label": title or name},
	]
	return context
