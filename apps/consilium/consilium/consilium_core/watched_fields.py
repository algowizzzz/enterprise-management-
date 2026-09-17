"""Watched fields.

"A change to certain fields triggers a compliance review" — with the set of
fields admin-editable rather than compiled in. One ``Watched Field Set`` per
target DocType; the action it takes on a trigger is configuration too.

``reset_to_state`` is read and written as configuration. It is never compared.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import notification

CACHE_KEY = "consilium_core:watched_doctypes"


def clear_cache(*args, **kwargs) -> None:
    frappe.cache().delete_value(CACHE_KEY)


def _watched_doctypes() -> list[str]:
    cached = frappe.cache().get_value(CACHE_KEY)
    if cached is not None:
        return cached
    values = []
    if frappe.db.table_exists("Watched Field Set"):
        values = frappe.get_all("Watched Field Set", filters={"is_active": 1}, pluck="target_doctype")
    frappe.cache().set_value(CACHE_KEY, values)
    return values


# Row keys that say nothing about whether the content changed. Two loads of the
# same unchanged child row differ in every one of these.
_ROW_NOISE = frozenset({
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "parent", "parentfield", "parenttype", "doctype", "__islocal", "__unsaved",
})


def _comparable(value):
    """Reduce a field value to something two loads of the same data compare equal on.

    A child-table field does not hold a value, it holds a list of documents, and
    two loads of the same unchanged rows are never equal: different Python
    objects, different `name` values for unsaved rows, different `modified`
    timestamps. Compared directly, a watched child-table field reports a change
    on every single save — which means a forum tagged with risk types would go
    back for compliance review every time anyone touched it, for any reason.

    So a list of rows becomes a sorted set of their meaningful values, and order
    is deliberately ignored: rearranging the same rows is not a change.
    """
    if isinstance(value, (list, tuple)):
        rows = []
        for row in value:
            data = row.as_dict() if hasattr(row, "as_dict") else dict(row or {})
            rows.append(tuple(sorted(
                (k, str(v)) for k, v in data.items()
                if k not in _ROW_NOISE and not k.startswith("_") and v not in (None, "")
            )))
        return tuple(sorted(rows))
    return value


def _triggered(mode: str, before, after) -> bool:
    if mode == "Set To Empty":
        return bool(before) and not after
    if mode == "Set From Empty":
        return not before and bool(after)
    if mode == "Value Increase":
        try:
            return float(after or 0) > float(before or 0)
        except (TypeError, ValueError):
            return False
    return _comparable(before) != _comparable(after)


def changed_watched_fields(doc) -> list[dict]:
    """Which watched fields this save changed, and how."""
    if doc.doctype not in _watched_doctypes() or doc.is_new():
        return []
    before = doc.get_doc_before_save()
    if not before:
        return []

    field_set = frappe.get_doc("Watched Field Set", doc.doctype)
    hits = []
    for watched in field_set.fields:
        old, new = before.get(watched.fieldname), doc.get(watched.fieldname)
        if _triggered(watched.compare_mode, old, new):
            hits.append(
                {"fieldname": watched.fieldname, "label": watched.label, "from": old, "to": new,
                 "compare_mode": watched.compare_mode}
            )
    return hits


def on_update(doc, method=None) -> list[dict]:
    """``on_update`` hook: apply the configured action when a watched field changed."""
    hits = changed_watched_fields(doc)
    if not hits:
        return []

    field_set = frappe.get_doc("Watched Field Set", doc.doctype)
    summary = ", ".join(hit["label"] or hit["fieldname"] for hit in hits)

    if field_set.on_change_action == "Reset Workflow State" and field_set.reset_to_state:
        state_field = "workflow_state" if doc.meta.has_field("workflow_state") else None
        if state_field:
            # The target state is configuration, written as given. Nothing here
            # compares it, and the semantic flags are recomputed from the new value.
            doc.db_set(state_field, field_set.reset_to_state)
    elif field_set.on_change_action == "Raise Review Task":
        if doc.meta.has_field("requires_review"):
            doc.db_set("requires_review", 1)
        frappe.get_doc(
            {
                "doctype": "ToDo",
                "reference_type": doc.doctype,
                "reference_name": doc.name,
                "description": f"Compliance review: watched field(s) changed — {summary}.",
                "allocated_to": doc.modified_by,
            }
        ).insert(ignore_permissions=True)
    elif field_set.on_change_action == "Notify Only" and field_set.notify_channel:
        notification.dispatch(
            field_set.notify_channel,
            doc.modified_by,
            subject=f"Watched field changed on {doc.doctype} {doc.name}",
            body=f"Changed: {summary}.",
            subject_doctype=doc.doctype,
            subject_name=doc.name,
        )
    return hits
