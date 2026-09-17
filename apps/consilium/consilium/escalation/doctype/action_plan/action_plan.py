"""Action Plan — controller.

Several plans may hang off one matter, each with its own dates, accountable
executive, owner and status (E16-S3).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now

from consilium.consilium_core import state_flags
from consilium.escalation import sensitivity, templates


class ActionPlan(Document):
    def validate(self):
        self.sensitive = sensitivity.inherited_sensitivity(self.escalation_matter)
        self.validate_dates()
        state_flags.apply_state_flags(self)
        templates.apply_template(self, templates.SCOPE_ACTION_PLAN, self.matter_severity())
        self.stamp_completion()

    def matter_severity(self) -> str | None:
        return frappe.db.get_value("Escalation Matter", self.escalation_matter, "severity")

    def validate_dates(self) -> None:
        if self.start_date and self.end_date and getdate(self.end_date) < getdate(self.start_date):
            frappe.throw(_("An action plan cannot end before it starts."), title=_("Dates Out Of Order"))

    def stamp_completion(self) -> None:
        """A plan that has come to rest while still having effect is complete."""
        if not self.is_open and self.is_active and not self.completed_on:
            self.completed_on = now()
        if self.is_open:
            self.completed_on = None
