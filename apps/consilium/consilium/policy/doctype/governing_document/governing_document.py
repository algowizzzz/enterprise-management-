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
from consilium.policy import applicability, glossary, handling, lineage, metadata, naming

#: Handling classifications that close the three named actions by default. An
#: administrator may reopen them on a record; this only supplies the default.
_RESTRICTED_HANDLING = ("Confidential", "Restricted")


class GoverningDocument(Document):
    def validate(self):
        # Where the lifecycle runs on workflow_state, the phase follows the
        # state; written first, so the gates below see the phase being entered.
        from consilium.policy import lifecycle

        lifecycle.sync_phase(self)
        self._enforce_lifecycle_gates()
        apply_state_flags(self)
        lineage.validate_lineage(self)
        self._derive_handling_defaults()
        # P-1/P-13: who may loosen the handling, and private storage for the
        # attachments of a confidential or restricted document.
        handling.secure_on_save(self)
        self._validate_applicability()
        self._validate_conditional_fields()
        # P-15 naming convention and P-24 glossary wording; both refuse and log.
        naming.enforce_on_document(self)
        glossary.enforce_on_document(self)
        self._derive_review_date()
        self._derive_retirement_date()

    def on_update(self):
        self._raise_remediation_on_deactivation()
        # P-26 dispositions, E11-S5 change and retirement notices, and the
        # fulfilment of change and retirement intake requests: all read the
        # flags before and after this save. See consilium.policy.disposition.
        from consilium.policy import disposition

        disposition.on_document_update(self)

    # ------------------------------------------------------------------ rules

    def _enforce_lifecycle_gates(self) -> None:
        """P-25: no phase is entered past a failing gate, by any route.

        The gates used to run only inside ``lifecycle.perform``. The workspace's
        workflow menu calls the framework's ``apply_workflow`` directly, and a
        REST write can set the phase field outright; both saved the document
        without asking, so a document could be published with no approval chain
        at all. Checking here puts every route through the same gate.
        ``perform`` has already checked (and may hold a written exception), so
        it marks the transition it cleared and this steps aside for that one.
        """
        from consilium.consilium_core import audit
        from consilium.policy import lifecycle

        if self.is_new():
            return
        before = self.get_doc_before_save()
        if before is None or before.lifecycle_phase == self.lifecycle_phase:
            return
        if frappe.flags.get("consilium_gates_cleared") == (self.name, self.lifecycle_phase):
            return
        failures = lifecycle.check_gates(self, "lifecycle_phase", self.lifecycle_phase)
        if failures:
            audit.refuse(
                _("Moving {0} to {1} is refused. {2}").format(self.name, self.lifecycle_phase, " | ".join(failures)),
                subject_doctype=self.doctype,
                subject_name=self.name,
                attempted_action="Other",
                control="lifecycle gate",
                context={"next_state": self.lifecycle_phase, "failures": failures, "route": "direct save"},
                exc=frappe.ValidationError,
            )

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
        if self.is_active or self.is_editable:
            # Reinstated or back in force: a retirement date left behind would
            # show a live document as retired on every report that reads it.
            if self.retired_on and not self.is_new():
                self.retired_on = None
            return
        if self.is_new():
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
        # Reopening for change also takes a document out of force, but into an
        # editable draft that is coming back; its children's parent link is
        # still good. Only a document leaving force for good (not editable, as
        # on retirement) invalidates it.
        if int(before.get("is_active") or 0) == 1 and not int(self.is_active or 0) \
                and not int(self.is_editable or 0):
            metadata.raise_tasks_for_deactivated_parent(self)

    # -------------------------------------------------------------- convenience

    @frappe.whitelist()
    def missing_metadata(self) -> list[str]:
        return metadata.missing_fields(self)
