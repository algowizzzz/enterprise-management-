"""Import Profile — controller.

The field mapping, validation and handling rules for one file-based import, expressed as configuration (02-data-model.md §5.6).
"""

from frappe.model.document import Document


class ImportProfile(Document):
    def validate(self):
        pass
