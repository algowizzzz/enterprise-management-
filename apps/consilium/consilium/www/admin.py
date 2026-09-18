"""Context for the administration area.

Restricted here, on the server, and restricted again by the framework on every
screen this page links to. The page itself rebuilds nothing the framework
already does well — it is a way in, plus the two facts an administrator wants
before going anywhere: what is configured, and what is missing.
"""

import frappe

no_cache = 1

#: The roles this area is for. Membership of either is enough.
ADMIN_ROLES = ("System Manager", "Consilium Administrator")


def get_context(context):
	context.no_cache = 1
	roles = set(frappe.get_roles())
	if not roles.intersection(ADMIN_ROLES):
		frappe.throw(
			"This area is for administrators. Ask the governance office if you need access to it.",
			frappe.PermissionError,
			title="Administration",
		)

	context.page_title = "Administration"
	context.page_description = (
		"Users, roles and the reference data the rest of the portal reads from."
	)
	context.active_nav = "admin"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Administration"},
	]
	context.is_system_manager = "System Manager" in roles
	# The guide's administrators' chapter, read in the platform (/guide).
	from consilium.consilium_core import guide

	context.admin_guide_url = guide.admin_guide_url()
	return context
