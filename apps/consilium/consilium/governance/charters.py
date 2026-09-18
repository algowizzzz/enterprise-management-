"""Committee charters, held in Core's version chain.

A charter's body is not a field on the charter. It is a ``Document Version``
written by Core's versioning engine, because "what did this charter say on a
given date" must have exactly one answer and a revert must write a new version
rather than rewrite an old one. Nothing about that is reimplemented here.

What is here is the risk governance office's effective challenge — a control,
not a courtesy — and the rule that a charter is not cleared for approval while
the challenge is outstanding.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now, nowdate

from consilium.consilium_core import versioning

CHALLENGE_CLEARED = "Cleared"
CHALLENGE_CHANGES_REQUESTED = "Changes Requested"


def publish_version(charter, change_summary: str, *, body_file: str | None = None,
                    body_text: str | None = None, version_label: str | None = None,
                    origin: str = "Authored"):
    """Append a version to the charter's chain and point the charter at it."""
    if isinstance(charter, str):
        charter = frappe.get_doc("Committee Charter", charter)
    version = versioning.create_version(
        charter,
        change_summary=change_summary,
        origin=origin,
        body_file=body_file,
        body_text=body_text,
        version_label=version_label,
        retention_class=frappe.db.get_value("Governance Forum", charter.forum, "retention_class")
        if charter.forum else None,
    )
    charter.db_set("current_version", version.name, update_modified=False)
    return version


def record_challenge(charter, status: str, *, comments: str | None = None, by: str | None = None):
    """Record the risk governance office's challenge outcome."""
    if isinstance(charter, str):
        charter = frappe.get_doc("Committee Charter", charter)
    charter.rgo_challenge_status = status
    charter.rgo_challenge_comments = comments
    charter.rgo_reviewed_by = by or frappe.session.user
    charter.rgo_reviewed_on = now()
    charter.save(ignore_permissions=True)
    return charter


def clearance_blockers(charter) -> list[str]:
    """Why this charter is not ready to be approved. Reads flags and rows."""
    if isinstance(charter, str):
        charter = frappe.get_doc("Committee Charter", charter)
    blockers = []
    if charter.requires_review:
        blockers.append(_("the risk governance office challenge is not cleared"))
    if not charter.current_version:
        blockers.append(_("the charter has no version in the chain"))
    if not charter.approval_evidence:
        blockers.append(_("no approval evidence is recorded"))
    return blockers


def history(charter) -> list[dict]:
    name = charter if isinstance(charter, str) else charter.name
    return versioning.version_history("Committee Charter", name)


# --------------------------------------------------------------- the gate
#
# G-7 asks for the draft charter to be challenged by the risk governance office
# before final approval is sought, and E33-S1 makes an unresolved challenge an
# approval blocker. The question "is there an uncleared challenge?" is asked in
# two places — formation approval and a forum's compliance standing — so it is
# answered once, here, from the charter's ``requires_review`` flag. The challenge
# label is written by ``record_challenge`` and ``reopen_challenge`` and shown to
# people; it is never compared.

CHALLENGE_NOT_REVIEWED = "Not Reviewed"


def uncleared_challenges(*, forum: str | None = None, formation_request: str | None = None) -> list[dict]:
    """Charters whose risk governance office challenge is outstanding.

    For a formation request: every charter drafted against it. For a forum: the
    charters in force on it — one whose ``effective_to`` has passed is history,
    and an old charter's challenge cannot block the forum it no longer governs.

    Written with the query builder because "no end date" must be ``IS NULL``:
    the framework's ``["is", "not set"]`` compares a date column with the empty
    string, which PostgreSQL rejects.
    """
    if not (forum or formation_request):
        return []
    charter = frappe.qb.DocType("Committee Charter")
    query = (
        frappe.qb.from_(charter)
        .select(charter.name, charter.charter_title, charter.rgo_challenge_status,
                charter.rgo_challenge_comments)
        .where(charter.requires_review == 1)
        .orderby(charter.name)
    )
    if formation_request:
        query = query.where(charter.formation_request == formation_request)
    if forum:
        query = query.where(charter.forum == forum).where(
            charter.effective_to.isnull() | (charter.effective_to >= nowdate())
        )
    return query.run(as_dict=True)


def challenge_blocker_text(rows: list[dict]) -> str | None:
    """One sentence naming the charters whose challenge is outstanding."""
    if not rows:
        return None
    return _("the risk governance office has not cleared the charter challenge on {0}").format(
        ", ".join(
            "{0} ({1})".format(row["name"], row["rgo_challenge_status"] or CHALLENGE_NOT_REVIEWED)
            for row in rows
        )
    )


def reopen_challenge(charter, reason: str):
    """Put a charter back in front of the risk governance office.

    A challenge clears a *text*. When a new version replaces that text the old
    clearance no longer says anything about what the charter now says, so the
    challenge returns to not reviewed. The earlier outcome, who gave it and when
    stay in the charter's change log (the DocType tracks changes).
    """
    if isinstance(charter, str):
        charter = frappe.get_doc("Committee Charter", charter)
    charter.rgo_challenge_status = CHALLENGE_NOT_REVIEWED
    charter.rgo_challenge_comments = reason
    charter.rgo_reviewed_by = None
    charter.rgo_reviewed_on = None
    charter.save(ignore_permissions=True)
    return charter


# ------------------------------------------------------- portal entry points
#
# A new charter version could be taken only from a script (G-15), and the
# challenge could be recorded only on the desk (G-7). These are the doors the
# forum page's Documents tab uses. Each checks the framework's document
# permission first and then the role the action belongs to, and audits a
# refusal, so the screen cannot offer something the server will not accept.

#: The second line. The effective challenge is theirs and nobody else's: a
#: committee secretary may write a charter (the DocType grants it) but may not
#: clear their own charter's challenge.
CHALLENGE_ROLE = "Risk Governance Office"
SUPERUSER_ROLES = ("System Manager",)


def may_challenge(user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & ({CHALLENGE_ROLE} | set(SUPERUSER_ROLES)))


def challenge_options() -> list[dict]:
    """Each challenge outcome, and whether it must say what is to change.

    Read from the select options and the ``requires_statement`` flag, so the
    form cannot drift from the controller that enforces it.
    """
    from consilium.consilium_core import state_flags

    field = frappe.get_meta("Committee Charter").get_field("rgo_challenge_status")
    out = []
    for status in [option for option in (field.options or "").split("\n") if option]:
        flags = state_flags.flags_for("Committee Charter", "rgo_challenge_status", status) or {}
        out.append({
            "status": status,
            "requires_statement": bool(flags.get("requires_statement")),
            "clears": not flags.get("requires_review"),
        })
    return out


def _refuse(message: str, charter_name: str, control: str, exc=frappe.PermissionError):
    from consilium.consilium_core import audit

    audit.refuse(
        message,
        subject_doctype="Committee Charter",
        subject_name=charter_name,
        attempted_action="Other",
        control=control,
        exc=exc,
    )


def _load_for_write(charter: str):
    doc = frappe.get_doc("Committee Charter", charter)
    if not frappe.has_permission("Committee Charter", "write", doc=doc):
        _refuse(
            _("{0} may not change charter {1}.").format(frappe.session.user, doc.name),
            doc.name, "charter write permission",
        )
    if doc.forum and not frappe.db.get_value("Governance Forum", doc.forum, "is_active"):
        frappe.throw(
            _("Forum {0} is disbanded. Its charter is kept as it stood and is not revised.").format(doc.forum),
            title=_("Forum Inactive"),
        )
    return doc


def charter_view(doc, *, with_body: bool = True) -> dict:
    """One charter as the screen shows it: the record, its chain and its blockers."""
    versions = frappe.get_all(
        "Document Version",
        filters={"subject_doctype": "Committee Charter", "subject_name": doc.name},
        fields=["name", "version_number", "version_label", "origin", "is_current", "change_summary",
                "body_file", "owner", "creation"],
        order_by="version_number desc",
    )
    current_text = None
    if with_body and doc.current_version:
        current_text = frappe.db.get_value("Document Version", doc.current_version, "body_text")
    return {
        "name": doc.name,
        "charter_title": doc.charter_title,
        "forum": doc.forum,
        "formation_request": doc.formation_request,
        "rgo_challenge_status": doc.rgo_challenge_status,
        "rgo_challenge_comments": doc.rgo_challenge_comments,
        "rgo_reviewed_by": doc.rgo_reviewed_by,
        "rgo_reviewed_on": str(doc.rgo_reviewed_on) if doc.rgo_reviewed_on else None,
        "challenge_outstanding": bool(doc.requires_review),
        "effective_from": str(doc.effective_from) if doc.effective_from else None,
        "effective_to": str(doc.effective_to) if doc.effective_to else None,
        "next_charter_review_on": str(doc.next_charter_review_on) if doc.next_charter_review_on else None,
        "current_version": doc.current_version,
        "current_text": current_text,
        "versions": [{**row, "creation": str(row["creation"])} for row in versions],
        "blockers": clearance_blockers(doc),
        "can_publish": bool(frappe.has_permission("Committee Charter", "write", doc=doc)),
    }


@frappe.whitelist(methods=["GET"])
def get_forum_charters(forum: str) -> dict:
    """The forum page's Documents tab: the forum's charters and what the viewer may do.

    The version chain is read here rather than over the REST interface because
    ``Document Version`` is readable only by administrators and audit; anyone
    who may read the charter may read what it says.
    """
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    active = bool(frappe.db.get_value("Governance Forum", forum, "is_active"))
    if not frappe.has_permission("Committee Charter", "read"):
        return {"forum": forum, "readable": False, "charters": [], "forum_active": active,
                "can_start": False, "can_challenge": False, "challenge_options": []}
    names = frappe.get_list(
        "Committee Charter", filters={"forum": forum}, pluck="name", order_by="effective_from desc, creation desc",
    )
    charters = [charter_view(frappe.get_doc("Committee Charter", name)) for name in names]
    return {
        "forum": forum,
        "readable": True,
        "forum_active": active,
        "charters": charters,
        "can_start": active and bool(frappe.has_permission("Committee Charter", "create")),
        "can_challenge": active and may_challenge() and bool(frappe.has_permission("Committee Charter", "write")),
        "challenge_options": challenge_options(),
    }


@frappe.whitelist(methods=["POST"])
def start_forum_charter(forum: str, charter_title: str) -> dict:
    """Open a charter for a forum that has none, so a first version can be taken."""
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not frappe.has_permission("Committee Charter", "create"):
        from consilium.consilium_core import audit

        audit.refuse(
            _("{0} may not start a charter for forum {1}.").format(frappe.session.user, forum),
            subject_doctype="Governance Forum", subject_name=forum,
            attempted_action="Other", control="charter create permission",
        )
    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        frappe.throw(_("Forum {0} is disbanded.").format(forum), title=_("Forum Inactive"))
    if not (charter_title or "").strip():
        frappe.throw(_("A charter needs a title."), title=_("Title Required"))
    doc = frappe.get_doc(
        {"doctype": "Committee Charter", "charter_title": charter_title.strip(), "forum": forum}
    ).insert()
    return charter_view(doc)


@frappe.whitelist(methods=["POST"])
def publish_charter_version(charter: str, change_summary: str, body_text: str | None = None,
                            body_file: str | None = None, version_label: str | None = None,
                            challenge_status: str | None = None,
                            challenge_comments: str | None = None) -> dict:
    """Take a new charter version into the chain, from uploaded text or a file.

    A file arrives through the framework's own upload, attached to this charter;
    only a file attached to *this* charter is accepted, so a version cannot be
    made to point at somebody else's attachment.

    The new text reopens the challenge (see ``reopen_challenge``) unless the
    caller is the risk governance office and records its outcome on the text in
    the same step — the one case where the challenge demonstrably covers it.
    """
    doc = _load_for_write(charter)
    body_text = (body_text or "").strip() or None
    body_file = (body_file or "").strip() or None
    change_summary = (change_summary or "").strip()
    if not (body_text or body_file):
        frappe.throw(_("A version needs a body: upload a file or enter the text."), title=_("Body Required"))
    if not change_summary:
        frappe.throw(_("A version needs a change summary: it is the record of why the version exists."),
                     title=_("Summary Required"))
    if body_file and not frappe.db.exists(
        "File", {"file_url": body_file, "attached_to_doctype": "Committee Charter", "attached_to_name": doc.name}
    ):
        frappe.throw(_("{0} is not a file attached to charter {1}.").format(body_file, doc.name),
                     title=_("Unknown File"))
    if challenge_status and not may_challenge():
        _refuse(
            _("{0} may not record the charter challenge on {1}. It belongs to the {2}.").format(
                frappe.session.user, doc.name, CHALLENGE_ROLE),
            doc.name, "charter challenge role",
        )
    _check_challenge_outcome(challenge_status, challenge_comments)

    version = publish_version(
        doc, change_summary, body_file=body_file, body_text=body_text,
        version_label=(version_label or "").strip() or None,
    )
    doc.reload()
    if challenge_status:
        record_challenge(doc, challenge_status, comments=(challenge_comments or "").strip() or None)
    else:
        reopen_challenge(
            doc,
            _("Version {0} was published by {1}; the text has not yet been challenged.").format(
                version.version_number, frappe.session.user),
        )
    return charter_view(frappe.get_doc("Committee Charter", doc.name))


def _check_challenge_outcome(status: str | None, comments: str | None) -> None:
    if not status:
        return
    options = {row["status"]: row for row in challenge_options()}
    if status not in options:
        frappe.throw(_("{0} is not a challenge outcome.").format(status), title=_("Unknown Outcome"))
    if options[status]["requires_statement"] and not (comments or "").strip():
        frappe.throw(_("A challenge that requests changes says what changes."), title=_("Comments Required"))


@frappe.whitelist(methods=["POST"])
def record_charter_challenge(charter: str, status: str, comments: str | None = None) -> dict:
    """The risk governance office records its challenge outcome on a charter."""
    doc = _load_for_write(charter)
    if not may_challenge():
        _refuse(
            _("{0} may not record the charter challenge on {1}. It belongs to the {2}.").format(
                frappe.session.user, doc.name, CHALLENGE_ROLE),
            doc.name, "charter challenge role",
        )
    if not doc.current_version:
        frappe.throw(_("Charter {0} has no version to challenge yet.").format(doc.name),
                     title=_("Nothing To Challenge"))
    _check_challenge_outcome(status, comments)
    record_challenge(doc, status, comments=(comments or "").strip() or None)
    return charter_view(frappe.get_doc("Committee Charter", doc.name))
