"""Business Calendar — controller.

Working days and hours for business-hours service levels. [Inferred — §11 I-15. Without it every service level is 24x7 and will misreport.]
"""

from frappe.model.document import Document


class BusinessCalendar(Document):
    def validate(self):
        pass
