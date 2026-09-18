"""Setup for the Escalation module: state flags, roles and the import path.

**Shared-file change requested.** `after_migrate` in `consilium/hooks.py` should
call `consilium.escalation.setup.install.after_migrate` alongside Core's, and
`scheduler_events["daily"]` should include
`consilium.escalation.resolution.sweep_breaches`. Until then this module is
invoked by hand and by the tests.

`ensure_state_flags` is a stand-in for a Core change, not a second mechanism:
the rows it writes are exactly `ESCALATION_STATE_FLAGS`, and they belong in
Core's seed table. It is written to be a no-op once they are there.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import state_flags
from consilium.escalation.setup import constraints
from consilium.escalation.state_flag_seed import ESCALATION_STATE_FLAGS, FLAG_COLUMNS

#: Access roles this module's permission rows refer to, plus the one that is not
#: a permission row at all: sensitive access is checked in code, on every read
#: path, because a DocPerm cannot express a per-record restriction.
ROLES = (
    "Escalation Owner",
    "Escalation Reviewer",
    "Sensitive Escalation Access",
)

IMPORT_SYSTEM = "ESC_FILE"
IMPORT_PROFILE_TITLE = "Escalation Matter — file import"


def ensure_roles() -> None:
    for role in ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
                ignore_permissions=True
            )


def ensure_state_flags() -> None:
    """Write the module's semantic flag rows. Rows already present are left alone."""
    for row in ESCALATION_STATE_FLAGS:
        doctype, state_field, state_value = row[0], row[1], row[2]
        if not frappe.db.exists("DocType", doctype):
            continue
        if frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
            "name",
        ):
            continue
        frappe.get_doc(
            {
                "doctype": "Workflow State Flag",
                "target_doctype": doctype,
                "state_field": state_field,
                "state_value": state_value,
                **dict(zip(FLAG_COLUMNS, row[3:], strict=True)),
            }
        ).insert(ignore_permissions=True)
    state_flags.clear_cache()


def ensure_import_profile() -> str:
    """The file import path that stands in for an escalation feed (D-18, E21).

    Integrations are out of scope, so an inbound matter arrives as a file through
    Core's governed pipeline: a batch keeps the file and its hash, rows keep both
    payloads, and the foreign identifier survives as an External Reference.
    """
    if not frappe.db.exists("External System", IMPORT_SYSTEM):
        frappe.get_doc(
            {
                "doctype": "External System",
                "system_code": IMPORT_SYSTEM,
                "title": "Escalation file import",
                "description": "The file drop that replaces an escalation feed while integrations are out of scope.",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

    existing = frappe.db.get_value("Import Profile", {"profile_title": IMPORT_PROFILE_TITLE}, "name")
    if existing:
        return existing

    mappings = [
        ("escalation_title", "escalation_title", "Trim", None, None, 1),
        ("escalation_type", "escalation_type", "Lookup", "Escalation Type", "escalation_type_code", 1),
        ("identification_date", "escalation_identification_date", "Date Parse", None, None, 1),
        ("escalation_date", "escalation_date", "Date Parse", None, None, 0),
        ("description", "description", "Trim", None, None, 1),
        ("tier_1_risk_type", "tier_1_risk_type", "Lookup", "Risk Type", "risk_type_code", 1),
        ("identified_by", "identified_by", "Trim", None, None, 1),
        ("organizational_level", "organizational_level", "Lookup", "Organizational Level", "organizational_level_code", 1),
        ("accountable_executive", "accountable_executive", "Trim", None, None, 1),
        ("escalation_trigger", "escalation_trigger", "Trim", None, None, 1),
        ("severity", "severity", "Trim", None, None, 1),
    ]
    profile = frappe.get_doc(
        {
            "doctype": "Import Profile",
            "profile_title": IMPORT_PROFILE_TITLE,
            "source_system": IMPORT_SYSTEM,
            "target_doctype": "Escalation Matter",
            "key_strategy": "External Key",
            "external_key_column": "external_id",
            "on_missing_required": "Reject Row",
            "on_unknown_taxonomy": "Reject Row",
            "on_duplicate_key": "Update",
            "is_active": 1,
            "mappings": [
                {
                    "source_column": source,
                    "target_fieldname": target,
                    "transform": transform,
                    "lookup_doctype": lookup_doctype,
                    "lookup_field": lookup_field,
                    "is_required": required,
                }
                for source, target, transform, lookup_doctype, lookup_field, required in mappings
            ],
        }
    ).insert(ignore_permissions=True)
    return profile.name


#: The escalation workflow as configuration (E-8, `consilium.escalation.transitions`).
#:
#: ``ESC-ANY`` is the catch-all: any matter may move from any state it is worked
#: in to any other, and be closed from any of them, by whoever holds it at its
#: stage — which is exactly how the portal behaved before moves were
#: configurable, so seeding it changes nothing.
#:
#: The ``ESC-HIGH-*`` rows are the demonstrative stricter workflow for High
#: severity: a High matter must go to second-line review before it can be
#: closed. From its first state it may only be sent for review; the reviewer
#: hands it back to be worked; and only then may the owner close it. They are
#: seeded **inactive**, so no High matter changes behaviour until an
#: administrator switches them on (all together: a partial set can leave a state
#: with no way out). Once active they replace, for High matters only, the
#: catch-all — the most specific set of matching rules is the one that applies.
#:
#: Columns: rule code, type, severity, from, to, role, active, description.
TRANSITION_RULES = (
    ("ESC-ANY", None, None, None, None, None, 1,
     "Any matter may move between the states it is worked in, and be closed, by whoever holds it."),
    ("ESC-HIGH-OPEN-REVIEW", None, "High", "Open", "Under Review", None, 0,
     "A new High matter goes to second-line review first."),
    ("ESC-HIGH-OPEN-PENDING", None, "High", "Open", "Pending Review", None, 0,
     "A new High matter goes to second-line review first."),
    ("ESC-HIGH-WORK-REVIEW", None, "High", "In Progress", "Under Review", None, 0,
     "A High matter being worked may go back to review."),
    ("ESC-HIGH-WORK-PENDING", None, "High", "In Progress", "Pending Review", None, 0,
     "A High matter being worked may go back to review."),
    ("ESC-HIGH-REVIEW-BACK", None, "High", "Under Review", "In Progress", "Escalation Reviewer", 0,
     "The second line hands a reviewed High matter back to be worked."),
    ("ESC-HIGH-PENDING-BACK", None, "High", "Pending Review", "In Progress", "Escalation Reviewer", 0,
     "The second line hands a reviewed High matter back to be worked."),
    ("ESC-HIGH-CLOSE", None, "High", "In Progress", "Closed", "Escalation Owner", 0,
     "A High matter is closed only once it has been through review and handed back."),
    ("ESC-HIGH-CLOSE-EXTERNAL", None, "High", "In Progress", "Closed — Tracked Externally", "Escalation Owner", 0,
     "A High matter is closed only once it has been through review and handed back."),
)


def ensure_transition_rules() -> None:
    """Seed the transition rules. A rule already present — edited, deactivated or
    switched on by an administrator — is left exactly as it is."""
    if not frappe.db.table_exists("Escalation Transition Rule"):
        return
    for code, escalation_type, severity, from_status, to_status, role, active, description in TRANSITION_RULES:
        if frappe.db.exists("Escalation Transition Rule", code):
            continue
        if role and not frappe.db.exists("Role", role):
            continue
        frappe.get_doc({
            "doctype": "Escalation Transition Rule",
            "rule_code": code,
            "escalation_type": escalation_type,
            "severity": severity,
            "from_status": from_status,
            "to_status": to_status,
            "allowed_role": role,
            "is_active": active,
            "description": description,
        }).insert(ignore_permissions=True)


def after_migrate() -> None:
    ensure_roles()
    ensure_state_flags()
    ensure_import_profile()
    ensure_transition_rules()
    applied = constraints.apply()
    frappe.db.commit()
    if applied:
        print(f"Consilium Escalation: {len(applied)} database objects re-applied.")
