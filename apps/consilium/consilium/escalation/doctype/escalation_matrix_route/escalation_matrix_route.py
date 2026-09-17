"""Escalation Matrix Route — controller.

A destination forum for one matrix rule. Flattened out of Escalation Matrix Rule because the framework does not support a table inside a child table; the rule_code column keys the rows back to their rule.
"""

from frappe.model.document import Document


class EscalationMatrixRoute(Document):
    def validate(self):
        pass
