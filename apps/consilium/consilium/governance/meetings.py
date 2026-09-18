"""Meeting minutes.

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
