"""Legal Hold — controller.

A hold is active from the day it is placed until the day it is released. The flag
is derived, never typed, so nothing can be held by a stale checkbox.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from consilium.consilium_core import retention


class LegalHold(Document):
    def validate(self):
        if self.released_on and self.placed_on and getdate(self.released_on) < getdate(self.placed_on):
            frappe.throw(_("A hold cannot be released before it is placed."))
        today = getdate(nowdate())
        active = bool(self.placed_on) and getdate(self.placed_on) <= today
        if self.released_on and getdate(self.released_on) <= today:
            active = False
        self.is_active = 1 if active else 0

    def on_update(self):
        retention.clear_cache()

    def on_trash(self):
        retention.clear_cache()
