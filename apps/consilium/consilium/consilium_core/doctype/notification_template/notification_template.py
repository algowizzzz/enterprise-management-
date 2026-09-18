"""Notification Template — controller.

The wording of one notification event on one channel (G-14, P-14, E-17, O-4).
Subject and body are Jinja, rendered by ``notification.notify`` against the
event's context, so an administrator changes what people are told without a
release.

A template that does not parse is refused here, where the person who wrote it
is looking. A template that parses but fails when rendered (a name the event
does not supply, a division by zero) is caught at send time instead, logged,
and replaced by the built-in wording for that send — a typo must not cost
anyone a reminder.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import notification


class NotificationTemplate(Document):
    def validate(self):
        self.event_code = (self.event_code or "").strip()
        if not self.event_code or " " in self.event_code:
            frappe.throw(_("An event code is a single word such as policy.review.overdue."))
        notification.validate_template(self.subject)
        notification.validate_template(self.body)
