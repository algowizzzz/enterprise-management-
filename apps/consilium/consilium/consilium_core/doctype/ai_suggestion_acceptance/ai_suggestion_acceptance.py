"""AI Suggestion Acceptance — controller. Append-only."""

from frappe.model.document import Document

from consilium.consilium_core import append_only


class AISuggestionAcceptance(Document):
    def validate(self):
        append_only.guard_update(self, control="ai acceptance append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="ai acceptance append-only")
