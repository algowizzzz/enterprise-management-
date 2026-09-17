"""Escalation Risk Type Reference — controller.

One risk type in an escalation matrix's scope. Multi -> Risk Type.
"""

from frappe.model.document import Document


class EscalationRiskTypeReference(Document):
    def validate(self):
        pass
