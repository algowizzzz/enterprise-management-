"""Helpers shared by the Escalation behaviour tests."""

from __future__ import annotations

import contextlib
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from consilium.consilium_core import retention, state_flags, watched_fields
from consilium.escalation import sensitivity
from consilium.escalation.setup import install


def unique(prefix: str) -> str:
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def make_user(*roles: str, email: str | None = None) -> str:
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
    for role in roles:
        user.add_roles(role)
    return user.name


def make_taxonomy(doctype: str, code_field: str, name_field: str, **extra) -> str:
    code = unique("C").upper()
    return frappe.get_doc(
        {"doctype": doctype, code_field: code, name_field: "Reference value", **extra}
    ).insert(ignore_permissions=True).name


def make_forum(*, is_active: int = 1, protocol: str = "Escalate within five business days",
               threshold: str = "Any High severity matter") -> str:
    """A governance forum.

    Forums belong to the Governance module and are created here only as a
    destination to route to. The helper writes only the fields the forum
    actually has, so the Escalation tests keep running whether the Governance
    module's own schema moves under them or is absent altogether.
    """
    meta = frappe.get_meta("Governance Forum")
    values = {
        "doctype": "Governance Forum",
        "forum_name": unique("Forum"),
        "forum_code": unique("FORUM").upper(),
        "forum_type": make_taxonomy("Governance Forum Type", "forum_type_code", "forum_type_name"),
        "description": "A forum that receives escalated matters.",
        "cadence": "Quarterly",
        "primary_risk_category": make_taxonomy(
            "Risk Category", "risk_category_code", "risk_category_name"
        ),
        "owning_operating_group": frappe.get_doc(
            {
                "doctype": "Organization Unit",
                "org_unit_code": unique("OU").upper(),
                "org_unit_name": "Operating group",
                "unit_level": "Operating Group",
            }
        ).insert(ignore_permissions=True).name,
        "quorum_rule_type": "Count",
        "quorum_value": 3,
        "is_active": is_active,
        "escalation_protocol": protocol,
        "escalation_threshold": threshold,
    }
    doc = frappe.get_doc({k: v for k, v in values.items() if k == "doctype" or meta.has_field(k)})
    if not meta.autoname:
        doc.name = doc.get("forum_code") or unique("FORUM")
    return doc.insert(ignore_permissions=True).name


@contextlib.contextmanager
def escalation_permission_hooks():
    """Register the sensitive-matter permission hooks for the duration of a test.

    They belong in `consilium/hooks.py`, which this module may not edit; see
    `consilium/escalation/sensitivity.py`. Registering them here means the tests
    exercise the same code the hook would call, through the same framework path.
    """
    real = frappe.get_hooks
    query_conditions = {
        doctype: [f"consilium.escalation.sensitivity.{fn}"]
        for doctype, fn in sensitivity.HOOK_NAMES.items()
    }
    controller = {
        doctype: ["consilium.escalation.sensitivity.has_permission"]
        for doctype in sensitivity.RESTRICTED_DOCTYPES
    }

    def patched(hook=None, *args, **kwargs):
        value = real(hook, *args, **kwargs)
        if hook == "permission_query_conditions":
            return {**(value or {}), **query_conditions}
        if hook == "has_permission":
            return {**(value or {}), **controller}
        return value

    frappe.get_hooks = patched
    try:
        yield
    finally:
        frappe.get_hooks = real


@contextlib.contextmanager
def as_user(user: str):
    previous = frappe.session.user
    frappe.set_user(user)
    try:
        yield
    finally:
        frappe.set_user(previous)


def rest_list(doctype: str, user: str, **params) -> list[dict]:
    """Read a list exactly as `GET /api/resource/<doctype>` does.

    `frappe.api.v1.document_list` is the endpoint the REST route dispatches to,
    so this is the API path and not a convenience wrapper around it.
    """
    from frappe.api import v1

    with as_user(user):
        previous = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict(params)
        try:
            return v1.document_list(doctype)
        finally:
            frappe.local.form_dict = previous


def rest_get(doctype: str, name: str, user: str):
    """Read one record exactly as `GET /api/resource/<doctype>/<name>` does."""
    with as_user(user):
        return frappe.client.get(doctype, name)


class EscalationTestCase(FrappeTestCase):
    """Each test rolls back its own data and drops the caches the controls keep."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        install.ensure_roles()
        install.ensure_state_flags()
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()
        retention.clear_cache()
        watched_fields.clear_cache()
        state_flags.clear_cache()
        super().tearDown()

    # ------------------------------------------------------------- fixtures

    def reference_data(self) -> dict:
        """The taxonomy a matter needs, plus a type and a forum."""
        tier_1 = make_taxonomy("Risk Type", "risk_type_code", "risk_type_name", tier=1)
        data = {
            "risk_type": tier_1,
            "risk_type_2": make_taxonomy(
                "Risk Type", "risk_type_code", "risk_type_name", tier=2, parent_risk_type=tier_1
            ),

            "organizational_level": make_taxonomy(
                "Organizational Level", "organizational_level_code", "organizational_level_name", level_rank=3
            ),
            "legal_entity": make_taxonomy("Legal Entity", "legal_entity_code", "legal_entity_name"),
            "escalation_type": make_taxonomy(
                "Escalation Type", "escalation_type_code", "escalation_type_name"
            ),
            "forum": make_forum(),
            "user": make_user("Escalation Owner"),
        }
        return data

    def matter_values(self, reference: dict, **overrides) -> dict:
        values = {
            "doctype": "Escalation Matter",
            "escalation_title": "A matter requiring a decision",
            "escalation_type": reference["escalation_type"],
            "escalation_identification_date": "2026-01-05",
            "description": "Something happened that needs a decision above this level.",
            "tier_1_risk_type": reference["risk_type"],
            "identified_by": reference["user"],
            "organizational_level": reference["organizational_level"],
            "accountable_executive": reference["user"],
            "escalation_trigger": "A control failed twice in one quarter.",
            "severity": "Medium",
            "severity_source": "Manual Override",
            "impacted_entities": [
                {"entity_type": "Legal Entity", "entity_value": reference["legal_entity"]}
            ],
        }
        values.update(overrides)
        return values

    def make_matter(self, reference: dict | None = None, **overrides):
        reference = reference or self.reference_data()
        return frappe.get_doc(self.matter_values(reference, **overrides)).insert(ignore_permissions=True)

    def make_template(self, reference: dict, scope: str, fields: list[dict]):
        return frappe.get_doc(
            {
                "doctype": "Escalation Template",
                "template_code": unique("TPL").upper(),
                "title": f"{scope} template",
                "escalation_type": reference["escalation_type"],
                "template_scope": scope,
                "is_active": 1,
                "template_fields": fields,
            }
        ).insert(ignore_permissions=True)

    def make_matrix(self, reference: dict, *, rules: list[dict], routes: list[dict] | None = None,
                    notifications: list[dict] | None = None, **overrides):
        values = {
            "doctype": "Escalation Matrix",
            "matrix_code": unique("MTX").upper(),
            "title": "Enterprise escalation matrix",
            "effective_from": "2026-01-01",
            "is_active": 1,
            "rules": [
                {
                    **rule,
                    "condition": rule.get("condition")
                    if isinstance(rule.get("condition"), str)
                    else json.dumps(rule.get("condition") or {}),
                }
                for rule in rules
            ],
            "routes": routes or [],
            "rule_notifications": notifications or [],
        }
        values.update(overrides)
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def make_sla_definition(self, *, target_hours: float = 1.0, business_calendar: str | None = None):
        values = {
            "doctype": "SLA Definition",
            "sla_code": unique("SLA").upper(),
            "title": "Escalation response threshold",
            "target_doctype": "Escalation Matter",
            "measure": "Total Open Time",
            "target_hours": target_hours,
            "calendar": "Business Hours" if business_calendar else "24x7",
            "business_calendar": business_calendar,
            "is_active": 1,
        }
        return frappe.get_doc(values).insert(ignore_permissions=True)

    def make_business_calendar(self):
        return frappe.get_doc(
            {
                "doctype": "Business Calendar",
                "calendar_code": unique("CAL").upper(),
                "title": "Head office hours",
                "day_start": "09:00:00",
                "day_end": "17:00:00",
                "holidays": json.dumps(["2026-01-01"]),
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)

    def make_closure(self, matter, **overrides):
        values = {
            "doctype": "Escalation Closure",
            "escalation_matter": matter.name,
            "closure_type": "Resolved",
            "closure_summary": "The control was rebuilt and tested; the matter is resolved.",
        }
        values.update(overrides)
        return frappe.get_doc(values).insert(ignore_permissions=True)
