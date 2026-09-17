"""External Reference — controller.

A recorded, reportable foreign identifier with a known provenance batch, standing where a live connector would otherwise be (02-data-model.md §5.6). When a connector is eventually built it populates these same rows.
"""

from frappe.model.document import Document


class ExternalReference(Document):
    def validate(self):
        pass
