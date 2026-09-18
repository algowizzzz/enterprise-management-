"""Where a document applies, and who therefore has to be told.

E11-S5 is the requirement that shapes this module: *notification derives from
applicability rather than a manual list*. There is no recipient table anywhere in
the Policy module. Every notification of a publication, a change or a retirement
resolves its audience by reading the document's applicability rows at the moment
it is sent, and by subtracting anyone an authorised exemption covers.

Sending is Core's job. This module decides *who*; ``consilium_core.notification``
decides *how*, and records that it happened.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate

from consilium.consilium_core import notification

DOCTYPE = "Governing Document"

#: A scope type is spelled as the DocType it names, so the Select on the row is
#: also the Dynamic Link's DocType pointer and the framework validates the
#: reference for us. ``Function`` names no DocType: it is a business function
#: with no row of its own, and it carries a label instead.
SCOPE_WITHOUT_RECORD = ("Function",)
ROLE_SCOPE = "Role"

#: The channel every Policy notification goes through. Configuration, not code:
#: a deployment points this channel at email, chat or a digest without a change
#: here, and the dispatch row is the evidence either way.
CHANNEL = "RECORD"


def scope_doctype_for(scope_type: str | None) -> str | None:
    """The DocType a scope type names, or None where it names no record."""
    if not scope_type or scope_type in SCOPE_WITHOUT_RECORD:
        return None
    return scope_type


def _in_force(row, on_date) -> bool:
    if row.get("applies_from") and getdate(row["applies_from"]) > on_date:
        return False
    if row.get("applies_to") and getdate(row["applies_to"]) < on_date:
        return False
    return True


def applicable_scopes(document: str, on_date=None) -> list[dict]:
    """The document's applicability rows that are in force on a date."""
    on_date = getdate(on_date or nowdate())
    rows = frappe.get_all(
        "Document Applicability",
        filters={"parent": document, "parenttype": DOCTYPE},
        fields=[
            "name", "scope_type", "scope_value", "scope_label",
            "applies_from", "applies_to", "notification_group",
        ],
        order_by="idx asc",
    )
    return [row for row in rows if _in_force(row, on_date)]


def active_exemptions(document: str, on_date=None) -> list[dict]:
    """Exemptions in force on a date.

    ``is_active`` is the semantic flag the exemption's status sets; only an
    authorised exemption carries it. The dates narrow it further.
    """
    on_date = getdate(on_date or nowdate())
    rows = frappe.get_all(
        "Applicability Exemption",
        filters={"document": document, "is_active": 1, "docstatus": ["<", 2]},
        fields=["name", "scope_type", "scope_value", "scope_label",
                "valid_from", "valid_to", "exemption_type"],
    )
    out = []
    for row in rows:
        if row.get("valid_from") and getdate(row["valid_from"]) > on_date:
            continue
        if row.get("valid_to") and getdate(row["valid_to"]) < on_date:
            continue
        out.append(row)
    return out


def _scope_key(row) -> tuple:
    return (row.get("scope_type"), row.get("scope_value") or row.get("scope_label"))


def _users_in_group(user_group: str) -> set[str]:
    return set(
        frappe.get_all(
            "User Group Member",
            filters={"parent": user_group, "parenttype": "User Group"},
            pluck="user",
        )
    )


def _users_with_role(role: str) -> set[str]:
    return set(
        frappe.get_all(
            "Has Role",
            filters={"parenttype": "User", "role": role},
            pluck="parent",
        )
    )


def affected_parties(document: str, on_date=None) -> list[str]:
    """Every user an in-force applicability row reaches, minus the exempt.

    A scope reaches users two ways: through the notification group named on the
    row, and — for a Role scope — through the holders of that role. Nothing else
    in the model connects a person to a business unit or a jurisdiction, so a
    scope of that kind reaches people only through its notification group. That
    is stated rather than silently dropped: a business-unit scope with no group
    named notifies nobody, and the maintenance view lists it as incomplete.
    """
    exempt_scopes = {_scope_key(row) for row in active_exemptions(document, on_date)}

    recipients: set[str] = set()
    for row in applicable_scopes(document, on_date):
        if _scope_key(row) in exempt_scopes:
            continue
        if row.get("notification_group"):
            recipients |= _users_in_group(row["notification_group"])
        if row.get("scope_type") == ROLE_SCOPE and row.get("scope_value"):
            recipients |= _users_with_role(row["scope_value"])

    recipients.discard("Administrator")
    recipients.discard("Guest")
    enabled = set(
        frappe.get_all("User", filters={"name": ["in", list(recipients)], "enabled": 1}, pluck="name")
    ) if recipients else set()
    return sorted(enabled)


def scopes_without_recipients(document: str) -> list[dict]:
    """Applicability rows that would notify nobody. Feeds the maintenance view."""
    out = []
    for row in applicable_scopes(document):
        if row.get("notification_group"):
            continue
        if row.get("scope_type") == ROLE_SCOPE and row.get("scope_value"):
            continue
        out.append(row)
    return out


def notify_affected(document: str, event: str, *, detail: str | None = None) -> list[str]:
    """Notify everyone applicability reaches. Returns the dispatch row names.

    ``event`` is a plain description — published, changed, retired — used in the
    message. It is not a workflow state and nothing branches on it.
    """
    recipients = affected_parties(document)
    if not recipients:
        return []
    # Raised as ``policy.document.audience``: the wording is the template's, and
    # the template reads the document itself (``doc``) for its name.
    return notification.notify(
        "policy.document.audience", recipients, {"event": event, "detail": detail or ""},
        subject_doctype=DOCTYPE, subject_name=document,
    )


@frappe.whitelist()
def preview_audience(document: str) -> dict:
    """Who would be notified, and which scopes reach nobody. Visible before sending."""
    frappe.has_permission(DOCTYPE, "read", doc=document, throw=True)
    return {
        "document": document,
        "recipients": affected_parties(document),
        "exemptions": [row["name"] for row in active_exemptions(document)],
        "scopes_without_recipients": [row["name"] for row in scopes_without_recipients(document)],
    }
