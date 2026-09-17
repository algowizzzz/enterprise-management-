"""Import Field Mapping — controller.

One source column mapped onto one target field, with its transform and its handling.
"""

from frappe.model.document import Document


class ImportFieldMapping(Document):
    def validate(self):
        pass
