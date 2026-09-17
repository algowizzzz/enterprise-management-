"""Monitoring Result — controller."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate

#: How far ahead the next occurrence of an activity falls, by frequency.
FREQUENCY_MONTHS = {
    "Monthly": 1,
    "Quarterly": 3,
    "Semi Annual": 6,
    "Annual": 12,
}


class MonitoringResult(Document):
    def validate(self):
        if not self.document:
            self.document = frappe.db.get_value("Monitoring Activity", self.monitoring_activity, "document")
        if self.outcome != "Not Performed" and not (self.findings or self.evidence):
            frappe.throw(
                _("A performed monitoring activity records findings, evidence, or both."),
                title=_("Evidence Required"),
            )

    def on_update(self):
        self._advance_activity()

    def _advance_activity(self) -> None:
        activity = frappe.get_doc("Monitoring Activity", self.monitoring_activity)
        months = FREQUENCY_MONTHS.get(activity.frequency)
        if not months or not self.performed_on:
            return
        next_due = add_months(getdate(self.performed_on), months)
        if not activity.next_due_on or getdate(activity.next_due_on) <= getdate(self.performed_on):
            frappe.db.set_value("Monitoring Activity", activity.name, "next_due_on", next_due)
