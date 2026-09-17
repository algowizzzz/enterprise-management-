"""Approval Route Step — controller.

One step of a configured approval path. The assignee is resolved from the record, so a route survives a change of owner.
"""

from frappe.model.document import Document


class ApprovalRouteStep(Document):
    def validate(self):
        pass
