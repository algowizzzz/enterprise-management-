"""Organization Unit — controller.

The organisational hierarchy. A tree, because ownership is recorded at different levels.
"""

from frappe.model.document import Document


class OrganizationUnit(Document):
    def validate(self):
        pass
