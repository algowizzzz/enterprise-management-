"""Meeting minutes, and the notices a meeting's schedule raises (G-14).

A meeting's minutes are a record of what was decided, so they are versioned
exactly as a charter is: each correction appends a version to the meeting's
chain and the meeting points at the latest one. Nothing is overwritten, and the
minutes as they stood on any past date can be read back.

Until this existed nothing wrote ``Forum Meeting.minutes_version``, so a held
meeting could never carry its minutes.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import format_datetime, get_datetime, getdate, now_datetime

from consilium.consilium_core import versioning


def record_minutes(meeting, minutes: str, *, change_summary: str | None = None,
                   body_file: str | None = None):
    """Append the minutes as a new version and point the meeting at it."""
    if isinstance(meeting, str):
        meeting = frappe.get_doc("Forum Meeting", meeting)
    if not (minutes or "").strip() and not body_file:
        frappe.throw(_("Minutes need either their text or an attached file."), title=_("Minutes Required"))
    first = not meeting.minutes_version
    version = versioning.create_version(
        meeting,
        change_summary=change_summary or (_("Minutes recorded") if first else _("Minutes corrected")),
        body_text=minutes or None,
        body_file=body_file,
        retention_class=frappe.db.get_value("Governance Forum", meeting.forum, "retention_class")
        if meeting.forum else None,
    )
    meeting.db_set("minutes_version", version.name, update_modified=True)
    return version


@frappe.whitelist(methods=["POST"])
def record_meeting_minutes(meeting: str, minutes: str | None = None, change_summary: str | None = None,
                           body_file: str | None = None) -> dict:
    """The workspace's entry point. Whoever may edit the meeting may minute it."""
    doc = frappe.get_doc("Forum Meeting", meeting)
    doc.check_permission("write")
    version = record_minutes(doc, minutes or "", change_summary=change_summary, body_file=body_file)
    return {"meeting": doc.name, "minutes_version": version.name, "version_number": version.version_number}


# ---------------------------------------------------------------------------
# Meeting-schedule notifications (G-14, O-4).
#
# A forum's members are told when a meeting is scheduled, when a scheduled
# meeting moves (its time or its place), and when one that has not yet taken
# place is cancelled. Wired from the meeting's controller (``on_update``), so
# every door — the desk, the portal, an import — tells them the same way.
#
# What happened is read from the meeting's semantic flags, never its status
# label: a meeting that is ``is_open`` is still to be held, and one that stops
# being ``is_active`` was called off. A meeting whose time has already passed
# is not announced — recording last month's meeting is not scheduling it.
# ---------------------------------------------------------------------------

EVENT_SCHEDULED = "governance.meeting.scheduled"
EVENT_RESCHEDULED = "governance.meeting.rescheduled"
EVENT_CANCELLED = "governance.meeting.cancelled"


def meeting_audience(meeting) -> list[str]:
    """Who hears about a meeting: the forum's members with a seat open on the
    meeting's date (and any delegate standing in for one), its chair and its
    secretary."""
    from consilium.governance import membership

    on_date = getdate(meeting.scheduled_on) if meeting.scheduled_on else None
    people = []
    for seat in membership.members_as_at(meeting.forum, on_date) if meeting.forum else []:
        people.append(seat.get("member"))
        if seat.get("delegate"):
            people.append(seat.get("delegate"))
    people += [meeting.get("chaired_by"), meeting.get("secretary")]
    seen, out = set(), []
    for person in people:
        if person and person not in seen:
            seen.add(person)
            out.append(person)
    return out


def _is_future(value) -> bool:
    return bool(value) and get_datetime(value) >= get_datetime(now_datetime())


def _when(value) -> str:
    return format_datetime(value, "dd MMM yyyy HH:mm") if value else ""


def meeting_event(meeting, before) -> tuple[str, dict] | None:
    """The event this save of ``meeting`` raises, with its context, or None.

    ``before`` is the meeting as it stood before the save (None on insert).
    """
    if before is None:
        if meeting.is_open and _is_future(meeting.scheduled_on):
            return EVENT_SCHEDULED, {}
        return None
    if before.get("is_active") and not meeting.is_active:
        if _is_future(before.get("scheduled_on")):
            return EVENT_CANCELLED, {}
        return None
    if not (meeting.is_open and _is_future(meeting.scheduled_on)):
        return None
    moved = get_datetime(before.get("scheduled_on")) != get_datetime(meeting.scheduled_on)
    relocated = (before.get("location") or "") != (meeting.location or "")
    if not before.get("is_open"):
        # Back on the calendar after being held open no longer (an adjourned
        # meeting set again, say): announced as a new schedule.
        return EVENT_SCHEDULED, {}
    if moved or relocated:
        return EVENT_RESCHEDULED, {
            "previous_scheduled_on": _when(before.get("scheduled_on")),
            "previous_location": before.get("location") or "",
        }
    return None


def announce(meeting) -> list[str]:
    """Raise the meeting's schedule event, if this save made one. Never raises:
    the meeting is saved whether or not the notice could be sent."""
    from consilium.consilium_core import notification

    try:
        found = meeting_event(meeting, meeting.get_doc_before_save())
        if not found:
            return []
        event, extra = found
        forum_name = frappe.db.get_value("Governance Forum", meeting.forum, "forum_name") if meeting.forum else ""
        context = {
            "forum_name": forum_name or meeting.forum or "",
            "meeting_reference": meeting.meeting_reference or meeting.name,
            "scheduled_on": _when(meeting.scheduled_on),
            "location": meeting.location or "",
            **extra,
        }
        return notification.notify(event, meeting_audience(meeting), context, "Forum Meeting", meeting.name)
    except Exception:
        frappe.log_error(title=_("Meeting notice for {0} failed").format(meeting.name),
                         message=frappe.get_traceback())
        return []
