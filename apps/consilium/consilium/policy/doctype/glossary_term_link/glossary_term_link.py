"""Glossary Term Link — controller.

Term-to-document linkage, which is what lets a defined term be surfaced in context (E15-S4).
"""

from frappe.model.document import Document


class GlossaryTermLink(Document):
    def validate(self):
        pass
