"""Forum Risk Type — controller.

One risk type a forum covers. Multi-valued by decision M-3.
"""

from frappe.model.document import Document


class ForumRiskType(Document):
    def validate(self):
        pass
