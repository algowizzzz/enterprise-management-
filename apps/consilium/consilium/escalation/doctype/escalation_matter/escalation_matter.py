"""Escalation Matter — controller.

The order of work in `validate` matters: routing resolves the severity, the
severity decides which template fields are required, and the semantic flags
decide whether the matter must carry a closure. Nothing here reads a status
label.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now

from consilium.consilium_core import state_flags
from consilium.escalation import resolution, routing, sensitivity, templates
from consilium.escalation.doctype.escalation_impacted_entity.escalation_impacted_entity import (
    ENTITY_DOCTYPES,
)


class EscalationMatter(Document):
    def before_insert(self):
        if not self.opened_on:
            self.opened_on = now()

    def validate(self):
        self.escalation_id = self.escalation_id or self.name
        self.resolve_impacted_entities()
        self.validate_dates()
        routing.apply_routing(self)
        routing.validate_pathway(self)
        state_flags.apply_state_flags(self)
        templates.apply_template(self, templates.SCOPE_ESCALATION, self.severity)
        resolution.validate_closure(self)

    def on_update(self):
        resolution.sync_clock(self)
        if self.has_value_changed("sensitive"):
            sensitivity.propagate(self.name, int(self.sensitive or 0))
        if self.material_entity_impact and self.has_value_changed("material_entity_impact"):
            resolution.notify_material_entity_impact(self)

    # ------------------------------------------------------------------ helpers

    def resolve_impacted_entities(self) -> None:
        for row in self.impacted_entities:
            row.entity_doctype = ENTITY_DOCTYPES.get(row.entity_type)
            if not row.entity_doctype:
                frappe.throw(
                    _("{0} is not an impacted-entity kind this platform knows.").format(row.entity_type),
                    title=_("Unknown Entity Kind"),
                )

    def validate_dates(self) -> None:
        if self.escalation_date and getdate(self.escalation_date) < getdate(
            self.escalation_identification_date
        ):
            frappe.throw(
                _("A matter cannot be escalated before it was identified."),
                title=_("Dates Out Of Order"),
            )
