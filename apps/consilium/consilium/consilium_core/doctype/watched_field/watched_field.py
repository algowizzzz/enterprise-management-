"""Watched Field — controller.

One watched field and the change that counts as a trigger.
"""

from frappe.model.document import Document


class WatchedField(Document):
    def validate(self):
        pass
