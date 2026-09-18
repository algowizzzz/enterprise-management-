"""Context for the voting screen: one motion put to a forum, or a new one.

``/forum-motion?name=<motion>`` shows a motion, its entitled voters and their
ballots, lets each entitled member cast their own ballot, and lets the forum's
secretary record the outcome. ``/forum-motion?forum=<forum>`` is where the
secretary puts a new motion to the forum.

The motion and everything the viewer may do with it come from
``voting.get_motion``, and every action goes through the entry points beside
it, which check the caller's standing again. This module settles only whether
the page is open at all: to anyone who may read the motion, and to anyone
entitled to vote on it — a member often holds no governance role.
"""

from urllib.parse import quote

import frappe

from consilium.governance import voting

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "governance"
	context.user_display = frappe.session.user

	name = (frappe.form_dict.get("name") or "").strip()
	forum = (frappe.form_dict.get("forum") or "").strip()
	context.motion = None
	context.forum = None
	context.found = False
	context.allowed = False
	context.may_propose = False
	context.meetings = []

	if name and frappe.db.exists("Forum Motion", name):
		doc = frappe.get_doc("Forum Motion", name)
		context.motion = name
		context.forum = doc.forum
		context.found = True
		context.allowed = voting._may_read_motion(doc, frappe.session.user)
		title = doc.motion_reference or name
	elif forum and not name:
		context.forum = forum
		context.found = bool(frappe.db.exists("Governance Forum", forum))
		context.allowed = context.found and frappe.has_permission("Governance Forum", "read", doc=forum)
		context.may_propose = bool(
			context.allowed
			and voting.may_administer(forum)
			and frappe.db.get_value("Governance Forum", forum, "is_active")
		)
		if context.may_propose:
			context.meetings = frappe.get_all(
				"Forum Meeting", filters={"forum": forum},
				fields=["name", "meeting_reference", "scheduled_on"], order_by="scheduled_on desc", limit=50,
			)
		title = "Put a motion"
	else:
		title = "Motion"

	forum_name = frappe.db.get_value("Governance Forum", context.forum, "forum_name") if context.forum else None
	crumbs = [{"label": "Home", "url": "/"}, {"label": "Forum inventory", "url": "/forums"}]
	if context.allowed and forum_name and frappe.has_permission("Governance Forum", "read", doc=context.forum):
		crumbs.append({"label": forum_name, "url": "/forum?name={0}#decisions".format(quote(context.forum))})
	context.forum_name = forum_name
	context.page_title = title if context.allowed else "Motion"
	context.page_description = (
		"{0} — a motion put to {1}".format(name, forum_name) if context.allowed and context.motion
		else ("Record a motion and who may vote on it." if context.allowed else "")
	)
	context.breadcrumbs = [*crumbs, {"label": title if context.allowed else "Motion"}]
	return context
