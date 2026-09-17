"""Disbandment Approval — controller.

One of the four approvals G-11 names for a disbandment. The row records who must approve; the decision itself is a Core Approval Decision, so that delegation, exception authorisation and the semantic open flag are the same machinery the rest of the platform uses. The mirrored decision label here is for display and is never compared.
"""

from frappe.model.document import Document


class DisbandmentApproval(Document):
    def validate(self):
        pass
