"""Configurable templates per escalation type (E-5, E-6, E16-S1, E16-S2).

Three templates govern one escalation type: the escalation itself, its action
plans and its risk acceptances. Each carries a required-field set chosen from a
shared list of standard fields, and each entry may be required always, or only
above a severity. Selecting a type applies the type's template.

The standard field list is code — it is the set of fields the entities actually
have, so it cannot be configuration — but *which* of them a template requires
is data, and so is the severity at which the requirement starts.
"""

from __future__ import annotations

import frappe
from frappe import _

SCOPE_ESCALATION = "Escalation"
SCOPE_ACTION_PLAN = "Action Plan"
SCOPE_RISK_ACCEPTANCE = "Risk Acceptance"

#: Scope -> the standard fields a template may make required, and the DocType
#: the scope configures. Shared across templates: the escalation's own fields
#: are the ones any escalation template can require, and so on.
STANDARD_FIELDS: dict[str, tuple[str, ...]] = {
    SCOPE_ESCALATION: (
        "escalation_title",
        "escalation_type",
        "escalation_identification_date",
        "escalation_date",
        "description",
        "tier_1_risk_type",
        "tier_2_risk_type",
        "impacted_entities",
        "identified_by",
        "organizational_level",
        "accountable_executive",
        "response_owner",
        "escalation_trigger",
        "severity",
        "governance_forums",
        "material_entity_impact",
        "risk_appetite_breach",
        "risk_appetite_reference",
        "related_risk_reference",
        "source_policy_violation",
        "external_reference",
        "response_template_completed",
    ),
    SCOPE_ACTION_PLAN: (
        "action_plan_name",
        "start_date",
        "end_date",
        "accountable_executive",
        "owner_user",
        "status",
        "governance_forums",
        "description",
        "completion_evidence",
        "external_reference",
    ),
    SCOPE_RISK_ACCEPTANCE: (
        "risk_acceptance_name",
        "external_acceptance_id",
        "start_date",
        "end_date",
        "accountable_executive",
        "rationale",
        "status",
        "governance_forums",
        "next_reassessment_on",
        "reassessment_frequency_months",
        "external_reference",
    ),
}

SCOPE_DOCTYPES = {
    SCOPE_ESCALATION: "Escalation Matter",
    SCOPE_ACTION_PLAN: "Action Plan",
    SCOPE_RISK_ACCEPTANCE: "Risk Acceptance",
}

#: Severities at which a `required_when_severity` setting bites.
SEVERITY_TRIGGERS = {
    "Always": ("High", "Medium", "Low"),
    "High": ("High",),
    "High Or Medium": ("High", "Medium"),
}


def standard_fields(scope: str) -> tuple[str, ...]:
    return STANDARD_FIELDS[scope]


def resolve_template(escalation_type: str | None, scope: str) -> str | None:
    """The active template configured for one escalation type and scope."""
    if not escalation_type:
        return None
    return frappe.db.get_value(
        "Escalation Template",
        {"escalation_type": escalation_type, "template_scope": scope, "is_active": 1},
        "name",
        order_by="modified desc",
    )


def required_fields(template: str, severity: str | None) -> list[tuple[str, str]]:
    """``(fieldname, label)`` for every field the template requires at ``severity``."""
    rows = frappe.get_all(
        "Escalation Template Field",
        filters={"parent": template, "parenttype": "Escalation Template", "is_required": 1},
        fields=["fieldname", "label", "required_when_severity"],
        order_by="display_order asc, idx asc",
    )
    required = []
    for row in rows:
        triggers = SEVERITY_TRIGGERS.get(row.required_when_severity or "Always", ("High", "Medium", "Low"))
        if (severity or "Low") in triggers:
            required.append((row.fieldname, row.label or row.fieldname))
    return required


def apply_template(doc, scope: str, severity: str | None) -> None:
    """Resolve the template for a record's type and enforce its required fields.

    Called from ``validate``. A missing template is not an error: a type may be
    configured before its templates are.
    """
    if not doc.get("escalation_template"):
        doc.escalation_template = resolve_template(_type_of(doc, scope), scope)
    if not doc.escalation_template:
        return

    template = frappe.get_cached_doc("Escalation Template", doc.escalation_template)
    if template.template_scope != scope:
        frappe.throw(
            _("Template {0} configures {1} records, not {2}.").format(
                template.name, template.template_scope, scope
            ),
            title=_("Wrong Template"),
        )

    missing = [
        label for fieldname, label in required_fields(template.name, severity) if _is_empty(doc, fieldname)
    ]
    if missing:
        frappe.throw(
            _("Template {0} requires: {1}.").format(template.title or template.name, ", ".join(missing)),
            title=_("Required By Template"),
        )


def _type_of(doc, scope: str) -> str | None:
    if scope == SCOPE_ESCALATION:
        return doc.get("escalation_type")
    if not doc.get("escalation_matter"):
        return None
    return frappe.db.get_value("Escalation Matter", doc.escalation_matter, "escalation_type")


def _is_empty(doc, fieldname: str) -> bool:
    value = doc.get(fieldname)
    if isinstance(value, list):
        return not value
    return value in (None, "", 0) and value is not False


def validate_template(template) -> None:
    """A template may only name fields that exist on the record it configures."""
    allowed = set(standard_fields(template.template_scope))
    meta = frappe.get_meta(SCOPE_DOCTYPES[template.template_scope])
    for row in template.template_fields:
        if row.fieldname not in allowed or not meta.has_field(row.fieldname):
            frappe.throw(
                _("{0} is not a standard field of a {1} record.").format(
                    row.fieldname, template.template_scope
                ),
                title=_("Unknown Field"),
            )
        if not row.label:
            row.label = meta.get_label(row.fieldname)
