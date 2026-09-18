"""External Reference — controller.

A recorded, reportable foreign identifier with a known provenance batch, standing where a live connector would otherwise be (02-data-model.md §5.6). When a connector is eventually built it populates these same rows.

An optional ``url`` lets a reader open the record in its own system (P-5). It
is shown as a link and never fetched, so only an http(s) address with a host is
accepted — whether it arrives from the policy page, an import or the desk.
"""

from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.model.document import Document

MAX_URL = 1000


def is_web_url(value) -> bool:
	"""An http(s) address with a host, no spaces and nothing that breaks out of an attribute."""
	value = (value or "").strip()
	if not value or len(value) > MAX_URL or any(ch.isspace() or ch in '<>"\'' for ch in value):
		return False
	parts = urlsplit(value)
	return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


class ExternalReference(Document):
	def validate(self):
		if self.url:
			self.url = self.url.strip()
			if not is_web_url(self.url):
				frappe.throw(_("A link must be a full web address starting with http:// or https://."),
					title=_("Invalid Link"))
