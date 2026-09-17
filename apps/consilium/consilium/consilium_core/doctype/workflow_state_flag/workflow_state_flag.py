"""Workflow State Flag — controller.

The configuration that turns a workflow state or status label into semantic flags (02-data-model.md M-4). State names live here, as data. No business logic anywhere compares a state string; it reads the flags this table sets. That is what makes a state rename configuration rather than a rebuild. [Addition — the model states the rule and names the flags but defines no table to hold the mapping.]
"""

from frappe.model.document import Document


class WorkflowStateFlag(Document):
    def validate(self):
        pass
