"""Template Section — controller.

A predefined section of a document template (P-15).
"""

from frappe.model.document import Document


class TemplateSection(Document):
    def validate(self):
        pass
