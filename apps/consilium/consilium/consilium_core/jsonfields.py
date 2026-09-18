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


def normalise_loaded(doc, method=None) -> None:
    """The same normalisation, for a record that has just been read.

    ``normalise`` covers the way in; this covers the way out. PostgreSQL hands a
    ``JSON`` column back already parsed, and the framework serialises a record
    through ``as_dict``, which turns a dict back into text but refuses a list
    outright ("Value for Holidays cannot be a list"). A record whose JSON field
    holds a list — a calendar's holidays, the fields that triggered a review, an
    import row's messages — therefore could not be opened on the desk at all:
    the form came back blank with that message. Wired to ``onload``, which the
    desk runs before it sends the record, and called from a controller's
    ``load_from_db`` where a record is also read over the REST interface.
    """
    normalise(doc, method)
