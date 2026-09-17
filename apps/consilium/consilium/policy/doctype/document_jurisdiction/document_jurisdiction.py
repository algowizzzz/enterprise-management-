"""Document Jurisdiction — controller.

A single Jurisdiction held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class DocumentJurisdiction(Document):
    def validate(self):
        pass
