"""Jurisdiction — controller.

Regulatory jurisdictions used for applicability and for tagging.
"""

from frappe.model.document import Document


class Jurisdiction(Document):
    def validate(self):
        pass
