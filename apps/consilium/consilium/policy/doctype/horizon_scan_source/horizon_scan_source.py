"""Horizon Scan Source — controller.

One source a scanner reviewed. This is the whole of the 'feed': a human recording what they read and when.
"""

from frappe.model.document import Document


class HorizonScanSource(Document):
    def validate(self):
        pass
