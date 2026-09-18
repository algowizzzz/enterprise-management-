"""Service levels and time limits for forums (G-12).

G-12 asks for "service-level performance" among the forum views, and the
escalation module already showed what that looks like for a matter: how long it
spent in each status against the target configured for that status, and the
clocks Core keeps. Forums had nothing of the kind. This module supplies it, in
two shapes, from the same sources:

* **One forum** (``forum_time_limits``, the *Time limits* tab on ``/forum``):
  how long the forum has spent at each compliance status, each stretch judged
  against a *Time In State* ``SLA Definition`` where one is configured; the same
  for the formation request that created it; the periodic review and the
  annual attestation as dated obligations (due, due soon, overdue); how long
  each compliance review took; and every clock Core keeps on either record.
* **Every forum the viewer may read** (``forum_service_levels``, the *Forum
  time limits* section of ``/reports``): reviews overdue and due soon,
  attestations older than a year, forums waiting on a compliance review and for
  how long, formation requests open and how long decided ones took, the clocks
  running and breached — and the forums past a time limit, each linked.

**Nothing here names a state.** "Waiting on a compliance review" is the forum's
``requires_review`` flag; an open formation request is its ``is_open`` flag;
targets come from the definitions' own ``state_value``. Which statuses have a
target, and how long, is an administrator's choice made in ``SLA Definition``.

**Counts are the viewer's.** Every list is read through ``frappe.get_list``,
so a person restricted to some forums (a user permission, say) is shown totals
over those forums only — the same rule the rest of the reporting page follows.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, get_datetime, getdate, now_datetime, nowdate

from consilium.consilium_core import sla, state_durations

FORUM = "Governance Forum"
REQUEST = "Committee Formation Request"
REVIEW = "Forum Compliance Review"

#: The fields whose values the durations are measured over.
FORUM_STATUS_FIELD = "compliance_status"
REQUEST_STATUS_FIELD = "workflow_state"

#: A forum attests once a year.
ATTESTATION_DAYS = 365
#: "Due soon" for a periodic review.
DUE_SOON_DAYS = 90


def _date(value):
	return getdate(value) if value else None


def review_standing(next_review_on, today) -> dict:
	due = _date(next_review_on)
	if not due:
		return {"standing": "not_set", "due_on": None, "days": None}
	days = date_diff(due, today)
	standing = "overdue" if days < 0 else ("due_soon" if days <= DUE_SOON_DAYS else "on_track")
	return {"standing": standing, "due_on": str(due), "days": days}


def attestation_standing(last_attested_on, today) -> dict:
	last = _date(last_attested_on)
	if not last:
		return {"standing": "never", "last_on": None, "due_on": None, "days": None}
	due = add_days(last, ATTESTATION_DAYS)
	days = date_diff(due, today)
	return {"standing": "overdue" if days < 0 else "on_track", "last_on": str(last), "due_on": str(getdate(due)),
		"days": days}


def _waiting_since(name: str):
	"""When the forum's current compliance-status stretch began."""
	stretches = state_durations.stretches(FORUM, name, FORUM_STATUS_FIELD)
	return get_datetime(stretches[-1]["started_on"]) if stretches else None


def _current_target(name: str, value) -> float | None:
	definition = state_durations.targets(FORUM, name, FORUM_STATUS_FIELD).get(frappe.utils.cstr(value))
	return float(definition.target_hours or 0) if definition else None


# ------------------------------------------------------------------ one forum


@frappe.whitelist(methods=["GET"])
def forum_time_limits(forum: str) -> dict:
	"""The Time limits tab. Anyone who may read the forum.

	The change log is read directly after the permission check on the forum:
	how long a forum a person may read sat at each status tells them nothing
	the forum does not (the same judgement ``escalation.timing`` makes).
	"""
	if not forum or not frappe.db.exists(FORUM, forum):
		frappe.throw(_("There is no forum {0}.").format(forum), frappe.DoesNotExistError)
	frappe.has_permission(FORUM, "read", doc=forum, throw=True)
	doc = frappe.get_doc(FORUM, forum)
	today = getdate(nowdate())

	formation = None
	if doc.formation_request and frappe.db.exists(REQUEST, doc.formation_request):
		readable = bool(frappe.has_permission(REQUEST, "read", doc=doc.formation_request))
		formation = {"request": doc.formation_request, "readable": readable}
		if readable:
			formation["status"] = state_durations.summary(REQUEST, doc.formation_request, REQUEST_STATUS_FIELD)
			formation["clocks"] = state_durations.status_driven_clocks(REQUEST, doc.formation_request)
			formation["decided_on"] = str(frappe.db.get_value(REQUEST, doc.formation_request, "decided_on") or "") \
				or None

	reviews = []
	if frappe.has_permission(REVIEW, "read"):
		for row in frappe.get_list(REVIEW, filters={"forum": forum},
				fields=["name", "review_type", "decision", "reviewer", "creation", "decided_on"],
				order_by="creation desc", limit_page_length=20):
			decided = get_datetime(row.decided_on) if row.decided_on else None
			reviews.append({
				"name": row.name, "review_type": row.review_type, "decision": row.decision,
				"reviewer": row.reviewer, "raised_on": str(row.creation),
				"decided_on": str(decided) if decided else None,
				"days": date_diff(decided or now_datetime(), row.creation),
				"is_decided": bool(decided),
			})

	return {
		"forum": doc.name,
		"as_of": str(today),
		"review": review_standing(doc.next_review_on, today),
		"attestation": attestation_standing(doc.last_attested_on, today),
		"awaiting_review": bool(int(doc.requires_review or 0)),
		"status": state_durations.summary(FORUM, forum, FORUM_STATUS_FIELD),
		"clocks": state_durations.status_driven_clocks(FORUM, forum),
		"formation": formation,
		"reviews": reviews,
		"reviews_readable": bool(frappe.has_permission(REVIEW, "read")),
		"is_active": bool(int(doc.is_active or 0)),
	}


# ------------------------------------------------------------- every forum


def _clock_counts(doctype: str, names: set[str]) -> dict:
	counts = {"running": 0, "breached_running": 0, "breached_ever": 0}
	if not names:
		return counts
	for row in frappe.get_all("SLA Clock", filters={"subject_doctype": doctype, "subject_name": ["in", list(names)]},
			fields=["is_open", "breached_on"], limit_page_length=0):
		open_ = bool(int(row.is_open or 0))
		counts["running"] += 1 if open_ else 0
		counts["breached_running"] += 1 if open_ and row.breached_on else 0
		counts["breached_ever"] += 1 if row.breached_on else 0
	return counts


def _median(values: list[float]) -> float | None:
	if not values:
		return None
	ordered = sorted(values)
	mid = len(ordered) // 2
	return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


@frappe.whitelist(methods=["GET"])
def forum_service_levels() -> dict:
	"""The reporting section, over the forums (and requests) the caller may read."""
	if frappe.session.user == "Guest" or not frappe.has_permission(FORUM, "read"):
		raise frappe.PermissionError(_("Forum reporting is not open to you."))
	today = getdate(nowdate())
	forums = frappe.get_list(FORUM,
		fields=["name", "forum_name", "is_active", "requires_review", "next_review_on", "last_attested_on",
			FORUM_STATUS_FIELD], limit_page_length=0, order_by="forum_name asc")
	active = [f for f in forums if int(f.is_active or 0)]
	late = []
	review = {"overdue": 0, "due_soon": 0, "on_track": 0, "not_set": 0}
	attestation = {"overdue": 0, "never": 0, "on_track": 0}
	for forum in active:
		r = review_standing(forum.next_review_on, today)
		review[r["standing"]] += 1
		if r["standing"] == "overdue":
			late.append({"forum": forum.name, "forum_name": forum.forum_name, "kind": "review",
				"what": _("Periodic review overdue since {0}").format(r["due_on"]), "days_late": -r["days"]})
		a = attestation_standing(forum.last_attested_on, today)
		attestation[a["standing"]] += 1
		if a["standing"] == "overdue":
			late.append({"forum": forum.name, "forum_name": forum.forum_name, "kind": "attestation",
				"what": _("Last attested {0}, more than a year ago").format(a["last_on"]), "days_late": -a["days"]})

	waiting = []
	for forum in forums:
		if not int(forum.requires_review or 0):
			continue
		since = _waiting_since(forum.name)
		days = date_diff(today, since) if since else None
		target = _current_target(forum.name, forum.get(FORUM_STATUS_FIELD))
		over = bool(target is not None and since and
			(now_datetime() - since).total_seconds() / 3600 > target)
		waiting.append({"forum": forum.name, "forum_name": forum.forum_name, "since": str(since) if since else None,
			"days": days, "target_hours": target, "over_target": over})
		if over:
			late.append({"forum": forum.name, "forum_name": forum.forum_name, "kind": "compliance",
				"what": _("Waiting {0} days on a compliance review, past its target").format(days),
				"days_late": days or 0})

	formation = None
	if frappe.has_permission(REQUEST, "read"):
		requests = frappe.get_list(REQUEST, fields=["name", "forum_name", "is_open", "creation", "decided_on"],
			limit_page_length=0)
		open_ages = [date_diff(today, r.creation) for r in requests if int(r.is_open or 0)]
		decided = [date_diff(r.decided_on, r.creation) for r in requests
			if r.decided_on and getdate(r.decided_on) >= add_days(today, -365)]
		formation = {
			"open": len(open_ages),
			"oldest_open_days": max(open_ages) if open_ages else None,
			"decided_last_year": len(decided),
			"median_days_to_decision": _median(decided),
			"clocks": _clock_counts(REQUEST, {r.name for r in requests}),
		}

	late.sort(key=lambda row: row["days_late"] or 0, reverse=True)
	configured = frappe.get_all("SLA Definition",
		filters={"is_active": 1, "target_doctype": ["in", [FORUM, REQUEST]], "measure": ["in", list(sla.STATE_MEASURES)]},
		fields=["name", "title", "target_doctype", "state_value", "target_hours", "calendar"],
		order_by="target_doctype asc, title asc")
	return {
		"as_of": str(today),
		"forums": len(forums),
		"active": len(active),
		"review": review,
		"attestation": attestation,
		"awaiting_review": waiting,
		"forum_clocks": _clock_counts(FORUM, {f.name for f in forums}),
		"formation": formation,
		"late": late[:50],
		"late_total": len(late),
		"definitions": configured,
	}
