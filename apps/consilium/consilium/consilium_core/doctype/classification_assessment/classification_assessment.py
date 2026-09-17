"""Classification Assessment — controller.

Immutable, except for the override fields, which are written once through
:func:`consilium.consilium_core.classification.override`.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import append_only

OVERRIDE_FIELDS = ("overridden", "override_outcome", "override_justification", "override_approved_by")


class ClassificationAssessment(Document):
    def validate(self):
        append_only.guard_update(
            self,
            allowed=OVERRIDE_FIELDS,
            permit_flag="consilium_override",
            control="assessment append-only",
        )
        if self.overridden and not (self.override_justification or "").strip():
            frappe.throw(_("An override needs a justification."))

    def on_trash(self):
        append_only.guard_delete(self, control="assessment append-only")
