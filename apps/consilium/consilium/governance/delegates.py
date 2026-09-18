"""Delegate nomination from the forum page (G-13).

G-13 says chairs, sponsors and secretaries shall be able to nominate delegates
for administrative tasks. Core had the mechanism — ``Authority Delegation``, a
dated, scoped transfer of named actions that ``delegation.resolve_actor``
honours at the point of action — but only an administrator could create one,
on the desk. This module lets the forum's own chair, sponsor or secretary
nominate their delegate from ``/forum``, within limits the platform enforces:

* **Only their own authority.** The delegator is always the person signed in,
  and only while they hold the chair, sponsor or secretary field on this forum.
  Nobody nominates a delegate on someone else's behalf here.
* **Only this forum.** The delegation is scoped to the forum (scope type
  *Forum*), so it covers actions on this forum's records and nothing else.
* **Only administrative actions.** Just the ``Delegable Action`` rows marked
  administrative and active are offered and accepted; delegating a decision
  such as an attestation stays an administrator's deliberate act on the desk.
* **Always dated.** A start and an end, the end within a year: an open-ended
  delegation made from a web form is the kind nobody remembers to end.

Each nomination is recorded three ways: the ``Authority Delegation`` itself
(with its change log), a line in the forum's history, and a notice to the
delegate (``governance.delegate.nominated``). Ending one early is the same
act in reverse, and the delegation row is kept — closed by its end date, never
deleted, so "who was acting for whom, when" stays answerable.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from consilium.consilium_core import audit, notification

FORUM = "Governance Forum"
DELEGATION = "Authority Delegation"

#: The forum fields naming the people G-13 lets nominate a delegate.
NOMINATING_FIELDS = (("committee_chair", "Chair"), ("sponsor", "Sponsor"), ("secretary", "Secretary"))

#: The longest a delegation made from the portal may run.
MAX_DAYS = 366

EVENT_NOMINATED = "governance.delegate.nominated"
EVENT_ENDED = "governance.delegate.ended"


def _load_forum(forum: str, ptype: str = "read"):
	if not forum or not frappe.db.exists(FORUM, forum):
		frappe.throw(_("There is no forum {0}.").format(forum), frappe.DoesNotExistError)
	frappe.has_permission(FORUM, ptype, doc=forum, throw=True)
	return frappe.get_doc(FORUM, forum)


def capacities(forum_doc, user: str | None = None) -> list[str]:
	"""The capacities in which ``user`` may nominate on this forum (Chair, Sponsor…)."""
	user = user or frappe.session.user
	return [label for field, label in NOMINATING_FIELDS if user and forum_doc.get(field) == user]


def administrative_actions() -> list[dict]:
	return frappe.get_all("Delegable Action", filters={"is_active": 1, "is_administrative": 1},
		fields=["name", "delegable_action_name as label", "description"], order_by="sort_order asc, name asc")


def _candidates(exclude: str) -> list[dict]:
	"""People a delegate may be: enabled accounts that can sign in to the portal."""
	return frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Guest", "Administrator", exclude]],
			"user_type": ["in", ["System User", "Website User"]]},
		fields=["name", "full_name"], order_by="full_name asc", limit_page_length=1000,
	)


def _rows(forum: str) -> list[dict]:
	rows = frappe.get_all(
		DELEGATION,
		filters={"scope_type": "Forum", "scope_doctype": FORUM, "scope_record": forum},
		fields=["name", "delegator", "delegate", "valid_from", "valid_to", "reason", "is_active", "creation"],
		order_by="valid_from desc",
	)
	today = getdate(nowdate())
	for row in rows:
		row["actions"] = frappe.get_all("Delegated Action Item", filters={"parent": row.name,
			"parenttype": DELEGATION}, pluck="delegable_action", order_by="idx asc")
		started = getdate(row.valid_from) <= today
		ended = bool(row.valid_to) and getdate(row.valid_to) < today
		row["standing"] = "ended" if ended else ("current" if started else "upcoming")
		row["may_end"] = row.delegator == frappe.session.user and not ended
		for key in ("valid_from", "valid_to", "creation"):
			row[key] = str(row[key]) if row.get(key) else None
	return rows


@frappe.whitelist(methods=["GET"])
def forum_delegates(forum: str) -> dict:
	"""The forum's delegations, and whether the viewer may nominate one."""
	doc = _load_forum(forum)
	me = frappe.session.user
	mine = capacities(doc, me)
	return {
		"forum": doc.name,
		"delegations": _rows(doc.name),
		"capacities": mine,
		"may_nominate": bool(mine),
		"actions": administrative_actions() if mine else [],
		"people": _candidates(me) if mine else [],
		"max_days": MAX_DAYS,
	}


def _refuse(forum: str, message: str):
	audit.refuse(message, subject_doctype=FORUM, subject_name=forum, attempted_action="Nominate delegate",
		control="delegate nomination")


def _history(forum: str, text: str) -> None:
	frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": FORUM,
		"reference_name": forum, "content": text}).insert(ignore_permissions=True)


def _notify(event: str, delegation, forum_doc, delegator: str) -> None:
	notification.notify(
		event,
		[delegation.delegate],
		context={
			"forum_name": forum_doc.forum_name,
			"delegator": delegator,
			"delegator_name": frappe.utils.get_fullname(delegator),
			"valid_from": str(delegation.valid_from),
			"valid_to": str(delegation.valid_to) if delegation.valid_to else "",
			"actions": ", ".join(row.delegable_action for row in delegation.delegated_actions),
			"link": frappe.utils.get_url(f"/forum?name={forum_doc.name}#members"),
		},
		subject_doctype=DELEGATION,
		subject_name=delegation.name,
	)


@frappe.whitelist(methods=["POST"])
def nominate_delegate(forum: str, delegate: str, actions, valid_from: str, valid_to: str, reason: str) -> dict:
	"""The chair, sponsor or secretary nominates their own delegate for this forum."""
	doc = _load_forum(forum)
	me = frappe.session.user
	held = capacities(doc, me)
	if not held:
		_refuse(doc.name, _("Only the forum's chair, sponsor or secretary may nominate a delegate for it, and "
			"only for themselves."))
	actions = frappe.parse_json(actions) if isinstance(actions, str) else (actions or [])
	allowed = {row.name for row in administrative_actions()}
	actions = [a for a in dict.fromkeys(actions) if a]
	if not actions:
		frappe.throw(_("Choose at least one task to delegate."), title=_("Tasks Required"))
	outside = [a for a in actions if a not in allowed]
	if outside:
		_refuse(doc.name, _("{0} cannot be delegated from the forum page: only administrative tasks can.").format(
			", ".join(outside)))
	if not delegate or not frappe.db.get_value("User", {"name": delegate, "enabled": 1}, "name"):
		frappe.throw(_("Choose the person who will act for you."), title=_("Delegate Required"))
	if delegate == me:
		frappe.throw(_("A delegate is someone other than yourself."), title=_("Choose Someone Else"))
	if not (reason or "").strip():
		frappe.throw(_("Say why, for the record: for example, leave between two dates."), title=_("Reason Required"))
	if not valid_from or not valid_to:
		frappe.throw(_("Give the first and last day the delegate acts for you."), title=_("Dates Required"))
	start, end = getdate(valid_from), getdate(valid_to)
	if start < getdate(nowdate()):
		frappe.throw(_("A delegation starts today or later; it cannot be back-dated."), title=_("Start In The Past"))
	if end < start:
		frappe.throw(_("The last day is before the first."), title=_("Dates Out Of Order"))
	if (end - start).days > MAX_DAYS:
		frappe.throw(_("A delegation from the forum page lasts at most a year. Nominate again when it ends."),
			title=_("Too Long"))
	delegation = frappe.get_doc({
		"doctype": DELEGATION,
		"delegator": me,
		"delegate": delegate,
		"scope_type": "Forum",
		"scope_doctype": FORUM,
		"scope_record": doc.name,
		"valid_from": start,
		"valid_to": end,
		"reason": _("Nominated as {0} of {1}: {2}").format(" and ".join(held), doc.forum_name, reason.strip()),
		"delegated_actions": [{"delegable_action": a} for a in actions],
	}).insert(ignore_permissions=True)
	_history(doc.name, _("{0} ({1}) nominated {2} as delegate for {3}, from {4} to {5} ({6}).").format(
		me, " and ".join(held), delegate, ", ".join(actions), start, end, delegation.name))
	_notify(EVENT_NOMINATED, delegation, doc, me)
	return forum_delegates(doc.name)


@frappe.whitelist(methods=["POST"])
def end_delegation(delegation: str, reason: str | None = None) -> dict:
	"""The delegator ends their own delegation early. The row is kept, closed by its dates."""
	if not delegation or not frappe.db.exists(DELEGATION, delegation):
		frappe.throw(_("There is no delegation {0}.").format(delegation), frappe.DoesNotExistError)
	row = frappe.get_doc(DELEGATION, delegation)
	if row.scope_doctype != FORUM or not row.scope_record:
		frappe.throw(_("{0} is not a forum delegation.").format(delegation))
	forum_doc = _load_forum(row.scope_record)
	me = frappe.session.user
	if row.delegator != me:
		_refuse(forum_doc.name, _("Only the person who delegated may end the delegation from the forum page."))
	today = getdate(nowdate())
	yesterday = add_days(today, -1)
	if row.valid_to and getdate(row.valid_to) < today:
		frappe.throw(_("{0} has already ended.").format(delegation), title=_("Already Ended"))
	if getdate(row.valid_from) > yesterday:
		# Not started, or starting today: a window that closed before it began.
		row.valid_from = yesterday
	row.valid_to = yesterday
	row.save(ignore_permissions=True)
	_history(forum_doc.name, _("{0} ended the delegation {1} to {2}{3}.").format(
		me, delegation, row.delegate, (": " + reason.strip()) if (reason or "").strip() else ""))
	_notify(EVENT_ENDED, row, forum_doc, me)
	return forum_delegates(forum_doc.name)
