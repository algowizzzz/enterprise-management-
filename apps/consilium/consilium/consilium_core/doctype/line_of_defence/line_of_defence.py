"""Line Of Defence — controller."""

import frappe
from frappe import _
from frappe.model.document import Document


class LineOfDefence(Document):
    def validate(self):
        if int(self.line_number or 0) not in (1, 2, 3):
            frappe.throw(_("The three-lines model has lines 1, 2 and 3."))
