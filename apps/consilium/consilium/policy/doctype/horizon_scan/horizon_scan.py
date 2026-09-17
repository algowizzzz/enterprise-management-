"""Horizon Scan — controller.

The due date is derived from the document's review cadence, and an impact
assessment that triggers a review opens the review cycle and links it back. Both
are behaviours of the record rather than of a screen, so they live here.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from consilium.policy import horizon


class HorizonScan(Document):
    def validate(self):
        if not self.get("sources"):
            frappe.throw(
                _("A scan records what was reviewed. Name at least one source."),
                title=_("Sources Required"),
            )
        if not self.get("coverage_areas"):
            frappe.throw(
                _("A scan records which areas it covered. Name at least one coverage area."),
                title=_("Coverage Required"),
            )
        document = frappe.get_doc("Governing Document", self.document)
        previous = horizon.last_scan(self.document)
        anchor = None
        if previous and previous["name"] != self.name:
            anchor = previous["scan_date"]
        self.due_on = horizon.due_on_for(document, after=anchor)
        for row in self.get("sources") or []:
            if row.reviewed_on and getdate(row.reviewed_on) > getdate(self.scan_date):
                frappe.throw(
                    _("Source {0} is dated after the scan itself.").format(row.idx)
                )

    def on_update(self):
        horizon.open_review_cycle(self)
