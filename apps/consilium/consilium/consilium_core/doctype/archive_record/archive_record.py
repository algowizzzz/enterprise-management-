"""Archive Record — controller.

The write-once retention artefact. The hash chain is computed on insert and
nothing but the integrity sweep may write afterwards.
"""

import hashlib
import json

import frappe
from frappe.model.document import Document

from consilium.consilium_core import append_only

SWEEP_FIELDS = ("verified_on", "verification_result")


class ArchiveRecord(Document):
    def before_insert(self):
        previous = frappe.db.sql(
            '''SELECT "chain_hash" FROM "tabArchive Record" ORDER BY "creation" DESC LIMIT 1'''
        )
        self.previous_archive_hash = previous[0][0] if previous else ""
        self.chain_hash = self.compute_chain_hash()

    def compute_chain_hash(self) -> str:
        payload = json.dumps(
            {
                "subject_doctype": self.subject_doctype,
                "subject_name": self.subject_name,
                "document_version": self.document_version,
                "archived_on": str(self.archived_on),
                "retention_class": self.retention_class,
                "payload_sha256": self.payload_sha256,
                "previous": self.previous_archive_hash or "",
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate(self):
        append_only.guard_update(self, allowed=SWEEP_FIELDS, control="archive append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="archive append-only")
