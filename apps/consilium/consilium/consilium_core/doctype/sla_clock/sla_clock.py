"""SLA Clock — controller.

One clock per record per definition.
"""

from frappe.model.document import Document


class SLAClock(Document):
    def validate(self):
        pass
