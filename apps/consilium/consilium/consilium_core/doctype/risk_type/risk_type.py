"""Risk Type — controller."""

import frappe
from frappe import _
from frappe.model.document import Document


class RiskType(Document):
    def validate(self):
        if int(self.tier or 0) not in (1, 2):
            frappe.throw(_("The risk taxonomy has two tiers: 1 and 2."))
        if int(self.tier or 0) == 2 and not self.parent_risk_type:
            frappe.throw(_("A tier 2 risk type sits under a tier 1 parent."))
        if int(self.tier or 0) == 1 and self.parent_risk_type:
            frappe.throw(_("A tier 1 risk type has no parent."))
