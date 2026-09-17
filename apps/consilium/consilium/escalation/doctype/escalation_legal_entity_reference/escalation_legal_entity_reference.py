"""Escalation Legal Entity Reference — controller.

One legal entity in an escalation matrix's scope. Multi -> Legal Entity.
"""

from frappe.model.document import Document


class EscalationLegalEntityReference(Document):
    def validate(self):
        pass
