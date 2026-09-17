"""Database objects the framework will not create, re-applied after every migrate.

Three groups, all from `03-schema.md`:

* §9.3 — uniqueness the framework cannot express, as partial unique indexes.
  Exactly one current version per subject, no gaps or repeats in version
  numbering, and one attestation task per (campaign, participant, record).
* §7.1 — the indexes the PostgreSQL schema builder omits but the MariaDB one
  creates, notably ``modified``, plus the lookup indexes this model needs.
* §9.3 — a cheap CHECK constraint as a backstop behind an application validation.

The framework's ALTER path does not preserve objects it did not create, which is
why this runs from ``after_migrate`` rather than once.
"""

from __future__ import annotations

import frappe

#: Index names are schema-wide in PostgreSQL, so every name here is prefixed and
#: distinctive — see `03-schema.md` §7.2 on the collision hazard.
STATEMENTS = [
    # --- §9.3 uniqueness -------------------------------------------------
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_document_version__current"
       ON "tabDocument Version" ("subject_doctype", "subject_name")
       WHERE "is_current" = 1 AND "docstatus" < 2''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_document_version__number"
       ON "tabDocument Version" ("subject_doctype", "subject_name", "version_number")
       WHERE "docstatus" < 2''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_attestation_task__unique"
       ON "tabAttestation Task" ("campaign", "assigned_to", "subject_doctype", "subject_name")
       WHERE "docstatus" < 2''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_state_flag__unique"
       ON "tabWorkflow State Flag" ("target_doctype", "state_field", "state_value")''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_campaign__period"
       ON "tabAttestation Campaign" ("campaign_type", "period_label")
       WHERE "docstatus" < 2''',
    # --- §7.1 indexes the PostgreSQL builder omits -----------------------
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_document_version__subject"
       ON "tabDocument Version" ("subject_doctype", "subject_name", "version_number")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_archive_record__subject"
       ON "tabArchive Record" ("subject_doctype", "subject_name")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_external_reference__subject"
       ON "tabExternal Reference" ("subject_doctype", "subject_name")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_external_reference__key"
       ON "tabExternal Reference" ("external_system", "external_key")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_import_row__batch"
       ON "tabImport Row" ("import_batch", "row_number")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_attestation_task__assignee"
       ON "tabAttestation Task" ("assigned_to", "is_open")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_approval_decision__subject"
       ON "tabApproval Decision" ("subject_doctype", "subject_name", "is_open")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_refusal_log__subject"
       ON "tabGovernance Refusal Log" ("subject_doctype", "subject_name")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_delegation__delegate"
       ON "tabAuthority Delegation" ("delegate", "is_active")''',
]

#: ``ADD CONSTRAINT`` has no IF NOT EXISTS, so each is guarded by a catalogue read.
CHECK_CONSTRAINTS = [
    (
        "tabAuthority Delegation",
        "ck_consilium_delegation__dates",
        '''CHECK ("valid_to" IS NULL OR "valid_from" IS NULL OR "valid_to" >= "valid_from")''',
    ),
    (
        "tabDocument Version",
        "ck_consilium_document_version__number",
        '''CHECK ("version_number" > 0)''',
    ),
]

#: Tables the framework leaves without a ``modified`` index on PostgreSQL.
MODIFIED_INDEX_TABLES = [
    "tabDocument Version",
    "tabAttestation Task",
    "tabNotification Dispatch",
    "tabImport Row",
    "tabApproval Decision",
    "tabGovernance Refusal Log",
    "tabArchive Record",
]


def apply() -> list[str]:
    """Create everything that is missing. Safe to run on every migrate."""
    applied = []
    if frappe.conf.db_type != "postgres":
        # These statements are written for PostgreSQL only, which is the
        # supported engine; nothing is attempted elsewhere.
        return applied

    for statement in STATEMENTS:
        table = statement.split('"')[3] if '"' in statement else None
        if table and not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        frappe.db.sql_ddl(statement)
        applied.append(statement.split('"')[1])

    for table in MODIFIED_INDEX_TABLES:
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        index_name = f"ix_consilium_{table.replace('tab', '', 1).lower().replace(' ', '_')}__modified"
        frappe.db.sql_ddl(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ("modified")')
        applied.append(index_name)

    for table, name, definition in CHECK_CONSTRAINTS:
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        exists = frappe.db.sql(
            """SELECT 1 FROM pg_constraint WHERE conname = %s""", (name,)
        )
        if exists:
            continue
        frappe.db.sql_ddl(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')
        applied.append(name)

    return applied
