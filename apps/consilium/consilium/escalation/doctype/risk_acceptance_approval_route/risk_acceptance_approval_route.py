"""Risk Acceptance Approval Route — controller.

The approval chain a risk acceptance goes through, for a matter type and
severity. How a route is chosen and turned into Core `Approval Decision` steps
is `consilium.escalation.approvals`; this controller only refuses a route that
could not be raised: one with no steps, a step without a sequence, or a named
step without the person it names.

    Specified by: REQUIREMENTS-COVERAGE.md E-9: configurable sequential or parallel approvals by type and severity.
"""

from frappe.model.document import Document

from consilium.escalation import approvals


class RiskAcceptanceApprovalRoute(Document):
    def validate(self):
        approvals.validate_route(self)
