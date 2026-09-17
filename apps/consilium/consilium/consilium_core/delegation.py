"""Authority delegation.

A delegation transfers named actions from an accountable person to another for a
bounded period. It deliberately grants **no** framework permission: it is
evaluated here, at the point of action, and recorded on the artefact the action
produced — an approval decision or an attestation task. A delegation that were a
permission grant would be invisible to audit, which is the opposite of what is
asked for.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, nowdate


#: The seeded Delegable Action codes. Named here so callers do not spell them out.
ACTION_APPROVE = "APPROVE"
ACTION_REVIEW = "REVIEW"
ACTION_ATTEST = "ATTEST"
ACTION_SUBMIT = "SUBMIT"
ACTION_EDIT = "EDIT"
ACTION_ACKNOWLEDGE = "ACKNOWLEDGE"


def is_within_dates(delegation, on_date=None) -> bool:
    on_date = getdate(on_date or nowdate())
    if delegation.valid_from and getdate(delegation.valid_from) > on_date:
        return False
    if delegation.valid_to and getdate(delegation.valid_to) < on_date:
        return False
    return True


def refresh_active_flag(delegation) -> None:
    delegation.is_active = 1 if is_within_dates(delegation) else 0


def refresh_all() -> int:
    """Daily sweep. The flag is stored so that queries do not compute dates."""
    changed = 0
    for name in frappe.get_all("Authority Delegation", pluck="name"):
        doc = frappe.get_doc("Authority Delegation", name)
        wanted = 1 if is_within_dates(doc) else 0
        if int(doc.is_active or 0) != wanted:
            doc.db_set("is_active", wanted)
            changed += 1
    return changed


def _covers_scope(delegation, doctype: str | None, name: str | None) -> bool:
    if delegation.scope_type == "All":
        return True
    if delegation.scope_type == "DocType":
        return delegation.scope_doctype == doctype
    # Record and Forum scopes both name one record.
    return delegation.scope_doctype == doctype and delegation.scope_record == name


def find_delegations(
    delegator: str,
    action: str,
    *,
    doctype: str | None = None,
    name: str | None = None,
    delegate: str | None = None,
    on_date=None,
) -> list[str]:
    """Delegations of ``action`` from ``delegator`` that cover a record, today."""
    filters = {"delegator": delegator, "is_active": 1}
    if delegate:
        filters["delegate"] = delegate
    out = []
    for candidate in frappe.get_all("Authority Delegation", filters=filters, pluck="name"):
        doc = frappe.get_doc("Authority Delegation", candidate)
        if not is_within_dates(doc, on_date):
            continue
        if action not in [row.delegable_action for row in doc.delegated_actions]:
            continue
        if not _covers_scope(doc, doctype, name):
            continue
        out.append(doc.name)
    return out


def resolve_actor(
    accountable_user: str,
    action: str,
    *,
    acting_user: str | None = None,
    doctype: str | None = None,
    name: str | None = None,
) -> dict:
    """Who may act, and under which delegation.

    Returns ``{"permitted": bool, "delegation": str|None, "reason": str}``. The
    accountable person always acts for themselves; anyone else needs a live
    delegation naming the action and covering the record.
    """
    acting_user = acting_user or frappe.session.user
    if acting_user == accountable_user:
        return {"permitted": True, "delegation": None, "reason": "acting for themselves"}

    delegations = find_delegations(
        accountable_user, action, doctype=doctype, name=name, delegate=acting_user
    )
    if delegations:
        return {
            "permitted": True,
            "delegation": delegations[0],
            "reason": f"acting under delegation {delegations[0]}",
        }
    return {
        "permitted": False,
        "delegation": None,
        "reason": _("{0} holds no live delegation of {1} from {2}.").format(acting_user, action, accountable_user),
    }
