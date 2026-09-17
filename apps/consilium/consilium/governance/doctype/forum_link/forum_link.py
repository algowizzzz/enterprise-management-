"""Forum Link — controller.

An upstream or downstream relationship between two forums (G-4 mapping, and the interconnectivity view). One child table used by two parent fields, which is why the parent index is composite — see 03-schema.md §7.1.
"""

from frappe.model.document import Document


class ForumLink(Document):
    def validate(self):
        pass
