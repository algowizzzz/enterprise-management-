"""Authority Delegation — controller."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.consilium_core import delegation


class AuthorityDelegation(Document):
    def validate(self):
        if self.delegator == self.delegate:
            frappe.throw(_("A delegation needs two different people."))
        if self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
            frappe.throw(_("A delegation cannot end before it starts."))
        self._validate_scope()
        self._validate_actions()
        delegation.refresh_active_flag(self)

    def _validate_scope(self):
        if self.scope_type in ("DocType", "Record", "Forum") and not self.scope_doctype:
            frappe.throw(_("Scope type {0} needs a scope DocType.").format(self.scope_type))
        if self.scope_type in ("Record", "Forum") and not self.scope_record:
            frappe.throw(_("Scope type {0} needs a scope record.").format(self.scope_type))

    def _validate_actions(self):
        if not self.delegated_actions:
            frappe.throw(_("A delegation must name the actions it transfers."))
        for row in self.delegated_actions:
            if not frappe.db.get_value("Delegable Action", row.delegable_action, "is_administrative"):
                frappe.msgprint(
                    _("{0} is not an administrative action; delegating it needs deliberate approval.").format(
                        row.delegable_action
                    ),
                    alert=True,
                )
