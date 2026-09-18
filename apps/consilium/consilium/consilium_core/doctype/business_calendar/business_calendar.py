"""Business Calendar — controller."""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time

from consilium.consilium_core import jsonfields


class BusinessCalendar(Document):
    def load_from_db(self):
        # ``holidays`` is a JSON list, which the framework refuses to serialise
        # when PostgreSQL hands it back parsed: the desk form opened blank with
        # "Value for Holidays cannot be a list", and the REST interface failed
        # the same way. Held as its JSON text instead; readers already accept
        # either form (``sla._loads``).
        super().load_from_db()
        jsonfields.normalise_loaded(self)

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
