"""Context for the personal inbox (CS-10).

The list itself is read in the browser from `consilium_core.inbox.my_tasks`,
which applies the rules about who sees what: the server decides what is waiting
on the caller, and the page only draws it. This module supplies the shell and
one fact the page cannot ask cheaply — whether the viewer may run attestation
campaigns, which decides whether the page points them at the campaign screen.
"""

import frappe

from consilium.governance import reviews

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Inbox"
	context.page_description = (
		"Everything waiting on you, across forums, policies and escalations. "
		"Attestations are answered here; everything else opens on its own screen."
	)
	context.active_nav = "inbox"
	context.user_display = frappe.session.user
	context.breadcrumbs = [{"label": "Home", "url": "/"}, {"label": "Inbox"}]
	signed_in = frappe.session.user != "Guest"
	context.may_run_campaigns = signed_in and (
		reviews.may_run_forum_campaigns() or frappe.has_permission("Attestation Campaign", "read")
	)
	return context
