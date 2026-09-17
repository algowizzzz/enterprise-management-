"""The escalation file-import path (D-18, E21-S1, E21-S4).

Integrations are out of scope, so a matter raised in another system arrives as a
file. The pipeline is Core's — the batch keeps the file and its hash, each row
keeps its raw and mapped payload, validation happens before anything is written,
and the foreign identifier survives as an `External Reference`. This module adds
only what a flat file cannot express: a matter's impacted entities are a child
table, and the mapping engine maps columns to fields.

So the two impacted-entity columns are left out of the profile's field mappings,
read from the row's *raw* payload here, and attached to the mapped payload before
Core commits it. Core still does the writing, which is what keeps the audit trail
and the rollback story intact.
"""

from __future__ import annotations

import json

import frappe

from consilium.consilium_core import importing as core_importing

#: The columns a file uses for the impacted entity. Kept out of the profile's
#: mappings because they describe a child row, not a field.
ENTITY_TYPE_COLUMN = "impacted_entity_type"
ENTITY_VALUE_COLUMN = "impacted_entity"


def _loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


def stage(batch, rows: list[dict] | None = None) -> dict:
    """Validate a batch without writing a matter. Core's staging, unchanged."""
    return core_importing.validate_batch(batch, rows)


def attach_impacted_entities(batch) -> int:
    """Turn each row's impacted-entity columns into the child rows a matter needs."""
    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)

    attached = 0
    for name in frappe.get_all("Import Row", filters={"import_batch": batch.name}, pluck="name"):
        row = frappe.get_doc("Import Row", name)
        raw = _loads(row.raw_payload)
        value = raw.get(ENTITY_VALUE_COLUMN)
        if not value:
            continue
        mapped = _loads(row.mapped_payload)
        mapped["impacted_entities"] = [
            {
                "entity_type": raw.get(ENTITY_TYPE_COLUMN) or "Legal Entity",
                "entity_value": value,
            }
        ]
        row.mapped_payload = json.dumps(mapped, default=str)
        row.save(ignore_permissions=True)
        attached += 1
    return attached


def commit(batch) -> dict:
    """Write the staged rows. Core commits; this only prepares the child rows."""
    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)
    attach_impacted_entities(batch)
    batch.reload()
    return core_importing.commit_batch(batch)
