"""Closure Criterion — controller.

One criterion a closure must satisfy (E-10). [Inferred — E-10 requires closure criteria to be enforced but names none, so they are rows rather than code.]
"""

from frappe.model.document import Document


class ClosureCriterion(Document):
    def validate(self):
        pass
