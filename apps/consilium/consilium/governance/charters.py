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
from frappe.utils import now

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
