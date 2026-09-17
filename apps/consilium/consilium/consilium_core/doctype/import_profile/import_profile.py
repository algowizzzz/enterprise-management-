"""Import Profile — controller."""

import frappe
from frappe import _
from frappe.model.document import Document


class ImportProfile(Document):
    def validate(self):
        meta = frappe.get_meta(self.target_doctype)
        for mapping in self.mappings:
            if not meta.has_field(mapping.target_fieldname):
                frappe.throw(
                    _("{0} has no field {1}.").format(self.target_doctype, mapping.target_fieldname)
                )
            if mapping.transform == "Lookup" and not (mapping.lookup_doctype and mapping.lookup_field):
                frappe.throw(_("A lookup mapping needs a lookup DocType and field."))
        if self.key_strategy == "External Key" and not self.external_key_column:
            frappe.throw(_("The external-key strategy needs the source column holding the key."))
        if self.key_strategy == "Natural Key" and not self.natural_key_fieldname:
            frappe.throw(_("The natural-key strategy needs the target fieldname to match on."))
