"""Committee Charter — controller.

The charter's body lives in Core's version chain; nothing here holds it. What is
held here is the risk governance office's effective challenge, whose semantic
flags say whether the charter is cleared.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.governance import setup


class CommitteeCharter(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        if self.requires_statement and not (self.rgo_challenge_comments or "").strip():
            frappe.throw(
                _("A challenge that requests changes says what changes."),
                title=_("Comments Required"),
            )
        if self.effective_from and self.effective_to and getdate(self.effective_to) < getdate(self.effective_from):
            frappe.throw(_("A charter cannot expire before it takes effect."), title=_("Invalid Dates"))
        if not self.forum and not self.formation_request:
            frappe.throw(
                _("A charter belongs either to a forum or to the request that will create one."),
                title=_("Unattached Charter"),
            )
