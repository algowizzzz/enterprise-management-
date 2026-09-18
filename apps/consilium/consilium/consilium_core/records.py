"""Archiving on the retention trigger, and the records manager's disposal screen.

``retention.py`` holds the rules — a retained or held record cannot change, a
legal hold overrides disposal, disposal is never automatic — and the daily flag
that puts an archive past its retention period in front of a reviewer. Three
steps of the design in ``04-architecture.md`` §8 had no caller outside the
tests (G-16, P-18, E-18): nothing created an ``Archive Record``, and an
approved disposal and a hold release could be carried out only from a Python
shell. This module is those callers.

**Archiving (the retention trigger).** A record whose retention class counts
from a *terminal* event — retirement, closure, disbandment — is archived once
that event has happened: an immutable JSON payload of the record, its child
rows, its change log and an inventory of its attachments, hashed and chained
(``Archive Record``). From then on the record is read-only (``retention_lock``)
and its disposal falls due on the class's date. A class that counts from
creation, modification or the effective date is **not** archived by the sweep:
archiving a live record would freeze it while people still work on it. Such a
class protects its records through write-once handling (``requires_worm``)
instead, which applies from the moment an assignment covers the record.

**The disposal decision.** Every open ``Disposition Event`` is listed for the
records manager, with the record it concerns, its class, the due date and any
legal hold. A decision takes two people:

1. a records manager **proposes** to dispose of the record or to retain it (to a
   review date, or permanently where the class archives permanently), with a
   reason;
2. **a different** records manager or system manager **approves** it (or sends
   it back). Nobody approves their own proposal: the refusal is audited.

A legal hold refuses a proposal or an approval to dispose, and the execution,
through ``audit.refuse`` — so each attempt leaves a ``Governance Refusal Log``
row that survives the rolled-back transaction. Releasing a hold is an action on
the same screen, with a reason; it returns everything the hold held to
Scheduled (``retention.release_hold``).

**What executing a disposal does — and does not.** The platform deletes
nothing. Disposal is carried out as *redaction in place*: the record's free
text, bodies, JSON payloads and attachments — and the same fields on its child
rows and document versions, the matching values in its change log, and the
archive payload — are replaced with a marker naming the disposition event. What
is kept is a tombstone: the identifier, title, dates, links and status, so a
reference to the record still resolves and says what happened to it. The
``Disposition Event`` records what was redacted and the hashes of what was
destroyed; it outlives the content it disposed of, as the design requires.
The redaction writes directly (``frappe.db.set_value``) rather than saving the
record, because the record is archived and its own guards refuse any save; this
path is the one governed exception, and it runs only after the approval and
hold checks. Identifying ``Data`` fields (titles, codes, references) are kept
on purpose — a tombstone nobody can recognise is no evidence.
"""

from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils import getdate, now, nowdate

from consilium.consilium_core import audit, retention

EVENT = "Disposition Event"
ARCHIVE = "Archive Record"

#: Who may use the records screen: propose, approve, execute, release holds.
RECORDS_ROLES = ("Records Manager", "System Manager")

#: The class trigger events that mark a record finished, and the field that
#: dates each. Only these archive automatically (see the module notes).
TERMINAL_TRIGGERS = {"Retirement": "retired_on", "Closure": "closed_on", "Disbandment": "disbanded_on"}

#: Decision values (options of a configuration field, not workflow states).
DECISION_DISPOSE = "Dispose"
DECISION_RETAIN = retention.DECISION_RETAIN

#: The class disposition action that keeps records permanently.
ACTION_PERMANENT = "Archive Permanently"

#: Status labels written, never compared: what each means is read from the
#: event's semantic flags (``is_open``) and its facts (``approved_by``,
#: ``executed_on``).
STATUS_SCHEDULED = "Scheduled"
STATUS_APPROVED = "Approved"
STATUS_RETAINED = "Retained"

#: Field types whose content a disposal removes.
REDACTED_TYPES = {"Small Text", "Text", "Long Text", "Text Editor", "Markdown Editor", "HTML Editor", "Code",
	"JSON", "Attach", "Attach Image"}
EMPTIED_TYPES = {"Attach", "Attach Image"}


# ------------------------------------------------------------------ archiving


def class_for(doctype: str, name: str) -> str | None:
	"""The retention class that governs a record: the winning assignment, else
	the record's own ``retention_class`` field where it has one."""
	assignment = retention.effective_retention(doctype, name)
	if assignment:
		return assignment["retention_class"]
	if frappe.get_meta(doctype).has_field("retention_class"):
		return frappe.db.get_value(doctype, name, "retention_class")
	return None


def archived(doctype: str, name: str) -> str | None:
	return frappe.db.get_value(ARCHIVE, {"subject_doctype": doctype, "subject_name": name}, "name")


def _history(doctype: str, name: str) -> list[dict]:
	return [
		{"on": str(row.creation), "by": row.owner, "data": row.data}
		for row in frappe.get_all("Version", filters={"ref_doctype": doctype, "docname": name},
			fields=["creation", "owner", "data"], order_by="creation asc")
	]


def _attachments(doctype: str, name: str) -> list[dict]:
	return frappe.get_all("File", filters={"attached_to_doctype": doctype, "attached_to_name": name},
		fields=["name", "file_name", "file_url", "content_hash", "file_size", "is_private"], order_by="creation asc")


def archive(doctype: str, name: str) -> str:
	"""Archive one record under its retention class. Idempotent: an archived
	record returns its existing archive."""
	existing = archived(doctype, name)
	if existing:
		return existing
	retention_class = class_for(doctype, name)
	if not retention_class:
		frappe.throw(_("{0} {1} has no retention class, so it cannot be archived.").format(doctype, name))
	stamp = now()
	doc = frappe.get_doc(doctype, name)
	attachments = _attachments(doctype, name)
	payload = {
		"subject_doctype": doctype,
		"subject_name": name,
		"archived_on": stamp,
		"retention_class": retention_class,
		"record": doc.as_dict(convert_dates_to_str=True),
		"history": _history(doctype, name),
		"attachments": attachments,
	}
	content = json.dumps(payload, default=str, sort_keys=True, indent=1)
	digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
	slug = re.sub(r"[^a-z0-9]+", "-", f"{doctype}-{name}".lower()).strip("-")
	saved = frappe.get_doc({
		"doctype": "File", "file_name": f"archive-{slug}.json", "is_private": 1, "content": content,
	}).insert(ignore_permissions=True)
	record = frappe.get_doc({
		"doctype": ARCHIVE,
		"subject_doctype": doctype,
		"subject_name": name,
		"document_version": doc.get("current_version") if doc.meta.has_field("current_version") else None,
		"archived_on": stamp,
		"retention_class": retention_class,
		"disposition_due_on": retention.disposition_due_date(retention_class, doctype, name),
		"payload_file": saved.file_url,
		"payload_sha256": digest,
		"manifest": json.dumps({
			"fields": len(doc.meta.fields),
			"child_rows": sum(len(doc.get(df.fieldname) or []) for df in doc.meta.get_table_fields()),
			"history_entries": len(payload["history"]),
			"attachments": [{"file_name": a.file_name, "content_hash": a.content_hash} for a in attachments],
		}),
	}).insert(ignore_permissions=True)
	saved.db_set({"attached_to_doctype": ARCHIVE, "attached_to_name": record.name}, update_modified=False)
	retention.clear_cache()
	return record.name


def archive_on_trigger(as_of=None) -> list[str]:
	"""Daily: archive every record whose terminal retention trigger has passed.

	Walks the active retention assignments. A record is archived under the
	assignment that wins for it (``retention.effective_retention``), so two
	overlapping assignments never archive it twice or under the wrong class.
	Each record in its own savepoint: one failure is logged and the rest go on.
	"""
	as_of = getdate(as_of or nowdate())
	made: list[str] = []
	if not (frappe.db.table_exists("Retention Assignment") and frappe.db.table_exists(ARCHIVE)):
		return made
	for assignment in frappe.get_all(
		"Retention Assignment", filters={"is_active": 1},
		fields=["name", "target_doctype", "record_filter", "retention_class"], order_by="priority desc",
	):
		trigger = frappe.db.get_value("Retention Class", assignment.retention_class, "trigger_event")
		field = TERMINAL_TRIGGERS.get(trigger)
		if not field or not frappe.db.exists("DocType", assignment.target_doctype):
			continue
		if not frappe.get_meta(assignment.target_doctype).has_field(field):
			continue
		filters = [[k, "=", v] if not isinstance(v, (list, tuple)) else [k, *v]
			for k, v in retention._loads(assignment.record_filter).items()]
		# The framework reads an empty date as 0001-01-01 in a comparison, so
		# the lower bound is what leaves out a record whose trigger has not
		# happened; "is set" would compare a date column with '' and fail on
		# PostgreSQL.
		filters += [[field, ">", "1900-01-01"], [field, "<=", str(as_of) + " 23:59:59"]]
		frappe.db.savepoint("archive_query")
		try:
			names = frappe.get_all(assignment.target_doctype, filters=filters, pluck="name")
		except Exception:
			# A filter naming a field the DocType lacks is a configuration error;
			# it is logged, and the other assignments still run.
			frappe.db.rollback(save_point="archive_query")
			frappe.log_error(title="Consilium: unusable retention filter", message=frappe.get_traceback())
			continue
		for name in names:
			if archived(assignment.target_doctype, name):
				continue
			winner = retention.effective_retention(assignment.target_doctype, name)
			if not winner or winner["name"] != assignment.name:
				continue
			frappe.db.savepoint("archive_trigger")
			try:
				made.append(archive(assignment.target_doctype, name))
			except Exception:
				frappe.db.rollback(save_point="archive_trigger")
				frappe.log_error(title=f"Consilium: {assignment.target_doctype} {name} could not be archived",
					message=frappe.get_traceback())
	return made


# ----------------------------------------------------------------- the screen


def may_manage(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user != "Guest" and bool(set(frappe.get_roles(user)).intersection(RECORDS_ROLES))


def _require_manager() -> str:
	if not may_manage():
		raise frappe.PermissionError(_("Retention and disposal are for records managers."))
	return frappe.session.user


def _subject_title(doctype: str, name: str) -> tuple[str | None, bool]:
	"""The subject's title where the viewer may read it; a sensitive record is
	not named to a records manager the record itself is hidden from."""
	if not frappe.db.exists(doctype, name):
		return None, False
	if not frappe.has_permission(doctype, "read", doc=name):
		return None, False
	title_field = frappe.get_meta(doctype).title_field
	return (frappe.db.get_value(doctype, name, title_field) if title_field else None) or name, True


_EVENT_FIELDS = ["name", "archive_record", "due_on", "action", "status", "is_open", "held_by_legal_hold",
	"decision", "decision_reason", "retained_until", "proposed_by", "proposed_on", "approved_by", "approved_on",
	"approval_note", "executed_on", "executed_by", "evidence", "modified"]


def _event_row(row, me: str) -> dict:
	archive = frappe.db.get_value(ARCHIVE, row.archive_record,
		["subject_doctype", "subject_name", "retention_class", "archived_on", "payload_sha256"], as_dict=True) or {}
	title, readable = _subject_title(archive.get("subject_doctype"), archive.get("subject_name")) \
		if archive else (None, False)
	hold = retention.active_legal_hold(archive.get("subject_doctype"), archive.get("subject_name")) \
		if archive else None
	is_open = bool(int(row.is_open or 0))
	proposed = bool(row.decision and row.proposed_by)
	out = {k: (str(row[k]) if row.get(k) is not None and k.endswith(("_on", "_until")) else row.get(k))
		for k in _EVENT_FIELDS if k != "evidence"}
	out.update({
		"subject_doctype": archive.get("subject_doctype"),
		"subject_name": archive.get("subject_name"),
		"subject_title": title,
		"subject_readable": readable,
		"retention_class": archive.get("retention_class"),
		"class_title": frappe.db.get_value("Retention Class", archive.get("retention_class"), "title")
		if archive.get("retention_class") else None,
		"archived_on": str(archive.get("archived_on")) if archive.get("archived_on") else None,
		"legal_hold": hold,
		"is_open": is_open,
		"allows_permanent": row.action == ACTION_PERMANENT,
		"may_propose": is_open and not row.approved_by,
		"may_approve": is_open and proposed and not row.approved_by and row.proposed_by != me,
		"awaiting_other": is_open and proposed and not row.approved_by and row.proposed_by == me,
		"may_execute": is_open and row.decision == DECISION_DISPOSE and bool(row.approved_by) and not hold,
		"evidence": _loads(row.evidence) if row.executed_on else None,
	})
	return out


def _loads(value):
	if not value:
		return {}
	if isinstance(value, dict):
		return value
	try:
		return json.loads(value)
	except ValueError:
		return {}


@frappe.whitelist(methods=["GET"])
def disposal_overview() -> dict:
	"""Everything the records screen shows: what is due, what was decided, the holds."""
	me = _require_manager()
	open_rows = frappe.get_all(EVENT, filters={"is_open": 1}, fields=_EVENT_FIELDS, order_by="due_on asc")
	closed_rows = frappe.get_all(EVENT, filters={"is_open": 0}, fields=_EVENT_FIELDS, order_by="modified desc",
		limit_page_length=100)
	holds = frappe.get_all("Legal Hold", filters={"is_active": 1},
		fields=["name", "hold_reference", "description", "scope_doctype", "scope_filter", "placed_on",
			"requested_by", "approved_by"], order_by="placed_on desc")
	for hold in holds:
		hold["holding"] = frappe.db.count(EVENT, {"held_by_legal_hold": hold.name, "is_open": 1})
		hold["placed_on"] = str(hold.placed_on) if hold.placed_on else None
	return {
		"me": me,
		"due": [_event_row(row, me) for row in open_rows],
		"decided": [_event_row(row, me) for row in closed_rows],
		"holds": holds,
		"archives": frappe.db.count(ARCHIVE),
		"assignments": frappe.db.count("Retention Assignment", {"is_active": 1}),
		"may_release_holds": bool(frappe.has_permission("Legal Hold", "write")),
	}


def _load_event(event: str):
	if not event or not frappe.db.exists(EVENT, event):
		frappe.throw(_("There is no disposition event {0}.").format(event), frappe.DoesNotExistError)
	doc = frappe.get_doc(EVENT, event)
	archive = frappe.get_doc(ARCHIVE, doc.archive_record)
	return doc, archive


def _refuse(archive, event, action: str, control: str, message: str, **kwargs):
	audit.refuse(
		message,
		subject_doctype=archive.subject_doctype,
		subject_name=archive.subject_name,
		attempted_action=action,
		control=control,
		context={"disposition_event": event.name},
		**kwargs,
	)


def _require_open(event) -> None:
	if not int(event.is_open or 0):
		frappe.throw(_("{0} is already closed.").format(event.name), title=_("Already Decided"))


def _guard_hold(event, archive, action: str) -> None:
	hold = retention.active_legal_hold(archive.subject_doctype, archive.subject_name)
	if hold:
		_refuse(archive, event, action, "legal hold",
			_("{0} of {1} {2} is refused: legal hold {3} is in force and overrides the retention schedule "
				"entirely.").format(action, archive.subject_doctype, archive.subject_name, hold),
			legal_hold=hold)


@frappe.whitelist(methods=["POST"])
def propose_disposition(event: str, decision: str, reason: str, retained_until: str | None = None) -> dict:
	"""Step one: a records manager proposes to dispose of the record or to retain it."""
	me = _require_manager()
	doc, archive = _load_event(event)
	_require_open(doc)
	if doc.approved_by:
		frappe.throw(_("{0} is already approved; it can only be carried out.").format(doc.name))
	if decision not in (DECISION_DISPOSE, DECISION_RETAIN):
		frappe.throw(_("Choose to dispose of the record or to retain it."), title=_("Decision Required"))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Give the reason for the decision: it is kept with the record's disposal."),
			title=_("Reason Required"))
	if decision == DECISION_DISPOSE:
		_guard_hold(doc, archive, "Dispose")
		if doc.action == ACTION_PERMANENT:
			_refuse(archive, doc, "Dispose", "retention class",
				_("{0} {1} is kept permanently under its retention class; it cannot be disposed of.").format(
					archive.subject_doctype, archive.subject_name), exc=frappe.ValidationError)
		retained_until = None
	else:
		if retained_until and getdate(retained_until) <= getdate(nowdate()):
			frappe.throw(_("Retain until a date after today."), title=_("Date In The Past"))
		if not retained_until and doc.action != ACTION_PERMANENT:
			frappe.throw(_("Say until when the record is retained. Only a class that archives permanently "
				"keeps a record with no review date."), title=_("Review Date Required"))
	doc.update({
		"decision": decision, "decision_reason": reason, "retained_until": retained_until or None,
		"proposed_by": me, "proposed_on": now(),
	})
	doc.save(ignore_permissions=True)
	return disposal_overview()


@frappe.whitelist(methods=["POST"])
def send_back_disposition(event: str, note: str) -> dict:
	"""The approver declines the proposal: it is cleared, with the note, for a new one."""
	me = _require_manager()
	doc, archive = _load_event(event)
	_require_open(doc)
	if doc.approved_by or not doc.decision:
		frappe.throw(_("There is no proposal waiting on {0}.").format(doc.name))
	if not (note or "").strip():
		frappe.throw(_("Say why the proposal is sent back."), title=_("Reason Required"))
	doc.add_comment("Info", _("{0} sent back the proposal to {1} ({2}): {3}").format(
		me, (doc.decision or "").lower(), doc.decision_reason, note.strip()))
	doc.update({"decision": None, "decision_reason": None, "retained_until": None, "proposed_by": None,
		"proposed_on": None})
	doc.save(ignore_permissions=True)
	return disposal_overview()


@frappe.whitelist(methods=["POST"])
def approve_disposition(event: str, note: str | None = None) -> dict:
	"""Step two: a second person approves the proposal. Never the proposer."""
	me = _require_manager()
	doc, archive = _load_event(event)
	_require_open(doc)
	if not doc.decision or not doc.proposed_by:
		frappe.throw(_("Nothing is proposed on {0} yet.").format(doc.name), title=_("No Proposal"))
	if doc.approved_by:
		frappe.throw(_("{0} is already approved.").format(doc.name))
	if doc.proposed_by == me:
		_refuse(archive, doc, "Approve disposition", "four eyes",
			_("You proposed this decision, so someone else must approve it. A disposal decision always takes "
				"two people."))
	if doc.decision == DECISION_DISPOSE:
		_guard_hold(doc, archive, "Dispose")
	doc.update({"approved_by": me, "approved_on": now(), "approval_note": (note or "").strip() or None,
		"status": STATUS_APPROVED if doc.decision == DECISION_DISPOSE else STATUS_RETAINED})
	doc.save(ignore_permissions=True)
	return disposal_overview()


# ------------------------------------------------------------ the execution


def _redacted_value(df, marker: str):
	if df.fieldtype in EMPTIED_TYPES:
		return None
	if df.fieldtype == "JSON":
		return json.dumps({"disposed": marker})
	return marker


def _redact_row(doctype: str, name: str, values: dict, marker: str, originals: set) -> list[str]:
	changed = []
	for df in frappe.get_meta(doctype).fields:
		if df.fieldtype not in REDACTED_TYPES:
			continue
		value = values.get(df.fieldname)
		if value in (None, "", "{}", "[]"):
			continue
		if isinstance(value, str) and len(value) > 3:
			originals.add(value)
		frappe.db.set_value(doctype, name, df.fieldname, _redacted_value(df, marker), update_modified=False)
		changed.append(df.fieldname)
	return changed


def _scrub(value, originals: set, marker: str):
	if isinstance(value, str):
		return marker if value in originals else value
	if isinstance(value, list):
		return [_scrub(v, originals, marker) for v in value]
	if isinstance(value, dict):
		return {k: _scrub(v, originals, marker) for k, v in value.items()}
	return value


def _overwrite_file(file_url: str, text: str) -> dict | None:
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	file_doc = frappe.get_doc("File", name)
	before = file_doc.content_hash
	path = file_doc.get_full_path()
	with open(path, "w", encoding="utf-8") as handle:
		handle.write(text)
	digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
	file_doc.db_set({"content_hash": digest, "file_size": len(text.encode("utf-8"))}, update_modified=False)
	return {"file": file_doc.name, "file_name": file_doc.file_name, "previous_hash": before}


def redact(archive, event) -> dict:
	"""Carry out a disposal as redaction in place. Returns the evidence."""
	marker = _("[Disposed under {0} on {1}]").format(event.name, nowdate())
	doctype, name = archive.subject_doctype, archive.subject_name
	originals: set = set()
	evidence: dict = {"marker": marker, "subject_doctype": doctype, "subject_name": name,
		"archive_record": archive.name, "archive_payload_sha256": archive.payload_sha256}
	if not frappe.db.exists(doctype, name):
		evidence["record"] = "not found; only the archive payload was disposed of"
	else:
		doc = frappe.get_doc(doctype, name)
		evidence["fields"] = _redact_row(doctype, name, doc.as_dict(), marker, originals)
		child_values = 0
		for tf in doc.meta.get_table_fields():
			for row in doc.get(tf.fieldname) or []:
				child_values += len(_redact_row(tf.options, row.name, row.as_dict(), marker, originals))
		evidence["child_values"] = child_values
	versions = frappe.get_all("Document Version", filters={"subject_doctype": doctype, "subject_name": name},
		fields=["*"]) if frappe.db.table_exists("Document Version") else []
	evidence["document_versions"] = [row.name for row in versions
		if _redact_row("Document Version", row.name, row, marker, originals)]
	files = []
	for owner_doctype, owner_names in ((doctype, [name]), ("Document Version", evidence["document_versions"])):
		for owner in owner_names:
			for attachment in _attachments(owner_doctype, owner):
				done = _overwrite_file(attachment.file_url, marker)
				if done:
					files.append(done)
	evidence["files"] = files
	history = 0
	for row in frappe.get_all("Version", filters={"ref_doctype": doctype, "docname": name}, fields=["name", "data"]):
		data = _loads(row.data)
		scrubbed = _scrub(data, originals, marker)
		if scrubbed != data:
			frappe.db.set_value("Version", row.name, "data", json.dumps(scrubbed), update_modified=False)
			history += 1
	evidence["history_entries"] = history
	if archive.payload_file:
		evidence["archive_payload"] = _overwrite_file(archive.payload_file, json.dumps({
			"disposed": True, "disposition_event": event.name, "archive_record": archive.name,
			"original_payload_sha256": archive.payload_sha256, "on": nowdate(),
		}, indent=1))
	return evidence


@frappe.whitelist(methods=["POST"])
def execute_disposition(event: str) -> dict:
	"""Carry out an approved disposal: redaction in place, logged. Never deletion."""
	me = _require_manager()
	doc, archive = _load_event(event)
	_require_open(doc)
	if doc.decision != DECISION_DISPOSE:
		frappe.throw(_("{0} is not a decision to dispose.").format(doc.name), title=_("Nothing To Execute"))
	_guard_hold(doc, archive, "Dispose")
	if not doc.approved_by:
		_refuse(archive, doc, "Dispose", "disposition approval",
			_("A disposition must be approved by a second person before it is carried out."),
			exc=frappe.ValidationError)
	evidence = redact(archive, doc)
	evidence.update({"executed_by": me, "decision_reason": doc.decision_reason, "approved_by": doc.approved_by})
	retention.execute_disposition(doc.name, evidence)
	frappe.db.set_value(EVENT, doc.name, "executed_by", me, update_modified=False)
	if frappe.db.exists(archive.subject_doctype, archive.subject_name):
		frappe.get_doc({
			"doctype": "Comment", "comment_type": "Info",
			"reference_doctype": archive.subject_doctype, "reference_name": archive.subject_name,
			"content": _("Disposed of under {0}, approved by {1}: its content was redacted in place and the "
				"record kept as a tombstone.").format(doc.name, doc.approved_by),
		}).insert(ignore_permissions=True)
	return disposal_overview()


@frappe.whitelist(methods=["POST"])
def release_legal_hold(hold: str, reason: str) -> dict:
	"""Release a hold, with a reason. Everything it held returns to Scheduled."""
	me = _require_manager()
	if not frappe.has_permission("Legal Hold", "write"):
		raise frappe.PermissionError(_("You may not release legal holds."))
	if not hold or not frappe.db.exists("Legal Hold", hold):
		frappe.throw(_("There is no legal hold {0}.").format(hold), frappe.DoesNotExistError)
	if not (reason or "").strip():
		frappe.throw(_("Give the reason the hold is released."), title=_("Reason Required"))
	retention.release_hold(hold)
	frappe.get_doc("Legal Hold", hold).add_comment("Info", _("Released by {0}: {1}").format(me, reason.strip()))
	return disposal_overview()


@frappe.whitelist(methods=["POST"])
def run_check() -> dict:
	"""Run today's archive and disposal checks now, rather than waiting for the night."""
	_require_manager()
	archived_now = archive_on_trigger()
	flagged = retention.flag_due_for_disposal()
	out = disposal_overview()
	out["check"] = {"archived": len(archived_now), "scheduled": len(flagged["scheduled"]),
		"held": len(flagged["held"])}
	return out
