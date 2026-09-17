"""Document Publication — controller."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class DocumentPublication(Document):
    def validate(self):
        version = frappe.db.get_value(
            "Document Version", self.document_version, ["subject_doctype", "subject_name"], as_dict=True
        )
        if not version or (version["subject_doctype"], version["subject_name"]) != (
            "Governing Document",
            self.document,
        ):
            frappe.throw(
                _("Version {0} does not belong to {1}.").format(self.document_version, self.document),
                title=_("Wrong Version"),
            )
        if self.audience_type == "Targeted Groups" and not self.get("audiences"):
            frappe.throw(_("A targeted publication must name at least one audience."))
        if self.rendition_view_only:
            self.rendition_print = 0
            self.rendition_download = 0
