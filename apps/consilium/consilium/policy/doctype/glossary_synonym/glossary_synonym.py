"""Glossary Synonym — controller.

An alternative form of a glossary term.
"""

from frappe.model.document import Document


class GlossarySynonym(Document):
    def validate(self):
        pass
