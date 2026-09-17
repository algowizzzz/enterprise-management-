"""Charter Approval Evidence — controller.

Proof that a charter was approved, in one of the forms G-5 accepts.
"""

from frappe.model.document import Document


class CharterApprovalEvidence(Document):
    def validate(self):
        pass
