"""Exception Authorisation — controller.

The documented authorisation without which an approval step may not be bypassed. [Inferred — §11 I-6.]
"""

from frappe.model.document import Document


class ExceptionAuthorisation(Document):
    def validate(self):
        pass
