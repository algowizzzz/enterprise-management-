"""Email Delivery Settings — controller.

How the platform's notification email leaves the server: through the
framework's mail queue and the site's outgoing Email Account over SMTP (the
default), or through Microsoft Graph for an organisation that does not allow
SMTP (``consilium_core.integrations.graph_mail``). Either way every
notification is recorded as a Notification Dispatch and a failed one is
retried.

What is refused on save:

* a base address that is not http(s), through the audited refusal path, like
  every administrator-entered address (``external_tools.check_url``);
* a plain http:// base address anywhere but this machine's loopback address.
  The client secret and every message travel over it; http is allowed only for
  a stand-in server on 127.0.0.1, which is what the tests use;
* choosing Graph while something it needs is missing, because the first
  notification would otherwise be the first to find out;
* a tenant or sender with a character that would change the request's path.

    Specified by: Integrations: notification email over Microsoft Graph for organisations without SMTP.
"""

import re
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core.integrations import external_tools, graph_mail

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_PATH_SAFE = re.compile(r"^[A-Za-z0-9._@+-]*$")


class EmailDeliverySettings(Document):
	def validate(self):
		low, high = graph_mail.TIMEOUT_RANGE
		if not low <= int(self.graph_timeout_seconds or 0) <= high:
			frappe.throw(_("{0} must be between {1} and {2}.").format(
				self.meta.get_label("graph_timeout_seconds"), low, high), title=_("Out of Range"))

		for field, default in (("graph_authority_url", graph_mail.DEFAULT_AUTHORITY),
		                       ("graph_api_url", graph_mail.DEFAULT_GRAPH)):
			label = self.meta.get_label(field)
			value = external_tools.check_url(self.get(field), label, subject_doctype=self.doctype) or default
			parsed = urlsplit(value)
			if parsed.scheme == "http" and (parsed.hostname or "") not in LOOPBACK:
				frappe.throw(_("{0} must be an https:// address: the client secret and every message travel over it.")
				             .format(label), title=_("Address Not Usable"))
			if parsed.query or parsed.fragment:
				frappe.throw(_("{0} is a base address: leave out the query string.").format(label),
				             title=_("Address Not Usable"))
			self.set(field, value.rstrip("/"))

		for field in ("graph_tenant_id", "graph_client_id", "graph_sender"):
			value = (self.get(field) or "").strip()
			if not _PATH_SAFE.match(value):
				frappe.throw(_("{0} may hold letters, digits and . _ @ + - only.").format(self.meta.get_label(field)),
				             title=_("Not Usable"))
			self.set(field, value)

		if self.delivery_route == graph_mail.GRAPH_ROUTE:
			absent = graph_mail.missing(self)
			if absent:
				frappe.throw(_("Microsoft Graph needs: {0}.").format(", ".join(absent)),
				             title=_("Incomplete Microsoft Graph Configuration"))
		graph_mail.forget_tokens()
