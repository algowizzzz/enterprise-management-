"""Horizon Scan Coverage — controller.

A single Horizon Scanning Coverage Area held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class HorizonScanCoverage(Document):
    def validate(self):
        pass
