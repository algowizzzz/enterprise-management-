"""Database objects for the Escalation module, re-applied after every migrate.

The framework's ALTER path does not preserve objects it did not create, which is
why these are re-applied rather than created once — the same reason Core keeps
`consilium_core/setup/constraints.py`. **Core change requested:** these belong in
that module's `STATEMENTS` list once the three modules ship together; they are
here because the Escalation module may not edit Core.

Index names are schema-wide in PostgreSQL, so each is prefixed and distinctive
(`03-schema.md` §7.2).
"""

from __future__ import annotations

import frappe

STATEMENTS = [
    # One closure per matter, ignoring cancelled rows.
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_consilium_escalation_closure__matter"
       ON "tabEscalation Closure" ("escalation_matter")
       WHERE "docstatus" < 2''',
    # The lookups this module actually makes.
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_escalation_matter__open"
       ON "tabEscalation Matter" ("is_open", "severity")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_escalation_matter__sensitive"
       ON "tabEscalation Matter" ("sensitive")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_escalation_matter__type_date"
       ON "tabEscalation Matter" ("escalation_type", "escalation_identification_date")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_action_plan__matter"
       ON "tabAction Plan" ("escalation_matter", "is_open")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_risk_acceptance__matter"
       ON "tabRisk Acceptance" ("escalation_matter", "is_active")''',
    '''CREATE INDEX IF NOT EXISTS "ix_consilium_escalation_forum_link__forum"
       ON "tabEscalation Forum Link" ("governance_forum")''',
]


def apply() -> list[str]:
    applied = []
    for statement in STATEMENTS:
        frappe.db.sql(statement)
        applied.append(statement.split('"')[1])
    return applied
