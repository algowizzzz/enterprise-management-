"""Implementation Working Group — controller.

A single User Group held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class ImplementationWorkingGroup(Document):
    def validate(self):
        pass
