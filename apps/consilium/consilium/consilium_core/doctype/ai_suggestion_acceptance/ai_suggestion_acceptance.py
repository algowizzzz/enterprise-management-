"""AI Suggestion Acceptance — controller.

Who took responsibility for machine-generated content, against which version (02-data-model.md §5.10). An accountability control, not derivable from the request record. Append-only.
"""

from frappe.model.document import Document


class AISuggestionAcceptance(Document):
    def validate(self):
        pass
