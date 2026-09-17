"""Escalation Template — controller. A template may only require fields that exist."""

from __future__ import annotations

from frappe.model.document import Document

from consilium.escalation import templates


class EscalationTemplate(Document):
    def validate(self):
        templates.validate_template(self)
