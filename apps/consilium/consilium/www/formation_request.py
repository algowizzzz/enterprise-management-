"""Context for one formation request, as the governance office works it.

The record, its findings, its approval steps and the actions open to the viewer
all come from one server method, ``formation.get_request_review``, rather than
from the REST interface. Two reasons: the approval steps live on Core records
that most governance roles cannot read directly, and which actions are open is
a decision the server must make — the page is told, and each action is checked
again on the way in.

What is settled here is only whether the viewer may open the page at all: anyone
who may read the request, and anyone asked to decide one of its steps (a sponsor
or delegating authority often holds no governance role).
"""

import frappe

from consilium.governance import formation

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "requests"
	context.user_display = frappe.session.user

	name = (frappe.form_dict.get("name") or "").strip()
	context.request_name = name
	context.found = False
	context.allowed = False
	context.can_read_queue = frappe.has_permission("Committee Formation Request", "read")

	crumbs = [{"label": "Home", "url": "/"}, {"label": "Forum inventory", "url": "/forums"}]
	if context.can_read_queue:
		crumbs.append({"label": "Formation requests", "url": "/formation-requests"})

	if name and frappe.db.exists("Committee Formation Request", name):
		doc = frappe.get_doc("Committee Formation Request", name)
		context.found = True
		context.allowed = bool(
			frappe.has_permission(doc.doctype, "read", doc=doc) or formation.decidable_steps(doc)
		)
		if context.allowed:
			context.page_title = doc.forum_name or name
			context.page_description = "Formation request {0} — {1}".format(name, doc.request_type or "")
			context.breadcrumbs = [*crumbs, {"label": name}]
			return context

	context.page_title = "Formation request"
	context.page_description = (
		"No request was named in the address." if not name else "Reference {0}".format(name)
	)
	context.breadcrumbs = [*crumbs, {"label": name or "Formation request"}]
	return context
