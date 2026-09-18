"""Context for the emerging-risks page (O-7).

A shell: the trends and leading indicators are read in the browser from
``consilium_core.ai.trends.analyse``, which counts only records the viewer may
read and needs no network. The AI narrative is optional and asked for on demand.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Emerging risks"
	context.page_description = (
		"Month-over-month trends in escalations, violations, adverse monitoring and breaches, the series that are "
		"rising, and the leading indicators that tend to come first."
	)
	context.active_nav = "insights"
	context.user_display = frappe.session.user
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Insights", "url": "/reports"},
	                       {"label": "Emerging risks"}]
	return context
