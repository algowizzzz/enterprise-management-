"""Glossary Term — controller."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core.state_flags import apply_state_flags


class GlossaryTerm(Document):
    def validate(self):
        apply_state_flags(self)
        if self.scope_level != "Enterprise" and not self.scope_document:
            frappe.throw(
                _("A term scoped below the enterprise must name the document it is scoped to."),
                title=_("Scope Document Required"),
            )
        if self.superseded_by == self.name:
            frappe.throw(_("A term cannot supersede itself."))
