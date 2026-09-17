"""Horizon Scan Impacted Document — controller.

A single Governing Document held in a multi-valued field (02-data-model.md §7 'Multi → X').
"""

from frappe.model.document import Document


class HorizonScanImpactedDocument(Document):
    def validate(self):
        pass
