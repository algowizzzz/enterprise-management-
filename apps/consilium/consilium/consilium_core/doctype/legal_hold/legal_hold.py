"""Legal Hold — controller.

A suspension of disposition, placed for litigation, investigation or regulatory reasons. Overrides retention unconditionally; does not suspend retention accrual and does not change the retention class.
"""

from frappe.model.document import Document


class LegalHold(Document):
    def validate(self):
        pass
