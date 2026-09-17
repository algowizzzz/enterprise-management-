"""Notification Channel — controller.

A delivery channel and its adapter, so a channel can be introduced without touching a notification definition (02-data-model.md §5.7).
"""

from frappe.model.document import Document


class NotificationChannel(Document):
    def validate(self):
        pass
