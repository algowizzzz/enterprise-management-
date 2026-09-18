"""Where the asker is and what they may do there — settled on the server.

The widget reports the page it is on: the path, the query string, the title
and whatever ``data-cns-context`` the page exposes. **All of that is a hint.**
Nothing the browser sends is trusted for a decision:

* The roles are the session's own (``frappe.get_roles``).
* A record named in the address is looked up only if its type is one of the
  few the assistant knows (``pages.RECORD_ROUTES``), and only through the
  permission engine — ``frappe.has_permission`` and a permission-checked list
  read, the same two paths the record's own page uses.
* A record the asker may not read and a record that does not exist produce the
  **same** result. A sensitive escalation is invisible to anyone without the
  right to see it; saying "you may not see ESC-…" for one reference and "not
  found" for another would tell them which references are sensitive, which is
  the very thing the restriction withholds (see ``www/escalation.py``).
* The state and actions of a record come from the module that owns it
  (``formation.review_context``, ``lifecycle.readiness``), never from the page.

The owning modules are being changed by other people while this is written, so
every call into them is guarded: if one fails, the assistant says less about
the record rather than failing the question — and it clears any message the
failed call queued, so the asker never sees a stray error dialog.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, quote

import frappe

from consilium.consilium_core.assistant import pages as page_map

#: Roles every signed-in user holds automatically. Naming them in an answer
#: ("you hold: All") is noise.
AUTOMATIC_ROLES = {"All", "Guest", "Desk User"}

#: A few fields that say what a record is and where it stands. Kept short on
#: purpose: they are what the built-in answer mentions, and what AI mode may
#: send when an administrator allows a record summary.
SUMMARY_FIELDS = {
	"Governance Forum": ("forum_name", "forum_type", "compliance_status", "cadence", "next_review_on"),
	"Governing Document": ("document_name", "document_type", "lifecycle_phase", "version_label", "next_review_on"),
	"Escalation Matter": ("escalation_title", "status", "severity", "escalation_type", "opened_on"),
	"Committee Formation Request": ("forum_name", "request_type", "workflow_state"),
	"Document Version": ("version_label", "version_number", "published", "is_current"),
	"Document Intake Request": ("proposed_document_name", "request_type", "change_classification", "workflow_state"),
}

#: Which summary field is the record's title, and which says where it stands.
TITLE_FIELD = {
	"Governance Forum": "forum_name",
	"Governing Document": "document_name",
	"Escalation Matter": "escalation_title",
	"Committee Formation Request": "forum_name",
	"Document Version": "version_label",
	"Document Intake Request": "proposed_document_name",
}
STATE_FIELD = {
	"Governance Forum": "compliance_status",
	"Governing Document": "lifecycle_phase",
	"Escalation Matter": "status",
	"Committee Formation Request": "workflow_state",
	"Document Intake Request": "workflow_state",
}

#: A general-purpose label for each kind of record, used instead of the
#: record's own title wherever the record's contents must not appear.
KIND_LABEL = {
	"Governance Forum": "forum",
	"Governing Document": "governing document",
	"Escalation Matter": "escalation matter",
	"Committee Formation Request": "formation request",
	"Document Version": "document version",
	"Document Intake Request": "document request",
}


def _guarded(fn, *args, **kwargs):
	"""Call into another module; on any failure return None and leave no trace
	in the response's message log."""
	log = getattr(frappe.local, "message_log", None)
	mark = len(log) if log is not None else 0
	try:
		return fn(*args, **kwargs)
	except Exception:
		log = getattr(frappe.local, "message_log", None)
		if log is not None:
			del log[mark:]
		return None


def parse_input(raw) -> dict:
	"""The widget's context, as a dict of plain strings. Anything malformed is dropped."""
	if isinstance(raw, str):
		try:
			raw = json.loads(raw) if raw.strip() else {}
		except ValueError:
			raw = {}
	if not isinstance(raw, dict):
		raw = {}
	query = raw.get("query")
	if isinstance(query, str):
		query = {k: v[0] for k, v in parse_qs(query.lstrip("?")).items() if v}
	if not isinstance(query, dict):
		query = {}
	page_context = raw.get("page_context")
	if isinstance(page_context, str):
		try:
			page_context = json.loads(page_context)
		except ValueError:
			page_context = {}
	if not isinstance(page_context, dict):
		page_context = {}
	return {
		"route": str(raw.get("route") or "/")[:300],
		"title": str(raw.get("title") or "")[:300],
		"query": {str(k)[:40]: str(v)[:200] for k, v in list(query.items())[:20]},
		"page_context": {str(k)[:40]: v for k, v in list(page_context.items())[:20]
		                 if isinstance(v, str | int | float | bool)},
	}


def user_roles(user: str | None = None) -> list[str]:
	return sorted(set(frappe.get_roles(user or frappe.session.user)) - AUTOMATIC_ROLES)


def is_admin(roles=None) -> bool:
	held = set(roles if roles is not None else frappe.get_roles())
	return frappe.session.user == "Administrator" or bool(held & set(page_map.ADMIN_ROLES))


def has_desk_access() -> bool:
	if frappe.session.user == "Guest":
		return False
	return frappe.get_cached_value("User", frappe.session.user, "user_type") == "System User"


def roles_granting(doctype: str, ptype: str) -> list[str]:
	"""Roles whose level-0 permission row carries ``ptype`` on ``doctype``."""
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []
	roles = []
	for perm in meta.get("permissions") or []:
		if perm.get(ptype) and not perm.get("permlevel") and perm.role not in roles:
			roles.append(perm.role)
	return roles


def _doctype_exists(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


# ------------------------------------------------------------------ records


def _readable(doctype: str, name: str) -> bool:
	"""May the session read this record? False for "no such record" too."""
	if not name or not _doctype_exists(doctype) or not frappe.db.exists(doctype, name):
		return False
	if doctype == "Committee Formation Request":
		# A sponsor or delegating authority asked to decide a step may open the
		# request without any governance role; the formation module says who.
		doc = frappe.get_doc(doctype, name)
		if frappe.has_permission(doctype, "read", doc=doc):
			return True

		def decides_a_step():
			from consilium.governance import formation  # noqa: PLC0415 — owned elsewhere

			return formation.decidable_steps(doc)

		return bool(_guarded(decides_a_step))
	if not frappe.has_permission(doctype, "read", doc=name):
		return False
	# The same query path the list API uses, so a permission-query condition
	# (the sensitive-escalation rule is one) is honoured as well as the
	# controller hook.
	if not frappe.get_list(doctype, filters={"name": name}, fields=["name"], limit_page_length=1):
		return False
	if doctype == "Document Version":
		subject = frappe.db.get_value(doctype, name, ["subject_doctype", "subject_name"], as_dict=True)
		if subject and subject.subject_doctype and subject.subject_name:
			return _readable(subject.subject_doctype, subject.subject_name) if (
				subject.subject_doctype in page_map.RECORD_ROUTES
			) else bool(frappe.has_permission(subject.subject_doctype, "read", doc=subject.subject_name))
	return True


def is_restricted(doctype: str, name: str) -> bool:
	"""Sensitive, confidential or restricted: never sent out, never logged by name.

	Read only after the asker's right to read the record is established, and
	never returned to the browser.
	"""
	meta = frappe.get_meta(doctype)
	if doctype == "Document Version":
		subject = frappe.db.get_value(doctype, name, ["subject_doctype", "subject_name"], as_dict=True)
		if subject and subject.subject_doctype in page_map.RECORD_ROUTES and subject.subject_name:
			return is_restricted(subject.subject_doctype, subject.subject_name)
		return False
	if meta.has_field("subject_document"):
		# A request about a governing document says something about that
		# document, so it is as restricted as the document is.
		subject = frappe.db.get_value(doctype, name, "subject_document")
		if subject and frappe.db.exists("Governing Document", subject) and is_restricted("Governing Document", subject):
			return True
	fields = [f for f in ("sensitive", "confidential", "handling_classification") if meta.has_field(f)]
	if not fields:
		return False
	values = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
	if values.get("sensitive") or values.get("confidential"):
		return True
	# A value of the handling scale, not a workflow state: the two top grades
	# are the ones the handling rules withhold.
	return (values.get("handling_classification") or "") in ("Confidential", "Restricted")


def _summary(doctype: str, name: str, *, via_list: bool) -> dict:
	"""The summary fields the asker may read, as {label: value}."""
	meta = frappe.get_meta(doctype)
	levels = set(meta.get_permlevel_access("read")) | {0}
	fields = [f for f in SUMMARY_FIELDS.get(doctype, ())
	          if meta.has_field(f) and (meta.get_field(f).permlevel or 0) in levels]
	if not fields:
		return {}
	if via_list:
		rows = frappe.get_list(doctype, filters={"name": name}, fields=fields, limit_page_length=1)
		row = rows[0] if rows else {}
	else:
		row = frappe.db.get_value(doctype, name, fields, as_dict=True) or {}
	out = {}
	for field in fields:
		value = row.get(field)
		if value in (None, ""):
			continue
		df = meta.get_field(field)
		if df.fieldtype == "Check":
			value = "Yes" if value else "No"
		out[field] = {"label": df.label or field, "value": str(value)}
	return out


def _module_actions(payload: dict, offered: set, roles: dict, owner_actions, owner_label: str) -> dict:
	"""Sort a module's own ``{action: allowed}`` answer into what the asker may
	do now, what the stage offers but not to them (and who it belongs to), and
	what the stage does not offer at all."""
	labels = payload.get("action_labels") or {}
	available, unavailable = [], []
	for action, allowed in (payload.get("actions") or {}).items():
		label = str(labels.get(action, action.replace("_", " ").capitalize()))
		if allowed:
			available.append(label)
		elif action in offered:
			if action == "record_step_decision":
				why = "only the person a step is assigned to, or their delegate, decides it"
			else:
				holders = list(roles.get(action, ()))
				if action in owner_actions:
					holders.insert(0, owner_label)
				why = "needs " + " or ".join(holders) if holders else "not open to you"
			unavailable.append({"label": label, "why": why})
	not_offered = [str(labels[a]) for a in labels if a not in offered]
	return {"available": available, "unavailable": unavailable, "not_offered": not_offered,
	        "blockers": [str(b) for b in payload.get("blockers") or []]}


def _formation_actions(name: str) -> dict:
	from consilium.governance import formation  # noqa: PLC0415

	doc = frappe.get_doc("Committee Formation Request", name)
	return _module_actions(formation.review_context(doc), formation.stage_actions(doc),
	                       getattr(formation, "ACTION_ROLES", {}), getattr(formation, "ORIGINATOR_ACTIONS", ()),
	                       "the request's originator")


def _intake_actions(name: str) -> dict:
	from consilium.policy import intake  # noqa: PLC0415

	doc = frappe.get_doc("Document Intake Request", name)
	return _module_actions(intake.intake_context(doc), intake.intake_stage_actions(doc),
	                       getattr(intake, "INTAKE_ROLES", {}), getattr(intake, "REQUESTER_ACTIONS", ()),
	                       "the requester")


def _document_actions(name: str) -> dict:
	from consilium.policy import lifecycle  # noqa: PLC0415

	ready = lifecycle.readiness(name)
	available, unavailable, blockers = [], [], []
	for entry in ready.get("actions") or []:
		label = f"{entry['action']} (to {entry['next_state']})"
		if not entry.get("permitted"):
			unavailable.append({"label": label, "why": f"needs {entry.get('allowed_role')}"})
		elif entry.get("blocked_by"):
			unavailable.append({"label": label, "why": "blocked: " + "; ".join(map(str, entry["blocked_by"]))})
			blockers.extend(map(str, entry["blocked_by"]))
		else:
			available.append(label)
	return {"available": available, "unavailable": unavailable, "blockers": blockers}


def _simple_actions(doctype: str, name: str) -> dict:
	"""Edit, plus the records that hang off it, from the permission engine alone."""
	desk = has_desk_access()
	checks = [("Edit this record in the workspace", doctype, "write", name)]
	if doctype == "Governance Forum":
		checks.append(("Record a compliance review", "Forum Compliance Review", "create", None))
	if doctype == "Escalation Matter":
		checks += [
			("Add an action plan", "Action Plan", "create", None),
			("Record a risk acceptance", "Risk Acceptance", "create", None),
			("Record the closure", "Escalation Closure", "create", None),
		]
	available, unavailable = [], []
	for label, target, ptype, docname in checks:
		if not _doctype_exists(target):
			continue
		allowed = bool(frappe.has_permission(target, ptype, doc=docname)) if docname else bool(
			frappe.has_permission(target, ptype))
		if allowed and (desk or target == "Forum Compliance Review"):
			available.append(label)
		elif not allowed:
			granting = [r for r in roles_granting(target, ptype) if r not in AUTOMATIC_ROLES]
			held = set(frappe.get_roles())
			if docname and held & set(granting):
				why = "your role allows it in general, but not on this record at its current stage or under your record-level restrictions"
			else:
				why = "needs " + " or ".join(granting) if granting else "not open to anyone at present"
			unavailable.append({"label": label, "why": why})
		else:
			unavailable.append({"label": label, "why": "happens in the workspace, which your account cannot open"})
	return {"available": available, "unavailable": unavailable, "blockers": []}


def resolve_record(doctype: str, name: str) -> dict:
	"""Everything the assistant may say about one record, or only that it
	cannot say anything."""
	record = {"doctype": doctype, "kind": KIND_LABEL.get(doctype, doctype.lower()), "requested": True,
	          "visible": False}
	if not _readable(doctype, name):
		return record
	via_list = doctype != "Committee Formation Request" or bool(frappe.has_permission(doctype, "read", doc=name))
	summary = _guarded(_summary, doctype, name, via_list=via_list) or {}
	route, param = page_map.RECORD_ROUTES[doctype]
	record.update({
		"visible": True,
		"name": name,
		# Fail closed: if the flags cannot be read, treat the record as restricted.
		"restricted": _guarded(is_restricted, doctype, name) is not False,
		"summary": summary,
		"title": (summary.get(TITLE_FIELD.get(doctype, "")) or {}).get("value") or name,
		"state": (summary.get(STATE_FIELD.get(doctype, "")) or {}).get("value"),
		"href": f"{route}?{param}={quote(name)}",
	})
	if doctype == "Committee Formation Request":
		actions = _guarded(_formation_actions, name)
	elif doctype == "Document Intake Request":
		actions = _guarded(_intake_actions, name)
	elif doctype == "Governing Document":
		actions = _guarded(_document_actions, name)
		simple = _guarded(_simple_actions, doctype, name)
		if actions and simple:
			actions["available"] += simple["available"]
			actions["unavailable"] += simple["unavailable"]
		actions = actions or simple
	elif doctype == "Document Version":
		actions = None
	else:
		actions = _guarded(_simple_actions, doctype, name)
	record["actions"] = actions
	return record


# ------------------------------------------------------------------- context


def resolve(raw) -> dict:
	"""The whole server-side picture for one question."""
	given = parse_input(raw)
	route = page_map.normalise_route(given["route"])
	page = page_map.PAGES.get(route)
	roles = user_roles()
	ctx = {
		"route": route,
		"page": page,
		"page_title": page["title"] if page else (given["title"].split(" · ")[0] or "this page"),
		"roles": roles,
		"is_admin": is_admin(),
		"desk": has_desk_access(),
		"record": None,
		"installed": page_map.installed_routes(),
	}

	doctype = name = None
	if page and page.get("record_param"):
		doctype = page.get("doctype")
		name = (given["query"].get(page["record_param"]) or "").strip()
	if not name:
		# A page may name its record in ``data-cns-context``. Only a type the
		# assistant knows is looked at; anything else is ignored.
		hinted = given["page_context"].get("doctype")
		if hinted in page_map.RECORD_ROUTES and given["page_context"].get("name"):
			doctype, name = hinted, str(given["page_context"]["name"]).strip()
	if doctype in page_map.RECORD_ROUTES and name:
		ctx["record"] = resolve_record(doctype, name[:140])
	return ctx


def check_requirement(requires: dict, ctx: dict) -> tuple[bool, str | None]:
	"""Whether the asker meets a task's requirement, and if not, why — in words
	they can take to their administrator."""
	if not requires:
		return True, None
	held = set(frappe.get_roles())
	if requires.get("roles"):
		wanted = requires["roles"]
		if not held & set(wanted) and frappe.session.user != "Administrator":
			return False, "it needs one of these roles: {0}".format(", ".join(wanted))
	doctype = requires.get("doctype")
	if doctype:
		if not _doctype_exists(doctype):
			return False, "that part of the platform is not installed on this site yet"
		ptype = requires.get("ptype", "read")
		record = ctx.get("record")
		if requires.get("record") and record and record.get("requested") and not record.get("visible"):
			# Same words whether the record is missing or hidden.
			return False, "there is no record on this page that you can open"
		on_record = requires.get("record") and record and record.get("visible") and record["doctype"] == doctype
		allowed = frappe.has_permission(doctype, ptype, doc=record["name"]) if on_record else frappe.has_permission(doctype, ptype)
		if not allowed:
			granting = [r for r in roles_granting(doctype, ptype) if r not in AUTOMATIC_ROLES]
			if on_record and held & set(granting):
				return False, ("your role allows it in general, but not on this record — it may be locked at its "
				               "current stage, or outside your record-level restrictions")
			if granting:
				return False, "it needs one of these roles: {0}".format(", ".join(granting))
			return False, "nobody holds that permission at present"
	if requires.get("desk") and not has_desk_access():
		return False, "it happens in the workspace, which your account cannot open"
	if requires.get("advanced"):
		# The record pages offer the workspace ("Advanced view") to administrators
		# only (branding.cns_advanced_view); the assistant must not send anyone
		# else looking for a button they will not see.
		from consilium.consilium_core.branding import cns_advanced_view

		if not cns_advanced_view():
			return False, "it is done in the Advanced view, which is for administrators"
	return True, None
