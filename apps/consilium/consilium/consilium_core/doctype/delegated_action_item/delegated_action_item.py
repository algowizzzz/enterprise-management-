"""Delegated Action Item — controller.

One delegable action carried by an authority delegation.
"""

from frappe.model.document import Document


class DelegatedActionItem(Document):
    def validate(self):
        pass
