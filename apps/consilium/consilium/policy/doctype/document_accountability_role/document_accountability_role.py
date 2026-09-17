"""Document Accountability Role — controller.

A many-per-document accountability role — Monitor, Partner, Reviewer and the rest — which cannot be a single field on the document (02-data-model.md §7.4).
"""

from frappe.model.document import Document


class DocumentAccountabilityRole(Document):
    def validate(self):
        pass
