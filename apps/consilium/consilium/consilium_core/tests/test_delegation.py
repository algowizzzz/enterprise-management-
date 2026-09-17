"""Authority delegation: bounded, action-scoped, and never a permission grant."""

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import delegation
from consilium.consilium_core.tests.utils import CoreTestCase, make_guide_article, make_user


class TestDelegation(CoreTestCase):
    def setUp(self):
        self.delegator = make_user()
        self.delegate = make_user()
        self.stranger = make_user()
        self.article = make_guide_article()

    def _delegation(self, actions=("APPROVE",), **overrides):
        values = {
            "doctype": "Authority Delegation",
            "delegator": self.delegator,
            "delegate": self.delegate,
            "scope_type": "DocType",
            "scope_doctype": "Guide Article",
            "valid_from": nowdate(),
            "valid_to": add_days(nowdate(), 30),
            "delegated_actions": [{"delegable_action": action} for action in actions],
        }
        values.update(overrides)
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def test_a_live_delegation_permits_the_named_action(self):
        row = self._delegation()
        self.assertTrue(row.is_active)
        resolution = delegation.resolve_actor(
            self.delegator, "APPROVE", acting_user=self.delegate,
            doctype="Guide Article", name=self.article.name,
        )
        self.assertTrue(resolution["permitted"])
        self.assertEqual(resolution["delegation"], row.name)

    def test_an_action_that_was_not_delegated_is_refused(self):
        self._delegation(actions=("REVIEW",))
        resolution = delegation.resolve_actor(
            self.delegator, "APPROVE", acting_user=self.delegate, doctype="Guide Article"
        )
        self.assertFalse(resolution["permitted"])
        self.assertIn("no live delegation", resolution["reason"])

    def test_a_delegation_outside_its_dates_does_not_apply(self):
        row = self._delegation(valid_from=add_days(nowdate(), -30), valid_to=add_days(nowdate(), -1))
        self.assertFalse(row.is_active)
        resolution = delegation.resolve_actor(
            self.delegator, "APPROVE", acting_user=self.delegate, doctype="Guide Article"
        )
        self.assertFalse(resolution["permitted"])

    def test_a_delegation_of_another_doctype_does_not_apply(self):
        self._delegation(scope_doctype="Retention Class")
        resolution = delegation.resolve_actor(
            self.delegator, "APPROVE", acting_user=self.delegate, doctype="Guide Article"
        )
        self.assertFalse(resolution["permitted"])

    def test_a_record_scope_covers_only_that_record(self):
        self._delegation(scope_type="Record", scope_record=self.article.name)
        other = make_guide_article()
        self.assertTrue(
            delegation.resolve_actor(
                self.delegator, "APPROVE", acting_user=self.delegate,
                doctype="Guide Article", name=self.article.name,
            )["permitted"]
        )
        self.assertFalse(
            delegation.resolve_actor(
                self.delegator, "APPROVE", acting_user=self.delegate,
                doctype="Guide Article", name=other.name,
            )["permitted"]
        )

    def test_a_third_party_is_not_covered(self):
        self._delegation()
        self.assertFalse(
            delegation.resolve_actor(
                self.delegator, "APPROVE", acting_user=self.stranger, doctype="Guide Article"
            )["permitted"]
        )

    def test_the_accountable_person_always_acts_for_themselves(self):
        resolution = delegation.resolve_actor(
            self.delegator, "APPROVE", acting_user=self.delegator, doctype="Guide Article"
        )
        self.assertTrue(resolution["permitted"])
        self.assertIsNone(resolution["delegation"])

    def test_self_delegation_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._delegation(delegate=self.delegator)

    def test_a_delegation_ending_before_it_starts_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._delegation(valid_from=nowdate(), valid_to=add_days(nowdate(), -5))

    def test_a_delegation_with_no_actions_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._delegation(actions=())

    def test_a_record_scope_without_a_record_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self._delegation(scope_type="Record")

    def test_the_sweep_corrects_a_stale_flag(self):
        row = self._delegation()
        frappe.db.set_value(
            "Authority Delegation",
            row.name,
            {"valid_from": add_days(nowdate(), -30), "valid_to": add_days(nowdate(), -1)},
        )
        delegation.refresh_all()
        self.assertEqual(frappe.db.get_value("Authority Delegation", row.name, "is_active"), 0)

    def test_the_database_backstops_the_date_validation(self):
        """The application refuses it; the CHECK constraint refuses it too, for
        anything that reaches the table without going through the application."""
        row = self._delegation()
        with self.assertRaises(Exception):
            frappe.db.sql(
                '''UPDATE "tabAuthority Delegation" SET "valid_to" = %s WHERE "name" = %s''',
                (add_days(nowdate(), -900), row.name),
            )
        frappe.db.rollback()
