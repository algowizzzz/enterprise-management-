"""Document Template — controller.

P-15. A template per document type and action, with its predefined sections and its required-field set.
"""

from frappe.model.document import Document


class DocumentTemplate(Document):
    def validate(self):
        pass
