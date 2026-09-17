"""Notification Channel — controller."""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import notification


class NotificationChannel(Document):
    def validate(self):
        if self.adapter not in notification.ADAPTERS:
            frappe.throw(
                _("No notification adapter named {0} is registered.").format(self.adapter),
                title=_("Unknown Adapter"),
            )
        self._validate_no_fallback_cycle()

    def _validate_no_fallback_cycle(self):
        seen, current = {self.name}, self.fallback_channel
        while current:
            if current in seen:
                frappe.throw(_("The fallback chain through {0} is a cycle.").format(current))
            seen.add(current)
            current = frappe.db.get_value("Notification Channel", current, "fallback_channel")
