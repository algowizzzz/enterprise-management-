"""Formation Approval Route — controller.

The configurable multi-step approval a committee formation request follows (E7-S4). Not named in 02-data-model.md §6; added because the acceptance criterion requires the steps to be configuration rather than code. One active route per request type wins, most recently modified first.
"""

from frappe.model.document import Document


class FormationApprovalRoute(Document):
    def validate(self):
        pass
