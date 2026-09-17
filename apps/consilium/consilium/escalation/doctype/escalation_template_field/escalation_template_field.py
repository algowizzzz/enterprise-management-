"""Escalation Template Field — controller.

One standard field made required, or optional, by a template (02-data-model.md §8.3, E-5).
"""

from frappe.model.document import Document


class EscalationTemplateField(Document):
    def validate(self):
        pass
