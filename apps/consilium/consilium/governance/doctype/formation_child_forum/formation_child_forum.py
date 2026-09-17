"""Formation Child Forum — controller.

One proposed child forum named on a formation request (G-18). Its own child table rather than Forum Link, because at request time the parent forum does not yet exist.
"""

from frappe.model.document import Document


class FormationChildForum(Document):
    def validate(self):
        pass
