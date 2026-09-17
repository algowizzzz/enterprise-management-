"""Watched Field Set — controller."""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import watched_fields


class WatchedFieldSet(Document):
    def validate(self):
        meta = frappe.get_meta(self.target_doctype)
        for watched in self.fields:
            if not meta.has_field(watched.fieldname):
                frappe.throw(
                    _("{0} has no field {1}.").format(self.target_doctype, watched.fieldname)
                )
            if not watched.label:
                watched.label = meta.get_label(watched.fieldname)

    def on_update(self):
        watched_fields.clear_cache()

    def on_trash(self):
        watched_fields.clear_cache()
