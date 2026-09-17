"""Classification Rule Set — controller.

The versioned, admin-defined questions, answer options and rules that produce a classification outcome (02-data-model.md §5.2). Data, not code. A rule set that has classified anything is locked; a change is a new version.
"""

from frappe.model.document import Document


class ClassificationRuleSet(Document):
    def validate(self):
        pass
