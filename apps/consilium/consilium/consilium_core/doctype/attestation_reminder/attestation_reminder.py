"""Attestation Reminder — controller.

An offset at which a reminder fires for a campaign. [Inferred — §11 I-4.]
"""

from frappe.model.document import Document


class AttestationReminder(Document):
    def validate(self):
        pass
