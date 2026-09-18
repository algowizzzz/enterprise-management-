"""Context for the standalone policy-change impact page (O-6).

The Impact panel is a self-contained include
(``templates/includes/ai_impact_panel.html``) meant for the policy page. This
page hosts the same include on its own, at ``/policy-impact?name=GDOC-…``, so
the assessment can be linked to directly. The document is named in the
address; whether the viewer may read it is decided by the permission engine
(the handling hook included), both here and again in the panel's endpoint.
"""

import frappe

no_cache = 1

DOCTYPE = "Governing Document"


def get_context(context):
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user
	name = (frappe.form_dict.get("name") or "").strip()
	crumbs = [{"label": "Home", "url": "/"}, {"label": "Policies", "url": "/policies"}]
	context.record_name = None
	context.page_title = "Impact of a change"
	title = None
	if name and frappe.session.user != "Guest" and frappe.db.exists(DOCTYPE, name) \
			and frappe.has_permission(DOCTYPE, "read", doc=frappe.get_doc(DOCTYPE, name)):
		context.record_name = name
		title = frappe.db.get_value(DOCTYPE, name, "document_name")
	# The same words for a missing document and one the viewer may not read.
	context.page_description = (
		"What a change to {0} would reach.".format(title) if title
		else "Name a governing document you may read, from its own page."
	)
	context.breadcrumbs = crumbs + ([{"label": title or name, "url": "/policy?name=" + frappe.utils.quote(name, safe="")},
	                                 {"label": "Impact"}] if title else [{"label": "Impact"}])
	return context
