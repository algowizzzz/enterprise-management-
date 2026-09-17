"""Escalation Impacted Entity — controller.

The user picks a *kind* of impacted entity; the Dynamic Link needs the DocType
that kind lives in. The mapping is resolved as the row is built — in `__setup__`
rather than in `validate` — because the framework checks a dynamic link's target
before any validate hook runs.
"""

from __future__ import annotations

from frappe.model.document import Document

#: Entity kind -> the taxonomy that holds it. Two kinds share one table: a line
#: of business and a business unit are both levels of the organisation.
ENTITY_DOCTYPES = {
    "Legal Entity": "Legal Entity",
    "Material Entity": "Material Entity",
    "Business Unit": "Organization Unit",
    "Line of Business": "Organization Unit",
}


class EscalationImpactedEntity(Document):
    def __setup__(self):
        self.resolve_entity_doctype()

    def resolve_entity_doctype(self) -> None:
        kind = self.get("entity_type")
        if kind and not self.get("entity_doctype"):
            self.entity_doctype = ENTITY_DOCTYPES.get(kind)

    def validate(self):
        self.resolve_entity_doctype()
