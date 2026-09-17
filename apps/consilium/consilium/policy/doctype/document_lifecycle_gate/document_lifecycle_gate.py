"""Document Lifecycle Gate — controller."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class DocumentLifecycleGate(Document):
    def validate(self):
        from consilium.policy.lifecycle import GATES

        if self.gate not in GATES:
            frappe.throw(
                _("{0} names no implemented check. A gate binds a state to a check; the check is code.")
                .format(self.gate),
                title=_("Unknown Gate"),
            )
