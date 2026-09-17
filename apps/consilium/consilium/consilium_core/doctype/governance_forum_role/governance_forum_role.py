"""Governance Forum Role — controller.

Seat roles on a governance forum (T-13). A taxonomy with behaviour: the flags below are read by quorum, voting and attestation logic, so an administrator can add a seat role without a code change.
"""

from frappe.model.document import Document


class GovernanceForumRole(Document):
    def validate(self):
        pass
