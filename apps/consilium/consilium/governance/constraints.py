"""Database objects the framework will not create for the Governance module.

Same reasoning as Core's ``setup/constraints.py``, applied to this module's
tables. Two verified PostgreSQL divergences drive it (03-schema.md §2.3.1, §7.1,
§7.2):

* the PostgreSQL schema builder creates **no** ``parent`` index on a child table
  and **no** ``modified`` index on a parent table, both of which the MariaDB
  builder creates. Without them, loading a forum with ten child tables is ten
  sequential scans and every default-sorted list view is a sequential scan plus
  a sort;
* index names are schema-wide in PostgreSQL and the builder names an index after
  the bare field name, so a second table declaring ``search_index`` on ``forum``
  or ``status`` silently gets no index. Every name here is therefore prefixed
  ``ix_governance_`` and no entity in this module declares ``search_index``.

Uniqueness the database cannot otherwise express is here too: one entitlement
row per seat per motion.

**Core change requested.** Nothing calls this yet, because ``after_migrate`` is
wired in the shared ``hooks.py``. Core's ``setup/install.py`` should call
:func:`apply` alongside its own. Until it does, the tests call it, which is also
what proves the statements are valid against a real PostgreSQL.
"""

from __future__ import annotations

import frappe

STATEMENTS = [
    # --- uniqueness the framework cannot express -------------------------
    '''CREATE UNIQUE INDEX IF NOT EXISTS "ux_governance_forum_vote__entitlement"
       ON "tabForum Vote" ("motion", "membership") WHERE "docstatus" < 2''',
    # --- the membership-as-at query, which everything else is built on ---
    '''CREATE INDEX IF NOT EXISTS "ix_governance_membership__as_at"
       ON "tabForum Membership" ("forum", "start_date", "end_date")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_membership__member"
       ON "tabForum Membership" ("member", "end_date")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_forum_vote__motion"
       ON "tabForum Vote" ("motion", "membership")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_motion__forum"
       ON "tabForum Motion" ("forum", "decision_date")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_meeting__forum"
       ON "tabForum Meeting" ("forum", "scheduled_on")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_review__forum"
       ON "tabForum Compliance Review" ("forum", "review_type")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_forum__review_due"
       ON "tabGovernance Forum" ("is_active", "next_review_on")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_forum__owner"
       ON "tabGovernance Forum" ("forum_owner", "compliance_status")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_forum__parent"
       ON "tabGovernance Forum" ("parent_forum")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_forum_link__linked"
       ON "tabForum Link" ("linked_forum")''',
    '''CREATE INDEX IF NOT EXISTS "ix_governance_request__subject"
       ON "tabCommittee Formation Request" ("subject_forum", "workflow_state")''',
]

#: Parent tables the PostgreSQL builder leaves without a ``modified`` index.
MODIFIED_INDEX_TABLES = [
    "tabGovernance Forum",
    "tabForum Membership",
    "tabCommittee Formation Request",
    "tabCommittee Charter",
    "tabForum Compliance Review",
    "tabForum Meeting",
    "tabForum Motion",
    "tabForum Vote",
    "tabDisbandment Plan",
]

#: Child tables the PostgreSQL builder leaves without a parent index. The
#: composite is preferred over MariaDB's single-column form because one child
#: table can sit under two parent fields — Forum Link does.
CHILD_TABLES = [
    "tabForum Business Unit",
    "tabForum Risk Type",
    "tabForum Legal Entity",
    "tabForum Jurisdiction",
    "tabForum Governance Responsibility",
    "tabForum Link",
    "tabForum Regulatory Requirement",
    "tabForum Risk Reference",
    "tabFormation Evaluation",
    "tabFormation Child Forum",
    "tabCharter Approval Evidence",
    "tabMeeting Attendance",
    "tabDisbandment Approval",
    "tabFormation Approval Route Step",
]


def _slug(table: str) -> str:
    return table.replace("tab", "", 1).lower().replace(" ", "_")


def apply() -> list[str]:
    """Create everything that is missing. Safe to run on every migrate."""
    applied: list[str] = []
    if frappe.conf.db_type != "postgres":
        return applied

    for statement in STATEMENTS:
        table = statement.split('"')[3]
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        frappe.db.sql_ddl(statement)
        applied.append(statement.split('"')[1])

    for table in MODIFIED_INDEX_TABLES:
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        name = f"ix_governance_{_slug(table)}__modified"
        frappe.db.sql_ddl(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("modified")')
        applied.append(name)

    for table in CHILD_TABLES:
        if not frappe.db.table_exists(table.replace("tab", "", 1)):
            continue
        name = f"ix_governance_{_slug(table)}__parent"
        frappe.db.sql_ddl(
            f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("parent", "parenttype", "parentfield")'
        )
        applied.append(name)

    return applied
