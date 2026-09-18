"""``/doc-ai?name=<Governing Document>&version=<Document Version>``: the Doc AI hand-off.

Every "Open in Doc AI" button links here rather than to the tool, so the
tool's address is never in a page and every hand-off passes the same checks:
the person may read the document (and the version, under its handling rules),
holds a role the settings require if any are listed, and the version belongs
to the document. Then the hand-off is written to the Access Log and the browser
is sent on with a 302 (``external_tools.doc_ai_handoff``).

When Doc AI is not connected, or switched off, or the reference is wrong, the
page says so in plain words instead. The buttons normally show the "not
connected" explanation themselves; this page is what a person sees without
script, or with a link someone pasted.
"""

import frappe
from consilium.consilium_core.integrations import external_tools

no_cache = 1


def get_context(context):
	# The portal shell escapes the title, description and breadcrumb labels it
	# prints, so values from the address and the record are passed as they are.
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user
	if frappe.session.user == "Guest":
		# The portal's sign-in card (base_portal.html), which brings the
		# visitor back here with the document reference, rather than a bare
		# refusal. Nothing about the reference is looked at first.
		context.page_title = "Open in Doc AI"
		return context

	name = (frappe.form_dict.get("name") or "").strip()
	version = (frappe.form_dict.get("version") or "").strip() or None
	tools = external_tools.cns_external_tools()
	context.tool = tools["doc_ai"]
	context.is_admin = tools["admin"]
	context.record_name = name
	context.outcome = None
	context.page_title = "Doc AI"
	context.page_description = "Hand a governing document over to the document editor."
	crumbs = [{"label": "Home", "url": "/"}, {"label": "Policy library", "url": "/policies"}]

	if not name:
		context.outcome = "no_document"
		context.breadcrumbs = crumbs + [{"label": "Doc AI"}]
		return context
	try:
		result = external_tools.doc_ai_handoff(name, version)
	except frappe.DoesNotExistError:
		frappe.clear_messages()
		context.outcome = "not_found"
		context.breadcrumbs = crumbs + [{"label": name}]
		return context

	if result["url"]:
		frappe.flags.redirect_location = result["url"]
		raise frappe.Redirect(302)

	context.outcome = result["state"]
	context.document_title = result["title"] or name
	context.breadcrumbs = crumbs + [
		{"label": result["title"] or name, "url": "/policy?name=" + frappe.utils.quote(name)},
		{"label": "Doc AI"},
	]
	return context
