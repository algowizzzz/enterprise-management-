"""Classification Rule — controller.

One rule. Rules evaluate in priority order and the first match wins; which rule matched is recorded.
"""

from frappe.model.document import Document


class ClassificationRule(Document):
    def validate(self):
        pass
