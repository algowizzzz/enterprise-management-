"""Material Entity — controller.

Entities designated material for regulatory or resolution purposes (T-8). Referenced as a link and read as a derived flag.
"""

from frappe.model.document import Document


class MaterialEntity(Document):
    def validate(self):
        pass
