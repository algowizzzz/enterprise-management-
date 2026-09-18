"""Context for a single escalation matter's page.

A read-only summary; the matter itself is read in the browser over the REST
API. What is settled here is whether the page may say anything at all.

**A matter the viewer may not see and a matter that does not exist look the
same.** A sensitive matter is hidden from anyone without the right to see it
(``consilium/escalation/sensitivity.py``). Answering "forbidden" for one
reference and "not found" for another would tell that person which references
belong to sensitive matters, which is exactly what the restriction exists to
withhold. So both get the same page, and the permission engine — never a
direct read — is what decides.
"""

import frappe

no_cache = 1

DOCTYPE = "Escalation Matter"


def _has_desk_access() -> bool:
	"""A website user cannot use the workspace, so the link would only refuse them."""
	if frappe.session.user == "Guest":
		return False
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def get_context(context):
	context.no_cache = 1
	context.active_nav = "escalations"
	context.user_display = frappe.session.user

	if frappe.session.user == "Guest":
		# Nothing about any matter is shown to a visitor who has not signed in,
		# including whether the reference they typed exists.
		frappe.throw("Sign in to see escalation matters.", frappe.PermissionError)

	name = (frappe.form_dict.get("name") or "").strip()
	context.record_name = name
	context.found = False
	context.can_edit = False
	context.desk_access = False

	crumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Escalation register", "url": "/escalations"},
	]

	if not name:
		context.page_title = "Escalation matter"
		context.page_description = "No matter was named in the address."
		context.breadcrumbs = crumbs + [{"label": "Matter"}]
		return context

	permitted = bool(frappe.db.exists(DOCTYPE, name)) and bool(
		frappe.has_permission(DOCTYPE, "read", doc=name)
	)
	if not permitted:
		context.page_title = "Escalation matter"
		context.page_description = "Reference {0}".format(name)
		context.breadcrumbs = crumbs + [{"label": name}]
		return context

	# Read through the permission-checked list API rather than a direct value
	# read, so the title is fetched by the same path that just granted access.
	rows = frappe.get_list(DOCTYPE, filters={"name": name}, fields=["escalation_title"], limit_page_length=1)
	title = rows[0].escalation_title if rows else None
	context.found = True
	# The change log records fieldnames; the page shows them as the form labels.
	context.field_labels = {df.fieldname: df.label for df in frappe.get_meta(DOCTYPE).fields if df.label}
	context.page_title = title or name
	context.page_description = "Reference {0}".format(name)
	context.desk_access = _has_desk_access()
	context.can_edit = context.desk_access and bool(frappe.has_permission(DOCTYPE, "write", doc=name))
	context.breadcrumbs = crumbs + [{"label": title or name}]
	return context
