"""Escalation analysis: volumes, durations, destinations and outcomes (E-15, E17-S5).

Every figure is read through `frappe.get_list`, never raw SQL, so the numbers a
user sees are the records that user may see: the sensitive-matter restriction
and any row-level permission apply to the analysis exactly as they apply to the
list. Export is the same rows through a CSV writer, so an exported file cannot
contain what the screen would not show.
"""

from __future__ import annotations

import csv
import io
import json

import frappe
from frappe.utils import get_datetime, getdate

MATTER = "Escalation Matter"

#: Grouping happens in Python rather than in SQL, so that every figure comes
#: back through `frappe.get_list` and carries the caller's permissions with it.
PERIODS = ("Month", "Quarter", "Year")


def _loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


def period_of(value, period: str) -> str:
    date = getdate(value)
    if period == "Year":
        return f"{date.year}"
    if period == "Quarter":
        return f"{date.year}-Q{(date.month - 1) // 3 + 1}"
    return f"{date.year}-{date.month:02d}"


def matters(filters: dict | None = None) -> list[dict]:
    """The population under analysis, read with the caller's own permissions."""
    return frappe.get_list(
        MATTER,
        filters=_loads(filters),
        fields=[
            "name",
            "escalation_id",
            "escalation_title",
            "escalation_type",
            "severity",
            "status",
            "is_open",
            "escalation_identification_date",
            "escalation_date",
            "opened_on",
            "closed_on",
            "threshold_breached",
            "breach_count",
            "escalation_matrix",
            "matched_matrix_rule",
        ],
        limit_page_length=0,
        order_by="opened_on asc",
    )


def duration_hours(row) -> float | None:
    """Total time open, in hours. Open matters have no duration yet."""
    if not row.get("closed_on") or not row.get("opened_on"):
        return None
    delta = get_datetime(row["closed_on"]) - get_datetime(row["opened_on"])
    return round(delta.total_seconds() / 3600.0, 2)


def volumes(filters: dict | None = None, period: str = "Month") -> list[dict]:
    """How many matters were raised, by period and by type and severity."""
    buckets: dict[tuple, dict] = {}
    for row in matters(filters):
        key = (
            period_of(row.get("opened_on") or row["escalation_identification_date"], period),
            row["escalation_type"],
            row["severity"],
        )
        bucket = buckets.setdefault(
            key,
            {"period": key[0], "escalation_type": key[1], "severity": key[2], "raised": 0, "closed": 0, "breached": 0},
        )
        bucket["raised"] += 1
        if not row["is_open"]:
            bucket["closed"] += 1
        if row["threshold_breached"]:
            bucket["breached"] += 1
    return sorted(buckets.values(), key=lambda b: (b["period"], b["escalation_type"], b["severity"]))


def durations(filters: dict | None = None, period: str = "Month") -> list[dict]:
    """How long matters stayed open, by period."""
    buckets: dict[str, list[float]] = {}
    for row in matters(filters):
        hours = duration_hours(row)
        if hours is None:
            continue
        buckets.setdefault(period_of(row["closed_on"], period), []).append(hours)
    return [
        {
            "period": key,
            "closed": len(values),
            "mean_hours_open": round(sum(values) / len(values), 2),
            "max_hours_open": max(values),
            "min_hours_open": min(values),
        }
        for key, values in sorted(buckets.items())
    ]


def destinations(filters: dict | None = None) -> list[dict]:
    """Where matters went: the forums on their pathways, and in which role."""
    names = [row["name"] for row in matters(filters)]
    if not names:
        return []
    rows = frappe.get_all(
        "Escalation Forum Link",
        filters={"parenttype": MATTER, "parent": ["in", names]},
        fields=["governance_forum", "role_in_escalation", "count(name) as matters"],
        group_by="governance_forum, role_in_escalation",
        order_by="matters desc",
    )
    return [dict(row) for row in rows]


def outcomes(filters: dict | None = None) -> list[dict]:
    """How matters ended: closure type against matter type."""
    names = [row["name"] for row in matters(filters)]
    if not names:
        return []
    rows = frappe.get_all(
        "Escalation Closure",
        filters={"escalation_matter": ["in", names]},
        fields=["closure_type", "count(name) as matters"],
        group_by="closure_type",
        order_by="matters desc",
    )
    return [dict(row) for row in rows]


@frappe.whitelist()
def summary(filters: dict | str | None = None, period: str = "Month") -> dict:
    filters = _loads(filters)
    return {
        "volumes": volumes(filters, period),
        "durations": durations(filters, period),
        "destinations": destinations(filters),
        "outcomes": outcomes(filters),
    }


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@frappe.whitelist()
def export(view: str = "volumes", filters: dict | str | None = None, period: str = "Month") -> str:
    """A CSV of one analysis view, over the records the caller may read."""
    views = {"volumes": volumes, "durations": durations, "destinations": destinations, "outcomes": outcomes}
    if view not in views:
        frappe.throw(f"Unknown analysis view {view!r}. Known views: {', '.join(sorted(views))}.")
    filters = _loads(filters)
    rows = views[view](filters, period) if view in ("volumes", "durations") else views[view](filters)
    return to_csv(rows)
