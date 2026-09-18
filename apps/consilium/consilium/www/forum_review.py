"""Context for recording a forum's compliance review.

A forum's standing moves only when a ``Forum Compliance Review`` is recorded,
and until now nothing on the portal could record one: a forum created by an
approved request sat "awaiting review" with no way forward. This page is that
way forward. The forum and its review history are read over the REST interface;
the review itself goes through ``lifecycle.record_compliance_review``, which
checks the reviewer's role and the forum's standing again on the way in.

Two things are settled here because the server must decide them: whether the
viewer may record a review at all, and which decisions exist and what each one
does — read from the review's own select options, the outcome map and the
decision's ``requires_statement`` flag, so the form cannot drift from the rules.
"""

from urllib.parse import quote

import frappe

from consilium.governance import lifecycle

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "forums"
	context.user_display = frappe.session.user

	name = (frappe.form_dict.get("forum") or frappe.form_dict.get("name") or "").strip()
	context.forum = name
	context.found = False
	context.allowed = False
	context.can_record = False
	context.can_read_queue = frappe.has_permission("Committee Formation Request", "read")
	context.decisions = lifecycle.review_decisions()
	context.review_types = list(lifecycle.PORTAL_REVIEW_TYPES)

	title = frappe.db.get_value("Governance Forum", name, "forum_name") if name else None
	context.found = bool(title)
	context.allowed = bool(title) and frappe.has_permission("Governance Forum", "read", doc=name)
	context.can_record = (
		context.allowed
		and lifecycle.may_record_review()
		and frappe.has_permission("Forum Compliance Review", "create")
	)

	crumbs = [{"label": "Home", "url": "/"}, {"label": "Forum inventory", "url": "/forums"}]
	if context.allowed:
		crumbs.append({"label": title, "url": "/forum?name={0}".format(quote(name))})
		context.page_title = "Compliance review"
		context.page_description = "{0} — reference {1}".format(title, name)
	else:
		context.page_title = "Compliance review"
		context.page_description = "No forum was named in the address." if not name else "Reference {0}".format(name)
	context.breadcrumbs = [*crumbs, {"label": "Compliance review"}]
	return context
