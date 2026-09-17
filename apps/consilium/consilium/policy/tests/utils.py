"""Helpers shared by the Policy behaviour tests.

Two conventions hold throughout these tests and are worth stating once.

**Nothing asserts on a state name.** The tests read the semantic flags, exactly
as the business logic does, so a state rename does not break the test suite
either. Where a test must put a record into a state it does so by performing the
configured action, not by writing the label.

**Permissions are tested by doing, not by reading.** A permission assertion here
switches ``frappe.session.user`` to a user holding only the role under test and
attempts the action, because a permission row that looks right and does not hold
is the failure mode that matters.
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase

from consilium.consilium_core import audit, retention, state_flags, watched_fields
from consilium.policy.setup import seed

DOCTYPE = "Governing Document"


def unique(prefix: str) -> str:
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def make_user(*roles: str, email: str | None = None) -> str:
    email = email or f"{frappe.generate_hash(length=10)}@example.com"
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "Policy",
            "last_name": "Person",
            "send_welcome_email": 0,
            "enabled": 1,
        }
    ).insert(ignore_permissions=True)
    for role in roles:
        user.add_roles(role)
    return user.name


@contextmanager
def as_user(user: str):
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)


def make_org_unit(level: str = "Operating Group") -> str:
    code = unique("OU")
    return frappe.get_doc(
        {
            "doctype": "Organization Unit",
            "org_unit_code": code,
            "org_unit_name": f"Unit {code}",
            "unit_level": level,
        }
    ).insert(ignore_permissions=True).name


def make_risk_category() -> str:
    code = unique("RC")
    return frappe.get_doc(
        {
            "doctype": "Risk Category",
            "risk_category_code": code,
            "risk_category_name": f"Category {code}",
        }
    ).insert(ignore_permissions=True).name


def make_document_type(code: str | None = None) -> str:
    code = code or unique("DT")
    return frappe.get_doc(
        {
            "doctype": "Governing Document Type",
            "document_type_code": code,
            "document_type_name": f"Type {code}",
        }
    ).insert(ignore_permissions=True).name


def make_coverage_area() -> str:
    code = unique("CA")
    return frappe.get_doc(
        {
            "doctype": "Horizon Scanning Coverage Area",
            "coverage_area_code": code,
            "coverage_area_name": f"Area {code}",
        }
    ).insert(ignore_permissions=True).name


def make_user_group(members: list[str]) -> str:
    return frappe.get_doc(
        {
            "doctype": "User Group",
            "name": unique("group"),
            "user_group_members": [{"user": member} for member in members],
        }
    ).insert(ignore_permissions=True).name


def make_document(**values) -> "frappe.Document":
    """A repository record with the minimum a Governing Document requires."""
    owner = values.pop("owner_user", None) or make_user("Policy Owner")
    defaults = {
        "doctype": DOCTYPE,
        "document_name": unique("Policy"),
        "document_type": values.pop("document_type", None) or make_document_type(),
        "document_owner": owner,
        "document_approver": values.pop("document_approver", None) or make_user("Policy Owner"),
        "owning_operating_group": values.pop("owning_operating_group", None) or make_org_unit(),
        "primary_risk_category": values.pop("primary_risk_category", None) or make_risk_category(),
        "handling_classification": "Internal",
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


def refusals_for(subject_doctype: str, subject_name: str) -> list[dict]:
    db = audit._open_side_connection()
    try:
        return db.sql(
            """SELECT "attempted_action", "control", "refusal_reason"
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


class PolicyTestCase(FrappeTestCase):
    """Isolates each test, and guarantees the module's configuration is present.

    The Policy configuration — the flag map, the lifecycle workflow, the gates,
    the routes and the intake rule set — is seeded here because no shared hook
    calls the Policy install module yet. Seeding is idempotent, so this is a
    no-op once the hook exists.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        seed.seed_all()
        frappe.db.commit()

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()
        for subject_doctype, subject_name in getattr(self, "_purge", []):
            purge_refusals(subject_doctype, subject_name)
        retention.clear_cache()
        watched_fields.clear_cache()
        state_flags.clear_cache()
        frappe.clear_cache()
        super().tearDown()

    def purge_on_teardown(self, doctype: str, name: str) -> None:
        self._purge = [*getattr(self, "_purge", []), (doctype, name)]

    # ------------------------------------------------------------- assertions

    def assertInForce(self, doc):
        doc.reload()
        self.assertTrue(int(doc.is_active or 0), "expected the record to be in force")

    def assertNotInForce(self, doc):
        doc.reload()
        self.assertFalse(int(doc.is_active or 0), "expected the record not to be in force")

    def assertEditable(self, doc, expected: bool = True):
        doc.reload()
        self.assertEqual(bool(int(doc.is_editable or 0)), expected)
