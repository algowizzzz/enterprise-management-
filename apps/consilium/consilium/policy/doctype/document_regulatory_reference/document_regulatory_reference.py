"""Document Regulatory Reference — controller.

P-6 regulatory capture against the shared Regulatory Requirement library, so a regulatory change is assessed once and fans out to every document that cites it.
"""

from frappe.model.document import Document


class DocumentRegulatoryReference(Document):
    def validate(self):
        pass
