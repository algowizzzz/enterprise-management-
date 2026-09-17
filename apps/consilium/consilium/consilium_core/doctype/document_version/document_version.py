"""Document Version — controller.

An immutable snapshot in a record's version chain: the body file, its hash and the full field state at that version (02-data-model.md §5.4). Append-only. Revert writes a NEW row; it never mutates one.
"""

from frappe.model.document import Document


class DocumentVersion(Document):
    def validate(self):
        pass
