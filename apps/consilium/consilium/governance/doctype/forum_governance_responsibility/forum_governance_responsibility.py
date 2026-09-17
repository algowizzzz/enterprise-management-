"""Forum Governance Responsibility — controller.

One governance responsibility a forum holds — oversight, decision making, or both.
"""

from frappe.model.document import Document


class ForumGovernanceResponsibility(Document):
    def validate(self):
        pass
