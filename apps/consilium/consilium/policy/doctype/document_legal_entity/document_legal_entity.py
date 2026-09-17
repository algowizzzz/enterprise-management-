"""Document Legal Entity — controller.

A single Legal Entity held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class DocumentLegalEntity(Document):
    def validate(self):
        pass
