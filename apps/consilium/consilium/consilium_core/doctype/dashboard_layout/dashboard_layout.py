"""Dashboard Layout — controller.

One person's saved arrangement of a dashboard page: which sections and
dimensions it shows, and in what order (O-3). Written only through
``consilium_core.dashboard_layout``, which always writes the caller's own row.

One row per person per page. The rule is kept here too, so a second row made on
the desk cannot leave the page unsure which layout is the person's.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class DashboardLayout(Document):
	def validate(self):
		self.page = (self.page or "").strip()
		clash = frappe.db.get_value(
			"Dashboard Layout", {"user": self.user, "page": self.page, "name": ["!=", self.name]}, "name"
		)
		if clash:
			frappe.throw(
				_("{0} already has a layout for {1} ({2}).").format(self.user, self.page, clash),
				title=_("One Layout Per Page"),
			)
