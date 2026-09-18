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

from consilium.consilium_core import audit

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


# ====================================================== the guided intake form


def requirements_for(escalation_type: str | None, scope: str, severity: str | None) -> list[dict]:
    """What the template for a type and scope requires at a severity, with its guidance.

    ``[{"fieldname", "label", "guidance"}]`` — the same list `apply_template`
    enforces on save, so the form marks exactly what the server will refuse.
    """
    template = resolve_template(escalation_type, scope)
    if not template:
        return []
    guidance = {
        row.fieldname: row.guidance
        for row in frappe.get_all(
            "Escalation Template Field",
            filters={"parent": template, "parenttype": "Escalation Template"},
            fields=["fieldname", "guidance"],
        )
    }
    return [
        {"fieldname": fieldname, "label": label, "guidance": guidance.get(fieldname), "template": template}
        for fieldname, label in required_fields(template, severity)
    ]


def _may_raise() -> None:
    if not frappe.has_permission("Escalation Matter", "create"):
        frappe.throw(_("You cannot raise an escalation."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def template_requirements(escalation_type: str | None = None, severity: str | None = None,
                          scope: str = SCOPE_ESCALATION) -> dict:
    """The required fields for a type at a severity, for a person raising a matter."""
    _may_raise()
    if scope not in SCOPE_DOCTYPES:
        frappe.throw(_("{0} is not a template scope.").format(scope), title=_("Unknown Scope"))
    return {"template": resolve_template(escalation_type, scope),
            "required": requirements_for(escalation_type, scope, severity)}


def _named(doctype: str, label_field: str, filters=None, extra=()) -> list[dict]:
    """A reference list read with the caller's permissions, as ``{value, label}``."""
    rows = frappe.get_list(doctype, filters=filters or {}, fields=["name", label_field, *extra],
                           order_by=f"{label_field} asc", limit_page_length=0)
    return [{"value": row.name, "label": row.get(label_field) or row.name,
             **{field: row.get(field) for field in extra}} for row in rows]


@frappe.whitelist(methods=["GET"])
def intake_options() -> dict:
    """Everything the guided form offers, read from the configuration itself so
    the form cannot offer a value the record would refuse."""
    from consilium.escalation import routing, sensitivity
    from consilium.escalation.doctype.escalation_impacted_entity.escalation_impacted_entity import (
        ENTITY_DOCTYPES,
    )

    _may_raise()
    meta = frappe.get_meta("Escalation Matter")
    active = {"is_active": 1}
    risk_types = _named("Risk Type", "risk_type_name", active, extra=("tier", "parent_risk_type"))
    units = _named("Organization Unit", "org_unit_name", active, extra=("unit_level",))
    entities = {
        "Legal Entity": _named("Legal Entity", "legal_entity_name", active),
        "Material Entity": _named("Material Entity", "material_entity_name", active),
        # Two kinds share the organisation tree; each offers only its own level.
        "Business Unit": [u for u in units if u["unit_level"] == "Business Unit"],
        "Line of Business": [u for u in units if u["unit_level"] == "Line of Business"],
    }
    forums = [{"value": row.name, "label": row.forum_name or row.name} for row in routing.selectable_forums()]
    return {
        "escalation_types": _named("Escalation Type", "escalation_type_name", active),
        "risk_types": risk_types,
        "organizational_levels": _named("Organizational Level", "organizational_level_name", active),
        "entity_kinds": [kind for kind in ENTITY_DOCTYPES],
        "entities": entities,
        "severities": [o for o in (meta.get_field("severity").options or "").split("\n") if o],
        "forums": forums,
        "forum_roles": [o for o in (frappe.get_meta("Escalation Forum Link").get_field("role_in_escalation").options or "").split("\n") if o],
        "people": frappe.get_all(
            "User",
            filters={"enabled": 1, "user_type": "System User", "name": ["not in", list(frappe.STANDARD_USERS)]},
            fields=["name", "full_name"],
            order_by="full_name asc",
        ),
        "may_restrict": sensitivity.may_see_sensitive(),
        "me": frappe.session.user,
    }


#: What the guided form may set. Everything else on a matter is the platform's.
INTAKE_FIELDS = (
    "escalation_title", "escalation_type", "escalation_identification_date", "escalation_date",
    "description", "tier_1_risk_type", "tier_2_risk_type", "identified_by", "organizational_level",
    "accountable_executive", "response_owner", "escalation_trigger", "severity",
    "material_entity_impact", "risk_appetite_breach", "systemic", "sensitive",
)


@frappe.whitelist(methods=["POST"])
def raise_escalation(values) -> dict:
    """Raise an escalation matter from the guided form (E-1, E-5). Anyone who may
    create a matter — Escalation Owner by default.

    The matter is inserted with the caller's own permissions, so its controller
    applies the matrix, the pathway and the template for the type and severity
    exactly as the desk does. Two things are settled here first:

    * **Severity.** Left blank, the matrix decides and the source is recorded as
      the matrix; chosen by the person raising it, it is recorded as a manual
      override, so a later reader knows it was a judgement and whose.
    * **Restricted handling.** Only someone cleared to see sensitive matters may
      raise one as sensitive. Anyone else would lose sight of their own matter
      the moment it was saved, so the request is refused instead.
    """
    from consilium.escalation import routing, sensitivity

    _may_raise()
    data = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    fields = {key: data.get(key) for key in INTAKE_FIELDS if data.get(key) not in (None, "")}

    if int(fields.get("sensitive") or 0) and not sensitivity.may_see_sensitive():
        audit.refuse(
            _("{0} is not cleared for restricted handling and so cannot raise a matter as sensitive; "
              "ask someone who is to raise it.").format(frappe.session.user),
            subject_doctype="Escalation Matter",
            subject_name=fields.get("escalation_title") or "new matter",
            attempted_action="Create",
            control="sensitive escalation access",
        )

    rows = []
    for row in data.get("impacted_entities") or []:
        if row.get("entity_type") and row.get("entity_value"):
            rows.append({"entity_type": row["entity_type"], "entity_value": row["entity_value"],
                         "impact_note": row.get("impact_note")})
    pathway = [
        {"governance_forum": row["governance_forum"], "role_in_escalation": row.get("role_in_escalation") or None}
        for row in data.get("governance_forums") or [] if row.get("governance_forum")
    ]

    doc = frappe.get_doc({
        "doctype": "Escalation Matter",
        **fields,
        "identified_by": fields.get("identified_by") or frappe.session.user,
        "impacted_entities": rows,
        "governance_forums": [{k: v for k, v in row.items() if v} for row in pathway],
    })
    if fields.get("severity"):
        doc.severity_source = "Manual Override"
    else:
        doc.severity_source = "Matrix"
        proposed = routing.match_rule(doc)
        if not (proposed and proposed.get("severity")):
            frappe.throw(
                _("No escalation matrix rule sets a severity for this matter. Choose the severity yourself."),
                title=_("Severity Required"),
            )
        doc.severity = proposed["severity"]
    doc.insert()
    return {"name": doc.name, "url": f"/escalation?name={doc.name}"}
