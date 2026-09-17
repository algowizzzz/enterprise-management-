"""Horizon Scanning Coverage Area — controller.

The areas a periodic horizon scan is expected to cover.
"""

from frappe.model.document import Document


class HorizonScanningCoverageArea(Document):
    def validate(self):
        pass
