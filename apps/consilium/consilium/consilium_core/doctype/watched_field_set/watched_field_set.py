"""Watched Field Set — controller.

The admin-editable list of fields whose modification triggers a compliance re-review (02-data-model.md §5.3). One set per target DocType.
"""

from frappe.model.document import Document


class WatchedFieldSet(Document):
    def validate(self):
        pass
