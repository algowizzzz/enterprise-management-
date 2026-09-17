"""Forum Business Unit — controller.

One business unit a forum is tagged against. Multi-valued by decision M-3 (02-data-model.md §6.8): four child tables rather than four Link columns, because multi-to-single is a presentation change and single-to-multi is a data migration.
"""

from frappe.model.document import Document


class ForumBusinessUnit(Document):
    def validate(self):
        pass
