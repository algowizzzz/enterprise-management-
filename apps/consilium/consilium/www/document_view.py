"""Context for the governing document viewer: ``/document-view?version=<Document Version>``.

Shows one version's body: an uploaded file through the browser's own viewer, or
authored ``body_text`` as sanitised HTML. Alongside it are the version's
metadata, the other versions in the chain, and the glossary definitions that
apply. The policy page links every version here, so the URL and its one
parameter are a contract.

Every decision is the server's. Whether the viewer may read the document at all
is the framework's permission check, which runs the handling rules
(``consilium.policy.handling``). Whether a download is offered, whether printing
is suppressed, and whether a watermark is drawn come from ``handling.actions_for``.
The page never offers what the file endpoint would refuse.

The file itself is not linked from ``/private/files``. It is served by
``consilium.policy.handling.version_body``, which checks the same rules and sets
the headers (inline, and ``no-store`` for a view-only rendition).

The page says plainly that a browser cannot stop a determined reader copying
what it displays. The controls deter and attribute. They do not prevent.
"""

import frappe
from frappe.utils import escape_html, now_datetime
from frappe.utils.html_utils import sanitize_html

from consilium.consilium_core import versioning
from consilium.policy import glossary, handling

no_cache = 1

DOCTYPE = "Governing Document"
VERSION_DOCTYPE = "Document Version"
BODY_ENDPOINT = "/api/method/consilium.policy.handling.version_body"


def _crumbs(extra):
	# The portal shell prints breadcrumb labels, the title and the description
	# as given, so anything that came from the address or a record is escaped
	# before it gets there.
	return [
		{"label": "Home", "url": "/"},
		{"label": "Policy inventory", "url": "/policies"},
	] + extra


def _body(version_doc, allowed):
	"""What the page shows as the body, and how."""
	file_url = version_doc.body_file
	if file_url:
		mimetype = handling.mimetype_for(file_url)
		inline = handling.can_display_inline(file_url)
		kind = "none"
		if inline and mimetype == "application/pdf":
			kind = "pdf"
		elif inline and mimetype.startswith("image/"):
			kind = "image"
		elif inline:
			kind = "text"
		else:
			kind = "file"
		src = "{0}?version={1}".format(BODY_ENDPOINT, frappe.utils.quote(version_doc.name))
		# The built-in PDF viewers read these fragment hints; they hide the
		# toolbar (and so its download and print buttons) where supported. A
		# hint, not a control: see the page notice.
		if kind == "pdf" and not (allowed["download"] and allowed["print"]):
			src += "#toolbar=0&navpanes=0"
		return {
			"kind": kind,
			"mimetype": mimetype,
			"file_name": file_url.rsplit("/", 1)[-1],
			"src": src,
			"html": sanitize_html(version_doc.body_text or "", linkify=False) if version_doc.body_text else "",
		}
	if version_doc.body_text:
		return {"kind": "html", "html": sanitize_html(version_doc.body_text, linkify=False)}
	return {"kind": "none"}


def _versions(document_name):
	chain = versioning.version_history(DOCTYPE, document_name)
	published = {
		row.name: row
		for row in frappe.get_all(
			VERSION_DOCTYPE,
			filters={"subject_doctype": DOCTYPE, "subject_name": document_name},
			fields=["name", "published", "creation"],
		)
	}
	rows = []
	for row in sorted(chain, key=lambda item: int(item.get("version_number") or 0), reverse=True):
		extra = published.get(row["name"]) or {}
		rows.append({**row, "published": int(extra.get("published") or 0), "creation": str(extra.get("creation") or "")})
	return rows


def _definitions(document_name):
	"""The glossary panel. A glossary that cannot be read leaves the body readable."""
	try:
		return glossary.in_context(document_name)
	except frappe.PermissionError:
		return {"terms": [], "findings": []}


def get_context(context):
	context.no_cache = 1
	context.active_nav = "policies"
	context.user_display = frappe.session.user

	if frappe.session.user == "Guest":
		# Refused before the reference is looked at, as on /policy.
		frappe.throw("Sign in to read governing documents.", frappe.PermissionError)

	name = (frappe.form_dict.get("version") or "").strip()
	context.version_name = name
	context.found = False

	if not name:
		context.page_title = "Document viewer"
		context.page_description = "No version was named in the address."
		context.breadcrumbs = _crumbs([{"label": "Viewer"}])
		return context

	try:
		# Refuses, logs and raises for a reader the handling rules exclude; the
		# framework then renders its not-permitted page.
		version_doc, document = handling.governing_version(name)
	except frappe.DoesNotExistError:
		frappe.clear_messages()
		context.page_title = "Document viewer"
		context.page_description = "Version {0}".format(escape_html(name))
		context.breadcrumbs = _crumbs([{"label": escape_html(name)}])
		return context

	allowed = handling.actions_for(document, version=version_doc.name)
	restricted = allowed["classification"] == handling.RESTRICTED

	from frappe.core.doctype.access_log.access_log import make_access_log

	make_access_log(doctype=VERSION_DOCTYPE, document=version_doc.name, method="View", page="document-view")

	context.found = True
	context.document = {
		"name": document.name,
		"title": document.document_name,
		"classification": allowed["classification"] or "",
		"current_version": document.current_version,
	}
	context.version = {
		"name": version_doc.name,
		"number": version_doc.version_number,
		"label": version_doc.version_label,
		"change_summary": version_doc.change_summary,
		"change_classification": version_doc.change_classification,
		"origin": version_doc.origin,
		"published": int(version_doc.published or 0),
		"is_current": int(version_doc.is_current or 0),
		"superseded_by": version_doc.superseded_by,
		"created_from": version_doc.created_from_version,
		"captured_by": version_doc.owner,
		"captured_on": str(version_doc.creation or ""),
	}
	context.allowed = allowed
	context.view_only = not allowed["download"]
	context.print_blocked = not allowed["print"]
	context.body = _body(version_doc, allowed)
	context.download_url = (
		"{0}?version={1}&download=1".format(BODY_ENDPOINT, frappe.utils.quote(version_doc.name))
		if version_doc.body_file and allowed["download"] else None
	)
	context.watermark = handling.watermark_text() if restricted else None
	context.viewed_at = str(now_datetime())
	context.versions = _versions(document.name)
	context.glossary = _definitions(document.name)

	label = escape_html(str(version_doc.version_label or version_doc.version_number))
	title = escape_html(document.document_name or document.name)
	context.page_title = title
	context.page_description = "Version {0} · {1}".format(label, escape_html(document.name))
	context.breadcrumbs = _crumbs([
		{"label": title, "url": "/policy?name={0}".format(frappe.utils.quote(document.name))},
		{"label": "Version {0}".format(label)},
	])
	return context
