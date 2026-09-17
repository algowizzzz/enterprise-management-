"""Approval Route — controller."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ApprovalRoute(Document):
    def validate(self):
        if not self.get("steps"):
            frappe.throw(_("A route with no steps approves nothing."), title=_("Steps Required"))
        sequences = [int(row.step_sequence or 0) for row in self.steps]
        if len(set(sequences)) != len(sequences):
            frappe.throw(_("Two steps share a sequence number; the order would be undefined."))
        labels = [row.approval_step for row in self.steps]
        if len(set(labels)) != len(labels):
            frappe.throw(
                _("Two steps share a name. A decision is matched to its step by name, so names must differ.")
            )
        for row in self.steps:
            if row.assignee_source == "Named User" and not row.assignee:
                frappe.throw(_("Step {0} names a user as its source but names no user.").format(row.idx))
