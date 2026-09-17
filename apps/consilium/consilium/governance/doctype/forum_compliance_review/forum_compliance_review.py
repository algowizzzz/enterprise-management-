"""Forum Compliance Review — controller.

The compliance decision that moves a forum, kept as its own record so that a
history of compliance decisions exists. Recording one is what changes the
forum's standing, and only a compliance role may create one — which is how
"only compliance roles may set the outcome states" holds server-side.

A decision that returns the forum to its creator carries questions, because the
state's ``requires_statement`` flag says so.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

from consilium.governance import lifecycle, setup


class ForumComplianceReview(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        if not self.reviewer:
            self.reviewer = frappe.session.user
        if not self.decided_on:
            self.decided_on = now()
        if self.requires_statement and not (self.returned_questions or self.comments or "").strip():
            frappe.throw(
                _("This decision cannot be recorded without written questions or comments."),
                title=_("Statement Required"),
            )
        if not frappe.db.get_value("Governance Forum", self.forum, "name"):
            frappe.throw(_("Forum {0} does not exist.").format(self.forum))

    def after_insert(self):
        lifecycle.apply_review(self)
