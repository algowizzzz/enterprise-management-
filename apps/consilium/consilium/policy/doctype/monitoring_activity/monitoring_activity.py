"""Monitoring Activity — controller.

P-11. A recurring monitoring obligation against a document.
"""

from frappe.model.document import Document


class MonitoringActivity(Document):
    def validate(self):
        pass
