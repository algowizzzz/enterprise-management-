"""Legal Entity — controller.

Legal entities that governance forums, policies and escalations can be attributed to.
"""

from frappe.model.document import Document


class LegalEntity(Document):
    def validate(self):
        pass
