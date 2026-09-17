"""Forum Regulatory Requirement — controller.

The regulatory detail G-4 requires once a forum is marked regulatory-required. The citation is drawn from Core's shared Regulatory Requirement library so that a regulatory change fans out in one hop.
"""

from frappe.model.document import Document


class ForumRegulatoryRequirement(Document):
    def validate(self):
        pass
