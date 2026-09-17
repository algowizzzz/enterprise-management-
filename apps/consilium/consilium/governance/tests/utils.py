"""Fixtures shared by the Governance behaviour tests.

Everything here builds a forum out of real taxonomy rows rather than mocks, so
the tests exercise the schema, the permission engine and the state-flag map the
way the running system does.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import retention, state_flags, watched_fields
from consilium.consilium_core.tests.utils import CoreTestCase, make_user, purge_refusals, unique
from consilium.governance import setup

__all__ = ["GovernanceTestCase", "make_user", "unique", "purge_refusals"]


def taxonomy(doctype: str, code_field: str, name_field: str, **extra) -> str:
    code = unique("TX").upper()
    return frappe.get_doc(
        {"doctype": doctype, code_field: code, name_field: f"Test {code}", **extra}
    ).insert(ignore_permissions=True).name


def make_forum_type() -> str:
    return taxonomy("Governance Forum Type", "forum_type_code", "forum_type_name")


def make_risk_category() -> str:
    return taxonomy("Risk Category", "risk_category_code", "risk_category_name")


def make_org_unit(level: str = "Operating Group", parent: str | None = None) -> str:
    return taxonomy(
        "Organization Unit", "org_unit_code", "org_unit_name",
        unit_level=level, parent_org_unit=parent,
    )


def make_jurisdiction() -> str:
    return taxonomy("Jurisdiction", "jurisdiction_code", "jurisdiction_name", jurisdiction_level="Federal")


def make_forum(**values):
    defaults = {
        "doctype": "Governance Forum",
        "forum_name": unique("Forum"),
        "forum_type": make_forum_type(),
        "description": "A forum with a mandate.",
        "cadence": "Quarterly",
        "primary_risk_category": make_risk_category(),
        "owning_operating_group": make_org_unit(),
        "quorum_rule_type": "Count",
        "quorum_value": 2,
        "compliance_status": "Draft",
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


def seat_role(**flags) -> str:
    """A throwaway seat role, so a test never depends on the seeded vocabulary."""
    values = {
        "counts_toward_quorum": 1, "votes_by_default": 1, "can_attest": 0,
        "is_chair_role": 0, "is_secretary_role": 0, "is_owner_role": 0, "max_holders": 0,
    }
    values.update(flags)
    return taxonomy(
        "Governance Forum Role", "governance_forum_role_code", "governance_forum_role_name", **values
    )


#: Distinguishes "give me anybody" from an explicitly vacant by-position seat.
AUTO = object()


def make_seat(forum: str, role: str, member=AUTO, **values):
    defaults = {
        "doctype": "Forum Membership",
        "forum": forum,
        "seat_type": "Person",
        "member": make_user() if member is AUTO else member,
        "forum_role": role,
        "start_date": add_days(nowdate(), -365),
    }
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class GovernanceTestCase(CoreTestCase):
    """Core's isolating base, plus the module configuration this module needs."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        setup.ensure_configuration(force=True)
        # The shipped approval route names a role-based step, so the site needs a
        # holder of that role for the route to be assignable.
        self.rgo = make_user("Risk Governance Office")

    def tearDown(self):
        frappe.set_user("Administrator")
        setup.clear_cache()
        super().tearDown()
