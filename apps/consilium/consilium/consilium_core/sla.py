"""Service-level clocks.

The framework supplies no service-level tracking, so one clock per record per
definition is kept here. Which records a definition applies to, what it measures
and against which calendar are all configuration; nothing in this module names a
workflow state.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, get_datetime, now

WEEKDAY_FIELDS = (
    "works_monday", "works_tuesday", "works_wednesday", "works_thursday",
    "works_friday", "works_saturday", "works_sunday",
)


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
    return frappe.get_doc(
        {
            "doctype": "SLA Clock",
            "sla_definition": sla_definition,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "started_on": started_on,
            "target_on": target_datetime(definition, started_on),
            "status": "Running",
        }
    ).insert(ignore_permissions=True)


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
        clock.breached_on = stopped_on
    clock.save(ignore_permissions=True)
    return clock


def sweep(as_of=None) -> list[str]:
    """Mark open clocks past their target as breached. Reads the semantic flag."""
    as_of = get_datetime(as_of or now())
    breached = []
    for name in frappe.get_all("SLA Clock", filters={"is_open": 1}, pluck="name"):
        clock = frappe.get_doc("SLA Clock", name)
        if get_datetime(clock.target_on) < as_of:
            clock.status = "Breached"
            clock.breached_on = now()
            clock.save(ignore_permissions=True)
            breached.append(name)
    return breached
