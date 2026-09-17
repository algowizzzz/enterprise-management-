"""AI Service Request — controller.

What data left the platform, to which capability, and what came back (02-data-model.md §5.10). A data-boundary control. Append-only.
"""

from frappe.model.document import Document


class AIServiceRequest(Document):
    def validate(self):
        pass
