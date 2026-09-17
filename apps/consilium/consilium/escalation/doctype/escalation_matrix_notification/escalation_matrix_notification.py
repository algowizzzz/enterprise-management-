"""Escalation Matrix Notification — controller.

A user group a matrix rule notifies. Flattened out of Escalation Matrix Rule for the same reason as Escalation Matrix Route.
"""

from frappe.model.document import Document


class EscalationMatrixNotification(Document):
    def validate(self):
        pass
