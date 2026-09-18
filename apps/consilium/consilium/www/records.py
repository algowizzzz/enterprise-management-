"""Context for the records manager's retention and disposal screen (G-16, P-18, E-18).

The screen lists every record whose retention period has run out, the
decisions taken on them and the legal holds in force, and carries out the two
person disposal decision. Everything is read and done through
``consilium_core.records``, which checks the records manager's role again on
every call; this module only decides whether to draw the screen at all.
"""

import frappe

no_cache = 1


def get_context(context):
	from consilium.consilium_core import records

	context.no_cache = 1
	context.page_title = "Records and disposal"
	context.page_description = (
		"Records whose retention period has ended, waiting for a decision to dispose of them or keep them. "
		"Every decision takes two people, a legal hold stops disposal outright, and nothing is ever deleted: "
		"disposal redacts the content and keeps a record of what was done."
	)
	context.active_nav = "insights"
	context.user_display = frappe.session.user
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Insights", "url": "/reports"},
		{"label": "Records and disposal"}]
	context.may_manage = records.may_manage()
	return context
