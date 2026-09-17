"""Escalation Matrix Rule — controller.

One routing rule of an approved escalation matrix (02-data-model.md §8.3). The condition is data, evaluated by consilium.escalation.routing.
"""

from frappe.model.document import Document


class EscalationMatrixRule(Document):
    def validate(self):
        pass
