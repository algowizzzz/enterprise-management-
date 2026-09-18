"""Reminder Log — controller.

One row per scheduled reminder sent, so the daily job can tell what it has already said and never repeats itself on the same day.

    Specified by: P-10, P-11, E-9, E-11: idempotent scheduled reminders.
"""

from frappe.model.document import Document


class ReminderLog(Document):
    def validate(self):
        pass
