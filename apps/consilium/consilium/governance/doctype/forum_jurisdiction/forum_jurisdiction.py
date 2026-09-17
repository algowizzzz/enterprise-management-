"""Forum Jurisdiction — controller.

One jurisdiction a forum operates in. Multi-valued by decision M-3.
"""

from frappe.model.document import Document


class ForumJurisdiction(Document):
    def validate(self):
        pass
