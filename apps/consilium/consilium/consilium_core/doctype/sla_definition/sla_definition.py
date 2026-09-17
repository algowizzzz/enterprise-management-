"""SLA Definition — controller.

An agreed time target for a workflow step, a status duration or total time open, with a warning threshold (02-data-model.md §5.8). The framework supplies none of this.
"""

from frappe.model.document import Document


class SLADefinition(Document):
    def validate(self):
        pass
