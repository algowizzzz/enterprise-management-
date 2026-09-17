"""Classification Answer Option — controller.

One answer option. Carries question_code because the framework has no nested child tables.
"""

from frappe.model.document import Document


class ClassificationAnswerOption(Document):
    def validate(self):
        pass
