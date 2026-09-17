"""Append-only enforcement for audit artefacts.

The database cannot make a row immutable — see `03-schema.md` §9. Immutability
here is three things together: no application path that mutates, database
privileges revoked from the application role in deployment, and a hash chain that
makes an out-of-band edit detectable. This module is the first of the three.

Every refusal is audited out of band and names the field that was touched.
"""

from __future__ import annotations

import datetime
import json

import frappe

from consilium.consilium_core import audit

_FRAMEWORK_FIELDS = {
    "creation", "modified", "modified_by", "owner", "docstatus", "idx",
    "_user_tags", "_comments", "_assign", "_liked_by",
}


def _normalise(value):
    """Compare values as the database would hold them.

    A JSON column is handed back parsed on one path and raw on the other, and an
    empty string and a null are the same absence. Neither difference is an edit.
    """
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        # One path hands back a string and the other a datetime; the value is
        # the same and the difference is not an edit.
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "["):
            try:
                return json.dumps(json.loads(text), sort_keys=True, default=str)
            except ValueError:
                return text
        return text
    return value


def changed_fields(doc, ignore: set[str] | None = None) -> list[str]:
    before = doc.get_doc_before_save()
    if not before:
        return []
    ignore = (ignore or set()) | _FRAMEWORK_FIELDS
    changed = []
    for field in doc.meta.get_valid_columns():
        if field in ignore:
            continue
        if _normalise(before.get(field)) != _normalise(doc.get(field)):
            changed.append(field)
    return changed


def guard_update(doc, *, allowed: tuple[str, ...] = (), permit_flag: str | None = None, control: str) -> None:
    """Refuse a change to anything outside ``allowed``."""
    if doc.is_new():
        return
    changed = changed_fields(doc)
    if permit_flag is None or doc.flags.get(permit_flag):
        # Either the DocType allows these fields outright (an integrity sweep
        # writing its result), or the caller has declared the exception.
        forbidden = [f for f in changed if f not in allowed]
    else:
        # The exception was not declared, so nothing at all may change.
        forbidden = changed
    if not forbidden:
        return
    audit.refuse(
        f"{doc.doctype} {doc.name} is append-only: {', '.join(sorted(forbidden))} cannot be changed "
        f"after the record is written. Write a new record instead.",
        subject_doctype=doc.doctype,
        subject_name=doc.name,
        attempted_action="Modify",
        control=control,
        context={"fields": sorted(forbidden)},
    )


def guard_delete(doc, *, control: str) -> None:
    audit.refuse(
        f"{doc.doctype} {doc.name} is append-only and cannot be deleted: it is the audit record.",
        subject_doctype=doc.doctype,
        subject_name=doc.name,
        attempted_action="Delete",
        control=control,
    )
