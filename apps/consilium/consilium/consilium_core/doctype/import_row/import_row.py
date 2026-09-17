"""Import Row — controller.

One staged record: what arrived, what it mapped to, and what happened to it. High volume, so field-level change history is off — the row itself is the history.
"""

from frappe.model.document import Document


class ImportRow(Document):
    def validate(self):
        pass
