"""Classification Question — controller.

One question in a rule set. Dependent questioning is expressed with depends_on_question / depends_on_answer.
"""

from frappe.model.document import Document


class ClassificationQuestion(Document):
    def validate(self):
        pass
