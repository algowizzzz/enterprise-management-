"""Document Risk Type — controller.

A single Risk Type held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class DocumentRiskType(Document):
    def validate(self):
        pass
