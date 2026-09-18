"""Context for the guided escalation intake.

The screen raises an ``Escalation Matter``. Everything it offers — the types,
the risk taxonomy, the people, the forums — is read in the browser from
``consilium.escalation.templates.intake_options``, which reads the configuration
with the caller's own permissions; the matter is created by
``templates.raise_escalation``, which inserts it with those permissions too, so
the matrix, the pathway rules and the escalation template for the type and
severity are applied exactly as they are on the desk.

What is settled here is only whether the viewer may raise a matter at all.
"""

import frappe

no_cache = 1

DOCTYPE = "Escalation Matter"


def get_context(context):
	context.no_cache = 1
	context.page_title = "Raise an escalation"
	context.page_description = (
		"A guided form. The escalation matrix proposes the severity and the forums; the template for the "
		"escalation type says what else is needed."
	)
	context.active_nav = "escalations"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Escalation register", "url": "/escalations"},
		{"label": "Raise an escalation"},
	]

	if frappe.session.user == "Guest":
		frappe.throw("Sign in to raise an escalation.", frappe.PermissionError)

	context.can_raise = bool(frappe.has_permission(DOCTYPE, "create"))
	return context
