"""Notification Dispatch — controller.

Evidence that a party was notified. Recorded because several requirements need proof of notification, and an email queue that prunes itself is not evidence.
"""

from frappe.model.document import Document


class NotificationDispatch(Document):
    def validate(self):
        pass
