"""Document Organization Unit — controller.

A single Organization Unit held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class DocumentOrganizationUnit(Document):
    def validate(self):
        pass
