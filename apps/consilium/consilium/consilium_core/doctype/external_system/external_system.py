"""External System — controller.

A system this platform exchanges files with. Holds a URL pattern so a stored foreign key can be rendered as a link without the platform calling anything.
"""

from frappe.model.document import Document


class ExternalSystem(Document):
    def validate(self):
        pass
