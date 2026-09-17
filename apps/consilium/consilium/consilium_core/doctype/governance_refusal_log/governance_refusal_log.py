"""Governance Refusal Log — controller.

Written out of band by :mod:`consilium.consilium_core.audit`. Nothing edits or
deletes a refusal record through the application.
"""

from frappe.model.document import Document

from consilium.consilium_core import append_only


class GovernanceRefusalLog(Document):
    def validate(self):
        append_only.guard_update(self, control="refusal log append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="refusal log append-only")
