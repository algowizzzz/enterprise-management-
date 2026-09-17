"""Formation Approval Route Step — controller.

One configured step of a formation approval route. Steps are configuration: a step can be added, reordered or made parallel without a deployment (E7-S4).
"""

from frappe.model.document import Document


class FormationApprovalRouteStep(Document):
    def validate(self):
        pass
