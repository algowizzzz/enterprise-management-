"""The physical schema: the indexes PostgreSQL does not get for free, and uniqueness.

03-schema.md §2.3.1 records a verified divergence — the PostgreSQL table builder
creates neither the child-table ``parent`` index nor the parent-table
``modified`` index that the MariaDB builder creates. §7.2 records a second: index
names are schema-wide in PostgreSQL and the builder names an index after the bare
field name, so the second table to declare one silently gets nothing.

These tests run the module's constraint statements against the real database and
then read ``pg_indexes`` back.
"""

import frappe

from consilium.governance import constraints
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_seat, seat_role


def indexes_on(table: str) -> set[str]:
    return {
        row[0] for row in frappe.db.sql(
            """SELECT "indexname" FROM pg_indexes WHERE "tablename" = %s""", (table,)
        )
    }


class TestSchemaObjects(GovernanceTestCase):
    def _apply_and_commit(self):
        """Apply the constraint statements and commit them — and only them.

        The base class makes a person for every test. A bare commit here would
        keep that person too, and each run of this class left five more behind.
        Rolling back first discards them; the configuration the base class also
        applied is idempotent and already on the site.
        """
        frappe.db.rollback()
        applied = constraints.apply()
        frappe.db.commit()
        return applied

    def test_the_database_is_postgres(self):
        self.assertEqual(frappe.conf.db_type, "postgres")

    def test_the_constraint_statements_apply(self):
        applied = self._apply_and_commit()
        self.assertTrue(applied)

    def test_parent_tables_get_the_modified_index_the_builder_omits(self):
        self._apply_and_commit()
        for table in constraints.MODIFIED_INDEX_TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"ix_governance_{constraints._slug(table)}__modified", indexes_on(table)
                )

    def test_child_tables_get_the_parent_index_the_builder_omits(self):
        self._apply_and_commit()
        for table in constraints.CHILD_TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"ix_governance_{constraints._slug(table)}__parent", indexes_on(table)
                )

    def test_no_entity_in_this_module_declares_a_search_index(self):
        """§7.2: a schema-wide index name silently swallows the second CREATE."""
        offenders = frappe.db.sql(
            """SELECT "parent", "fieldname" FROM "tabDocField"
               WHERE "search_index" = 1 AND "parent" IN (
                   SELECT "name" FROM "tabDocType" WHERE "module" = 'Governance')"""
        )
        self.assertEqual(offenders, [])

    def test_every_index_name_is_prefixed(self):
        for statement in constraints.STATEMENTS:
            with self.subTest(statement=statement.split('"')[1]):
                self.assertTrue(statement.split('"')[1].startswith("ix_governance_")
                                or statement.split('"')[1].startswith("ux_governance_"))

    def test_the_membership_as_at_index_exists(self):
        self._apply_and_commit()
        self.assertIn("ix_governance_membership__as_at", indexes_on("tabForum Membership"))

    def test_one_entitlement_row_per_seat_per_motion(self):
        self._apply_and_commit()
        self.assertIn("ux_governance_forum_vote__entitlement", indexes_on("tabForum Vote"))

    def test_the_forum_carries_the_standard_columns(self):
        columns = {
            row[0] for row in frappe.db.sql(
                """SELECT "column_name" FROM information_schema.columns
                   WHERE "table_name" = 'tabGovernance Forum'"""
            )
        }
        for column in ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx"):
            self.assertIn(column, columns)

    def test_a_child_table_carries_the_three_child_columns(self):
        columns = {
            row[0] for row in frappe.db.sql(
                """SELECT "column_name" FROM information_schema.columns
                   WHERE "table_name" = 'tabForum Link'"""
            )
        }
        for column in ("parent", "parenttype", "parentfield"):
            self.assertIn(column, columns)

    def test_one_child_table_serves_two_parent_fields(self):
        """Which is why the parent index is composite rather than single-column."""
        forum = make_forum()
        up, down = make_forum(), make_forum()
        forum.append("upstream_links", {"linked_forum": up.name, "relationship_type": "Reports To"})
        forum.append("downstream_links", {"linked_forum": down.name, "relationship_type": "Informs"})
        forum.save(ignore_permissions=True)

        fields = frappe.db.sql(
            """SELECT DISTINCT "parentfield" FROM "tabForum Link" WHERE "parent" = %s""",
            (forum.name,),
        )
        self.assertEqual(sorted(row[0] for row in fields), ["downstream_links", "upstream_links"])
