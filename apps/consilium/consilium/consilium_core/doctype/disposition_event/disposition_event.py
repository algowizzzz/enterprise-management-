"""Disposition Event — controller.

The scheduled, held, approved and executed end of a retention period. Never automatic, and it outlives the record it disposed of.
"""

from frappe.model.document import Document


class DispositionEvent(Document):
    def validate(self):
        pass
