"""Document Applicability — controller.

Where a document applies (P-21). Notification of affected parties is derived from these rows; there is no hand-maintained recipient list anywhere in the module.
"""

from frappe.model.document import Document


class DocumentApplicability(Document):
    def validate(self):
        pass
