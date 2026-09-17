"""Forum Legal Entity — controller.

One legal entity within a forum's scope. Multi-valued by decision M-3.
"""

from frappe.model.document import Document


class ForumLegalEntity(Document):
    def validate(self):
        pass
