"""Assistant Settings — controller.

The help assistant's configuration. The assistant is fully useful with nothing
set here: it answers from the built-in guides and needs no network. Everything
under "AI-assisted answers" is optional and off by default, because the target
environment has no internet access and an install must never depend on a
service it cannot reach.

The checks below refuse a configuration that could only fail at the moment
someone asks a question — the assistant would fall back to the built-in answer
anyway, but an administrator should find out when saving, not from the
interaction log a week later.

    Specified by: 01-requirements-baseline.md O-6/O-7 (AI integration); help assistant.
"""

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document

TIMEOUT_RANGE = (1, 120)
MAX_TOKENS_RANGE = (64, 4096)
RATE_LIMIT_RANGE = (1, 1000)


class AssistantSettings(Document):
    def validate(self):
        self._check_range("timeout_seconds", TIMEOUT_RANGE)
        self._check_range("max_tokens", MAX_TOKENS_RANGE)
        self._check_range("rate_limit_per_hour", RATE_LIMIT_RANGE)

        if self.endpoint_url:
            self.endpoint_url = self.endpoint_url.strip()
            parsed = urlparse(self.endpoint_url)
            # Only an absolute http(s) address. Anything else (file:, ftp:, a
            # bare host) would either fail at question time or, worse, let the
            # server read something it should not be pointed at.
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                frappe.throw(
                    _("The endpoint must be an absolute http:// or https:// address."),
                    title=_("Endpoint Not Usable"),
                )
            if parsed.query or parsed.fragment:
                frappe.throw(
                    _("Give the endpoint's base address without a query string; credentials belong in the API Key field."),
                    title=_("Endpoint Not Usable"),
                )

        if self.ai_enabled:
            missing = [label for field, label in (("endpoint_url", _("Endpoint Base URL")), ("model", _("Model")))
                       if not (self.get(field) or "").strip()]
            if missing:
                frappe.throw(
                    _("AI-assisted answers need: {0}.").format(", ".join(missing)),
                    title=_("Incomplete AI Configuration"),
                )

    def _check_range(self, field: str, bounds: tuple[int, int]) -> None:
        low, high = bounds
        value = int(self.get(field) or 0)
        if not low <= value <= high:
            frappe.throw(
                _("{0} must be between {1} and {2}.").format(self.meta.get_label(field), low, high),
                title=_("Out of Range"),
            )
