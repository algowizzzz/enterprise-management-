"""Confidential and restricted handling of governing documents (P-1, P-13, P-19).

P-1 and P-13 require that confidential and restricted documents limit **view,
download, print and share** to authorised users. P-19 adds that a publication
carries view-only, print-enabled or downloadable renditions. The framework has
no per-record control for any of the four, so this module supplies them. It is
registered in ``hooks.py`` as the Governing Document ``has_permission`` and
``permission_query_conditions`` hooks, and so it holds on every read path the
framework has: list, form, report, search, link pickers and the REST API. The
model is ``consilium/escalation/sensitivity.py``: a hook may only narrow what
the role permissions allow, never widen it.

Who may see a Confidential or Restricted document
-------------------------------------------------
The decision is written down here because the baseline does not spell it out.
P-13 says "authorised users". The data model names who is accountable for a
document (§7.2 accountability fields, §7.4 accountability roles), whom it
applies to (applicability) and whom it was published to (publication
audiences). The rule reads those records, and nothing else.

Everyone below must *also* hold a role that can read governing documents. The
hook narrows access and never grants it.

1. **Oversight, always.** Administrator, System Manager, Enterprise Policy
   Office (the repository's custodian and the "administrator" the data model
   says may override the handling defaults), and Consilium Audit. Audit is the
   third line: an assurance function that cannot read what it assures is no
   assurance at all.
2. **Named on the record.** The owner, approver, liaison, delegate, sponsor, key
   contact, the implementation confirmer and verifier, and whoever created the
   record, who has already seen all of it. Also any user on an accountability-role
   row that is in force today, or any member of that row's user group.
3. **Named in a publication.** A user or user-group member named in the audience
   of a publication of this document that has not been withdrawn (P-19
   "restricted, or targeted groups").
4. **Confidential only, the wider audience.** For a Confidential document (not a
   Restricted one), also members of the notification group of an in-force
   applicability row, holders of a role that an applicability row or a
   publication audience names as its scope. Restricted is the tighter class, so
   it admits only people named individually or by group, never everyone who
   holds a role.

Public and Internal documents are not narrowed. Their readers are whoever the
role permissions allow.

A document the framework has **shared** with a user is readable by that user,
because the framework grants read on a share even when a controller hook denies.
That cannot be changed from an app without forking the framework, so sharing
itself is gated below: a share is then a deliberate act by a steward.

Print, download and share
-------------------------
These apply at every classification, because the three flags are set per record
and an administrator may close them on an Internal document too.

* **Stewards may always print, download and share.** The stewards are
  Administrator, System Manager, Enterprise Policy Office, and the document's
  owner and delegate. They hold the source and administer its handling, and the
  owner needs the file in order to revise it in the external editor.
* **Everyone else** may print only when ``allow_print`` is set, download only
  when ``allow_download`` is set, and share or e-mail only when ``allow_share``
  is set. The publication's rendition must also allow it: the most recent
  publication of the version being served that has not been withdrawn (or of the
  document, where no version is identifiable). A view-only rendition closes print
  and download.

The framework treats *read* as enough to print (its print view accepts read or
print) and to fetch an attached file (``/private/files`` checks read on the
document the file is attached to). A read hook that ignored that would leave
both doors open. So the hook recognises the request it is answering: a request
that serves file bytes asks "may download", and a print-view or PDF request asks
"may print". See ``request_channel``.

Loosening the handling (lowering the classification, or reopening one of the
three actions on a Confidential or Restricted document) is reserved to the
people the data model calls administrators. It is refused and logged for anyone
else. Raising a document into Confidential or Restricted closes the three
actions again unless the same save sets them explicitly.

What a browser cannot prevent
-----------------------------
Anything a browser can display, a user can copy: a screenshot, a photograph of
the screen, the browser's own save or print. "View only" here means we do not
*offer* the file for download, we mark the response ``no-store`` so it is not
kept in the cache, and on Restricted documents we overlay the viewer's name and
the time so that a copy identifies its source. It deters and attributes. It does
not prevent, and the viewer page says so.

Hooks this module still needs (``hooks.py`` is not this module's to edit)
-------------------------------------------------------------------------
``Document Version`` rows carry the body, and Frappe attaches a version's body
file to the *version*, so the same private file is reachable through a
``File`` row the Governing Document hook never sees::

    permission_query_conditions["Document Version"] = "consilium.policy.handling.version_query_conditions"
    has_permission["Document Version"] = "consilium.policy.handling.version_has_permission"
    doc_events["File"] = {"before_insert": "consilium.policy.handling.guard_file_privacy"}

The tests register these at run time, as the escalation tests once did, so the
code the hooks would call is exercised through the framework's own path.
"""

from __future__ import annotations

import mimetypes
import os

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, nowdate

DOCTYPE = "Governing Document"
VERSION_DOCTYPE = "Document Version"
PUBLICATION_DOCTYPE = "Document Publication"

#: The two classifications that narrow who may see a document. Restricted is the
#: tighter of the two. These are data classifications, not workflow states.
CONFIDENTIAL = "Confidential"
RESTRICTED = "Restricted"
RESTRICTED_CLASSES = (CONFIDENTIAL, RESTRICTED)

#: Roles that see every document whatever its classification (rule 1).
OVERSIGHT_ROLES = ("System Manager", "Enterprise Policy Office", "Consilium Audit")

#: Roles that may always print, download and share (the stewards, with the
#: owner and delegate named on the record).
STEWARD_ROLES = ("System Manager", "Enterprise Policy Office")

#: Roles that may loosen a document's handling. The data model says the defaults
#: are "overridable by an administrator"; these are the administrators.
HANDLING_ADMIN_ROLES = ("System Manager", "Enterprise Policy Office", "Consilium Administrator")

#: The people fields that name someone on the record (rule 2). ``owner`` is the
#: framework's creator field.
PERSON_FIELDS = (
    "document_owner", "document_approver", "document_liaison", "document_delegate",
    "document_sponsor", "key_contact", "implementation_confirmed_by", "implementation_verified_by",
    "owner",
)

#: The people fields that make someone a steward of the document.
STEWARD_FIELDS = ("document_owner", "document_delegate")

#: Endpoints that return a file's bytes. Each checks only *read* on the
#: document the file is attached to, which is why the hook must tell them apart.
DOWNLOAD_METHODS = (
    "download_file",
    "frappe.handler.download_file",
    "frappe.core.doctype.file.file.download_file",
)

#: Endpoints that render a document for printing or as a PDF.
PRINT_METHODS = (
    "frappe.utils.print_format.download_pdf",
    "frappe.utils.print_format.download_multi_pdf",
    "frappe.utils.print_format.print_by_server",
    "frappe.www.printview.get_html_and_style",
    "frappe.www.printview.get_rendered_raw_commands",
)
PRINT_PATHS = ("/printview", "/printpreview")

#: Types the viewer shows inline. Anything else (HTML, SVG, office formats) is
#: never rendered inline from our origin: an uploaded HTML or SVG file served
#: same-origin would run its scripts with the viewer's session.
INLINE_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "text/plain")


# ------------------------------------------------------------------- classes


def classification(doc) -> str | None:
    """The document's handling class, with the legacy ``confidential`` flag
    counted as at least Confidential. The controller already derives this on
    save; this also covers rows written without one."""
    value = doc.get("handling_classification")
    if value == RESTRICTED:
        return RESTRICTED
    if value == CONFIDENTIAL or int(doc.get("confidential") or 0):
        return CONFIDENTIAL
    return value


def is_restricted_class(doc) -> bool:
    return classification(doc) in RESTRICTED_CLASSES


def _rank(doc) -> int:
    """How tightly a document is held: 0 open, 1 Confidential, 2 Restricted."""
    return {CONFIDENTIAL: 1, RESTRICTED: 2}.get(classification(doc), 0)


# ---------------------------------------------------------------- the people


def _roles(user: str) -> set[str]:
    return set(frappe.get_roles(user))


def is_oversight(user: str) -> bool:
    return user == "Administrator" or bool(_roles(user) & set(OVERSIGHT_ROLES))


def _groups_of(user: str) -> set[str]:
    return set(frappe.get_all("User Group Member", filters={"user": user}, pluck="parent"))


def _in_force(row, today) -> bool:
    start = row.get("from_date") or row.get("applies_from")
    end = row.get("to_date") or row.get("applies_to")
    if start and getdate(start) > today:
        return False
    if end and getdate(end) < today:
        return False
    return True


def _publication_is_live(row, today) -> bool:
    return not row.get("withdrawn_on") or getdate(row.get("withdrawn_on")) > today


def _publication_audience_grants(document: str | None, user: str, groups: set[str], roles: set[str]) -> dict:
    """Documents whose live publications name the user, by how they are named.

    Returns ``{"named": set, "by_role": set}``: named individually or by group
    (rule 3), or only through a role (rule 4). ``document`` limits the answer to
    one document; ``None`` answers for all of them.
    """
    filters = {"docstatus": ["<", 2]}
    if document:
        filters["document"] = document
    publications = {
        row["name"]: row
        for row in frappe.get_all(
            PUBLICATION_DOCTYPE, filters=filters, fields=["name", "document", "withdrawn_on"]
        )
    }
    today = getdate(nowdate())
    live = {name: row["document"] for name, row in publications.items() if _publication_is_live(row, today)}
    named: set[str] = set()
    by_role: set[str] = set()
    if not live:
        return {"named": named, "by_role": by_role}
    for row in frappe.get_all(
        "Publication Audience",
        filters={"parenttype": PUBLICATION_DOCTYPE, "parent": ["in", list(live)]},
        fields=["parent", "audience_kind", "audience_value"],
    ):
        kind, value = row.get("audience_kind"), row.get("audience_value")
        doc_name = live[row["parent"]]
        if (kind == "User" and value == user) or (kind == "User Group" and value in groups):
            named.add(doc_name)
        elif kind == "Role" and value in roles:
            by_role.add(doc_name)
    return {"named": named, "by_role": by_role}


def _named_on_record(doc, user: str, groups: set[str]) -> bool:
    """Rule 2 for one loaded document."""
    if any((doc.get(field) or "") == user for field in PERSON_FIELDS):
        return True
    today = getdate(nowdate())
    for row in doc.get("accountability_roles") or []:
        if not _in_force(row, today):
            continue
        if row.get("user") == user or (row.get("user_group") and row.get("user_group") in groups):
            return True
    return False


def _in_wider_audience(doc, groups: set[str], roles: set[str]) -> bool:
    """The applicability part of rule 4 for one loaded document."""
    today = getdate(nowdate())
    for row in doc.get("applicability") or []:
        if not _in_force(row, today):
            continue
        if row.get("notification_group") and row.get("notification_group") in groups:
            return True
        if row.get("scope_type") == "Role" and row.get("scope_value") in roles:
            return True
    return False


def may_see(doc, user: str | None = None) -> bool:
    """Whether ``user`` may see this document at all, over and above the roles."""
    user = user or frappe.session.user
    level = classification(doc)
    if level not in RESTRICTED_CLASSES or is_oversight(user):
        return True
    groups = _groups_of(user)
    if _named_on_record(doc, user, groups):
        return True
    roles = _roles(user)
    grants = _publication_audience_grants(doc.name, user, groups, roles)
    if doc.name in grants["named"]:
        return True
    if level == RESTRICTED:
        return False
    return doc.name in grants["by_role"] or _in_wider_audience(doc, groups, roles)


# -------------------------------------------------------------- the actions


def is_steward(doc, user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Administrator" or _roles(user) & set(STEWARD_ROLES):
        return True
    return any((doc.get(field) or "") == user for field in STEWARD_FIELDS)


def rendition(document: str, version: str | None = None) -> dict:
    """The renditions the governing publication allows.

    The governing publication is the latest live publication of ``version``,
    or of the document where no version is named or the version was never
    published. With none at all, the rendition does not restrict and the
    document's own flags decide.
    """
    today = getdate(nowdate())
    rows = frappe.get_all(
        PUBLICATION_DOCTYPE,
        filters={"document": document, "docstatus": ["<", 2]},
        fields=["name", "document_version", "withdrawn_on", "rendition_view_only",
                "rendition_print", "rendition_download"],
        order_by="published_on desc, creation desc",
    )
    live = [row for row in rows if _publication_is_live(row, today)]
    chosen = None
    if version:
        chosen = next((row for row in live if row["document_version"] == version), None)
    if chosen is None and live:
        chosen = live[0]
    if chosen is None:
        return {"publication": None, "view_only": False, "print": True, "download": True}
    view_only = bool(int(chosen.get("rendition_view_only") or 0))
    return {
        "publication": chosen["name"],
        "view_only": view_only,
        "print": not view_only and bool(int(chosen.get("rendition_print") or 0)),
        "download": not view_only and bool(int(chosen.get("rendition_download") or 0)),
    }


def may_download(doc, user: str | None = None, version: str | None = None) -> bool:
    if not may_see(doc, user):
        return False
    if is_steward(doc, user):
        return True
    return bool(int(doc.get("allow_download") or 0)) and rendition(doc.name, version)["download"]


def may_print(doc, user: str | None = None, version: str | None = None) -> bool:
    if not may_see(doc, user):
        return False
    if is_steward(doc, user):
        return True
    return bool(int(doc.get("allow_print") or 0)) and rendition(doc.name, version)["print"]


def may_share(doc, user: str | None = None) -> bool:
    if not may_see(doc, user):
        return False
    if is_steward(doc, user):
        return True
    return bool(int(doc.get("allow_share") or 0))


def actions_for(doc, user: str | None = None, version: str | None = None) -> dict:
    """Everything a page needs to decide what to offer, in one place."""
    user = user or frappe.session.user
    return {
        "classification": classification(doc),
        "see": may_see(doc, user),
        "download": may_download(doc, user, version),
        "print": may_print(doc, user, version),
        "share": may_share(doc, user),
        "steward": is_steward(doc, user),
        "rendition": rendition(doc.name, version),
    }


# ------------------------------------------------------------ the request


def _method_name(request) -> str:
    path = request.path or ""
    for prefix in ("/api/method/", "/api/v1/method/", "/api/v2/method/"):
        if path.startswith(prefix):
            return path[len(prefix):].strip("/")
    return (frappe.form_dict.get("cmd") or "") if frappe.form_dict else ""


def request_channel() -> str | None:
    """What the current request will do with a document it reads.

    ``"download"`` when it returns a file's bytes, ``"print"`` when it renders a
    print view or PDF, ``None`` otherwise. Outside a request (a background job,
    a test, the console) it is ``None``, so only the ordinary rules apply.
    """
    request = getattr(frappe.local, "request", None)
    if request is None:
        return None
    path = request.path or ""
    if path.startswith("/private/files/"):
        return "download"
    if path in PRINT_PATHS:
        return "print"
    method = _method_name(request)
    if method in DOWNLOAD_METHODS:
        return "download"
    if method in PRINT_METHODS:
        return "print"
    return None


def _requested_file_url() -> str | None:
    request = getattr(frappe.local, "request", None)
    if request is None:
        return None
    if (request.path or "").startswith("/private/files/"):
        return request.path
    return (frappe.form_dict or {}).get("file_url")


def _version_for_file(document: str, file_url: str | None) -> str | None:
    if not file_url:
        return None
    return frappe.db.get_value(
        VERSION_DOCTYPE,
        {"subject_doctype": DOCTYPE, "subject_name": document, "body_file": file_url},
        "name",
        order_by="version_number desc",
    )


# -------------------------------------------------------------- the hooks


def has_permission(doc, ptype: str | None = "read", user: str | None = None, debug: bool = False):
    """Deny what the handling rules do not allow. ``None`` means "no objection".

    A controller hook may deny, never grant, so every branch returns ``False``
    or ``None``.
    """
    user = user or frappe.session.user
    if user == "Administrator" or doc.doctype != DOCTYPE:
        return None
    if not may_see(doc, user):
        return False
    ptype = ptype or "read"
    if ptype == "print":
        return None if may_print(doc, user) else False
    if ptype in ("share", "email"):
        return None if may_share(doc, user) else False
    if ptype == "read":
        channel = request_channel()
        if channel == "download":
            version = _version_for_file(doc.name, _requested_file_url())
            return None if may_download(doc, user, version) else False
        if channel == "print":
            return None if may_print(doc, user) else False
    return None


def _document_conditions(user: str, table: str = f'"tab{DOCTYPE}"') -> str:
    """The SQL form of ``may_see`` over ``table``, or ``""`` for no restriction."""
    if is_oversight(user):
        return ""
    escape = frappe.db.escape
    groups = _groups_of(user)
    roles = _roles(user)
    today = nowdate()

    named: set[str] = set()
    wider: set[str] = set()

    role_rows = frappe.get_all(
        "Document Accountability Role",
        filters={"parenttype": DOCTYPE},
        or_filters=[["user", "=", user]] + ([["user_group", "in", list(groups)]] if groups else []),
        fields=["parent", "from_date", "to_date"],
    )
    named |= {row["parent"] for row in role_rows if _in_force(row, getdate(today))}

    grants = _publication_audience_grants(None, user, groups, roles)
    named |= grants["named"]
    wider |= grants["by_role"]

    applicability_filters = []
    if groups:
        applicability_filters.append(["notification_group", "in", list(groups)])
    if roles:
        applicability_filters.append(["scope_value", "in", list(roles)])
    if applicability_filters:
        for row in frappe.get_all(
            "Document Applicability",
            filters={"parenttype": DOCTYPE},
            or_filters=applicability_filters,
            fields=["parent", "scope_type", "scope_value", "notification_group", "applies_from", "applies_to"],
        ):
            if not _in_force(row, getdate(today)):
                continue
            if row.get("notification_group") in groups or (
                row.get("scope_type") == "Role" and row.get("scope_value") in roles
            ):
                wider.add(row["parent"])

    def in_list(names: set[str]) -> str:
        return ", ".join(escape(name) for name in sorted(names))

    hc = f'{table}."handling_classification"'
    classes = ", ".join(escape(value) for value in RESTRICTED_CLASSES)
    clauses = [
        f"(COALESCE({hc}, '') NOT IN ({classes}) AND COALESCE({table}.\"confidential\", 0) = 0)",
    ]
    clauses += [f'{table}."{field}" = {escape(user)}' for field in PERSON_FIELDS]
    if named:
        clauses.append(f'{table}."name" IN ({in_list(named)})')
    if wider:
        clauses.append(f'(COALESCE({hc}, \'\') <> {escape(RESTRICTED)} AND {table}."name" IN ({in_list(wider)}))')
    return "(" + " OR ".join(clauses) + ")"


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
    """The list, report, search and REST filter for Governing Document."""
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    return _document_conditions(user)


def version_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
    """A version of a governing document is visible to whoever may see the document."""
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    inner = _document_conditions(user, table='gd')
    if not inner:
        return ""
    version = f'"tab{VERSION_DOCTYPE}"'
    return (
        f"(COALESCE({version}.\"subject_doctype\", '') <> {frappe.db.escape(DOCTYPE)} OR "
        f'{version}."subject_name" IN (SELECT gd."name" FROM "tab{DOCTYPE}" gd WHERE {inner}))'
    )


def version_has_permission(doc, ptype: str | None = "read", user: str | None = None, debug: bool = False):
    """A version carries its document's body, so it carries its document's handling."""
    user = user or frappe.session.user
    if user == "Administrator" or doc.get("subject_doctype") != DOCTYPE or not doc.get("subject_name"):
        return None
    if not frappe.db.exists(DOCTYPE, doc.subject_name):
        return None
    subject = frappe.get_doc(DOCTYPE, doc.subject_name)
    if not may_see(subject, user):
        return False
    ptype = ptype or "read"
    channel = request_channel() if ptype == "read" else None
    if ptype == "print" or channel == "print":
        return None if may_print(subject, user, doc.name) else False
    if channel == "download":
        return None if may_download(subject, user, doc.name) else False
    if ptype in ("share", "email"):
        return None if may_share(subject, user) else False
    return None


# ------------------------------------------------------------- the files


def _restricted_subject_of_file(file_doc) -> bool:
    doctype, name = file_doc.get("attached_to_doctype"), file_doc.get("attached_to_name")
    if not doctype or not name:
        return False
    if doctype == VERSION_DOCTYPE:
        subject = frappe.db.get_value(VERSION_DOCTYPE, name, ["subject_doctype", "subject_name"], as_dict=True)
        if not subject or subject.subject_doctype != DOCTYPE:
            return False
        doctype, name = DOCTYPE, subject.subject_name
    if doctype != DOCTYPE:
        return False
    row = frappe.db.get_value(DOCTYPE, name, ["handling_classification", "confidential"], as_dict=True)
    return bool(row) and is_restricted_class(row)


def guard_file_privacy(doc, method=None) -> None:
    """A file attached to a confidential or restricted document is stored private.

    Public files are served by the web server with no permission check at all,
    so nothing in this module could protect one. Intended as the ``File``
    ``before_insert`` hook; see the module docstring.
    """
    if int(doc.get("is_private") or 0) or doc.get("is_folder"):
        return
    if (doc.get("file_url") or "").startswith(("http://", "https://")):
        return
    if _restricted_subject_of_file(doc):
        doc.is_private = 1


def secure_on_save(doc) -> None:
    """Called from the Governing Document ``validate``.

    Refuses a loosening of the handling by someone who may not loosen it, closes
    the three actions when a document is raised into a restricted class, and
    moves the document's own public attachments to private storage.
    """
    before = None if doc.is_new() else doc.get_doc_before_save()
    if before is not None:
        _guard_loosening(doc, before)
        _close_on_raise(doc, before)
    if is_restricted_class(doc) and not doc.is_new():
        _make_attachments_private(doc)


def _guard_loosening(doc, before) -> None:
    from consilium.consilium_core import audit

    user = frappe.session.user
    if user == "Administrator" or _roles(user) & set(HANDLING_ADMIN_ROLES):
        return
    lowered = _rank(doc) < _rank(before)
    reopened = [
        field for field in ("allow_download", "allow_print", "allow_share")
        if is_restricted_class(doc) and int(doc.get(field) or 0) and not int(before.get(field) or 0)
    ]
    if not (lowered or reopened):
        return
    what = []
    if lowered:
        what.append(_("lowering the handling from {0} to {1}").format(
            classification(before), doc.get("handling_classification") or _("none")))
    if reopened:
        what.append(_("reopening {0}").format(", ".join(reopened)))
    audit.refuse(
        _("{0}: {1} is refused. Only the Enterprise Policy Office or an administrator may loosen the "
          "handling of a confidential or restricted document.").format(doc.name, "; ".join(what)),
        subject_doctype=DOCTYPE,
        subject_name=doc.name,
        attempted_action="Modify",
        control="restricted handling",
        context={"lowered": lowered, "reopened": reopened},
        exc=frappe.PermissionError,
    )


def _close_on_raise(doc, before) -> None:
    if is_restricted_class(before) or not is_restricted_class(doc):
        return
    for field in ("allow_download", "allow_print", "allow_share"):
        # A value changed in this same save is a decision someone made; only
        # values carried over from before are reset to the restrictive default.
        if int(doc.get(field) or 0) == int(before.get(field) or 0):
            doc.set(field, 0)


def _make_attachments_private(doc) -> None:
    """Move the document's public attachments into private storage.

    A public file is served straight off the disk with no permission check, so
    for a confidential document it is simply published. A file that is also a
    version's body is left where it is, because version rows are append-only and
    moving the file would break the link the version holds; the user is told.
    """
    public = frappe.get_all(
        "File",
        filters={"attached_to_doctype": DOCTYPE, "attached_to_name": doc.name, "is_private": 0, "is_folder": 0},
        fields=["name", "file_url"],
    )
    stuck = []
    for row in public:
        url = row.get("file_url") or ""
        if not url.startswith("/files/"):
            continue
        if frappe.db.exists(VERSION_DOCTYPE, {"body_file": url}):
            stuck.append(url)
            continue
        file_doc = frappe.get_doc("File", row["name"])
        file_doc.is_private = 1
        file_doc.save(ignore_permissions=True)
    if stuck:
        frappe.msgprint(
            _("{0} is {1}, but the body of an earlier version is a public file ({2}) that anyone with the "
              "address can fetch. Take a new version with the file uploaded as private.").format(
                doc.name, classification(doc), ", ".join(stuck)),
            title=_("Public file on a restricted document"),
            indicator="orange",
        )


# ---------------------------------------------------------- the endpoint


def _refuse_view(version_name: str, message: str, **context) -> None:
    from consilium.consilium_core import audit

    audit.refuse(
        message,
        subject_doctype=VERSION_DOCTYPE,
        subject_name=version_name,
        attempted_action="Other",
        control="restricted handling",
        context=context or None,
        exc=frappe.PermissionError,
    )


def governing_version(version_name: str):
    """The version and its governing document, or a refusal.

    Refused alike for a missing version and one the caller may not see, so the
    difference cannot be used to probe for references.
    """
    if frappe.session.user == "Guest":
        raise frappe.PermissionError(_("Sign in to read governing documents."))
    row = frappe.db.get_value(
        VERSION_DOCTYPE, version_name, ["name", "subject_doctype", "subject_name"], as_dict=True
    ) if version_name else None
    if not row or row.subject_doctype != DOCTYPE or not frappe.db.exists(DOCTYPE, row.subject_name):
        raise frappe.DoesNotExistError(_("No governing document version {0}.").format(version_name))
    document = frappe.get_doc(DOCTYPE, row.subject_name)
    if not frappe.has_permission(DOCTYPE, "read", doc=document):
        _refuse_view(version_name, _("You may not read {0}, so you may not read its versions.").format(document.name),
                     document=document.name)
    return frappe.get_doc(VERSION_DOCTYPE, version_name), document


def _file_bytes(file_url: str) -> tuple[bytes, str]:
    """Read a body file's content. Local files only: a remote URL is not ours."""
    name = frappe.db.get_value("File", {"file_url": file_url, "is_folder": 0}, "name")
    if not name:
        raise frappe.DoesNotExistError(_("The file for this version is missing."))
    file_doc = frappe.get_doc("File", name)
    content = file_doc.get_content()
    if isinstance(content, str):
        content = content.encode("utf-8")
    return content, file_doc.file_name or os.path.basename(file_url)


def mimetype_for(file_url: str | None) -> str:
    return (mimetypes.guess_type(file_url or "")[0] or "application/octet-stream") if file_url else ""


def can_display_inline(file_url: str | None) -> bool:
    return mimetype_for(file_url) in INLINE_TYPES


@frappe.whitelist(methods=["GET"])
def version_body(version: str, download: int | str = 0):
    """Serve a governing document version's body file, permission-checked.

    ``GET /api/method/consilium.policy.handling.version_body?version=DVER-...``

    Inline by default, for the viewer's ``<iframe>``. ``download=1`` asks for an
    attachment and is refused unless the rules above allow a download. A body
    that may not be downloaded is sent ``Cache-Control: no-store``. The browser
    still has the bytes it displays; see the module docstring.
    """
    from frappe.core.doctype.access_log.access_log import make_access_log
    from werkzeug.wrappers import Response

    version_doc, document = governing_version(version)
    wants_download = str(download) in ("1", "true", "True")
    allowed = actions_for(document, version=version_doc.name)

    if not version_doc.body_file:
        raise frappe.DoesNotExistError(_("Version {0} has no body file.").format(version_doc.name))
    if wants_download and not allowed["download"]:
        _refuse_view(
            version_doc.name,
            _("{0} may not be downloaded: its handling or its published rendition allows viewing only.")
            .format(document.name),
            document=document.name,
            rendition=allowed["rendition"].get("publication"),
        )
    mimetype = mimetype_for(version_doc.body_file)
    if not wants_download and mimetype not in INLINE_TYPES:
        # Never rendered inline from our origin; see INLINE_TYPES.
        _refuse_view(
            version_doc.name,
            _("A {0} file cannot be displayed in the browser safely.").format(mimetype),
            document=document.name,
        )

    content, filename = _file_bytes(version_doc.body_file)
    make_access_log(
        doctype=VERSION_DOCTYPE,
        document=version_doc.name,
        method="Download" if wants_download else "View",
        file_type=os.path.splitext(filename)[1].lstrip("."),
    )

    response = Response(content, mimetype=mimetype if not wants_download else "application/octet-stream")
    response.headers.add("Content-Disposition", "attachment" if wants_download else "inline", filename=filename)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Framed only by our own viewer page.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Cache-Control"] = "private, no-cache" if allowed["download"] else "no-store, max-age=0"
    return response


def watermark_text(user: str | None = None) -> str:
    """The viewer's name and the time: what a copy of the screen would carry."""
    user = user or frappe.session.user
    full_name = frappe.utils.get_fullname(user) or user
    return f"{full_name} · {user} · {now_datetime().strftime('%Y-%m-%d %H:%M')}"
