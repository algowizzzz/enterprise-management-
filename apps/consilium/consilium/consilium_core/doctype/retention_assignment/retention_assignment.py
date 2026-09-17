"""Retention Assignment — controller."""

from frappe.model.document import Document

from consilium.consilium_core import retention


class RetentionAssignment(Document):
    def on_update(self):
        retention.clear_cache()

    def on_trash(self):
        retention.clear_cache()
