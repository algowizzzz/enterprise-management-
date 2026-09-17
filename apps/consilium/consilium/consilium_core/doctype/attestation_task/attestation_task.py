"""Attestation Task — controller.

One row per campaign, participant and record. Standalone, not a child, so a participant's task list is a first-class query and tasks survive campaign edits (02-data-model.md §5.1).
"""

from frappe.model.document import Document


class AttestationTask(Document):
    def validate(self):
        pass
