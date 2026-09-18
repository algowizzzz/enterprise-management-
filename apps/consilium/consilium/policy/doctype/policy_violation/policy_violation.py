"""Policy Violation — controller.

Semantic flags are derived from the configured state, and the moves between
states are held to what the flags allow (P-22). Nothing here names a state;
every rule reads the flags the old and the new state are configured with:

* **A violation is logged open.** A new record must start in a state that
  ``is_open``: logging something already closed would put a finding on the
  record that nobody ever investigated.
* **A closed violation stays closed.** Once a violation has left the open
  states — resolved or dismissed — its status does not move again. A breach
  that recurs is a new violation, with its own dates, so the history of the
  first is never rewritten. The refusal is audited.
* **Closing carries its statement.** A state whose flags demand a statement
  (``requires_statement``, set on resolving and dismissing) needs the resolution
  note, and it dates the resolution when the person closing it did not.

The order among the open states — logged, investigating, remediating — is not
policed here, because the flags cannot tell those states apart and a rule that
named them would be a rename waiting to break. Where a deployment wants that
order enforced, it is configuration: an active framework Workflow on
``violation_status`` is enforced by the framework on every save, alongside
these rules.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, nowdate

from consilium.consilium_core import audit
from consilium.consilium_core.state_flags import apply_state_flags, flags_for

STATE_FIELD = "violation_status"


class PolicyViolation(Document):
    def validate(self):
        apply_state_flags(self)
        self._enforce_transition()

    def _enforce_transition(self) -> None:
        flags = flags_for(self.doctype, STATE_FIELD, self.get(STATE_FIELD)) or {}
        if self.is_new():
            if flags and not cint(flags.get("is_open")):
                frappe.throw(
                    _("A violation is logged open, to be investigated; it cannot be recorded as already closed."),
                    title=_("Logged Closed"),
                )
        else:
            before = self.get_doc_before_save()
            if before is not None and before.get(STATE_FIELD) != self.get(STATE_FIELD):
                was = flags_for(self.doctype, STATE_FIELD, before.get(STATE_FIELD)) or {}
                if was and not cint(was.get("is_open")):
                    audit.refuse(
                        _("Violation {0} is closed ({1}) and cannot be moved to {2}. A recurrence is logged as "
                          "a new violation, so this one's history stands.").format(
                            self.name, before.get(STATE_FIELD), self.get(STATE_FIELD)
                        ),
                        subject_doctype=self.doctype,
                        subject_name=self.name,
                        attempted_action="Modify",
                        control="violation transition",
                        context={"from": before.get(STATE_FIELD), "to": self.get(STATE_FIELD)},
                        exc=frappe.ValidationError,
                    )
        if cint(flags.get("requires_statement")):
            if not (self.resolution_note or "").strip():
                frappe.throw(
                    _("Closing a violation needs a resolution note: what was done, or why it is dismissed."),
                    title=_("Resolution Note Required"),
                )
            if not self.resolved_on:
                self.resolved_on = nowdate()
