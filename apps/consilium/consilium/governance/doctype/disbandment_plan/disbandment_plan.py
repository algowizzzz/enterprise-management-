"""Disbandment Plan — controller.

G-11's controlled dissolution. The plan names its approvers; each decision is a
Core ``Approval Decision``, and the forum cannot be disbanded while any required
approval is open. Execution is in ``consilium.governance.lifecycle``.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import approvals


class DisbandmentPlan(Document):
    def validate(self):
        if self.successor_forum == self.forum:
            frappe.throw(_("A forum cannot succeed itself."), title=_("Invalid Successor"))
        if not [row for row in self.approvals if row.required]:
            frappe.throw(
                _("A disbandment plan names the approvals it requires (G-11)."),
                title=_("Approvals Required"),
            )
        self._mirror_decisions()

    def _mirror_decisions(self):
        """Copy the Core decision onto the row for display. Never read as logic."""
        for row in self.approvals:
            if not row.approval_decision:
                continue
            decided = frappe.db.get_value(
                "Approval Decision", row.approval_decision, ["decision", "decided_on"], as_dict=True
            )
            if decided:
                row.decision = decided.decision
                row.decided_on = decided.decided_on

    def raise_approvals(self) -> list[str]:
        """Raise a Core approval decision for every required approver."""
        raised = []
        for row in self.approvals:
            if not row.required or row.approval_decision:
                continue
            decision = approvals.request_decision(
                subject_doctype=self.doctype,
                subject_name=self.name,
                approval_step=row.approver_role,
                step_sequence=row.idx,
                # The required approvers of a disbandment sign in any order: the
                # row order on the plan is how they were listed, not a route.
                # Sequential steps are enforced by Core (E7-S4), so this says so.
                mode="Parallel",
                assigned_to=row.approver,
            )
            row.db_set("approval_decision", decision.name, update_modified=False)
            raised.append(decision.name)
        return raised
