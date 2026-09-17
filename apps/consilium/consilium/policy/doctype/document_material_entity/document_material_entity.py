"""Document Material Entity — controller.

A single Material Entity held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class DocumentMaterialEntity(Document):
    def validate(self):
        pass
