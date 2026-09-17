"""Attestation Task — controller."""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core.state_flags import apply_state_flags


class AttestationTask(Document):
    def validate(self):
        apply_state_flags(self)
        self._validate_uniqueness()
        self._validate_statement()
        self._validate_second_signatory()

    def _validate_uniqueness(self):
        duplicate = frappe.db.get_value(
            "Attestation Task",
            {
                "campaign": self.campaign,
                "assigned_to": self.assigned_to,
                "subject_doctype": self.subject_doctype,
                "subject_name": self.subject_name,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if duplicate:
            frappe.throw(
                _("Task {0} already asks {1} to attest {2} {3} in this campaign.").format(
                    duplicate, self.assigned_to, self.subject_doctype, self.subject_name
                ),
                title=_("Duplicate Attestation Task"),
            )

    def _validate_statement(self):
        if self.requires_statement and not (self.response_statement or "").strip():
            frappe.throw(
                _("This response needs a written statement."), title=_("Statement Required")
            )

    def _validate_second_signatory(self):
        requires_dual = frappe.db.get_value("Attestation Campaign", self.campaign, "requires_dual_signature")
        if requires_dual and not self.second_signatory:
            frappe.throw(_("This campaign requires a second signatory on every task."))
        if self.second_signatory and self.second_signatory == self.assigned_to:
            frappe.throw(_("A dual signature needs two different people."))
