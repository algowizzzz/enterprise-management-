"""Archive Record — controller.

The write-once retention artefact: record fields, body, attachments and audit trail, hashed and chained. Immutability here is three mechanisms — no application path that mutates, the hash chain, and immutable storage for the payload. The third is an infrastructure obligation (07-assumptions-and-gaps.md A-1).
"""

from frappe.model.document import Document


class ArchiveRecord(Document):
    def validate(self):
        pass
