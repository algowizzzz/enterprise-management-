"""Implementation Reference — controller.

A single External Reference held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class ImplementationReference(Document):
    def validate(self):
        pass
