"""JSON columns, written back the way they were stored.

The framework hands a ``JSON`` column back parsed — a dict or a list — but
refuses to write one back in that form. A record loaded, touched and saved would
therefore fail on a field nobody edited. This normalises Consilium's own JSON
fields on the way in, so callers can pass either form and round-trips work.
"""

from __future__ import annotations

import json

import frappe

MODULES = {"Consilium Core", "Governance", "Policy", "Escalation"}


def normalise(doc, method=None) -> None:
    if getattr(doc, "meta", None) is None or doc.meta.module not in MODULES:
        return
    for field in doc.meta.get("fields", {"fieldtype": "JSON"}):
        value = doc.get(field.fieldname)
        if isinstance(value, dict | list):
            doc.set(field.fieldname, json.dumps(value, default=str))
