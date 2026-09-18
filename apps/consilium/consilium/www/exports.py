"""Context for the governed export screen (G-19, P-20, E-19).

Lists the export profiles the viewer may run and the files already exported,
and runs a profile on request. Everything is read and done through
``consilium_core.exporting``, which checks the profile's roles and the
viewer's read access again on every call; this module only draws the shell.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Exports"
	context.page_description = (
		"Governed files of forums, governing documents and escalations for other systems. Each export is "
		"logged with who ran it, what it held and its fingerprint; restricted records are left out unless "
		"the profile allows them and you may read them."
	)
	context.active_nav = "insights"
	context.user_display = frappe.session.user
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Insights", "url": "/reports"},
		{"label": "Exports"}]
	context.signed_in = frappe.session.user != "Guest"
	context.may_configure = context.signed_in and bool(frappe.has_permission("Export Profile", "create"))
	return context
