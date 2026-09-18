"""Service-level clocks.

The framework supplies no service-level tracking, so one clock per record per
definition is kept here. Which records a definition applies to, what it measures
and against which calendar are all configuration; nothing in this module names a
workflow state.

What a definition measures (``SLA Definition.measure``):

* **Total Open Time** and **Time To Close** — started and stopped by the module
  that owns the record (escalation matters, intake requests), because only that
  module knows what "opened" and "closed" mean for it.
* **Time In State** — a clock runs for every stretch a record spends with its
  configured ``state_field`` equal to ``state_value``. Entering the state starts
  a clock; leaving stops it; coming back starts a new one. This is what makes a
  lifecycle step (P-7) or a status duration (E-13) measurable.
* **Time To First Action** — from the record's creation to the first recorded
  change to ``state_field`` (or, with no state field, to any recorded change).

The last two are driven by the record's status changes, and those are read from
the framework's change log (``Version``) rather than from a hook alone, for two
reasons. A hook sees only changes made while it was installed, and a scheduler
that was down for a day would otherwise leave clocks that start "when we
noticed" rather than when the record moved. So ``sync_state_clocks`` rebuilds
each record's stretches in the state from its history and makes the clocks
match — idempotently, hourly. ``on_subject_update`` does the same thing live
when it is wired as a document event, so a warning does not wait for the hour.
Both need the target DocType to track changes, which the definition's
validation insists on.

The sweep marks clocks past their target as breached and, once per clock, warns
when a running clock passes ``warning_threshold_pct`` of its time.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, cstr, get_datetime, now

WEEKDAY_FIELDS = (
    "works_monday", "works_tuesday", "works_wednesday", "works_thursday",
    "works_friday", "works_saturday", "works_sunday",
)

#: The measure options this module interprets. These are the option labels of
#: a configuration field, not workflow states.
MEASURE_TIME_IN_STATE = "Time In State"
MEASURE_FIRST_ACTION = "Time To First Action"
STATE_MEASURES = (MEASURE_TIME_IN_STATE, MEASURE_FIRST_ACTION)

#: How far a clock's start may sit from the change-log entry it corresponds to
#: and still be the same stretch. A live hook stamps the save's time moments
#: before the framework writes its Version row; minutes, not seconds, so a slow save or a
#: clock skew between workers does not produce a duplicate clock.
MATCH_TOLERANCE = timedelta(minutes=5)

#: Record fields naming who answers for a record, in the order they are tried.
#: A warning goes to whichever of these the measured DocType has and has
#: filled; a record with none goes to its creator.
RESPONSIBLE_FIELDS = (
    "response_owner", "owner_user", "document_owner", "forum_owner", "responsible",
    "reviewer", "requester", "assigned_to", "accountable_executive",
)

#: DocTypes whose owning module sends its own, richer breach notice, and the
#: field on the record naming the one definition that module handles. The sweep
#: does not send a second, generic notice for *that* clock. The escalation module
#: raises a matter's severity and notifies its matrix groups when the resolution
#: threshold its matrix imposed (``sla_definition``) is breached
#: (``resolution.notify_breach``); any other clock on a matter — a Time In State
#: or First Action measure — is not the module's to raise, so its breach is
#: announced here like any other record's.
BREACH_NOTIFIED_ELSEWHERE = {"Escalation Matter": "sla_definition"}


def _breach_notified_elsewhere(clock) -> bool:
    field = BREACH_NOTIFIED_ELSEWHERE.get(clock.subject_doctype)
    if not field:
        return False
    return frappe.db.get_value(clock.subject_doctype, clock.subject_name, field) == clock.sla_definition

_STATE_DOCTYPES_CACHE = "consilium_core:sla_state_doctypes"
_SYNC_WATERMARK = "consilium_sla_state_sync:{0}"


def _loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


def _business_target(start, hours: float, calendar) -> str:
    """Advance ``hours`` of working time from ``start``, honouring the calendar."""
    cursor = get_datetime(start)
    remaining = timedelta(hours=hours)
    holidays = set(_loads(calendar.holidays, []))
    day_start, day_end = calendar.day_start, calendar.day_end
    guard = 0
    while remaining > timedelta(0) and guard < 3650:
        guard += 1
        works = calendar.get(WEEKDAY_FIELDS[cursor.weekday()])
        if not works or str(cursor.date()) in holidays:
            cursor = get_datetime(f"{cursor.date()} 00:00:00") + timedelta(days=1)
            continue
        window_start = max(cursor, get_datetime(f"{cursor.date()} {day_start}"))
        window_end = get_datetime(f"{cursor.date()} {day_end}")
        if window_start >= window_end:
            cursor = get_datetime(f"{cursor.date()} 00:00:00") + timedelta(days=1)
            continue
        available = window_end - window_start
        if available >= remaining:
            return str(window_start + remaining)
        remaining -= available
        cursor = get_datetime(f"{cursor.date()} 00:00:00") + timedelta(days=1)
    return str(cursor)


def target_datetime(definition, started_on) -> str:
    if definition.calendar == "Business Hours" and definition.business_calendar:
        calendar = frappe.get_doc("Business Calendar", definition.business_calendar)
        return _business_target(started_on, float(definition.target_hours or 0), calendar)
    return add_to_date(get_datetime(started_on), hours=float(definition.target_hours or 0), as_string=True)


def applies_to(definition, doctype: str, name: str) -> bool:
    if definition.target_doctype != doctype:
        return False
    filters = _loads(definition.applies_when)
    if not filters:
        return True
    filters["name"] = name
    return bool(frappe.db.exists(doctype, filters))


def _new_clock(definition, subject_doctype: str, subject_name: str, started_on):
    return frappe.get_doc(
        {
            "doctype": "SLA Clock",
            "sla_definition": definition.name,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "started_on": started_on,
            "target_on": target_datetime(definition, started_on),
            "status": "Running",
        }
    ).insert(ignore_permissions=True)


def start_clock(sla_definition: str, subject_doctype: str, subject_name: str, started_on=None):
    definition = frappe.get_doc("SLA Definition", sla_definition)
    started_on = started_on or now()
    existing = frappe.db.get_value(
        "SLA Clock",
        {
            "sla_definition": sla_definition,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "is_open": 1,
        },
        "name",
    )
    if existing:
        return frappe.get_doc("SLA Clock", existing)
    return _new_clock(definition, subject_doctype, subject_name, started_on)


def stop_clock(clock, stopped_on=None):
    if isinstance(clock, str):
        clock = frappe.get_doc("SLA Clock", clock)
    stopped_on = stopped_on or now()
    elapsed = (get_datetime(stopped_on) - get_datetime(clock.started_on)).total_seconds()
    clock.stopped_on = stopped_on
    clock.elapsed_seconds = int(elapsed) - int(clock.paused_seconds or 0)
    breached = get_datetime(stopped_on) > get_datetime(clock.target_on)
    clock.status = "Breached" if breached else "Met"
    if breached:
        # A clock the sweep already breached keeps the moment it breached; the
        # stop records when the stretch ended, which is a different fact.
        clock.breached_on = clock.breached_on or stopped_on
    clock.save(ignore_permissions=True)
    return clock


# ------------------------------------------------------------ notifications


def responsible_users(doctype: str, name: str) -> list[str]:
    """Who answers for a measured record: see ``RESPONSIBLE_FIELDS``."""
    if not frappe.db.exists(doctype, name):
        return []
    meta = frappe.get_meta(doctype)
    fields = [
        f for f in RESPONSIBLE_FIELDS
        if (df := meta.get_field(f)) and df.fieldtype == "Link" and df.options == "User"
    ]
    values = frappe.db.get_value(doctype, name, [*fields, "owner"], as_dict=True) or {}
    users = []
    for field in fields:
        if values.get(field) and values[field] not in users:
            users.append(values[field])
    return users or [values.get("owner")]


def _clock_context(clock, definition) -> dict:
    return {
        "clock": clock.name,
        "definition": definition.name,
        "definition_title": definition.title,
        "measure": definition.measure,
        "threshold_pct": int(definition.warning_threshold_pct or 0),
        "state_value": definition.state_value,
        "started_on": str(clock.started_on),
        "target_on": str(clock.target_on),
    }


def _send(event_code: str, clock, definition) -> list[str]:
    from consilium.consilium_core import notification

    try:
        return notification.notify(
            event_code,
            responsible_users(clock.subject_doctype, clock.subject_name),
            _clock_context(clock, definition),
            clock.subject_doctype,
            clock.subject_name,
        )
    except Exception:
        # The sweep's job is the clock. A notification that cannot be sent is
        # logged; it must not leave the next clock unswept.
        frappe.log_error(title=_("Service-level notice for {0} failed").format(clock.name),
                         message=frappe.get_traceback())
        return []


def warning_due_at(clock, definition):
    """When a clock passes its warning threshold, or None if it has none.

    A share of the clock's span from start to target. On a business-hours
    calendar that span includes nights and weekends, so the warning lands a
    little early rather than late — the safer error for a warning.
    """
    pct = int(definition.warning_threshold_pct or 0)
    if pct <= 0 or pct >= 100:
        return None
    start, target = get_datetime(clock.started_on), get_datetime(clock.target_on)
    return start + (target - start) * (pct / 100)


def sweep(as_of=None) -> list[str]:
    """Mark open clocks past their target as breached, and warn those near it.

    Reads the semantic flag, never the status label. Each clock is warned at
    most once (``warning_sent_on``) and breached at most once (a breached clock
    is no longer open), so running the sweep hourly repeats nothing.
    """
    as_of = get_datetime(as_of or now())
    breached = []
    definitions: dict[str, object] = {}
    for name in frappe.get_all("SLA Clock", filters={"is_open": 1}, pluck="name"):
        clock = frappe.get_doc("SLA Clock", name)
        if clock.sla_definition not in definitions:
            definitions[clock.sla_definition] = frappe.get_doc("SLA Definition", clock.sla_definition)
        definition = definitions[clock.sla_definition]

        if get_datetime(clock.target_on) < as_of:
            clock.status = "Breached"
            clock.breached_on = now()
            clock.save(ignore_permissions=True)
            breached.append(name)
            if not _breach_notified_elsewhere(clock):
                _send("sla.breached", clock, definition)
            continue

        warn_at = warning_due_at(clock, definition)
        if warn_at and not clock.warning_sent_on and as_of >= warn_at:
            clock.db_set("warning_sent_on", now(), update_modified=False)
            _send("sla.warning", clock, definition)
    return breached


# ------------------------------------------------- clocks driven by status


def state_measured_doctypes() -> set[str]:
    """DocTypes some active Time In State / First Action definition measures.

    Cached, because ``on_subject_update`` runs on every save of every record
    and must cost nothing for the DocTypes nobody measures. The SLA Definition
    controller clears it.
    """
    cached = frappe.cache().get_value(_STATE_DOCTYPES_CACHE)
    if cached is not None:
        return set(cached)
    doctypes = set()
    if frappe.db.table_exists("SLA Definition"):
        doctypes = set(
            frappe.get_all(
                "SLA Definition",
                filters={"is_active": 1, "measure": ["in", STATE_MEASURES]},
                pluck="target_doctype",
            )
        )
    frappe.cache().set_value(_STATE_DOCTYPES_CACHE, sorted(doctypes))
    return doctypes


def clear_cache() -> None:
    frappe.cache().delete_value(_STATE_DOCTYPES_CACHE)


def _state_definitions(doctype: str | None = None) -> list:
    filters = {"is_active": 1, "measure": ["in", STATE_MEASURES]}
    if doctype:
        filters["target_doctype"] = doctype
    return [frappe.get_doc("SLA Definition", n) for n in frappe.get_all("SLA Definition", filters=filters, pluck="name")]


def _versions(doctype: str, name: str) -> list[tuple]:
    """``(when, data)`` for each change-log entry, oldest first."""
    out = []
    for row in frappe.get_all(
        "Version",
        filters={"ref_doctype": doctype, "docname": name},
        fields=["creation", "data"],
        order_by="creation asc",
    ):
        try:
            out.append((get_datetime(row.creation), _loads(row.data)))
        except ValueError:
            continue
    return out


def _matches(value, wanted) -> bool:
    return cstr(value) == cstr(wanted)


def state_intervals(definition, record: dict) -> list[tuple]:
    """Each stretch the record spent in the configured state: ``(start, end|None)``.

    Rebuilt from the change log. The value at creation is the "old" side of the
    first logged change to the field, or, if it never changed, today's value.
    A stretch still open in the log but not today (the field was written
    without a log entry) is closed at the record's last modification — the
    best evidence there is of when it moved.
    """
    field, wanted = definition.state_field, definition.state_value
    changes = []
    for when, data in _versions(definition.target_doctype, record["name"]):
        for entry in data.get("changed") or []:
            if entry and entry[0] == field:
                changes.append((when, entry[1], entry[2]))

    initial = changes[0][1] if changes else record.get(field)
    open_start = get_datetime(record["creation"]) if _matches(initial, wanted) else None
    intervals = []
    for when, _old, new in changes:
        if open_start is None and _matches(new, wanted):
            open_start = when
        elif open_start is not None and not _matches(new, wanted):
            intervals.append((open_start, when))
            open_start = None
    if open_start is not None:
        if _matches(record.get(field), wanted):
            intervals.append((open_start, None))
        else:
            left = get_datetime(record["modified"])
            intervals.append((open_start, left if left > open_start else get_datetime(now())))
    return intervals


def first_action_interval(definition, record: dict) -> list[tuple]:
    """From creation to the first logged change (to ``state_field`` if one is set)."""
    field = definition.state_field
    created = get_datetime(record["creation"])
    for when, data in _versions(definition.target_doctype, record["name"]):
        if when <= created:
            continue
        if field:
            acted = any(entry and entry[0] == field for entry in data.get("changed") or [])
        else:
            acted = any(data.get(key) for key in ("changed", "added", "removed", "row_changed"))
        if acted:
            return [(created, when)]
    return [(created, None)]


def sync_subject(definition, name: str) -> list[str]:
    """Make one record's clocks for one definition match its history.

    Idempotent: a stretch that already has a clock (started within
    ``MATCH_TOLERANCE`` of it) is left alone except to stop it when the stretch
    has ended. Stretches that ended before the definition existed are not
    back-filled — switching a definition on should not invent a history of
    breaches nobody was measuring.
    """
    doctype = definition.target_doctype
    fields = ["name", "creation", "modified"]
    if definition.state_field:
        fields.append(definition.state_field)
    record = frappe.db.get_value(doctype, name, fields, as_dict=True)
    if not record or not applies_to(definition, doctype, name):
        return []

    if definition.measure == MEASURE_TIME_IN_STATE:
        intervals = state_intervals(definition, record)
    else:
        intervals = first_action_interval(definition, record)
    defined_on = get_datetime(definition.creation)
    intervals = [(s, e) for s, e in intervals if e is None or e >= defined_on]

    clocks = frappe.get_all(
        "SLA Clock",
        filters={"sla_definition": definition.name, "subject_doctype": doctype, "subject_name": name},
        fields=["name", "started_on", "stopped_on", "is_open"],
        order_by="started_on asc",
    )
    matched: dict[int, dict] = {}
    used = set()
    for index, (start, _end) in enumerate(intervals):
        for clock in clocks:
            if clock.name not in used and abs(get_datetime(clock.started_on) - start) <= MATCH_TOLERANCE:
                matched[index] = clock
                used.add(clock.name)
                break

    touched = []
    # An open clock that matches no stretch is stale — the record left the
    # state by a path the log does not show. It is cancelled, not stopped, so
    # it cannot count as met or breached, and so a new clock can be started.
    for clock in clocks:
        if clock.is_open and clock.name not in used:
            doc = frappe.get_doc("SLA Clock", clock.name)
            doc.status = "Cancelled"
            doc.stopped_on = now()
            doc.save(ignore_permissions=True)
            touched.append(clock.name)

    for index, (start, end) in enumerate(intervals):
        clock = matched.get(index)
        if clock is None:
            doc = _new_clock(definition, doctype, name, start)
            if end:
                stop_clock(doc, end)
            touched.append(doc.name)
        elif end and not clock.stopped_on:
            stop_clock(clock.name, end)
            touched.append(clock.name)
    return touched


def sync_state_clocks(doctype: str | None = None, names: list[str] | None = None) -> list[str]:
    """Bring every Time In State / First Action clock up to date. Hourly.

    Looks only at records changed since the last run (with an hour's overlap)
    and records with a clock still open, so the cost follows activity rather
    than the size of the table. The first run for a definition looks at
    everything, once.
    """
    touched = []
    for definition in _state_definitions(doctype):
        run_started = now()
        key = _SYNC_WATERMARK.format(definition.name)
        try:
            if names is not None:
                subjects = list(names)
            else:
                filters = {}
                since = frappe.db.get_default(key)
                if since:
                    filters["modified"] = [">=", add_to_date(get_datetime(since), hours=-1)]
                subjects = set(frappe.get_all(definition.target_doctype, filters=filters, pluck="name"))
                subjects |= set(
                    frappe.get_all(
                        "SLA Clock",
                        filters={"sla_definition": definition.name, "is_open": 1},
                        pluck="subject_name",
                    )
                )
        except Exception:
            frappe.log_error(title=_("SLA {0}: records to measure could not be read").format(definition.name),
                             message=frappe.get_traceback())
            continue
        for name in sorted(subjects):
            try:
                touched.extend(sync_subject(definition, name))
            except Exception:
                frappe.log_error(title=_("SLA {0}: clock for {1} could not be synchronised").format(
                    definition.name, name), message=frappe.get_traceback())
        if names is None:
            frappe.db.set_default(key, run_started)
    return touched


def on_subject_update(doc, method=None) -> None:
    """Start or stop status-driven clocks the moment a record moves.

    For wiring as a document event (``doc_events["*"]["on_update"]``). The
    framework writes its change-log entry *after* ``on_update``, so this reads
    the before and after values directly rather than the log, and stamps the
    save's own ``modified`` time, which the log entry follows by moments; the hourly
    ``sync_state_clocks`` then recognises the clock it started as the same
    stretch. Costs one cached set lookup for a DocType nobody measures.
    """
    if doc.doctype not in state_measured_doctypes():
        return
    before = doc.get_doc_before_save()
    for definition in _state_definitions(doc.doctype):
        try:
            _live_update(definition, doc, before)
        except Exception:
            frappe.log_error(title=_("SLA {0}: live clock update for {1} failed").format(
                definition.name, doc.name), message=frappe.get_traceback())


def _open_clock(definition, doc) -> str | None:
    return frappe.db.get_value(
        "SLA Clock",
        {"sla_definition": definition.name, "subject_doctype": doc.doctype,
         "subject_name": doc.name, "is_open": 1},
        "name",
    )


def _live_update(definition, doc, before) -> None:
    field, wanted = definition.state_field, definition.state_value
    if definition.measure == MEASURE_TIME_IN_STATE:
        was_in = before is not None and _matches(before.get(field), wanted)
        is_in = _matches(doc.get(field), wanted)
        if is_in and not was_in and applies_to(definition, doc.doctype, doc.name):
            start_clock(definition.name, doc.doctype, doc.name,
                        started_on=doc.modified if before else doc.creation)
        elif was_in and not is_in:
            clock = _open_clock(definition, doc)
            if clock:
                stop_clock(clock, stopped_on=doc.modified)
        return

    if before is None:
        if applies_to(definition, doc.doctype, doc.name):
            start_clock(definition.name, doc.doctype, doc.name, started_on=doc.creation)
        return
    if field:
        acted = not _matches(before.get(field), doc.get(field))
    else:
        from frappe.core.doctype.version.version import get_diff

        acted = bool(get_diff(before, doc))
    if acted:
        clock = _open_clock(definition, doc)
        # First action only: a clock that has already stopped is not restarted.
        if clock:
            stop_clock(clock, stopped_on=doc.modified)
