"""Governance Refusal Log — controller.

Every refusal a Core control issued: what was attempted, on which record, why it was refused, by whom and when. Written on an out-of-band connection so that the refusal survives the rollback of the operation it refused. Append-only. [Addition — the model requires refusals to be audited but names no artefact.]
"""

from frappe.model.document import Document


class GovernanceRefusalLog(Document):
    def validate(self):
        pass
