"""Attestation Campaign — controller."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.consilium_core.state_flags import apply_state_flags


class AttestationCampaign(Document):
    def validate(self):
        apply_state_flags(self)
        self._validate_period()
        self._validate_dates()
        self._validate_population_config()

    def _validate_period(self):
        duplicate = frappe.db.get_value(
            "Attestation Campaign",
            {
                "campaign_type": self.campaign_type,
                "period_label": self.period_label,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if duplicate:
            frappe.throw(
                _("Campaign {0} already covers {1} for period {2}.").format(
                    duplicate, self.campaign_type, self.period_label
                )
            )

    def _validate_dates(self):
        if self.opens_on and self.due_on and getdate(self.due_on) < getdate(self.opens_on):
            frappe.throw(_("A campaign cannot be due before it opens."))

    def _validate_population_config(self):
        if self.participant_source == "Record Field" and not self.participant_field:
            frappe.throw(_("A record-field population needs the fieldname holding the accountable person."))
        if self.participant_source == "Seat Role":
            for fieldname in ("seat_doctype", "seat_subject_field", "seat_user_field"):
                if not self.get(fieldname):
                    frappe.throw(_("A seat-role population needs {0}.").format(_(fieldname)))
        if self.requires_dual_signature and not self.second_signatory_field:
            frappe.throw(_("A dual-signature campaign needs the fieldname holding the second signatory."))
