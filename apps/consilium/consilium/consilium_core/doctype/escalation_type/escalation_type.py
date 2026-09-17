"""Escalation Type — controller.

The kinds of matter that can be escalated. Drives which template is used.
"""

from frappe.model.document import Document


class EscalationType(Document):
    def validate(self):
        pass
