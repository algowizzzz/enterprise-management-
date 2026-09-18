"""Context for running attestation campaigns from the portal.

Opening a campaign and generating its tasks had no caller outside the tests
and the demonstration loader. This screen is that caller, for two audiences
with different standing:

* an administrator of campaigns (the right to write the campaign record) sees
  and generates every campaign, through Core's endpoints;
* the governance office sees, opens and generates the forum campaigns only,
  through the governance module's endpoints, because that is where the
  office's standing over forum campaigns is granted.

The server checks both again on every call; this only chooses what to draw.
"""

import frappe

from consilium.consilium_core import attestation
from consilium.governance import reviews

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.page_title = "Attestation campaigns"
	context.page_description = (
		"Open the annual forum attestations, generate each campaign's tasks, and chase "
		"the records a campaign could not ask about."
	)
	context.active_nav = "policies"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Attestation campaigns"},
	]
	signed_in = frappe.session.user != "Guest"
	administers = signed_in and attestation.may_administer_campaigns()
	reads_all = signed_in and bool(frappe.has_permission("Attestation Campaign", "read"))
	runs_forums = signed_in and reviews.may_run_forum_campaigns()
	# Which endpoints the page reads and acts through. "all" is Core's view of
	# every campaign; "forums" is the governance module's view of its own.
	if reads_all:
		context.scope = "all"
	elif runs_forums:
		context.scope = "forums"
	else:
		context.scope = ""
	context.may_generate_all = administers
	context.may_open_forum = runs_forums
	context.default_period = frappe.utils.getdate().year
	context.today = frappe.utils.nowdate()
	context.default_due = frappe.utils.add_days(frappe.utils.nowdate(), 45)
	# G-10: the inventory attestation is due in a first quarter. The form
	# offers the next quarter's deadline for it, and the page says which years
	# had no first-quarter attestation and which campaigns ran off-cycle.
	next_due = reviews.next_first_quarter_due()
	context.inventory_default_due = str(next_due)
	context.inventory_default_period = next_due.year
	context.inventory_q1 = reviews.inventory_q1_standing() if context.scope else None
	if context.inventory_q1:
		standing = context.inventory_q1
		standing["next_due_label"] = frappe.utils.formatdate(standing["next_due_on"])
		for row in standing["off_cycle"]:
			row["due_label"] = frappe.utils.formatdate(row["due_on"])
	return context
