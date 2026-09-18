"""Committee Formation Request — controller.

The intake for creating, modifying or retiring a forum. The nine-state flow is
carried here; the transitions live in ``consilium.governance.formation``.

The controller's own job is the shape of the record: the five evaluation
criteria are present, a modify or retire request names its subject, a criterion
with a finding carries a comment, and the record is not edited while the state's
``is_editable`` flag is false.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from consilium.governance import formation, setup


class CommitteeFormationRequest(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        if not self.requester:
            self.requester = frappe.session.user
        formation.seed_criteria(self)
        self._guard_editability()
        self._validate_subject()
        self._validate_findings()

    def on_update(self):
        # The originator reads, answers and withdraws their own request whatever
        # roles they hold (see formation.share_with_originator). Run on every
        # save so a request re-pointed at a new originator follows them; a
        # share already in place costs one lookup.
        formation.share_with_originator(self)

    def _guard_editability(self):
        if self.flags.consilium_formation or self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or before.get("is_editable"):
            return
        frappe.throw(
            _("Request {0} is not editable in its current state.").format(self.name),
            title=_("Locked"),
        )

    def _validate_subject(self):
        if self.request_type != formation.REQUEST_CREATE and not self.subject_forum:
            frappe.throw(
                _("A {0} request names the forum it concerns.").format(self.request_type),
                title=_("Subject Forum Required"),
            )

    def _validate_findings(self):
        for row in self.evaluations:
            if row.assessment != formation.UNASSESSED:
                if not (row.comments or "").strip():
                    frappe.throw(
                        _("Criterion {0} has a finding but no comment. A finding without a reason is not one.").format(
                            row.criterion
                        ),
                        title=_("Comment Required"),
                    )
                if not row.reviewed_by:
                    row.reviewed_by = frappe.session.user
                if not row.reviewed_on:
                    row.reviewed_on = now()
