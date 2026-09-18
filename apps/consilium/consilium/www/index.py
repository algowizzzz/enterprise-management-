"""Context for the home page.

The guidance on this page is data, not copy baked into a release: it is held in
``Guide Article`` and edited by an administrator. The page ships built-in text
for every section so that a site with an empty guide still explains itself, and
so that the page still reads correctly before any script runs.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Home"
	context.page_description = (
		"How the governance record works, and where the inventory stands today."
	)
	context.active_nav = "home"
	context.user_display = frappe.session.user
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	context.is_administrator = "System Manager" in frappe.get_roles() or (
		"Consilium Administrator" in frappe.get_roles()
	)
	return context
