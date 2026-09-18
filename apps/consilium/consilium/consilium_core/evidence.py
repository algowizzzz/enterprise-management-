"""A record's history in one place (E4-S2), and its evidence pack (E4-S4).

**History.** The framework keeps a record's story in several tables: field
changes in ``Version``, workflow moves, comments and attachments in ``Comment``,
in-app notices in ``Notification Log``, mail in ``Email Queue``. Consilium adds
its own evidence of who was told, ``Notification Dispatch``. An auditor asked
"what happened to this record" should not have to know that, so ``history_of``
reads all of them and returns one chronological list, in plain language.

The rows behind it are, several of them, readable only by administrators and
audit. They are shown here to whoever may read the *subject*: the check the
caller has already made, the same way a child row follows its parent — and the
same rule ``revision.history`` applies to the version chain. What a reader is
not shown is a notification's body; its subject line, recipient, channel and
outcome are the history, the wording is evidence and belongs in the pack.

**Evidence pack.** One ZIP an auditor can hand to a reviewer: the record, its
history, its revision chain, its approvals and exceptions, the refusals recorded
against it, every notification about it, and the files attached to it that the
exporter may read. Built with the standard library's ``zipfile`` — no
dependency, nothing written to disk — and a ``manifest.json`` carrying the
SHA-256 of every entry, so the pack can be checked after it has left the system.

Who may export: someone who can read the record **and** holds an audit or
administration role (``EVIDENCE_ROLES``). The pack carries Core evidence rows —
refusals, dispatches, approval decisions — that only those roles may read on
their own, so a pack for anyone else would be a way round those permissions. A
refused export is audited, like any refusal.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile

import frappe
from frappe import _
from frappe.utils import now, strip_html

from consilium.consilium_core import audit

#: The roles an evidence pack is for. Each can already read every Core table the
#: pack draws on.
EVIDENCE_ROLES = ("Consilium Audit", "Consilium Administrator", "System Manager")

#: Comment kinds that are part of a record's story. The framework's other kinds
#: (likes, bot messages, edit notices for comments) are not.
COMMENT_KINDS = {
    "Comment": "comment",
    "Workflow": "workflow",
    "Attachment": "attachment",
    "Attachment Removed": "attachment",
    "Info": "info",
    "Assigned": "info",
    "Assignment Completed": "info",
    "Shared": "info",
    "Unshared": "info",
    "Label": "info",
    "Deleted": "info",
    "Created": "info",
}

#: Attachments stop being added to a pack past this many bytes in total; the
#: rest are listed in the manifest as withheld, with the reason. A pack is
#: built in memory, and one very large file must not take the server with it.
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024

HISTORY_LIMIT = 500


# ------------------------------------------------------------------ access


def _not_available(doctype: str, name: str):
    frappe.throw(_("{0} {1} is not available to you.").format(doctype, name), frappe.PermissionError)


def _readable(doctype: str, name: str):
    """The record if the caller may read it, else None. A record that does not
    exist and one the caller may not see are the same answer, so probing a
    reference cannot reveal a sensitive matter."""
    if not doctype or not name or not frappe.db.exists("DocType", doctype):
        return None
    if frappe.get_meta(doctype).istable or not frappe.db.exists(doctype, name):
        return None
    doc = frappe.get_doc(doctype, name)
    return doc if frappe.has_permission(doctype, "read", doc=doc) else None


def _load(doctype: str, name: str):
    doc = _readable(doctype, name)
    if doc is None:
        _not_available(doctype, name)
    return doc


def may_export(doc=None, user: str | None = None) -> bool:
    user = user or frappe.session.user
    if user == "Guest" or not set(EVIDENCE_ROLES) & set(frappe.get_roles(user)):
        return False
    return doc is None or bool(frappe.has_permission(doc.doctype, "read", doc=doc, user=user))


# ----------------------------------------------------------------- history


def _labels(doctype: str) -> dict[str, str]:
    return {df.fieldname: df.label or df.fieldname for df in frappe.get_meta(doctype).fields}


def _version_entries(doctype: str, name: str) -> list[dict]:
    labels = _labels(doctype)
    out = []
    for row in frappe.get_all(
        "Version",
        filters={"ref_doctype": doctype, "docname": name},
        fields=["name", "owner", "creation", "data"],
        order_by="creation desc",
        limit=HISTORY_LIMIT,
    ):
        try:
            data = json.loads(row.data or "{}")
        except ValueError:
            data = {}
        changed = [labels.get(entry[0], entry[0]) for entry in data.get("changed") or []]
        if data.get("added"):
            changed.append(_("rows added"))
        if data.get("removed"):
            changed.append(_("rows removed"))
        if data.get("row_changed"):
            changed.append(_("rows changed"))
        summary = _("Changed {0}").format(", ".join(changed[:8])) if changed else _("Record updated")
        if len(changed) > 8:
            summary += " " + _("and {0} more").format(len(changed) - 8)
        out.append({"kind": "change", "on": row.creation, "by": row.owner, "summary": summary,
                    "reference": row.name})
    return out


def _comment_entries(doctype: str, name: str) -> list[dict]:
    out = []
    for row in frappe.get_all(
        "Comment",
        filters={"reference_doctype": doctype, "reference_name": name,
                 "comment_type": ["in", list(COMMENT_KINDS)]},
        fields=["name", "comment_type", "content", "owner", "comment_email", "creation"],
        order_by="creation desc",
        limit=HISTORY_LIMIT,
    ):
        text = strip_html(row.content or "").strip()
        kind = COMMENT_KINDS[row.comment_type]
        if kind == "workflow":
            summary = _("Workflow: {0}").format(text)
        elif kind == "attachment":
            summary = _("{0}: {1}").format(_(row.comment_type), text)
        else:
            summary = text or _(row.comment_type)
        out.append({"kind": kind, "on": row.creation, "by": row.comment_email or row.owner,
                    "summary": summary, "reference": row.name})
    return out


def notifications_about(doctype: str, name: str) -> list[dict]:
    """Every notice sent about a record: Core's dispatches, and the framework's
    own in-app notices and mail that no dispatch accounts for.

    An email dispatch hands its message to the mail queue; the queue's own
    outcome (sent, or refused by the mail server) is shown beside it, because a
    dispatch recorded as sent only means the queue accepted the message.
    """
    dispatches = frappe.get_all(
        "Notification Dispatch",
        filters={"subject_doctype": doctype, "subject_name": name},
        fields=["name", "channel", "recipient", "rendered_subject", "status", "queued_on", "sent_on",
                "failure_reason", "fallback_of", "creation"],
        order_by="creation desc",
        limit=HISTORY_LIMIT,
    )
    queue_status = {}
    if dispatches:
        for row in frappe.get_all(
            "Email Queue",
            filters={"reference_doctype": "Notification Dispatch",
                     "reference_name": ["in", [d.name for d in dispatches]]},
            fields=["reference_name", "status", "creation"],
            order_by="creation asc",
        ):
            queue_status[row.reference_name] = row.status
    out, seen = [], set()
    for row in dispatches:
        seen.add((row.recipient, (row.rendered_subject or "").strip()))
        out.append({
            "kind": "notification", "on": row.sent_on or row.queued_on or row.creation, "by": None,
            "summary": row.rendered_subject or _("Notification"), "recipient": row.recipient,
            "channel": row.channel, "status": row.status, "mail_status": queue_status.get(row.name),
            "failure_reason": row.failure_reason, "reference": row.name, "source": "Notification Dispatch",
        })
    for row in frappe.get_all(
        "Notification Log",
        filters={"document_type": doctype, "document_name": name},
        fields=["name", "for_user", "from_user", "subject", "type", "creation"],
        order_by="creation desc",
        limit=HISTORY_LIMIT,
    ):
        subject = strip_html(row.subject or "").strip()
        # The in-app channel writes a Notification Log for its dispatch; that
        # notice is already listed, once, as the dispatch.
        if (row.for_user, subject) in seen:
            continue
        out.append({
            "kind": "notification", "on": row.creation, "by": row.from_user, "summary": subject or _(row.type),
            "recipient": row.for_user, "channel": _("In-app"), "status": None, "mail_status": None,
            "failure_reason": None, "reference": row.name, "source": "Notification Log",
        })
    for row in frappe.get_all(
        "Email Queue",
        filters={"reference_doctype": doctype, "reference_name": name},
        fields=["name", "status", "error", "creation", "sender"],
        order_by="creation desc",
        limit=HISTORY_LIMIT,
    ):
        recipients = frappe.get_all("Email Queue Recipient", filters={"parent": row.name}, pluck="recipient")
        out.append({
            "kind": "notification", "on": row.creation, "by": row.sender, "summary": _("Email"),
            "recipient": ", ".join(recipients), "channel": _("Email"), "status": row.status,
            "mail_status": row.status, "failure_reason": _last_line(row.error),
            "reference": row.name, "source": "Email Queue",
        })
    return out


def _last_line(text: str | None) -> str | None:
    lines = (text or "").strip().splitlines()
    return lines[-1] if lines else None


def history_of(doc) -> list[dict]:
    """One chronological list, newest first: changes, workflow moves, comments,
    attachments and notifications."""
    entries = (
        _version_entries(doc.doctype, doc.name)
        + _comment_entries(doc.doctype, doc.name)
        + notifications_about(doc.doctype, doc.name)
    )
    for entry in entries:
        entry["on"] = str(entry["on"]) if entry.get("on") else ""
    entries.sort(key=lambda entry: entry["on"], reverse=True)
    return entries[:HISTORY_LIMIT]


@frappe.whitelist(methods=["GET"])
def record_history(doctype: str, name: str) -> dict:
    """The history view of a record the caller may read (E4-S2)."""
    doc = _load(doctype, name)
    return {
        "subject_doctype": doc.doctype,
        "subject_name": doc.name,
        "entries": history_of(doc),
        "can_export": may_export(doc),
    }


# ----------------------------------------------------------- evidence pack


def _rows(doctype: str, filters: dict, order_by: str = "creation asc") -> list[dict]:
    if not frappe.db.table_exists(doctype):
        return []
    return frappe.get_all(doctype, filters=filters, fields=["*"], order_by=order_by)


def _json(value) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("-.")
    return cleaned or "file"


def _attachments(doc) -> tuple[list[tuple[str, bytes, dict]], list[dict]]:
    """The files attached to the record that the exporter may read, and those withheld."""
    included, withheld, total, used = [], [], 0, set()
    for name in frappe.get_all(
        "File",
        filters={"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "is_folder": 0},
        pluck="name",
        order_by="creation asc",
    ):
        file_doc = frappe.get_doc("File", name)
        entry = {"file": file_doc.name, "file_name": file_doc.file_name, "file_url": file_doc.file_url,
                 "is_private": int(file_doc.is_private or 0)}
        if not frappe.has_permission("File", "read", doc=file_doc):
            withheld.append({**entry, "reason": _("You may not read this file.")})
            continue
        try:
            content = file_doc.get_content()
        except Exception:
            withheld.append({**entry, "reason": _("The file's content could not be read.")})
            continue
        if isinstance(content, str):
            content = content.encode("utf-8")
        if content is None:
            withheld.append({**entry, "reason": _("The file has no stored content (an external link).")})
            continue
        if total + len(content) > MAX_ATTACHMENT_BYTES:
            withheld.append({**entry, "reason": _("Left out: the pack's attachment size limit was reached.")})
            continue
        total += len(content)
        base = _safe_name(file_doc.file_name or file_doc.name)
        path = f"attachments/{base}"
        if path in used:
            path = f"attachments/{_safe_name(file_doc.name)}-{base}"
        used.add(path)
        included.append((path, content, entry))
    return included, withheld


def build_pack(doc) -> tuple[str, bytes]:
    """The pack's file name and bytes. The caller has already checked access."""
    subject = {"subject_doctype": doc.doctype, "subject_name": doc.name}
    parts: list[tuple[str, bytes]] = [
        ("record.json", _json(doc.as_dict(convert_dates_to_str=True))),
        ("history.json", _json(history_of(doc))),
        ("revisions.json", _json({
            "document_versions": _rows("Document Version", subject, "version_number asc"),
            "revert_log": _rows("Version Revert Log", subject),
            "field_changes": frappe.get_all(
                "Version", filters={"ref_doctype": doc.doctype, "docname": doc.name},
                fields=["name", "owner", "creation", "data"], order_by="creation asc",
            ),
        })),
        ("approvals.json", _json({
            "approval_decisions": _rows("Approval Decision", subject, "step_sequence asc, creation asc"),
            "exception_authorisations": _rows("Exception Authorisation", subject),
        })),
        ("refusals.json", _json(_rows("Governance Refusal Log", subject))),
        ("notifications.json", _json({
            "dispatches": _rows("Notification Dispatch", subject),
            "summary": notifications_about(doc.doctype, doc.name),
        })),
    ]
    attachments, withheld = _attachments(doc)
    parts.extend((path, content) for path, content, _entry in attachments)

    manifest = {
        **subject,
        "title": doc.get_title() if hasattr(doc, "get_title") else doc.name,
        "generated_on": now(),
        "generated_by": frappe.session.user,
        "entries": [
            {"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for path, content in parts
        ],
        "attachments": [{**entry, "path": path} for path, _content, entry in attachments],
        "attachments_withheld": withheld,
        "note": "Each entry's SHA-256 is recorded here so the pack can be verified after export.",
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in parts:
            archive.writestr(path, content)
        archive.writestr("manifest.json", _json(manifest))
    stamp = now()[:10]
    filename = f"evidence-{_safe_name(doc.doctype)}-{_safe_name(doc.name)}-{stamp}.zip"
    return filename, buffer.getvalue()


@frappe.whitelist(methods=["GET"])
def export_pack(doctype: str, name: str):
    """Download a record's evidence pack (E4-S4). Refused, and audited, for
    anyone who may not read the record or does not hold an evidence role."""
    doc = _readable(doctype, name)
    if doc is None:
        # Audited as a refusal, with the same words a missing record gets.
        audit.refuse(
            _("{0} {1} is not available to you.").format(doctype, name),
            subject_doctype=doctype if frappe.db.exists("DocType", doctype or "") else "DocType",
            subject_name=name or "",
            attempted_action="Other",
            control="evidence pack export",
        )
    if not may_export(doc):
        audit.refuse(
            _("{0} may not export the evidence pack of {1} {2}. Evidence packs belong to: {3}.").format(
                frappe.session.user, doctype, name, ", ".join(EVIDENCE_ROLES)
            ),
            subject_doctype=doctype,
            subject_name=name,
            attempted_action="Other",
            control="evidence pack export",
        )
    filename, content = build_pack(doc)
    frappe.local.response.filename = filename
    frappe.local.response.filecontent = content
    frappe.local.response.type = "download"
