"""Semantic state flags — the mechanism behind structural decision M-4.

A workflow-bearing record carries booleans such as ``is_editable``, ``is_active``
and ``requires_review``. Every piece of business logic reads those booleans.
Nothing anywhere compares a workflow state or status label, because that is what
makes renaming a state — or inserting an approval step — a configuration change
rather than a rebuild.

The mapping from a state label to its flags is data: one ``Workflow State Flag``
row per (DocType, state field, state value). State names therefore appear in the
database and in the seed module that populates it, and nowhere else.
``scripts/check_state_flags.py`` fails the build if one appears in a conditional.
"""

from __future__ import annotations

import frappe
from frappe import _

#: The flags a state may set. A record receives only the ones it declares.
FLAG_FIELDS = (
    "is_editable",
    "is_active",
    "requires_review",
    "is_open",
    "is_committable",
    "requires_statement",
)

CACHE_PREFIX = "consilium_core:state_flags"


def _cache_key(doctype: str) -> str:
    return f"{CACHE_PREFIX}:{doctype}"


def clear_cache(doctype: str | None = None) -> None:
    cache = frappe.cache()
    if doctype:
        cache.delete_value(_cache_key(doctype))
    else:
        cache.delete_keys(f"{CACHE_PREFIX}:*")


def get_flag_map(doctype: str) -> dict[str, dict[str, dict[str, int]]]:
    """``{state_field: {state_value: {flag: 0|1}}}`` for one DocType."""
    key = _cache_key(doctype)
    cached = frappe.cache().get_value(key)
    if cached is not None:
        return cached

    mapping: dict[str, dict[str, dict[str, int]]] = {}
    if frappe.db.table_exists("Workflow State Flag"):
        rows = frappe.get_all(
            "Workflow State Flag",
            filters={"target_doctype": doctype},
            fields=["state_field", "state_value", *FLAG_FIELDS],
        )
        for row in rows:
            mapping.setdefault(row["state_field"], {})[row["state_value"]] = {
                flag: int(row[flag] or 0) for flag in FLAG_FIELDS
            }

    frappe.cache().set_value(key, mapping)
    return mapping


def flags_for(doctype: str, state_field: str, state_value: str) -> dict[str, int] | None:
    return get_flag_map(doctype).get(state_field, {}).get(state_value)


def apply_state_flags(doc) -> None:
    """Set the semantic flags a record declares, from its configured state labels.

    Called from ``validate`` on every workflow-bearing Core record. A state label
    with no configured row is a configuration gap and is refused loudly: silently
    leaving stale flags would let logic act on a state it does not understand.
    """
    mapping = get_flag_map(doc.doctype)
    if not mapping:
        return

    meta = doc.meta
    for state_field, by_value in mapping.items():
        if not (meta.has_field(state_field) or state_field == "workflow_state"):
            continue
        value = doc.get(state_field)
        if value in (None, ""):
            continue
        flags = by_value.get(value)
        if flags is None:
            frappe.throw(
                _(
                    "No semantic state flags are configured for {0}, field {1}, value {2}. "
                    "Add a Workflow State Flag row: business logic reads the flags, never the label."
                ).format(doc.doctype, state_field, value),
                title=_("State Flags Not Configured"),
            )
        for flag, flag_value in flags.items():
            if meta.has_field(flag):
                doc.set(flag, flag_value)
