"""Authority Delegation — controller.

A time-bounded transfer of specified actions from an accountable person to another, recorded so that 'who was acting for whom, when' is answerable (02-data-model.md §4.3). It grants no framework permission: it is evaluated by application logic at the point of action and recorded on the resulting decision or task.
"""

from frappe.model.document import Document


class AuthorityDelegation(Document):
    def validate(self):
        pass
