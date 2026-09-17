"""ImportBatch — controller. Semantic flags are derived from the state label."""

from frappe.model.document import Document

from consilium.consilium_core.state_flags import apply_state_flags


class ImportBatch(Document):
    def validate(self):
        apply_state_flags(self)
