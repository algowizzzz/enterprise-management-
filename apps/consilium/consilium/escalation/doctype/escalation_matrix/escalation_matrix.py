"""Escalation Matrix — controller.

The matrix is the routing authority, so its own internal consistency is checked
here: rule codes are unique within a matrix, every destination and notification
belongs to a rule that exists, and a condition may only test a routable
attribute.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.escalation import routing


class EscalationMatrix(Document):
    def validate(self):
        self.validate_effective_dates()
        codes = self.validate_rule_codes()
        self.validate_rule_children(codes)
        self.validate_conditions()

    def validate_effective_dates(self) -> None:
        if self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
            frappe.throw(_("A matrix cannot expire before it takes effect."), title=_("Dates Out Of Order"))

    def validate_rule_codes(self) -> set[str]:
        codes: set[str] = set()
        for rule in self.rules:
            if rule.rule_code in codes:
                frappe.throw(
                    _("Rule code {0} appears twice in this matrix.").format(rule.rule_code),
                    title=_("Duplicate Rule Code"),
                )
            codes.add(rule.rule_code)
        return codes

    def validate_rule_children(self, codes: set[str]) -> None:
        for table, label in (("routes", _("destination")), ("rule_notifications", _("notification"))):
            for row in self.get(table):
                if row.rule_code not in codes:
                    frappe.throw(
                        _("The {0} in row {1} names rule {2}, which this matrix does not define.").format(
                            label, row.idx, row.rule_code
                        ),
                        title=_("Unknown Rule"),
                    )

    def validate_conditions(self) -> None:
        empty = frappe.get_doc({"doctype": "Escalation Matter"})
        for rule in self.rules:
            routing.condition_matches(rule.condition, empty)
