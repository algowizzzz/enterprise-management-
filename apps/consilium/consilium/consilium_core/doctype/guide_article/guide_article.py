"""Guide Article — controller.

The home-page user guide, editable without a deployment (02-data-model.md §5.11). Files are attached through the framework's own attachment mechanism rather than a field.
"""

from frappe.model.document import Document


class GuideArticle(Document):
    def validate(self):
        pass
