"""Install and migrate entry points for the Policy module.

> **Shared-file change requested.** Nothing calls this yet. Core's
> ``hooks.py`` wires ``after_install`` and ``after_migrate`` to Core's own
> install module, and this module must be added to both:
>
>     after_install = [
>         "consilium.consilium_core.setup.install.after_install",
>         "consilium.policy.setup.install.after_install",
>     ]
>     after_migrate = [
>         "consilium.consilium_core.setup.install.after_migrate",
>         "consilium.policy.setup.install.after_migrate",
>     ]
>
> ``consilium/consilium_core/setup/constraints.py`` also needs the Policy index
> statements listed at the bottom of this module; the framework's ALTER path does
> not preserve objects it did not create, so they have to be re-applied after
> every migrate from a module Core already calls.
>
> Until those two edits are made the Policy tests seed this themselves, so the
> behaviour is exercised; a fresh site is simply unconfigured.
"""

from __future__ import annotations

import frappe

from consilium.policy.setup import seed

#: §7.1/§7.2 of 03-schema.md: the PostgreSQL builder creates neither the child
#: parent index nor the `modified` index, and index names are schema-wide, so
#: every name is table-prefixed.
INDEX_STATEMENTS = [
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_governing_document__owner_phase"
       ON "tabGoverning Document" ("document_owner", "is_active")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_governing_document__type"
       ON "tabGoverning Document" ("document_type", "lifecycle_phase")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_governing_document__parent_document"
       ON "tabGoverning Document" ("parent_document")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_horizon_scan__document"
       ON "tabHorizon Scan" ("document", "scan_date")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_policy_violation__document"
       ON "tabPolicy Violation" ("document", "is_open")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_review_cycle__document"
       ON "tabDocument Review Cycle" ("document", "due_on")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_publication__document"
       ON "tabDocument Publication" ("document", "document_version")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_exemption__document"
       ON "tabApplicability Exemption" ("document", "is_active")''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_lifecycle_gate__unique"
       ON "tabDocument Lifecycle Gate" ("target_doctype", "state_field", "state_value", "gate")''',
]

#: Child tables need (parent, parenttype, parentfield); the PostgreSQL builder
#: creates none of them.
CHILD_TABLES = [
    "Document Accountability Role", "Document Relationship", "Document Applicability",
    "Document Regulatory Reference", "Glossary Term Link", "Glossary Synonym",
    "Template Section", "Horizon Scan Source", "Implementation Task", "Publication Audience",
    "Approval Route Step", "Document Organization Unit", "Document Legal Entity",
    "Document Jurisdiction", "Document Risk Type", "Document Material Entity",
    "Horizon Scan Coverage", "Horizon Scan Impacted Document", "Intake Party",
    "Implementation Working Group", "Implementation Reference",
]

PARENT_TABLES = [
    "Governing Document", "Document Intake Request", "Applicability Exemption",
    "Document Review Cycle", "Monitoring Activity", "Monitoring Result", "Policy Violation",
    "Glossary Term", "Horizon Scan", "Horizon Scan Finding", "Implementation Plan",
    "Document Publication", "Metadata Remediation Task", "Document Template",
    "Approval Route", "Document Lifecycle Gate",
]


def _slug(table: str) -> str:
    return table.lower().replace(" ", "_")


def apply_indexes() -> list[str]:
    applied: list[str] = []
    if frappe.conf.db_type != "postgres":
        return applied

    for statement in INDEX_STATEMENTS:
        table = statement.split('"')[3]
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        frappe.db.sql_ddl(statement)
        applied.append(statement.split('"')[1])

    for table in CHILD_TABLES:
        if not frappe.db.table_exists(table):
            continue
        name = f"ix_consilium_{_slug(table)}__parent"
        frappe.db.sql_ddl(
            f'CREATE INDEX IF NOT EXISTS "{name}" ON "tab{table}" ("parent", "parenttype", "parentfield")'
        )
        applied.append(name)

    for table in PARENT_TABLES:
        if not frappe.db.table_exists(table):
            continue
        name = f"ix_consilium_{_slug(table)}__modified"
        frappe.db.sql_ddl(f'CREATE INDEX IF NOT EXISTS "{name}" ON "tab{table}" ("modified")')
        applied.append(name)

    return applied


def after_install() -> None:
    seed.seed_all()
    apply_indexes()
    frappe.db.commit()


def after_migrate() -> None:
    seed.seed_all()
    applied = apply_indexes()
    frappe.db.commit()
    if applied:
        print(f"Consilium Policy: {len(applied)} database objects re-applied.")
