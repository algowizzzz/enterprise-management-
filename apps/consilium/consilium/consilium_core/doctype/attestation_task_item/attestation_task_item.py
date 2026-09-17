"""Attestation Task Item — controller.

Line-by-line confirmation where an attestation is over a list. [Inferred — §11 I-5.]
"""

from frappe.model.document import Document


class AttestationTaskItem(Document):
    def validate(self):
        pass
