"""Forum Risk Reference — controller.

A link from a forum to a risk held in the external risk register. The identifier is an External Reference, which is what stands where a connector would otherwise be (02-data-model.md §5.6).
"""

from frappe.model.document import Document


class ForumRiskReference(Document):
    def validate(self):
        pass
