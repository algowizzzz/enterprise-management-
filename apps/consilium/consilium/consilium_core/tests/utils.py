"""Helpers shared by the Core behaviour tests."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from consilium.consilium_core import audit, retention, state_flags, watched_fields


def unique(prefix: str) -> str:
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def make_user(role: str | None = None, *, email: str | None = None) -> str:
    """A throwaway user. Addresses are example.com, which is reserved for this."""
    email = email or f"{frappe.generate_hash(length=10)}@example.com"
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "Test",
            "last_name": "Person",
            "send_welcome_email": 0,
            "enabled": 1,
        }
    ).insert(ignore_permissions=True)
    if role:
        user.add_roles(role)
    return user.name


def make_guide_article(**values) -> "frappe.Document":
    """A simple Core-owned record to version, retain and attest against."""
    defaults = {
        "doctype": "Guide Article",
        "slug": unique("article"),
        "title": "Reference Article",
        "category": "Getting Started",
        "applies_to_module": "Core",
        "body": "<p>Body text.</p>",
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


def refusals_for(subject_doctype: str, subject_name: str) -> list[dict]:
    """Refusal rows are written out of band, so they are read out of band too."""
    db = audit._open_side_connection()
    try:
        return db.sql(
            """SELECT "attempted_action", "control", "refusal_reason", "legal_hold", "retention_class"
               FROM "tabGovernance Refusal Log"
               WHERE "subject_doctype" = %s AND "subject_name" = %s
               ORDER BY "creation" """,
            (subject_doctype, subject_name),
            as_dict=True,
        )
    finally:
        db.close()


def purge_refusals(subject_doctype: str, subject_name: str) -> None:
    db = audit._open_side_connection()
    try:
        db.sql(
            """DELETE FROM "tabGovernance Refusal Log"
               WHERE "subject_doctype" = %s AND "subject_name" = %s""",
            (subject_doctype, subject_name),
        )
        db.commit()
    finally:
        db.close()


class CoreTestCase(FrappeTestCase):
    """A test case that isolates each test.

    The framework's own base class rolls back once per class, which lets one
    test's legal hold freeze the next test's record. Core's controls are global
    by design, so each test rolls back its own data and drops the caches the
    controls keep.
    """

    def tearDown(self):
        frappe.db.rollback()
        for subject_doctype, subject_name in getattr(self, "_purge", []):
            purge_refusals(subject_doctype, subject_name)
        retention.clear_cache()
        watched_fields.clear_cache()
        state_flags.clear_cache()
        super().tearDown()

    def purge_on_teardown(self, doctype: str, name: str) -> None:
        self._purge = [*getattr(self, "_purge", []), (doctype, name)]
