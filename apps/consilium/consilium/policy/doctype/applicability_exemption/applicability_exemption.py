"""Applicability Exemption — controller.

P-21's formal exemption. It has its own approval and its own expiry, and while it
is in force it suppresses the notification the applicability row it names would
otherwise produce. `is_active` — the semantic flag its status sets — is what the
applicability resolver reads; nothing reads the status label.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from consilium.consilium_core.state_flags import apply_state_flags
from consilium.policy import applicability


class ApplicabilityExemption(Document):
    def validate(self):
        apply_state_flags(self)
        names_a_record = applicability.scope_doctype_for(self.scope_type)
        if names_a_record and not self.scope_value:
            frappe.throw(_("Scope type {0} names a record, so one must be chosen.").format(self.scope_type))
        if not names_a_record and not self.scope_label:
            frappe.throw(_("Scope type {0} names no record, so it needs a label.").format(self.scope_type))
        if self.valid_from and self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
            frappe.throw(_("An exemption cannot expire before it begins."))
        if self.is_active and not self.approved_by:
            frappe.throw(
                _("An exemption in force must name who authorised it."),
                title=_("Approval Required"),
            )

    def authorise(self, approved_by: str | None = None):
        """Put the exemption in force. A distinct act with a named authoriser."""
        self.check_permission("write")
        self.approved_by = approved_by or frappe.session.user
        self.approved_on = nowdate()
        self.exemption_status = "Authorised"
        self.save()
        return self


def lapse_expired(as_of=None) -> list[str]:
    """Take exemptions out of force once they expire. Scheduled work."""
    as_of = getdate(as_of or nowdate())
    lapsed = []
    for name in frappe.get_all(
        "Applicability Exemption",
        filters={"is_active": 1, "valid_to": ["<", as_of], "docstatus": ["<", 2]},
        pluck="name",
    ):
        doc = frappe.get_doc("Applicability Exemption", name)
        doc.exemption_status = "Lapsed"
        doc.save(ignore_permissions=True)
        lapsed.append(name)
    return lapsed
