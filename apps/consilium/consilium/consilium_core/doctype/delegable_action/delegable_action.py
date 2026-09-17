"""Delegable Action — controller.

The actions an authority delegation may transfer — approve, review, attest, submit, edit, acknowledge (§4.3). [Inferred — 02-data-model.md §11 I-3. Without it delegation is all-or-nothing, which conflicts with the segregation-of-duties requirement.]
"""

from frappe.model.document import Document


class DelegableAction(Document):
    def validate(self):
        pass
