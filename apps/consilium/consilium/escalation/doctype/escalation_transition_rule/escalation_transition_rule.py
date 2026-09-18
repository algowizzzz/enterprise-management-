"""Escalation Transition Rule — controller.

One allowed move of an escalation matter's status, for a matter type and
severity. A blank type, severity, from or to state means any. For each matter
the most specific set of matching rules applies: type and severity, then type,
then severity, then the rules that name neither. How the rules are read is
`consilium.escalation.transitions`; this controller only refuses a rule that
names a state the matter does not have, or a move out of a state at rest.

    Specified by: REQUIREMENTS-COVERAGE.md E-8: workflow configurable by matter type and severity.
"""

from frappe.model.document import Document

from consilium.escalation import transitions


class EscalationTransitionRule(Document):
    def validate(self):
        transitions.validate_rule(self)
