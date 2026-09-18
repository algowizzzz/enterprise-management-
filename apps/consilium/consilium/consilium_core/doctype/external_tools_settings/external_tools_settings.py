"""External Tools Settings — controller.

Buttons that hand a person over to another tool the organisation runs: a rich
document editor (Doc AI) and a horizon-scanning platform. The platform sends
each tool only a link: identifiers in the address, never a file or a record's
contents. The hand-off itself is ``consilium_core.integrations.external_tools``.

What is checked on save, and why here rather than only when a button is
clicked: an address that is not http(s) is refused through the audited
refusal path, so a ``javascript:`` address can never be saved behind a button
at all, and the attempt is on record. An empty label falls back to its
default, because a button with no words is not a button.

    Specified by: Integrations: external tool hand-off (Doc AI, horizon scanning).
"""

from frappe import _
from frappe.model.document import Document

from consilium.consilium_core.integrations import external_tools


class ExternalToolsSettings(Document):
	def validate(self):
		self.doc_ai_label = (self.doc_ai_label or "").strip() or external_tools.DEFAULT_DOC_AI_LABEL
		self.horizon_label = (self.horizon_label or "").strip() or external_tools.DEFAULT_HORIZON_LABEL
		self.doc_ai_url_template = external_tools.check_url(
			self.doc_ai_url_template, _("The Doc AI address template"), template=True)
		self.horizon_url = external_tools.check_url(self.horizon_url, _("The horizon scanning address"))
