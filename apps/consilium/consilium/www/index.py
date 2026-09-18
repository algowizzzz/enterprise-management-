"""Context for the home page.

The page is a set of cards (consilium_core/home.py): a greeting and what is
waiting on the viewer, what they can start, one card per area they may open
with its live figures, the records they viewed or pinned, announcements from
the governance office (the published Guide Articles) and the guide's chapters.
Everything is worked out here, on the server, so the figures arrive in the
page and match the pages they link to.
"""

import frappe

from consilium.consilium_core import home

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Home"
	context.page_description = (
		"What is waiting on you, what you can start, and how each area stands today."
	)
	context.active_nav = "home"
	context.user_display = frappe.session.user
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	context.is_administrator = "System Manager" in frappe.get_roles() or (
		"Consilium Administrator" in frappe.get_roles()
	)
	# A visitor who is not signed in sees the banner and the sign-in prompt only
	# (base_portal.html); nothing is worked out for them.
	context.home = home.context(frappe.session.user) if frappe.session.user != "Guest" else None
	return context
