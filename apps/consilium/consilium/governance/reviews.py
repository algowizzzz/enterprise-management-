"""The annual reviews a forum is subject to, run on Core's attestation engine.

Two of Core's three attestation events land on forums, and neither is built
again here:

* **Forum inventory attestation** (G-10) — annual, first quarter, to the chairs,
  secretaries and forum owners. Participants are drawn from seat roles flagged
  ``can_attest``, which is why that flag is a taxonomy field and not a constant.
* **Forum owner and compliance review** — annual, dually signed. The owner
  responds; the named compliance contact counter-signs. A review with only one
  signature is not a completed review, and recording one is refused.

What this module adds is the governance-specific part: the campaign
configuration, the completion rule, and the overdue query that makes an
incomplete review visible as an exception.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_years, getdate, nowdate

from consilium.consilium_core import attestation
from consilium.governance import lifecycle

INVENTORY_CAMPAIGN = "Forum Inventory"
DUAL_CAMPAIGN = "Forum Owner And Compliance"


def _active_forum_filter() -> dict:
    """The population: forums that are live. Read from the semantic flag."""
    return {"is_active": 1}


def open_inventory_attestation(period_label: str, *, opens_on=None, due_on=None, population_filter=None):
    """The G-10 annual inventory attestation, to every attesting seat."""
    campaign = frappe.get_doc(
        {
            "doctype": "Attestation Campaign",
            "campaign_title": _("Forum inventory attestation {0}").format(period_label),
            "campaign_type": INVENTORY_CAMPAIGN,
            "period_label": period_label,
            "target_doctype": "Governance Forum",
            "population_filter": frappe.as_json(population_filter or _active_forum_filter()),
            "participant_source": "Seat Role",
            "seat_doctype": "Forum Membership",
            "seat_subject_field": "forum",
            "seat_user_field": "member",
            "seat_role_field": "forum_role",
            "seat_end_date_field": "end_date",
            "opens_on": getdate(opens_on or nowdate()),
            "due_on": getdate(due_on or add_years(getdate(nowdate()), 1)),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)
    return campaign


def open_annual_review(period_label: str, *, opens_on=None, due_on=None, population_filter=None):
    """The dually-signed owner and compliance review."""
    campaign = frappe.get_doc(
        {
            "doctype": "Attestation Campaign",
            "campaign_title": _("Forum owner and compliance review {0}").format(period_label),
            "campaign_type": DUAL_CAMPAIGN,
            "period_label": period_label,
            "target_doctype": "Governance Forum",
            "population_filter": frappe.as_json(population_filter or _active_forum_filter()),
            "participant_source": "Record Field",
            "participant_field": "forum_owner",
            "second_signatory_field": "compliance_contact",
            "requires_dual_signature": 1,
            "opens_on": getdate(opens_on or nowdate()),
            "due_on": getdate(due_on or add_years(getdate(nowdate()), 1)),
            "status": "Open",
        }
    ).insert(ignore_permissions=True)
    return campaign


def generate(campaign) -> dict:
    """Materialise the tasks. Core's engine; safe to run twice."""
    return attestation.generate_tasks(campaign)


def dual_signature_complete(task) -> bool:
    """Both halves present: the owner responded and the compliance contact signed."""
    if isinstance(task, str):
        task = frappe.get_doc("Attestation Task", task)
    return bool(task.responded_on) and bool(task.second_signed_on)


def record_annual_review(task, decision: str, *, comments: str | None = None):
    """Turn a completed dual-signed task into the forum's annual compliance review.

    Refused while either signature is missing: an annual review needs the owner
    **and** compliance, and half of one is not a review.
    """
    if isinstance(task, str):
        task = frappe.get_doc("Attestation Task", task)
    if not dual_signature_complete(task):
        frappe.throw(
            _(
                "Attestation task {0} is not dually signed. The annual review needs both the forum "
                "owner's response and the compliance counter-signature."
            ).format(task.name),
            title=_("Annual Review Incomplete"),
        )
    return lifecycle.record_review(
        task.subject_name,
        decision,
        review_type="Annual",
        comments=comments,
        attestation_task=task.name,
    )


def overdue_reviews(as_of=None) -> list[dict]:
    """Forums whose annual review is late, and dual tasks still missing a signature.

    This is the exception list E8-S4 asks to be visible. It reads dates and
    semantic flags; it does not read a status label.
    """
    as_of = getdate(as_of or nowdate())
    exceptions = []
    for row in frappe.get_all(
        "Governance Forum",
        filters={"is_active": 1, "next_review_on": ["<", as_of]},
        fields=["name", "forum_name", "next_review_on", "forum_owner"],
    ):
        exceptions.append({"forum": row["name"], "reason": "review_overdue", "due_on": str(row["next_review_on"])})

    for task in frappe.get_all(
        "Attestation Task",
        filters={"subject_doctype": "Governance Forum", "due_on": ["<", as_of]},
        fields=["name", "subject_name", "due_on", "is_open", "responded_on", "second_signed_on",
                "second_signatory"],
    ):
        if task["is_open"]:
            exceptions.append({"forum": task["subject_name"], "reason": "attestation_open",
                               "task": task["name"], "due_on": str(task["due_on"])})
        elif task["second_signatory"] and not task["second_signed_on"]:
            exceptions.append({"forum": task["subject_name"], "reason": "second_signature_missing",
                               "task": task["name"], "due_on": str(task["due_on"])})
    return exceptions
