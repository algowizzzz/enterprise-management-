"""Risk Acceptance Approval Step — controller.

One step of a risk acceptance's approval chain. Validated with its route
(`consilium.escalation.approvals.validate_route`).
"""

from frappe.model.document import Document


class RiskAcceptanceApprovalStep(Document):
    pass
