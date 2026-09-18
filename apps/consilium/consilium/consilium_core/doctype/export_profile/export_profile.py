"""Export Profile — controller.

What one governed outbound file contains and who may run it (G-19, P-20,
E-19). The checks live in ``consilium_core.exporting`` beside the code that
reads the profile, so the two cannot drift: every field and filter name is
real, the roles exist, the row limit is at most 5,000, and a drop folder is a
name under the server's drop root, never a path of its own.
"""

from frappe.model.document import Document

from consilium.consilium_core import exporting


class ExportProfile(Document):
	def validate(self):
		exporting.validate_profile(self)
