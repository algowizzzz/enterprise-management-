"""Business Calendar — controller."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time


class BusinessCalendar(Document):
    def validate(self):
        if get_time(self.day_end) <= get_time(self.day_start):
            frappe.throw(_("The working day has to end after it starts."))
        if self.holidays:
            try:
                value = json.loads(self.holidays) if isinstance(self.holidays, str) else self.holidays
            except ValueError as exc:
                frappe.throw(_("Holidays must be a list of dates: {0}").format(exc))
            if not isinstance(value, list):
                frappe.throw(_("Holidays must be a list of dates."))
