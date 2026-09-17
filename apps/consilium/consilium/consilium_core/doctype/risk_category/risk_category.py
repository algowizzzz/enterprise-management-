"""Risk Category — controller.

The enterprise risk taxonomy. A tree so that tier 1 categories can carry sub-categories.
"""

from frappe.model.document import Document


class RiskCategory(Document):
    def validate(self):
        pass
