"""AI Service Request — controller.

Every request field is frozen once written. The response may be recorded exactly
once: a second response would overwrite the evidence of the first.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import append_only

RESPONSE_FIELDS = ("response_received_on", "response_payload", "status", "error_detail", "duration_ms")


class AIServiceRequest(Document):
    def validate(self):
        before = self.get_doc_before_save()
        if before and before.response_received_on and self.response_received_on != before.response_received_on:
            frappe.throw(
                _("Request {0} already carries a response; a second one would overwrite the evidence.").format(self.name)
            )
        append_only.guard_update(self, allowed=RESPONSE_FIELDS, control="ai request append-only")

    def on_trash(self):
        append_only.guard_delete(self, control="ai request append-only")
