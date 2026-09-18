"""Governing-document attestation campaigns, opened from the document (P-21, E17).

Core's attestation engine runs every campaign; this module only tells it who a
governing document's attesters are and gives the policy office a door onto it
from the document page.

**Who attests.** Everyone the document's applicability reaches today, minus the
formally exempt — ``applicability.affected_parties``, the same resolution that
decides who is told when the document is published, changed or retired. So a
campaign asks exactly the people the document was announced to, and nobody
keeps a second list. The engine derives the population when it generates tasks,
so regenerating after an applicability change picks up the people it adds.

The engine has two ways of finding people — a user field on the record, or a
dated seat table — and a document's audience is neither. It is registered
instead as the ``Document Audience`` resolver under the
``consilium_attestation_participants`` hook; the campaign stores that name,
never a code path.

**One campaign per document and period.** Core refuses two campaigns of one
type for one period, and every governing-document campaign shares a type, so
the period label carries the document's reference.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

DOCTYPE = "Governing Document"
CAMPAIGN_TYPE = "Governing Document"
RESOLVER = "Document Audience"
EVENT_OPENED = "policy.attestation.opened"
#: The campaign state that makes it open. A value handed to the flag map; the
#: engine reads ``is_open``.
STATUS_OPEN = "Open"


def period_prefix(document: str) -> str:
    return f"{document} · "


def audience_participants(campaign, record: str) -> list[dict]:
    """The registered resolver: the document's applicability audience."""
    from consilium.policy import applicability

    return [{"user": user, "seat_role": None} for user in applicability.affected_parties(record)]


def document_campaigns(document: str) -> list[dict]:
    """The campaigns raised for one document, with where their tasks stand."""
    from consilium.consilium_core import attestation

    # By the period label, which starts with the document's reference: the
    # population filter is a JSON column, which PostgreSQL will not compare
    # with LIKE.
    names = frappe.get_all(
        "Attestation Campaign",
        filters={"campaign_type": CAMPAIGN_TYPE, "target_doctype": DOCTYPE,
                 "period_label": ["like", f"{period_prefix(document)}%"]},
        pluck="name",
    )
    if not names:
        return []
    return attestation.campaign_board({"name": ["in", names]})


@frappe.whitelist(methods=["POST"])
def open_campaign(document: str, due_on: str, period_label: str | None = None) -> dict:
    """Open an attestation campaign for a document in force, and generate its tasks.

    Refused where the document is not in force (there is nothing to comply with
    yet, or any longer) and where its applicability reaches nobody — a campaign
    that asks no one proves nothing. Each person asked is told.
    """
    from consilium.consilium_core import attestation, notification
    from consilium.policy import applicability, lifecycle

    doc = lifecycle.load_for_portal(document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    lifecycle.authorise(doc, "open_attestation_campaign")
    if not due_on:
        frappe.throw(_("A campaign needs the date its attestations are due."), title=_("Due Date Required"))
    if getdate(due_on) < getdate(nowdate()):
        frappe.throw(_("A campaign cannot be due before it opens."), title=_("Dates Out Of Order"))
    if not applicability.affected_parties(doc.name):
        frappe.throw(
            _("{0}'s applicability reaches nobody, so there is no one to ask. Record where it applies first.").format(
                doc.name
            ),
            title=_("No Audience"),
        )
    period = (period_label or "").strip() or str(getdate(nowdate()).year)
    campaign = frappe.get_doc(
        {
            "doctype": "Attestation Campaign",
            "campaign_title": _("Attestation: {0}").format(doc.document_name)[:140],
            "campaign_type": CAMPAIGN_TYPE,
            "period_label": f"{period_prefix(doc.name)}{period}"[:140],
            "target_doctype": DOCTYPE,
            "population_filter": frappe.as_json({"name": doc.name}),
            "participant_source": attestation.REGISTERED_SOURCE,
            "participant_resolver": RESOLVER,
            "opens_on": nowdate(),
            "due_on": due_on,
            "status": STATUS_OPEN,
        }
    ).insert(ignore_permissions=True)
    result = attestation.generate_tasks(campaign)
    people = sorted({
        row for row in frappe.get_all("Attestation Task", filters={"name": ["in", result["created"] or [""]]},
                                      pluck="assigned_to")
    })
    notification.notify(
        EVENT_OPENED,
        people,
        {"campaign": campaign.name, "campaign_title": campaign.campaign_title, "due_on": str(due_on)},
        DOCTYPE,
        doc.name,
    )
    context = lifecycle.portal_context(frappe.get_doc(DOCTYPE, doc.name))
    context["campaign"] = {"name": campaign.name, "created": len(result["created"]), "population": result["population"]}
    return context


@frappe.whitelist(methods=["GET"])
def campaigns_for(document: str) -> list[dict]:
    """The document page's list of its campaigns. Readers of the document may see it."""
    from consilium.policy import lifecycle

    doc = lifecycle.load_for_portal(document)
    if not frappe.has_permission(DOCTYPE, "read", doc=doc):
        return []
    return document_campaigns(doc.name)
