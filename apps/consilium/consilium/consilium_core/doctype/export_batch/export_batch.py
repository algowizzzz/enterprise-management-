"""Export Batch — controller.

One generated outbound file, with its hash and the filter that produced it.
"""

from frappe.model.document import Document


class ExportBatch(Document):
    def validate(self):
        pass
