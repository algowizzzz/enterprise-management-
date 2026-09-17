"""Retention Class — controller.

How long a record is kept, from what trigger, and what happens at the end (02-data-model.md §5.5).
"""

from frappe.model.document import Document


class RetentionClass(Document):
    def validate(self):
        pass
