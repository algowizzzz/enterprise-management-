"""SLA Definition — controller.

An agreed time target for a workflow step, a status duration or total time
open, with a warning threshold (02-data-model.md §5.8). The framework supplies
none of this.

The status-driven measures are checked here rather than failing quietly at the
first sweep: a Time In State definition without a state to measure, or naming
a field the DocType does not have, would never start a clock, and nobody would
notice that the step was unmeasured until an audit asked for its figures.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import sla


class SLADefinition(Document):
    def validate(self):
        pct = int(self.warning_threshold_pct or 0)
        if pct < 0 or pct > 100:
            frappe.throw(_("The warning threshold is a percentage between 0 and 100; 0 means no warning."))
        if float(self.target_hours or 0) <= 0:
            frappe.throw(_("The target must be a positive number of hours."))
        if self.measure in sla.STATE_MEASURES:
            self._validate_state_measure()

    def _validate_state_measure(self):
        meta = frappe.get_meta(self.target_doctype)
        if self.measure == sla.MEASURE_TIME_IN_STATE and not (self.state_field and self.state_value):
            frappe.throw(
                _("{0} needs the state field and the state value to measure.").format(self.measure),
                title=_("State Not Configured"),
            )
        if self.state_field and not meta.has_field(self.state_field):
            frappe.throw(
                _("{0} has no field named {1}.").format(self.target_doctype, self.state_field),
                title=_("Unknown State Field"),
            )
        if not meta.track_changes:
            # The clocks are rebuilt from the change log; without one there is
            # no record of when the state changed.
            frappe.throw(
                _("{0} does not track changes, so the time it spends in a state cannot be measured.").format(
                    self.target_doctype
                ),
                title=_("Change Tracking Required"),
            )

    def on_update(self):
        sla.clear_cache()

    def on_trash(self):
        sla.clear_cache()
