"""Workflow State Flag — controller.

The mapping from a state label to semantic flags. State names live here as data;
no business logic compares them.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import state_flags

#: The business-facing phase a state may belong to (see the Phase field's help).
PHASE_FIELD = "lifecycle_phase"


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

        self._validate_phase()

    def _validate_phase(self):
        """A phase must be one the record type already has.

        The phase column lets a new state join an existing phase without a schema
        change, so a misspelt phase ("Legal" for "Review") would otherwise be saved
        and only surface at the first move, as a confusing refusal about missing
        flags. Checked here, against the phase field's own options, it is caught
        where it was typed.
        """
        if not self.phase:
            return
        field = frappe.get_meta(self.target_doctype).get_field(PHASE_FIELD) if self.target_doctype else None
        options = [o for o in ((field.options or "") if field else "").split("\n") if o]
        if not options:
            frappe.throw(
                _("{0} has no {1} field, so a state of it cannot name a phase. Leave Phase empty.").format(
                    self.target_doctype, PHASE_FIELD
                ),
                title=_("No Phase To Name"),
            )
        if self.phase not in options:
            frappe.throw(
                _("Phase \"{0}\" is not a phase of {1}. Use one of: {2}.").format(
                    self.phase, self.target_doctype, ", ".join(options)
                ),
                title=_("Unknown Phase"),
            )

    def on_update(self):
        state_flags.clear_cache(self.target_doctype)

    def on_trash(self):
        state_flags.clear_cache(self.target_doctype)
