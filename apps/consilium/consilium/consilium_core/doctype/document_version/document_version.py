"""Document Version — controller.

Append-only, with one deliberate exception: the two chain-linkage fields, written
only by the versioning service when the next version supersedes this one.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import append_only

CHAIN_FIELDS = ("is_current", "superseded_by")


class DocumentVersion(Document):
    def validate(self):
        append_only.guard_update(
            self,
            allowed=CHAIN_FIELDS,
            permit_flag="consilium_chain_update",
            control="document version append-only",
        )
        self._validate_single_current()

    def _validate_single_current(self):
        if not self.is_current:
            return
        other = frappe.db.get_value(
            "Document Version",
            {
                "subject_doctype": self.subject_doctype,
                "subject_name": self.subject_name,
                "is_current": 1,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if other:
            frappe.throw(
                _("Version {0} is already current for {1} {2}.").format(
                    other, self.subject_doctype, self.subject_name
                )
            )

    def on_trash(self):
        append_only.guard_delete(self, control="document version append-only")
