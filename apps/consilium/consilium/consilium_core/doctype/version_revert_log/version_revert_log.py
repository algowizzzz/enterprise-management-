"""Version Revert Log — controller. The audited act of reverting."""

from frappe.model.document import Document

from consilium.consilium_core import append_only


class VersionRevertLog(Document):
    def validate(self):
        append_only.guard_update(self, control="revert log append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="revert log append-only")
