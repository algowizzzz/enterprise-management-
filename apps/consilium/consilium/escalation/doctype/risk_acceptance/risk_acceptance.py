"""Risk Acceptance — controller.

A risk acceptance carries a rationale and a bounded period, and it does not take
effect without an explicit, recorded approval (E16-S4). The flags say when it
takes effect; `consilium.escalation.approvals` says whether an approval exists.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate

from consilium.consilium_core import state_flags
from consilium.escalation import approvals, sensitivity, templates


class RiskAcceptance(Document):
    def validate(self):
        self.sensitive = sensitivity.inherited_sensitivity(self.escalation_matter)
        self.validate_period()
        state_flags.apply_state_flags(self)
        templates.apply_template(self, templates.SCOPE_RISK_ACCEPTANCE, self.matter_severity())
        self.validate_approval()
        self.set_reassessment()

    def matter_severity(self) -> str | None:
        return frappe.db.get_value("Escalation Matter", self.escalation_matter, "severity")

    def validate_period(self) -> None:
        if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(
                _("A risk acceptance cannot end before it starts."), title=_("Dates Out Of Order")
            )

    def validate_approval(self) -> None:
        """A state that gives the acceptance effect requires an approval on the record."""
        if not self.is_committable:
            return
        if not approvals.is_approved(self):
            frappe.throw(
                _(
                    "A risk acceptance takes effect only on an explicit approval. "
                    "Record an approval decision through the approval path, or reference the forum motion that approved it."
                ),
                title=_("Approval Required"),
            )
        if self.requires_statement and not self.rationale:
            frappe.throw(_("An approved risk acceptance must state its rationale."), title=_("Rationale Required"))

    def set_reassessment(self) -> None:
        if self.reassessment_frequency_months and not self.next_reassessment_on and self.start_date:
            self.next_reassessment_on = add_months(
                getdate(self.start_date), int(self.reassessment_frequency_months)
            )
