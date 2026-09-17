"""Intake Party — controller.

A single User held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class IntakeParty(Document):
    def validate(self):
        pass
