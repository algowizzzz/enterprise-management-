"""Escalation Closure — controller. The recorded outcome of a matter (E-10)."""

from __future__ import annotations

from frappe.model.document import Document

from consilium.escalation import resolution, sensitivity


class EscalationClosure(Document):
    def validate(self):
        self.sensitive = sensitivity.inherited_sensitivity(self.escalation_matter)
        resolution.validate_closure_record(self)
