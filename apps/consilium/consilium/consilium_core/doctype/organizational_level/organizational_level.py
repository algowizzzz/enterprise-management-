"""Organizational Level — controller.

The authority level at which an escalation sits (T-10). A tree, so that levels nest.
"""

from frappe.model.document import Document


class OrganizationalLevel(Document):
    def validate(self):
        pass
