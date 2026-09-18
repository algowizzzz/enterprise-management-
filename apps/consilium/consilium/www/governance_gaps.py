"""Context for the governance gaps and risk assessment page (O-6, O-7).

The page is a shell: every gap and every score is read in the browser from
``consilium_core.ai.gaps.detect`` and ``consilium_core.ai.scoring.assess``,
which read through the permitted query, so the page shows only what the
viewer may read. Both work with no network; the AI commentary under each is
optional and asked for on demand.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Governance gaps and risk"
	context.page_description = (
		"Where governance coverage is missing or incomplete, and a rules-based risk score for every forum and "
		"policy — worked out from the records as they stand now."
	)
	context.active_nav = "reports"
	context.user_display = frappe.session.user
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Reports", "url": "/reports"},
	                       {"label": "Governance gaps and risk"}]
	return context
