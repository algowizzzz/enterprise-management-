"""How long a record spent in each state, and against which target (E-13, P-7).

``sla.py`` keeps a clock for each stretch a record spends in a state that some
Time In State definition measures. That answers "is this step late?" for the
steps someone configured; it does not answer "where has this matter spent its
life?", which is what a person reading the record asks first. This module
answers the second question, from the same evidence, and puts the first
beside it.

**The evidence is the change log.** Every stretch is rebuilt from the
framework's ``Version`` rows for the record — the value at creation is the
"old" side of the first logged change, and each logged change closes one
stretch and opens the next. Nothing is stored, so there is nothing to drift:
the figures are as good as the history, and a record whose field was written
without a log entry has its last stretch closed at its last modification, the
best evidence there is (the same rule ``sla.state_intervals`` applies).

**Targets are configuration.** A state's target is the active ``SLA
Definition`` measuring *Time In State* on this DocType, for this field and
this value, that applies to the record. The module never names a state: it
compares the record's history with the definitions' own ``state_value``, and
a state nobody configured simply has no target. Each stretch is judged
against its target on the definition's calendar, so a business-hours target
does not breach overnight. Where Core has kept a clock for the stretch, its
recorded breach is taken as well — the clock is the record of what the
platform said at the time.

Durations are elapsed wall-clock time. The target is on the definition's
calendar; the two are shown side by side rather than converted, because
"five days in review, target two working days" is what a reader can check.
"""

from __future__ import annotations

import frappe
from frappe.utils import cstr, get_datetime, now

from consilium.consilium_core import sla


def _as_str(value) -> str | None:
    return str(value) if value else None


def stretches(doctype: str, name: str, field: str) -> list[dict]:
    """Each stretch the record spent with ``field`` at one value, oldest first.

    ``[{"value", "started_on", "ended_on"}]``; the last stretch is still open
    (``ended_on`` None). Empty when the record does not exist.
    """
    record = frappe.db.get_value(doctype, name, ["name", "creation", "modified", field], as_dict=True)
    if not record:
        return []
    changes = []
    for when, data in sla._versions(doctype, name):
        for entry in data.get("changed") or []:
            if entry and entry[0] == field:
                changes.append((when, entry[1], entry[2]))

    current = record.get(field)
    value = changes[0][1] if changes else current
    start = get_datetime(record.creation)
    out: list[dict] = []
    for when, _old, new in changes:
        if cstr(new) == cstr(value):
            continue
        # A change logged before the record's own creation time is a record
        # whose creation was re-stamped (an import, a migration). The stretch
        # before it is empty rather than negative.
        when = max(when, start)
        out.append({"value": value, "started_on": start, "ended_on": when})
        value, start = new, when
    if cstr(value) != cstr(current):
        left = max(get_datetime(record.modified), start)
        out.append({"value": value, "started_on": start, "ended_on": left})
        value, start = current, left
    out.append({"value": value, "started_on": start, "ended_on": None})
    return out


def targets(doctype: str, name: str, field: str) -> dict[str, object]:
    """``{state value: SLA Definition}`` for the definitions that apply to the record.

    Where two definitions measure the same value, the one with the shorter
    target wins: it is the one the record can breach first.
    """
    found: dict[str, object] = {}
    for definition in sla._state_definitions(doctype):
        if definition.measure != sla.MEASURE_TIME_IN_STATE or definition.state_field != field:
            continue
        if not sla.applies_to(definition, doctype, name):
            continue
        key = cstr(definition.state_value)
        held = found.get(key)
        if held is None or float(definition.target_hours or 0) < float(held.target_hours or 0):
            found[key] = definition
    return found


def _clocks_for(doctype: str, name: str, definitions: list[str]) -> list[dict]:
    if not definitions:
        return []
    return frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": doctype, "subject_name": name, "sla_definition": ["in", definitions]},
        fields=["name", "sla_definition", "started_on", "stopped_on", "target_on", "breached_on",
                "warning_sent_on", "is_open", "status"],
        order_by="started_on asc",
    )


def summary(doctype: str, name: str, field: str, as_of=None) -> dict:
    """Every stretch with its duration and its judgement, and the totals per value.

    A stretch's ``outcome`` is this module's own vocabulary, not a state label:
    ``no_target``, ``within`` (ended inside its target), ``running`` (still in
    the state, inside its target), ``warning`` (still in it, past the
    definition's warning threshold), or ``breached``.
    """
    as_of = get_datetime(as_of or now())
    by_value = targets(doctype, name, field)
    clocks = _clocks_for(doctype, name, [d.name for d in by_value.values()])

    rows = []
    for stretch in stretches(doctype, name, field):
        start = get_datetime(stretch["started_on"])
        end = get_datetime(stretch["ended_on"]) if stretch["ended_on"] else None
        seconds = max(0, int(((end or as_of) - start).total_seconds()))
        row = {
            "value": stretch["value"],
            "started_on": _as_str(start),
            "ended_on": _as_str(end),
            "seconds": seconds,
            "is_current": end is None,
            "definition": None, "definition_title": None, "target_hours": None,
            "target_on": None, "clock": None, "outcome": "no_target",
        }
        definition = by_value.get(cstr(stretch["value"]))
        if definition:
            target_on = get_datetime(sla.target_datetime(definition, start))
            clock = next(
                (c for c in clocks
                 if c.sla_definition == definition.name
                 and abs(get_datetime(c.started_on) - start) <= sla.MATCH_TOLERANCE),
                None,
            )
            breached = (end or as_of) > target_on or bool(clock and clock.breached_on)
            if breached:
                outcome = "breached"
            elif end is not None:
                outcome = "within"
            else:
                warn_at = sla.warning_due_at(frappe._dict(started_on=start, target_on=target_on), definition)
                outcome = "warning" if warn_at and as_of >= warn_at else "running"
            row.update({
                "definition": definition.name,
                "definition_title": definition.title,
                "target_hours": float(definition.target_hours or 0),
                "calendar": definition.calendar,
                "target_on": _as_str(target_on),
                "clock": clock.name if clock else None,
                "outcome": outcome,
            })
        rows.append(row)

    totals: dict[str, dict] = {}
    for row in rows:
        key = cstr(row["value"])
        total = totals.setdefault(key, {
            "value": row["value"], "seconds": 0, "visits": 0, "breaches": 0, "is_current": False,
            "definition": row["definition"], "definition_title": row["definition_title"],
            "target_hours": row["target_hours"],
        })
        total["seconds"] += row["seconds"]
        total["visits"] += 1
        total["breaches"] += 1 if row["outcome"] == "breached" else 0
        total["is_current"] = total["is_current"] or row["is_current"]

    return {
        "field": field,
        "as_of": _as_str(as_of),
        "stretches": rows,
        "totals": list(totals.values()),
        "configured": [
            {"value": value, "definition": d.name, "definition_title": d.title,
             "target_hours": float(d.target_hours or 0), "calendar": d.calendar,
             "warning_threshold_pct": int(d.warning_threshold_pct or 0)}
            for value, d in by_value.items()
        ],
    }


def status_driven_clocks(doctype: str, name: str) -> list[dict]:
    """Every status-driven clock Core keeps on the record, with its definition.

    For display beside the durations: the time-in-state clocks behind the
    judgements above, and any others (a clock on a semantic flag, such as the
    second-line challenge of an escalation).
    """
    definitions = {
        d.name: d for d in (
            frappe.get_all(
                "SLA Definition",
                filters={"target_doctype": doctype, "measure": ["in", list(sla.STATE_MEASURES)]},
                fields=["name", "title", "measure", "state_field", "state_value", "target_hours", "calendar"],
            )
        )
    }
    out = []
    for clock in _clocks_for(doctype, name, list(definitions)):
        definition = definitions[clock.sla_definition]
        out.append({
            "name": clock.name,
            "definition": definition.name,
            "definition_title": definition.title,
            "measure": definition.measure,
            "state_field": definition.state_field,
            "state_value": definition.state_value,
            "target_hours": float(definition.target_hours or 0),
            "started_on": _as_str(clock.started_on),
            "stopped_on": _as_str(clock.stopped_on),
            "target_on": _as_str(clock.target_on),
            "breached_on": _as_str(clock.breached_on),
            "is_open": int(clock.is_open or 0),
            "status": clock.status,
        })
    return out
