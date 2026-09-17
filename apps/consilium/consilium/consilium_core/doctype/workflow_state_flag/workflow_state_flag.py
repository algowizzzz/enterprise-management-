"""Workflow State Flag — controller.

The mapping from a state label to semantic flags. State names live here as data;
no business logic compares them.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import state_flags


class WorkflowStateFlag(Document):
    def validate(self):
        duplicate = frappe.db.get_value(
            "Workflow State Flag",
            {
                "target_doctype": self.target_doctype,
                "state_field": self.state_field,
                "state_value": self.state_value,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if duplicate:
            frappe.throw(
                _("{0} already maps {1}.{2} = {3}.").format(
                    duplicate, self.target_doctype, self.state_field, self.state_value
                )
            )

    def on_update(self):
        state_flags.clear_cache(self.target_doctype)

    def on_trash(self):
        state_flags.clear_cache(self.target_doctype)
