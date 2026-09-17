"""Import Batch — controller.

One file, staged, validated and committed. The file is retained exactly as received, with its hash, because the requirement is that integration activity be traceable.
"""

from frappe.model.document import Document


class ImportBatch(Document):
    def validate(self):
        pass
