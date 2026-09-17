"""Escalation Forum Link — controller.

One governance forum on a matter's escalation pathway (E-7, E17-S1). Plural by decision D-4.
"""

from frappe.model.document import Document


class EscalationForumLink(Document):
    def validate(self):
        pass
