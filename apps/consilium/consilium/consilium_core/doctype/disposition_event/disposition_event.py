"""Disposition Event — controller."""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core.state_flags import apply_state_flags


class DispositionEvent(Document):
    def validate(self):
        apply_state_flags(self)
        if self.executed_on and not self.approved_by:
            frappe.throw(_("A disposition cannot be executed without a named approver."))
