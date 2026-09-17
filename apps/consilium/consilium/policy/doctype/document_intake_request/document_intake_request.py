"""document intake request — controller. Semantic flags are derived from the configured state."""

from frappe.model.document import Document

from consilium.consilium_core.state_flags import apply_state_flags


class DocumentIntakeRequest(Document):
    def validate(self):
        apply_state_flags(self)
