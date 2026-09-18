"""Context for Admin → Integrations (``/integrations``).

One card per connection to a service outside the platform — the AI endpoint,
Doc AI, horizon scanning and email — each with its status, its settings, a
plain statement of what leaves the platform, and a Save button. Administrators
only: anyone else is refused, and the refusal is audited.

The cards are drawn here from ``consilium_core.integrations.admin``, the same
functions the page's script calls after a save, so the first paint and every
redraw read one source. Secrets are never in the context: only whether one is
saved.
"""

import frappe

from consilium.consilium_core.integrations import admin

no_cache = 1

STATUS = {
	"connected": ("Connected", "success"),
	"not_connected": ("Not connected", "warning"),
	"off": ("Off", "neutral"),
}


def get_context(context):
	context.no_cache = 1
	if frappe.session.user == "Guest":
		# The portal's sign-in card (base_portal.html), which brings the
		# visitor back here; nothing about the settings is read or shown.
		context.page_title = "Integrations"
		context.active_nav = "admin"
		return context
	admin.require_admin(admin.TOOLS)

	context.page_title = "Integrations"
	context.page_description = (
		"Connect the portal to services your organisation runs. Each card says what it is for, "
		"what leaves the platform when it is on, and whether it is working."
	)
	context.active_nav = "admin"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Administration", "url": "/admin"},
		{"label": "Integrations"},
	]
	context.cards = admin.state()
	context.status_text = STATUS
	context.is_system_manager = "System Manager" in frappe.get_roles()
	return context
