"""Hand-offs to the organisation's other tools: Doc AI and horizon scanning.

Both are links, not integrations in the data sense. The platform never calls
either tool and never sends either one a file. It builds an address and sends
the person's browser there:

* **Doc AI**, a rich document editor. The address carries the governing
  document's reference, the version's reference and label, the document's
  title and the address of the document's own page here — identifiers the
  editor needs to find the source through its own connection, and nothing a
  reader of the address could not already see on the page they came from.
  The file itself never goes in the address.
* **Horizon scanning**, an external platform. The address is exactly what the
  administrator saved; nothing is added.

Why a button still shows when the tool is not connected. The button is how
people learn the tool exists and how an administrator hears that it is wanted.
A button that is absent until configured is found by nobody; one that explains
"not connected yet, an administrator sets it in Admin → Integrations" is
self-documenting. An administrator who does not want it switches it off.

Why every address is checked here and again when it is used. An administrator
enters it, a template substitutes into it and a browser follows it, so a
``javascript:`` (or ``data:``, or ``file:``) address would run in a colleague's
session under the portal's origin. ``check_url`` refuses anything but an
absolute http(s) address when it is saved, through the audited refusal path;
``build_doc_ai_url`` checks the finished address again, because a template can
only be judged fully once the values are in it.

Every Doc AI hand-off is written to the framework's Access Log — the same log
the document viewer writes a view to — so "who took which document where, and
when" has the same answer as "who read it".
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlsplit

import frappe
from frappe import _

SETTINGS = "External Tools Settings"
DOCUMENT = "Governing Document"
VERSION = "Document Version"

CONNECTED = "connected"
NOT_CONNECTED = "not_connected"
OFF = "off"

#: What a Doc AI address template may name. ``{document_url}`` is this
#: portal's page for the document, so the editor can link back to the source.
PLACEHOLDERS = ("document", "version", "version_label", "title", "document_url")
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]*)\}")

#: The Access Log ``method`` a hand-off is recorded under.
HANDOFF_METHOD = "Doc AI hand-off"

DEFAULT_DOC_AI_LABEL = "Open in Doc AI"
DEFAULT_HORIZON_LABEL = "Horizon scanning"

ADMIN_ROLES = ("System Manager", "Consilium Administrator")


# ------------------------------------------------------------ the addresses


def _refuse_address(message: str, field_label: str, scheme: str | None, subject_doctype: str = SETTINGS) -> None:
	from consilium.consilium_core import audit

	audit.refuse(
		message,
		subject_doctype=subject_doctype,
		subject_name=subject_doctype,
		attempted_action="Modify",
		control="external address check",
		context={"field": field_label, "scheme": scheme or ""},
		exc=frappe.ValidationError,
	)


def check_url(value: str | None, field_label: str, *, template: bool = False,
              subject_doctype: str = SETTINGS) -> str:
	"""An administrator's address, trimmed, or a refusal. Empty stays empty.

	Only an absolute http:// or https:// address with a host passes. Control
	characters and spaces are refused outright rather than cleaned, because a
	browser strips some of them before reading the scheme (``java\\tscript:``),
	which is exactly how a scheme check is got round.

	With ``template``, placeholders are allowed in the path and query but never
	in the scheme or host: a document's title must not choose where a person
	is sent.
	"""
	value = (value or "").strip()
	if not value:
		return ""
	if any(ord(ch) < 33 or ord(ch) == 127 for ch in value):
		_refuse_address(
			_("{0} contains a space or a control character. Give a plain http:// or https:// address.")
			.format(field_label), field_label, None, subject_doctype)
	probe = value
	if template:
		unknown = sorted({name for name in _PLACEHOLDER.findall(value) if name not in PLACEHOLDERS})
		if unknown:
			frappe.throw(
				_("{0} names placeholders this platform does not fill: {1}. Use {2}.").format(
					field_label, ", ".join("{" + n + "}" for n in unknown),
					", ".join("{" + n + "}" for n in PLACEHOLDERS)),
				title=_("Unknown Placeholder"),
			)
		probe = _PLACEHOLDER.sub("x", value)
	parsed = urlsplit(probe)
	scheme = (parsed.scheme or "").lower()
	if scheme not in ("http", "https") or not parsed.netloc:
		_refuse_address(
			_("{0} must be an absolute http:// or https:// address; a {1} address is refused.").format(
				field_label, (scheme + ":") if scheme else _("relative")),
			field_label, scheme, subject_doctype)
	if template and "{" in (urlsplit(value).netloc or ""):
		_refuse_address(
			_("{0}: placeholders may go in the path or the query, never in the host.").format(field_label),
			field_label, scheme, subject_doctype)
	return value


def build_doc_ai_url(template: str, values: dict) -> str:
	"""Fill a Doc AI address template. Every value is URL-encoded.

	Raises ``frappe.ValidationError`` if the finished address is not http(s),
	which a template saved through ``check_url`` cannot produce but a template
	written into the database by hand could.
	"""
	def fill(match):
		name = match.group(1)
		if name not in PLACEHOLDERS:
			return match.group(0)
		return quote(str(values.get(name) or ""), safe="")

	url = _PLACEHOLDER.sub(fill, (template or "").strip())
	parsed = urlsplit(url)
	if (parsed.scheme or "").lower() not in ("http", "https") or not parsed.netloc \
			or any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
		raise frappe.ValidationError(_("The Doc AI address is not an http:// or https:// address."))
	return url


def document_url(name: str) -> str:
	"""The document's own page in this portal, as an absolute address."""
	return frappe.utils.get_url("/policy?name=" + quote(name, safe=""))


# ---------------------------------------------------------------- the state


def settings():
	return frappe.get_cached_doc(SETTINGS, SETTINGS)


def doc_ai_state(s=None) -> str:
	s = s or settings()
	if not int(s.doc_ai_enabled or 0):
		return OFF
	return CONNECTED if (s.doc_ai_url_template or "").strip() else NOT_CONNECTED


def horizon_state(s=None) -> str:
	s = s or settings()
	if not int(s.horizon_enabled or 0):
		return OFF
	return CONNECTED if (s.horizon_url or "").strip() else NOT_CONNECTED


def doc_ai_roles(s=None) -> list[str]:
	s = s or settings()
	return sorted({row.role for row in (s.get("doc_ai_roles") or []) if row.role})


def _holds_a_listed_role(s, user: str | None = None) -> bool:
	listed = set(doc_ai_roles(s))
	return not listed or bool(listed & set(frappe.get_roles(user or frappe.session.user)))


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Guest":
		return False
	return bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def cns_external_tools() -> dict:
	"""For templates: what the buttons say and whether this person sees them.

	Nothing secret is in it — the Doc AI template is not, because the page
	never builds the address; ``/doc-ai`` does, after its checks. Whether the
	person may read a particular document is the page's question, not this
	one's: this answers only the settings and the role list.
	"""
	hidden = {"shown": False, "state": OFF, "label": "", "new_tab": False}
	if frappe.session.user == "Guest":
		return {"doc_ai": dict(hidden), "horizon": dict(hidden), "admin": False}
	try:
		s = settings()
	except Exception:
		# Not migrated yet on this site: no buttons rather than a broken page.
		return {"doc_ai": dict(hidden), "horizon": dict(hidden), "admin": False}
	doc_ai = doc_ai_state(s)
	horizon = horizon_state(s)
	return {
		"doc_ai": {
			"shown": doc_ai != OFF and _holds_a_listed_role(s),
			"state": doc_ai,
			"label": (s.doc_ai_label or "").strip() or DEFAULT_DOC_AI_LABEL,
			"new_tab": bool(int(s.doc_ai_new_tab or 0)),
		},
		"horizon": {
			"shown": horizon != OFF,
			"state": horizon,
			"label": (s.horizon_label or "").strip() or DEFAULT_HORIZON_LABEL,
			"new_tab": bool(int(s.horizon_new_tab or 0)),
		},
		"admin": is_admin(),
	}


# ---------------------------------------------------------------- hand-offs


def _refuse_handoff(document: str, message: str, control: str, **context) -> None:
	from consilium.consilium_core import audit

	audit.refuse(
		message,
		subject_doctype=DOCUMENT,
		subject_name=document,
		attempted_action="Other",
		control=control,
		context=context or None,
		exc=frappe.PermissionError,
	)


def doc_ai_handoff(document: str, version: str | None = None) -> dict:
	"""Check, log and address one Doc AI hand-off.

	Returns ``{"state", "url", "new_tab", "label", "document", "title",
	"version"}``. ``url`` is set only when the tool is connected, in which case
	the hand-off has been written to the Access Log. Raises
	``frappe.DoesNotExistError`` for a document or version that does not exist
	and refuses (audited) a person who may not read the document, who lacks a
	role the settings require, or whose version belongs to another document.
	"""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to open a governing document."))
	s = settings()
	state = doc_ai_state(s)
	label = (s.doc_ai_label or "").strip() or DEFAULT_DOC_AI_LABEL
	out = {"state": state, "url": None, "new_tab": bool(int(s.doc_ai_new_tab or 0)), "label": label,
	       "document": document, "title": None, "version": None}
	if state == OFF:
		return out
	if not document or not frappe.db.exists(DOCUMENT, document):
		raise frappe.DoesNotExistError(_("No governing document {0}.").format(document))

	doc = frappe.get_doc(DOCUMENT, document)
	if not frappe.has_permission(DOCUMENT, "read", doc=doc):
		# The same wording for "cannot read" and "cannot hand off", so the
		# refusal does not confirm the document's title or handling.
		_refuse_handoff(document, _("You may not read {0}, so you may not open it in {1}.").format(document, label),
		                "document read", tool=label)
	if not _holds_a_listed_role(s):
		_refuse_handoff(document, _("{0} is offered to particular roles only, and you hold none of them.").format(label),
		                "external tool roles", tool=label, roles=doc_ai_roles(s))

	version_name = (version or "").strip() or doc.get("current_version")
	version_label = None
	if version_name:
		from consilium.policy import handling

		try:
			# The viewer's own check: refuses (audited) a reader the handling
			# rules exclude from this version.
			version_doc, owner = handling.governing_version(version_name)
		except frappe.DoesNotExistError:
			frappe.clear_messages()
			raise
		if owner.name != doc.name:
			raise frappe.DoesNotExistError(_("Version {0} is not a version of {1}.").format(version_name, doc.name))
		version_label = str(version_doc.version_label or version_doc.version_number or "")

	out.update(title=doc.document_name or doc.name, version=version_name)
	if state != CONNECTED:
		return out

	url = build_doc_ai_url(s.doc_ai_url_template, {
		"document": doc.name,
		"version": version_name or "",
		"version_label": version_label or "",
		"title": doc.document_name or "",
		"document_url": document_url(doc.name),
	})
	from frappe.core.doctype.access_log.access_log import make_access_log

	make_access_log(
		doctype=DOCUMENT,
		document=doc.name,
		method=HANDOFF_METHOD,
		page="doc-ai",
		filters=json.dumps({"version": version_name or "", "destination": urlsplit(url).netloc}),
	)
	out["url"] = url
	return out


def horizon_target() -> dict:
	"""Where /horizon-scanning sends a signed-in person, if anywhere."""
	s = settings()
	state = horizon_state(s)
	url = None
	if state == CONNECTED:
		url = (s.horizon_url or "").strip()
		parsed = urlsplit(url)
		# Checked again on the way out: a value written into the database by
		# hand has not been through check_url.
		if (parsed.scheme or "").lower() not in ("http", "https") or not parsed.netloc:
			state, url = NOT_CONNECTED, None
	return {
		"state": state,
		"url": url,
		"new_tab": bool(int(s.horizon_new_tab or 0)),
		"label": (s.horizon_label or "").strip() or DEFAULT_HORIZON_LABEL,
	}
