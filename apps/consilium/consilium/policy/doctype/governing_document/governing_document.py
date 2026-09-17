"""Governing Document — controller.

The record's own rules. Everything that needs more than one record — routing,
gating, notification, lineage across the graph — lives in the module's engines
and is called from here.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate, nowdate

from consilium.consilium_core.state_flags import apply_state_flags
from consilium.policy import applicability, lineage, metadata

#: Handling classifications that close the three named actions by default. An
#: administrator may reopen them on a record; this only supplies the default.
_RESTRICTED_HANDLING = ("Confidential", "Restricted")


class GoverningDocument(Document):
    def validate(self):
        apply_state_flags(self)
        lineage.validate_lineage(self)
        self._derive_handling_defaults()
        self._validate_applicability()
        self._validate_conditional_fields()
        self._derive_review_date()
        self._derive_retirement_date()

    def on_update(self):
        self._raise_remediation_on_deactivation()

    # ------------------------------------------------------------------ rules

    def _derive_handling_defaults(self) -> None:
        """P-1/P-13: a confidential document is not downloadable, printable or
        shareable unless somebody says otherwise on the record."""
        if self.confidential and self.handling_classification not in _RESTRICTED_HANDLING:
            self.handling_classification = "Confidential"
        if self.is_new() and self.handling_classification in _RESTRICTED_HANDLING:
            self.allow_download = 0
            self.allow_print = 0
            self.allow_share = 0

    def _validate_applicability(self) -> None:
        """A scope either names a record or carries a label; never neither.

        The scope type is spelled as the DocType it names, so the framework has
        already validated the reference itself by the time this runs.
        """
        for row in self.get("applicability") or []:
            names_a_record = applicability.scope_doctype_for(row.scope_type)
            if names_a_record and not row.scope_value:
                frappe.throw(
                    _("Applicability row {0} has scope type {1} but names no record.").format(
                        row.idx, row.scope_type
                    )
                )
            if not names_a_record and not row.scope_label:
                frappe.throw(
                    _("Applicability row {0} has scope type {1}, which names no record, so it needs a label.")
                    .format(row.idx, row.scope_type)
                )

    def _validate_conditional_fields(self) -> None:
        if self.material_entity_impact and not self.get("material_entities"):
            frappe.throw(
                _("Material entity impact is marked, so at least one material entity must be named."),
                title=_("Material Entities Required"),
            )
        if self.regulatory_required and not self.get("regulatory_references"):
            frappe.throw(
                _("This document is regulatory-required, so at least one regulatory reference is needed."),
                title=_("Regulatory Reference Required"),
            )
        if self.superseded_by == self.name:
            frappe.throw(_("A document cannot supersede itself."))

    def _derive_review_date(self) -> None:
        months = int(self.review_frequency_months or 0)
        if months and not self.next_review_on:
            anchor = self.effective_on or nowdate()
            self.next_review_on = add_months(getdate(anchor), months)

    def _derive_retirement_date(self) -> None:
        """The retirement date follows the flags, not a state name: a document
        that has left force for the last time is retired as of today."""
        if self.is_active or self.is_editable or self.is_new():
            return
        before = self.get_doc_before_save()
        if before is None or int(before.get("is_active") or 0) != 1:
            return
        if not self.retired_on:
            self.retired_on = nowdate()

    def _raise_remediation_on_deactivation(self) -> None:
        """P-23: a parent leaving force invalidates its children's parent link."""
        before = self.get_doc_before_save()
        if before is None:
            return
        if int(before.get("is_active") or 0) == 1 and not int(self.is_active or 0):
            metadata.raise_tasks_for_deactivated_parent(self)

    # -------------------------------------------------------------- convenience

    @frappe.whitelist()
    def missing_metadata(self) -> list[str]:
        return metadata.missing_fields(self)
