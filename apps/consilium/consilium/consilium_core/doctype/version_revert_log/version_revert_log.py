"""Version Revert Log — controller.

The audited act of reverting (02-data-model.md §5.4). Records who reverted, when, from and to which version, and — always — the new version the revert produced.
"""

from frappe.model.document import Document


class VersionRevertLog(Document):
    def validate(self):
        pass
