"""``/horizon-scanning``: forwards to the organisation's horizon-scanning platform.

The address lives in External Tools Settings; the "Horizon scanning" buttons
and the header menu link here, so the external address is in one place and
never in a page. Connected: a 302 to it. Not connected or switched off: a page
that says so, with a way to Integrations for an administrator.

Nothing is sent to the platform but the person's browser: no parameters are
added to the saved address.
"""

import frappe

from consilium.consilium_core.integrations import external_tools

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user
	if frappe.session.user == "Guest":
		# The portal's sign-in card (base_portal.html), which brings the
		# visitor back here, rather than a bare refusal.
		context.page_title = "Horizon scanning"
		return context

	target = external_tools.horizon_target()
	if target["url"]:
		frappe.flags.redirect_location = target["url"]
		raise frappe.Redirect(302)

	context.target = target
	context.is_admin = external_tools.is_admin()
	context.page_title = target["label"] or "Horizon scanning"
	context.page_description = "The organisation's horizon scanning platform, for regulatory and emerging-risk watch."
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": target["label"] or "Horizon scanning"}]
	return context
