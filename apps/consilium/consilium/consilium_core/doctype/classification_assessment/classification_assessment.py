"""Classification Assessment — controller.

The immutable record of one evaluation: the answers given, the rule that fired, the outcome and the full trace of every rule considered (02-data-model.md §5.2). Append-only.
"""

from frappe.model.document import Document


class ClassificationAssessment(Document):
    def validate(self):
        pass
