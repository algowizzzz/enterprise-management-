"""Links from a governing document to risk-programme records elsewhere (P-5).

P-5 asks that a governing document be linkable to risk assessments, processes,
risks, controls, training and issues. Where the counterpart is a Consilium
record (a forum, an escalation, a regulatory requirement) the link is a field.
Where it lives in another system, the design says it is held as an **imported
reference record**, not a live link (S-2): an ``External Reference`` naming the
system and its key. Those rows could be entered on the desk only, and ``/policy``
did not show them. This module is the panel's server side: the document's
references listed on its page, and added, corrected and removed there by
someone who may edit the document.

The rules:

* **Read with the document, change with the document.** Anyone who may read the
  document sees its links; only someone with write permission on it (the
  handling rules included) may change them. A document under retention or legal
  hold is frozen, and so are its links: the refusal is audited.
* **http and https only.** A link is shown as an anchor, so ``javascript:``,
  ``data:``, ``file:`` and anything without a host are refused. The platform
  never fetches it.
* **Nothing is deleted.** Removing a link clears its ``is_active`` flag and
  records who removed it and when; the row stays for the change log.
* **Every change is logged** twice: on the reference's own change log, and as a
  line in the document's history, where the policy office reads it.

A reference without a named system is filed under ``WEB_LINK`` (a linked web
page), created on first use, so a reader can still tell what kind of thing it
points at.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import audit, retention
from consilium.consilium_core.doctype.external_reference.external_reference import is_web_url

DOCTYPE = "Governing Document"
REFERENCE = "External Reference"

#: The system a link with no other system is filed under.
WEB_LINK_SYSTEM = "WEB_LINK"

#: What a link may point at, as P-5 lists them. Offered, not enforced: a site
#: may name another kind.
LINK_TYPES = ("Risk", "Control", "Process", "Risk assessment", "Training", "Issue", "Other")

MAX_LABEL = 140


def clean_url(url: str | None) -> str:
	"""The address, trimmed, if it is an http(s) link with a host; else refused."""
	if not is_web_url(url):
		frappe.throw(_("A link must be a full web address starting with http:// or https://."),
			title=_("Invalid Link"))
	return url.strip()


def _load(document: str, ptype: str):
	if not document or not frappe.db.exists(DOCTYPE, document):
		frappe.throw(_("There is no governing document {0}.").format(document), frappe.DoesNotExistError)
	frappe.has_permission(DOCTYPE, ptype, doc=document, throw=True)
	return document


def _may_edit(document: str) -> bool:
	return bool(frappe.has_permission(DOCTYPE, "write", doc=document)) and not retention.retention_lock(DOCTYPE, document)


def _guard(document: str, action: str) -> None:
	_load(document, "write")
	lock = retention.retention_lock(DOCTYPE, document)
	if lock:
		audit.refuse(lock["reason"], subject_doctype=DOCTYPE, subject_name=document, attempted_action=action,
			control="retention", retention_class=lock["retention_class"], legal_hold=lock["legal_hold"])


def _ensure_web_system() -> str:
	if not frappe.db.exists("External System", WEB_LINK_SYSTEM):
		frappe.get_doc({"doctype": "External System", "system_code": WEB_LINK_SYSTEM, "title": "Linked web page",
			"description": "A page in another system, linked from a record by its address.",
			"is_active": 1}).insert(ignore_permissions=True)
	return WEB_LINK_SYSTEM


def _system(value: str | None) -> str:
	if not value:
		return _ensure_web_system()
	if not frappe.db.get_value("External System", {"name": value, "is_active": 1}, "name"):
		frappe.throw(_("{0} is not an active external system.").format(value), title=_("Unknown System"))
	return value


def _label(value: str | None) -> str:
	label = (value or "").strip()
	if not label:
		frappe.throw(_("Give the link a label a reader will recognise."), title=_("Label Required"))
	return label[:MAX_LABEL]


def _history(document: str, text: str) -> None:
	frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": DOCTYPE,
		"reference_name": document, "content": text}).insert(ignore_permissions=True)


def _links(document: str) -> list[dict]:
	rows = frappe.get_all(REFERENCE,
		filters={"subject_doctype": DOCTYPE, "subject_name": document, "is_active": 1},
		fields=["name", "external_system", "external_key", "external_type", "label", "url", "last_seen_on",
			"source_import_batch", "modified", "owner"],
		order_by="external_type asc, label asc")
	titles = dict(frappe.get_all("External System", fields=["name", "title"], as_list=True))
	for row in rows:
		row["system_title"] = titles.get(row.external_system, row.external_system)
		row["modified"] = str(row.modified)
		row["last_seen_on"] = str(row.last_seen_on) if row.last_seen_on else None
		# A row imported before links had to be http(s) is shown as text.
		row["url"] = row.url.strip() if is_web_url(row.url) else None
	return rows


@frappe.whitelist(methods=["GET"])
def document_links(document: str) -> dict:
	"""The document's links to risk-programme records, and whether the viewer may change them."""
	_load(document, "read")
	editable = _may_edit(document)
	return {
		"document": document,
		"links": _links(document),
		"may_edit": editable,
		"types": list(LINK_TYPES),
		"systems": frappe.get_all("External System", filters={"is_active": 1}, fields=["name", "title"],
			order_by="title asc") if editable else [],
	}


def _key(external_key: str | None, url: str) -> str:
	return ((external_key or "").strip() or url)[:140]


@frappe.whitelist(methods=["POST"])
def add_document_link(document: str, url: str, label: str, external_type: str | None = None,
		external_system: str | None = None, external_key: str | None = None) -> dict:
	_guard(document, "Add external link")
	url, label = clean_url(url), _label(label)
	row = frappe.get_doc({
		"doctype": REFERENCE, "subject_doctype": DOCTYPE, "subject_name": document,
		"external_system": _system(external_system), "external_key": _key(external_key, url),
		"external_type": (external_type or "").strip() or None, "label": label, "url": url,
		"last_seen_on": frappe.utils.nowdate(), "is_active": 1,
	}).insert(ignore_permissions=True)
	_history(document, _("{0} linked {1} “{2}” ({3}) as {4}.").format(
		frappe.session.user, row.external_type or _("a record"), label, url, row.name))
	return document_links(document)


def _reference(link: str):
	if not link or not frappe.db.exists(REFERENCE, link):
		frappe.throw(_("There is no link {0}.").format(link), frappe.DoesNotExistError)
	row = frappe.get_doc(REFERENCE, link)
	if row.subject_doctype != DOCTYPE or not int(row.is_active or 0):
		frappe.throw(_("{0} is not a current link on a governing document.").format(link))
	return row


@frappe.whitelist(methods=["POST"])
def update_document_link(link: str, url: str, label: str, external_type: str | None = None,
		external_key: str | None = None) -> dict:
	row = _reference(link)
	_guard(row.subject_name, "Edit external link")
	url, label = clean_url(url), _label(label)
	before = f"“{row.label}” ({row.url or row.external_key})"
	row.update({"url": url, "label": label, "external_type": (external_type or "").strip() or None,
		"external_key": _key(external_key, url) if (external_key or not row.source_import_batch) else row.external_key})
	row.save(ignore_permissions=True)
	_history(row.subject_name, _("{0} changed link {1} from {2} to “{3}” ({4}).").format(
		frappe.session.user, row.name, before, label, url))
	return document_links(row.subject_name)


@frappe.whitelist(methods=["POST"])
def remove_document_link(link: str, reason: str | None = None) -> dict:
	"""Take a link off the document. The row is kept, marked removed."""
	row = _reference(link)
	_guard(row.subject_name, "Remove external link")
	row.update({"is_active": 0, "removed_by": frappe.session.user, "removed_on": now()})
	row.save(ignore_permissions=True)
	_history(row.subject_name, _("{0} removed link {1} “{2}”{3}.").format(
		frappe.session.user, row.name, row.label, (": " + reason.strip()) if (reason or "").strip() else ""))
	return document_links(row.subject_name)
