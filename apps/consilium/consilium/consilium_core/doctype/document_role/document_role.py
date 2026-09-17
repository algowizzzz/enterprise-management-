"""Document Role — controller.

Accountability roles recorded on a governing document — owner, approver, liaison, delegate, sponsor, key contact, monitor, partner (§2.2, §4.2). Distinct from access roles, which live in the permission engine.
"""

from frappe.model.document import Document


class DocumentRole(Document):
    def validate(self):
        pass
