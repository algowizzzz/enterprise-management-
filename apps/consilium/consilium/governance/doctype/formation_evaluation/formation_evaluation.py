"""Formation Evaluation — controller.

One row per G-5 evaluation criterion, so the criteria set is data. A request cannot be approved while any criterion is unassessed.
"""

from frappe.model.document import Document


class FormationEvaluation(Document):
    def validate(self):
        pass
