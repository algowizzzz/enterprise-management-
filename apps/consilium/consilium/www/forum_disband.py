"""Context for a forum's disbandment (E8-S5, G-11).

A forum leaves service through a plan: a trigger, a successor, what happens to
its records, and the approvals G-11 names — delegating authority, sponsor, chair
and, where applicable, the jurisdictional chief risk officer. Each approval is a
Core ``Approval Decision``, so a delegate may decide it and the decision carries
who acted and under which delegation. When nothing is outstanding and nothing
was refused, the governance office executes the plan and the forum becomes
inactive; it is never deleted.

The plan and its approvals are read and changed through
``consilium.governance.lifecycle`` (``get_disbandment`` and the entry points
beside it), which check permission and role again on every call. This module
settles only whether the page is open to the viewer at all: to anyone who may
read the forum and its plans, and to anyone asked to decide one of its
approvals — a sponsor often holds no governance role.
"""

from urllib.parse import quote

import frappe

from consilium.governance import lifecycle

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.active_nav = "governance"
	context.user_display = frappe.session.user

	name = (frappe.form_dict.get("forum") or frappe.form_dict.get("name") or "").strip()
	context.forum = name
	title = frappe.db.get_value("Governance Forum", name, "forum_name") if name else None
	context.found = bool(title)
	context.allowed = bool(title) and lifecycle.may_view_disbandment(name)
	context.can_open_forum = bool(title) and frappe.has_permission("Governance Forum", "read", doc=name)

	crumbs = [{"label": "Home", "url": "/"}, {"label": "Forum inventory", "url": "/forums"}]
	if context.allowed and context.can_open_forum:
		crumbs.append({"label": title, "url": "/forum?name={0}".format(quote(name))})
	context.page_title = "Disbandment"
	context.page_description = (
		"{0} — reference {1}".format(title, name) if context.allowed
		else ("No forum was named in the address." if not name else "Reference {0}".format(name))
	)
	context.breadcrumbs = [*crumbs, {"label": "Disbandment"}]
	return context
