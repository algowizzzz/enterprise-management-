"""Context for the guided formation request.

The screen creates a ``Committee Formation Request``. It does not create a
forum: an approved request is what does that, and the page says so before the
first field. The select options come from the DocType itself so that the form
cannot offer a value the record would refuse.
"""

import frappe

from consilium.governance import formation

no_cache = 1


def _options(doctype: str, fieldname: str) -> list[str]:
	field = frappe.get_meta(doctype).get_field(fieldname)
	if not field or not field.options:
		return []
	return [option for option in field.options.split("\n") if option]


def get_context(context):
	context.no_cache = 1
	context.page_title = "Request a new forum"
	context.page_description = (
		"A guided request. Nothing is created until it has been evaluated and approved."
	)
	context.active_nav = "governance"
	context.user_display = frappe.session.user
	context.breadcrumbs = [
		{"label": "Home", "url": "/"},
		{"label": "Forum inventory", "url": "/forums"},
		{"label": "Request a new forum"},
	]
	context.can_request = frappe.has_permission("Committee Formation Request", "create")
	context.request_types = _options("Committee Formation Request", "request_type")
	context.cadence_options = _options("Committee Formation Request", "cadence")
	# G-8: a change states how material it is, which chooses its approval path.
	context.materiality_options = _options("Committee Formation Request", "change_materiality")
	context.existing = (frappe.form_dict.get("request") or "").strip()
	context.request_status = _request_status(context.existing)
	# The originator of a returned request answers it whatever roles they hold
	# (formation.may_take lets them; the request is shared with them). Someone
	# who may not raise requests was shown "You cannot raise a formation
	# request" instead of the questions; they now get the questions and a box
	# for the answer. The request form itself stays with those who may raise
	# one: its lists are read with the viewer's permissions, and saving a form
	# whose lists came back empty would blank the request's fields.
	context.can_answer = bool(context.request_status and context.request_status.get("can_respond"))
	context.answer_only = context.can_answer and not context.can_request
	return context


def _request_status(name: str) -> dict | None:
	"""Where an existing request stands, and what its originator may do with it.

	Settled on the server, from the request's flags and the formation module's
	own stage rules, so the page never has to read a state label to know that a
	request is back with its originator and waiting for answers. ``can_respond``
	is exactly the check the respond endpoint makes on the way in.
	"""
	if not name or not frappe.db.exists("Committee Formation Request", name):
		return None
	if not frappe.has_permission("Committee Formation Request", "read", doc=name):
		return None
	doc = frappe.get_doc("Committee Formation Request", name)
	actions = formation.stage_actions(doc)
	return {
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"stage": formation.stage_of(doc),
		"is_editable": bool(doc.is_editable),
		"can_submit": "submit" in actions and frappe.has_permission(doc.doctype, "write", doc=doc),
		"can_respond": "respond" in actions and formation.may_take(doc, "respond"),
		"return_questions": doc.return_questions,
		"returned_on": str(doc.returned_on) if doc.returned_on else None,
		"returned_by": doc.returned_by,
		"originator_response": doc.originator_response,
		"created_forum": doc.created_forum,
	}
