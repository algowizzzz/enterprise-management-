"""Retired taxonomy values stay out of pickers, and keep resolving on old records.

E3-S2: a taxonomy value is retired by clearing ``is_active``, never by deleting
it, because records made while it was live still point at it and must still
show it. What retiring has to change is only what is *offered*: a picker for a
new record must not suggest a value the organisation has stopped using.

The framework's link picker asks ``frappe.desk.search.search_widget``, which
defers to a per-DocType function registered under the ``standard_queries``
hook. ``active_only_search`` is that function for every taxonomy. It narrows
the offer to active values and changes nothing else, and it is the only thing
that narrows, so:

* **pickers** (desk link fields, and any portal picker that uses the same search
  endpoint) no longer offer a retired value;
* **existing links** are untouched — a saved record's link is validated by
  ``frappe.client.validate_link`` and titled by ``get_link_title`` and the form
  loader, all of which read the row directly and never go through search, so a
  retired value still resolves and still shows its name;
* **filters and reports** built on ``frappe.get_list`` are untouched, so a
  retired value can still be used to find the old records that carry it.

Why a reimplementation of the search rather than a call back into the
framework's: the framework's search looks up this very hook before doing
anything else, so calling it from here would call this function again.
The body below keeps the framework's contract — the same columns in the same
order (name, then the title, then the search fields), the same text matching,
the same relevance ordering, the same permission handling — so the picker's
display, which relies on that column order, does not change.

Shared-file change requested. ``hooks.py`` needs ``STANDARD_QUERIES`` below,
written out as a literal (hooks are read before the app is importable).
"""

from __future__ import annotations

import frappe
from frappe.desk.search import get_std_fields_list, relevance_sorter
from frappe.model.db_query import get_order_by
from frappe.permissions import has_permission
from frappe.utils import cint
from frappe.utils.data import make_filter_tuple

#: Every taxonomy: the admin-maintained reference tables of S-8, each carrying
#: ``is_active`` (``consilium_core.tests.test_entities.TAXONOMIES`` is the same
#: set, asserted there to carry the field).
TAXONOMY_DOCTYPES = (
    "Risk Category",
    "Risk Type",
    "Legal Entity",
    "Organization Unit",
    "Jurisdiction",
    "Material Entity",
    "Line Of Defence",
    "Organizational Level",
    "Governing Document Type",
    "Governance Forum Type",
    "Governance Forum Role",
    "Governance Responsibility",
    "Escalation Type",
    "Horizon Scanning Coverage Area",
    "Regulatory Requirement",
    "Delegable Action",
    "Document Role",
)

SEARCH = "consilium.consilium_core.taxonomy.active_only_search"

#: The ``standard_queries`` entry for hooks.py.
STANDARD_QUERIES = {doctype: SEARCH for doctype in TAXONOMY_DOCTYPES}

ACTIVE_FIELD = "is_active"

#: The field types the framework matches free text against in a picker.
_TEXT_TYPES = {"Data", "Text", "Small Text", "Long Text", "Link", "Select", "Read Only", "Text Editor"}


def _as_filter_list(doctype: str, filters) -> list:
    if not filters:
        return []
    if isinstance(filters, str):
        filters = frappe.parse_json(filters)
    if isinstance(filters, dict):
        return [make_filter_tuple(doctype, key, value) for key, value in filters.items()]
    return [list(f) for f in filters]


def _names_field(f: list, field: str) -> bool:
    """Whether a filter row, in any of the framework's shapes, is on ``field``."""
    if len(f) >= 4:
        return f[1] == field
    return bool(f) and f[0] == field


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def active_only_search(doctype, txt, searchfield, start, page_len, filters,
                       as_dict=False, reference_doctype=None, ignore_user_permissions=False):
    """The link picker's search for a taxonomy, offering active values only.

    A caller that filters on ``is_active`` itself (an administrator's screen
    that reactivates values, say) is taken at its word and not overridden.
    """
    meta = frappe.get_meta(doctype)
    filter_list = _as_filter_list(doctype, filters)
    if meta.has_field(ACTIVE_FIELD) and not any(_names_field(f, ACTIVE_FIELD) for f in filter_list):
        filter_list.append([doctype, ACTIVE_FIELD, "=", 1])

    or_filters = []
    if txt:
        search_fields = ["name"]
        if meta.title_field:
            search_fields.append(meta.title_field)
        if meta.search_fields:
            search_fields.extend(meta.get_search_fields())
        for field in dict.fromkeys(f.strip() for f in search_fields):
            df = meta.get_field(field)
            if field == "name" or (df and df.fieldtype in _TEXT_TYPES):
                or_filters.append([doctype, field, "like", f"%{txt}%"])

    fields = [f"`tab{doctype}`.`{f.strip()}`" for f in get_std_fields_list(meta, searchfield or "name")]
    ignore_permissions = cint(ignore_user_permissions) and has_permission(
        doctype, ptype="select" if frappe.only_has_select_perm(doctype) else "read",
        parent_doctype=reference_doctype,
    )
    values = frappe.get_list(
        doctype,
        filters=filter_list,
        or_filters=or_filters,
        fields=fields,
        limit_start=cint(start),
        limit_page_length=cint(page_len) or None,
        order_by=f"`tab{doctype}`.idx desc, {get_order_by(doctype, meta)}",
        ignore_permissions=bool(ignore_permissions),
        reference_doctype=reference_doctype,
        as_list=not as_dict,
        strict=False,
    )
    # The framework's own last step: values that start with what was typed first.
    return sorted(values, key=lambda row: relevance_sorter(row, txt or "", as_dict))
