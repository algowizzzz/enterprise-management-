"""Retention Assignment — controller.

Binds a retention class to a record population, so that adding a class does not require editing every record. The most specific active assignment wins.
"""

from frappe.model.document import Document


class RetentionAssignment(Document):
    def validate(self):
        pass
