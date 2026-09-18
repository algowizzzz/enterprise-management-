"""Context for the interface reference page.

The page is a visual reference and a manual test surface for the shared
front-end foundation. It carries no real records of its own: the live table
reads the framework's built-in ``User`` DocType, and every other example uses
neutral placeholder content.
"""

import frappe

no_cache = 1


def get_context(context):
	# A developer's reference for the shared components, not a business screen:
	# administrators only.
	if not ({"System Manager", "Consilium Administrator"} & set(frappe.get_roles())):
		raise frappe.PermissionError
	context.no_cache = 1
	context.page_title = "Interface reference"
	context.page_description = (
		"Every shared component, in both themes and at every text size. "
		"Use this page to check a change before it reaches a screen."
	)
	context.active_nav = "admin"
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Interface reference"},
	]
	context.user_display = frappe.session.user
	# Font-size steps are defined once in consilium.js; mirrored here only to
	# label the typography specimen rows.
	context.font_steps = [
		{"id": "xs", "label": "Extra small"},
		{"id": "sm", "label": "Small"},
		{"id": "md", "label": "Default"},
		{"id": "lg", "label": "Large"},
		{"id": "xl", "label": "Extra large"},
		{"id": "xxl", "label": "Largest"},
	]
	return context
