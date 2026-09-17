"""Periodic Submission — controller.

E-11's periodic return. A return with no matters in scope is not an empty
record: it is a nil return, and somebody has to say so.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now

from consilium.consilium_core import state_flags


class PeriodicSubmission(Document):
    def validate(self):
        self.validate_period()
        state_flags.apply_state_flags(self)
        self.matter_count = self.count_matters()
        if not self.is_open:
            self.submitted_by = self.submitted_by or frappe.session.user
            self.submitted_on = self.submitted_on or now()
            if not self.matter_count and not self.nil_return:
                frappe.throw(
                    _("No matters fall in this period. Confirm the nil return before submitting."),
                    title=_("Nil Return Required"),
                )

    def validate_period(self) -> None:
        if getdate(self.period_end) < getdate(self.period_start):
            frappe.throw(_("A period cannot end before it starts."), title=_("Dates Out Of Order"))

    def count_matters(self) -> int:
        filters = self.scope_filter
        if isinstance(filters, str):
            filters = json.loads(filters) if filters else {}
        filters = dict(filters or {})
        filters["escalation_identification_date"] = ["between", [self.period_start, self.period_end]]
        return frappe.db.count("Escalation Matter", filters)
