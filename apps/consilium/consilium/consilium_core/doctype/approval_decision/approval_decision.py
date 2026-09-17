"""Approval Decision — controller.

An approval's basis, not merely the fact of it: which step, which role, whether a delegate acted, which document version it was given against, and whether an exception authorised a bypass (02-data-model.md §5.9).
"""

from frappe.model.document import Document


class ApprovalDecision(Document):
    def validate(self):
        pass
