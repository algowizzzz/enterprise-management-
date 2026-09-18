"""Regulatory-change import: a change feed arrives as a file (P-6, O-7).

The regulatory-change feed is a connector the baseline takes out of scope
(S-2): a change reaches the platform as a delimited file, through Core's
governed import pipeline — the batch keeps the file and its hash, each row its
raw and mapped payload, a reviewer commits. This module adds the two things a
*change* feed needs that a generic import of records does not:

1. **An import profile that is always there.** Seeded with the Policy module's
   configuration, so the policy office can bring in a change file on a site
   with no AI features and no one having pressed a set-up button. It is keyed
   on the requirement's code and updates on a match: a row naming an existing
   requirement changes it, a row naming a new one creates it. The optional
   ``Change Reference`` column is kept as the change's External Reference
   against the feed, so each change can be traced to the line of the file that
   brought it. (The regulatory-updates page creates a profile of the same title
   on demand; whichever runs first makes it and the other finds it.)

2. **A preparer that makes a blank cell mean "unchanged".** A change feed
   carries what changed. Core's commit writes every mapped field, so an empty
   ``Citation`` column would erase the citation of every requirement the file
   touches. Before Core commits, ``prepare_changes`` drops the empty values of
   rows that update an existing requirement, says on each row what it will
   change, and leaves out (``Skipped``, with the reason) a row that would
   change nothing. It is registered under Core's ``consilium_import_preparers``
   hook for ``Regulatory Requirement``, so Core stays ignorant of it.

The fan-out — telling the owner of every document and forum that cites a
changed requirement — is not here. It happens because committing a row
*saves* the requirement, and the requirement's controller notifies its citers
on every save that changes its substance
(``regulatory_requirement.notify_citing_owners``). A file and a hand edit
reach the owners by the same route.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cstr

REQUIREMENT = "Regulatory Requirement"

#: Shared with the regulatory-updates page, which finds the profile by title.
PROFILE_TITLE = "Regulatory changes — file import"
SOURCE_SYSTEM = "REGULATORY-FEED"

KEY_COLUMN = "Code"
CHANGE_REFERENCE_COLUMN = "Change Reference"

#: (source column, target field, transform, required, lookup doctype, lookup field)
MAPPINGS = [
    (KEY_COLUMN, "regulatory_requirement_code", "Trim", 1, None, None),
    ("Name", "regulatory_requirement_name", "Trim", 0, None, None),
    ("Citation", "citation", "Trim", 0, None, None),
    ("Regulator", "regulator", "Trim", 0, None, None),
    ("Jurisdiction", "jurisdiction", "Lookup", 0, "Jurisdiction", "jurisdiction_code"),
    ("Effective Date", "effective_date", "Date Parse", 0, None, None),
    ("Summary", "summary", "None", 0, None, None),
    ("Description", "description", "None", 0, None, None),
]


def ensure_source_system() -> str:
    if not frappe.db.exists("External System", SOURCE_SYSTEM):
        frappe.get_doc(
            {
                "doctype": "External System",
                "system_code": SOURCE_SYSTEM,
                "title": "Regulatory change feed (file)",
                "description": "Delimited files of regulatory changes, imported by hand.",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
    return SOURCE_SYSTEM


def ensure_profile() -> str | None:
    """The regulatory-change import profile, created once. An existing one is left as it is."""
    if not (frappe.db.table_exists("Import Profile") and frappe.db.exists("DocType", REQUIREMENT)):
        return None
    existing = frappe.db.get_value("Import Profile", {"profile_title": PROFILE_TITLE}, "name")
    if existing:
        return existing
    ensure_source_system()
    return frappe.get_doc(
        {
            "doctype": "Import Profile",
            "profile_title": PROFILE_TITLE,
            "source_system": SOURCE_SYSTEM,
            "target_doctype": REQUIREMENT,
            "key_strategy": "Natural Key",
            "natural_key_fieldname": "regulatory_requirement_code",
            "external_key_column": CHANGE_REFERENCE_COLUMN,
            "on_missing_required": "Reject Row",
            "on_unknown_taxonomy": "Reject Row",
            "on_duplicate_key": "Update",
            "is_active": 1,
            "mappings": [
                {
                    "source_column": column,
                    "target_fieldname": field,
                    "transform": transform,
                    "is_required": required,
                    "lookup_doctype": lookup_doctype,
                    "lookup_field": lookup_field,
                }
                for column, field, transform, required, lookup_doctype, lookup_field in MAPPINGS
            ],
        }
    ).insert(ignore_permissions=True).name


def _loads(value, default):
    if not value:
        return default
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


def prepare_changes(batch) -> dict:
    """Finish each staged row of a regulatory-change batch before Core commits it.

    Registered for ``Regulatory Requirement`` under ``consilium_import_preparers``,
    so it runs for any batch committed into requirements, through any profile.
    Only committable rows are touched; a row already refused keeps its refusal.
    """
    from consilium.consilium_core import importing
    from consilium.consilium_core.doctype.regulatory_requirement.regulatory_requirement import (
        SUBSTANTIVE_FIELDS,
    )

    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)
    profile = frappe.get_doc("Import Profile", batch.import_profile)
    key_field = profile.natural_key_fieldname or "regulatory_requirement_code"
    labels = {df.fieldname: df.label for df in frappe.get_meta(REQUIREMENT).fields}

    counts = {"changes": 0, "new": 0, "unchanged": 0}
    for name in frappe.get_all(
        "Import Row", filters={"import_batch": batch.name, "is_committable": 1}, pluck="name",
        order_by="row_number asc",
    ):
        row = frappe.get_doc("Import Row", name)
        mapped = _loads(row.mapped_payload, {})
        messages = _loads(row.messages, [])
        existing = frappe.db.get_value(REQUIREMENT, {key_field: mapped.get(key_field)}, "name") \
            if mapped.get(key_field) else None

        if not existing:
            counts["new"] += 1
            messages.append(_("new requirement"))
            row.messages = json.dumps(messages)
            row.save(ignore_permissions=True)
            continue

        # A blank cell in a change feed means "no change to this field".
        mapped = {field: value for field, value in mapped.items() if value not in (None, "")}
        current = frappe.get_doc(REQUIREMENT, existing)
        changing = [
            field for field, value in mapped.items()
            if field in SUBSTANTIVE_FIELDS and cstr(current.get(field)) != cstr(value)
        ]
        row.mapped_payload = json.dumps(mapped, default=str)
        if changing:
            counts["changes"] += 1
            messages.append(
                _("changes {0}: {1}").format(existing, ", ".join(_(labels.get(f, f)) for f in changing))
            )
        else:
            counts["unchanged"] += 1
            messages.append(_("no substantive change to {0}; left out").format(existing))
            row.status = importing.EXCLUDED_ROW_STATUS
        row.messages = json.dumps(messages)
        row.save(ignore_permissions=True)
    return counts
