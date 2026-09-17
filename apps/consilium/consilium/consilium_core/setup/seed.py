"""Reference data Core ships with.

Everything here is generic vocabulary from the model documents. Seeds are
idempotent: a value an administrator has edited is left alone, and a value that
has been deactivated is not resurrected.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import state_flags
from consilium.consilium_core.setup.state_flag_seed import FLAG_COLUMNS, STATE_FLAGS

FORUM_ROLES = [
    # code, title, quorum, votes, attests, chair, secretary, owner
    ("CHAIR", "Chair", 1, 1, 1, 1, 0, 0),
    ("SECRETARY", "Secretary", 1, 1, 1, 0, 1, 0),
    ("FORUM_OWNER", "Forum Owner", 1, 1, 1, 0, 0, 1),
    ("SPONSOR", "Sponsor", 0, 0, 0, 0, 0, 0),
    ("VOTING_MEMBER", "Voting Member", 1, 1, 0, 0, 0, 0),
    ("NON_VOTING_MEMBER", "Non-Voting Member", 1, 0, 0, 0, 0, 0),
    ("OBSERVER", "Observer", 0, 0, 0, 0, 0, 0),
    ("RISK_OWNER", "Risk Owner", 1, 1, 0, 0, 0, 0),
    ("ESCALATOR", "Escalator", 0, 0, 0, 0, 0, 0),
    ("APPROVER", "Approver", 1, 1, 0, 0, 0, 0),
]

DELEGABLE_ACTIONS = [
    ("APPROVE", "Approve", 1),
    ("REVIEW", "Review", 1),
    ("ATTEST", "Attest", 0),
    ("SUBMIT", "Submit", 1),
    ("EDIT", "Edit", 1),
    ("ACKNOWLEDGE", "Acknowledge", 1),
]

DOCUMENT_ROLES = [
    # code, title, accountable, can_attest, optional
    ("DOC_OWNER", "Document Owner", 1, 1, 0),
    ("DOC_APPROVER", "Document Approver", 1, 0, 0),
    ("DOC_LIAISON", "Document Liaison", 0, 0, 0),
    ("DOC_DELEGATE", "Document Delegate", 0, 0, 1),
    ("DOC_SPONSOR", "Document Sponsor", 1, 0, 0),
    ("KEY_CONTACT", "Key Contact", 0, 0, 0),
    ("MONITOR", "Monitor", 0, 0, 0),
    ("PARTNER", "Partner", 0, 0, 0),
]

LINES_OF_DEFENCE = [
    ("1LOD", "First Line of Defence", 1),
    ("2LOD", "Second Line of Defence", 2),
    ("3LOD", "Third Line of Defence", 3),
]

GOVERNANCE_RESPONSIBILITIES = [
    ("OVERSIGHT", "Oversight"),
    ("DECISION_MAKING", "Decision Making"),
    ("OVERSIGHT_AND_DECISION", "Oversight and Decision Making"),
]


def _ensure(doctype: str, name: str, values: dict) -> None:
    if frappe.db.exists(doctype, name):
        return
    frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def seed_taxonomies() -> None:
    for code, title, quorum, votes, attests, chair, secretary, owner in FORUM_ROLES:
        _ensure(
            "Governance Forum Role",
            code,
            {
                "governance_forum_role_code": code,
                "governance_forum_role_name": title,
                "counts_toward_quorum": quorum,
                "votes_by_default": votes,
                "can_attest": attests,
                "is_chair_role": chair,
                "is_secretary_role": secretary,
                "is_owner_role": owner,
                "max_holders": 1 if chair or secretary or owner else 0,
            },
        )
    for code, title, administrative in DELEGABLE_ACTIONS:
        _ensure(
            "Delegable Action",
            code,
            {"delegable_action_code": code, "delegable_action_name": title, "is_administrative": administrative},
        )
    for code, title, accountable, attests, optional in DOCUMENT_ROLES:
        _ensure(
            "Document Role",
            code,
            {
                "document_role_code": code,
                "document_role_name": title,
                "is_accountable": accountable,
                "can_attest": attests,
                "is_optional": optional,
            },
        )
    for code, title, number in LINES_OF_DEFENCE:
        _ensure(
            "Line Of Defence",
            code,
            {"line_of_defence_code": code, "line_of_defence_name": title, "line_number": number},
        )
    for code, title in GOVERNANCE_RESPONSIBILITIES:
        _ensure(
            "Governance Responsibility",
            code,
            {"governance_responsibility_code": code, "governance_responsibility_name": title},
        )


def seed_notification_channels() -> None:
    _ensure(
        "Notification Channel",
        "RECORD",
        {
            "channel_code": "RECORD",
            "title": "Recorded Only",
            "channel_type": "In App",
            "adapter": "record_only",
            "is_active": 1,
        },
    )


def seed_state_flags() -> None:
    """Load the semantic flag map. Rows an administrator has edited are left alone."""
    for row in STATE_FLAGS:
        doctype, state_field, state_value = row[0], row[1], row[2]
        if not frappe.db.exists("DocType", doctype):
            continue
        existing = frappe.db.get_value(
            "Workflow State Flag",
            {"target_doctype": doctype, "state_field": state_field, "state_value": state_value},
            "name",
        )
        if existing:
            continue
        values = dict(zip(FLAG_COLUMNS, row[3:], strict=True))
        frappe.get_doc(
            {
                "doctype": "Workflow State Flag",
                "target_doctype": doctype,
                "state_field": state_field,
                "state_value": state_value,
                **values,
            }
        ).insert(ignore_permissions=True)
    state_flags.clear_cache()


def seed_all() -> None:
    seed_taxonomies()
    seed_notification_channels()
    seed_state_flags()
