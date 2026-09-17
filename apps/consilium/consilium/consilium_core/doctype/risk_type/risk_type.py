"""Risk Type — controller.

The tiered risk taxonomy (02-data-model.md T-7). Tier is carried as a number on a tree so that the two tiers the sources name need only one table.
"""

from frappe.model.document import Document


class RiskType(Document):
    def validate(self):
        pass
