"""Document Relationship — controller.

P-4 lineage: children, addenda, supersession and plain references. `owner_approval_required` is what makes P-8's parent-owner approval a derived step rather than a hand-added one.
"""

from frappe.model.document import Document


class DocumentRelationship(Document):
    def validate(self):
        pass
