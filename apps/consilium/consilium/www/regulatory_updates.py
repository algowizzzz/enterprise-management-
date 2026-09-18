"""Context for the regulatory updates page (O-7).

Without ``?requirement=`` it lists the regulatory requirements, most recently
changed first; with it, one requirement: what changed, who cites it, which
documents and sections a rule-based match finds, and — when AI is on — the
machine-generated summary and suggestions, each waiting for a person to accept
or reject it. Everything is read in the browser from
``consilium_core.ai.regulatory``, through permission-checked endpoints.
"""

import frappe

no_cache = 1


def get_context(context):
	context.no_cache = 1
	requirement = (frappe.form_dict.get("requirement") or "").strip()
	context.requirement = requirement
	context.page_title = "Regulatory updates"
	context.page_description = (
		"Record a change to a regulatory requirement, see everything that cites it, and work through what it touches."
	)
	context.active_nav = "reports"
	context.user_display = frappe.session.user
	crumbs = [{"label": "Home", "url": "/"}, {"label": "Reports", "url": "/reports"},
		{"label": "Regulatory updates", "url": "/regulatory-updates"}]
	context.breadcrumbs = crumbs + [{"label": requirement}] if requirement else crumbs[:2] + [{"label": "Regulatory updates"}]
	signed_in = frappe.session.user != "Guest"
	context.may_set_up_import = signed_in and bool(frappe.has_permission("Import Profile", "create"))
	return context
