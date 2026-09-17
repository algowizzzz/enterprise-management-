"""Implementation Task — controller.

A unit of implementation work. Completion is read from `completed_on`, never from the label.
"""

from frappe.model.document import Document


class ImplementationTask(Document):
    def validate(self):
        pass
