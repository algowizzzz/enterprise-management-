"""Context for the document intake page (P-16).

Two views on one route. With no request named, the page lists the intake
requests the viewer may read and, for anyone who may raise one, the form that
does. With ``?name=PINT-…`` it is that request: its classification questions,
rendered from the rule set in force, the outcome and the rule that produced it,
the requester's challenge, and — for the policy office — the override and the
creation of the document.

As on the document page, nothing here decides what may be done. The request's
payload (``consilium.policy.intake.request_context``) says which actions the
viewer may take now, and each posts to an entry point that checks again.
"""

import frappe

no_cache = 1

REQUEST_DOCTYPE = "Document Intake Request"
DOCUMENT_DOCTYPE = "Governing Document"


def _select_options(doctype: str, fieldname: str) -> list[str]:
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user

	if frappe.session.user == "Guest":
		frappe.throw("Sign in to raise or follow a document request.", frappe.PermissionError)

	name = (frappe.form_dict.get("name") or "").strip()
	context.request_name = name
	context.found = False
	context.can_raise = bool(frappe.has_permission(REQUEST_DOCTYPE, "create"))
	context.handling_options = _select_options(DOCUMENT_DOCTYPE, "handling_classification")

	crumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Policy inventory", "url": "/policies"},
		{"label": "Document requests", "url": "/policy-intake"},
	]

	if not name:
		context.page_title = "Document requests"
		context.page_description = (
			"Ask for a new governing document, or a change to or retirement of one. A few questions "
			"classify the change as major or minor, which decides its approval route and service level."
		)
		context.breadcrumbs = crumbs[:2] + [{"label": "Document requests"}]
		return context

	context.breadcrumbs = crumbs + [{"label": name}]
	context.page_title = "Document request {0}".format(name)
	if not frappe.db.exists(REQUEST_DOCTYPE, name):
		context.page_description = "Reference {0}".format(name)
		return context

	# Raises for a viewer who may not read the request.
	frappe.has_permission(REQUEST_DOCTYPE, "read", doc=name, throw=True)
	context.found = True
	proposed = frappe.db.get_value(REQUEST_DOCTYPE, name, "proposed_document_name")
	context.page_description = proposed or "Reference {0}".format(name)
	return context
