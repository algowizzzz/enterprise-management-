"""The attestation engine — one engine, three campaign types.

The three events the platform has to run are a forum inventory attestation, a
governing document attestation, and a dually-signed forum owner and compliance
review. They differ in who attests what, not in how attestation works, so there
is one engine and the differences are configuration on the campaign.

Two properties matter and are tested:

* **The population is derived from live data**, not from a stored list. The
  campaign stores the *filter*, so the derivation is reproducible; it does not
  store the names, so a record added after the campaign opened is picked up.
* **Regeneration is safe.** Generating twice does not duplicate an open task.
  Uniqueness is (campaign, participant, record), enforced in the application and
  backed by a partial unique index.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now, nowdate


def _loads(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


def population(campaign) -> list[str]:
    """The records in scope, resolved against live data at call time."""
    return frappe.get_all(
        campaign.target_doctype,
        filters=_loads(campaign.population_filter),
        pluck="name",
        order_by="name asc",
    )


def _attesting_seat_roles() -> list[str]:
    return frappe.get_all(
        "Governance Forum Role", filters={"can_attest": 1, "is_active": 1}, pluck="name"
    )


def participants_for(campaign, record: str) -> list[dict]:
    """Who must attest one record: ``[{user, seat_role}]``, from live data."""
    if campaign.participant_source == "Seat Role":
        return _seat_participants(campaign, record)
    return _record_field_participants(campaign, record)


def _record_field_participants(campaign, record: str) -> list[dict]:
    if not campaign.participant_field:
        frappe.throw(_("Campaign {0} needs a participant field.").format(campaign.name))
    user = frappe.db.get_value(campaign.target_doctype, record, campaign.participant_field)
    return [{"user": user, "seat_role": None}] if user else []


def seat_query(campaign, record: str) -> dict:
    """The filter that draws attesting seats. Separated out so it can be tested
    without a forum module being present.

    The open-seat condition is deliberately **not** here — see `_open_seat_names`.
    """
    filters = {campaign.seat_subject_field: record}
    if campaign.seat_role_field:
        roles = _attesting_seat_roles()
        filters[campaign.seat_role_field] = ["in", roles or [""]]
    return filters


def _open_seat_names(campaign, record: str) -> list[str] | None:
    """Names of seats that are still open, or None when the campaign has no end-date field.

    An open seat is one whose end date is NULL, and asking for that through the
    ordinary filter syntax does not work on PostgreSQL. Every spelling the query
    builder offers — ``["in", [None, ""]]``, ``["is", "not set"]`` — renders as a
    comparison against an empty string, and PostgreSQL refuses to compare a date
    to ``''`` where MySQL would quietly coerce it. The query fails outright with
    `invalid input syntax for type date`.

    So the condition is expressed as SQL directly. This is one of the places
    where the framework's PostgreSQL support diverges from its MySQL behaviour,
    and it will not be the last: anywhere a Date or Datetime column is tested for
    emptiness through filters, expect the same failure.
    """
    if not campaign.seat_end_date_field:
        return None
    table = f'tab{campaign.seat_doctype}'
    return frappe.db.sql_list(
        f'select name from "{table}" where "{campaign.seat_subject_field}" = %s '
        f'and "{campaign.seat_end_date_field}" is null',
        record,
    )


def _seat_participants(campaign, record: str) -> list[dict]:
    for fieldname in ("seat_doctype", "seat_subject_field", "seat_user_field"):
        if not campaign.get(fieldname):
            frappe.throw(_("Campaign {0} needs {1} for a seat-role population.").format(campaign.name, fieldname))
    fields = [campaign.seat_user_field]
    if campaign.seat_role_field:
        fields.append(campaign.seat_role_field)
    filters = seat_query(campaign, record)
    open_seats = _open_seat_names(campaign, record)
    if open_seats is not None:
        if not open_seats:
            return []
        filters["name"] = ["in", open_seats]
    rows = frappe.get_all(campaign.seat_doctype, filters=filters, fields=fields)
    seen, out = set(), []
    for row in rows:
        user = row.get(campaign.seat_user_field)
        role = row.get(campaign.seat_role_field) if campaign.seat_role_field else None
        if user and (user, role) not in seen:
            seen.add((user, role))
            out.append({"user": user, "seat_role": role})
    return out


def _existing_open_task(campaign_name: str, user: str, subject_doctype: str, subject_name: str) -> str | None:
    return frappe.db.get_value(
        "Attestation Task",
        {
            "campaign": campaign_name,
            "assigned_to": user,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
        },
        "name",
    )


def generate_tasks(campaign) -> dict:
    """Materialise tasks for a campaign. Safe to run repeatedly.

    Returns ``{"created": [...], "skipped": [...], "population": n}``.
    """
    if isinstance(campaign, str):
        campaign = frappe.get_doc("Attestation Campaign", campaign)

    if not campaign.is_open:
        frappe.throw(
            _("Campaign {0} is not open, so tasks cannot be generated.").format(campaign.name),
            title=_("Campaign Not Open"),
        )

    created, skipped = [], []
    records = population(campaign)
    for record in records:
        for participant in participants_for(campaign, record):
            existing = _existing_open_task(
                campaign.name, participant["user"], campaign.target_doctype, record
            )
            if existing:
                skipped.append(existing)
                continue
            second = None
            if campaign.requires_dual_signature and campaign.second_signatory_field:
                second = frappe.db.get_value(
                    campaign.target_doctype, record, campaign.second_signatory_field
                )
            task = frappe.get_doc(
                {
                    "doctype": "Attestation Task",
                    "campaign": campaign.name,
                    "subject_doctype": campaign.target_doctype,
                    "subject_name": record,
                    "assigned_to": participant["user"],
                    "assigned_role": participant["seat_role"],
                    "second_signatory": second,
                    "due_on": campaign.due_on,
                    "status": "Pending",
                }
            ).insert(ignore_permissions=True)
            created.append(task.name)

    campaign.db_set("generated_on", now())
    return {"created": created, "skipped": skipped, "population": len(records)}


def respond(
    task,
    status: str,
    *,
    statement: str | None = None,
    acting_delegation: str | None = None,
    items: list[dict] | None = None,
):
    """Record a participant's response. Validation lives on the task controller."""
    if isinstance(task, str):
        task = frappe.get_doc("Attestation Task", task)
    task.status = status
    task.response_statement = statement
    task.responded_on = now()
    task.acting_delegation = acting_delegation
    if items is not None:
        task.set("items", [])
        for item in items:
            task.append("items", item)
    task.save(ignore_permissions=True)
    return task


def second_sign(task, user: str | None = None):
    if isinstance(task, str):
        task = frappe.get_doc("Attestation Task", task)
    user = user or frappe.session.user
    if not task.second_signatory:
        frappe.throw(_("Task {0} carries no second signatory.").format(task.name))
    if task.second_signatory != user:
        frappe.throw(_("Only the named second signatory may sign task {0}.").format(task.name))
    if task.is_open:
        frappe.throw(_("The first signatory has not yet responded to task {0}.").format(task.name))
    task.second_signed_on = now()
    task.save(ignore_permissions=True)
    return task


def expire_overdue(campaign: str | None = None) -> list[str]:
    """Daily sweep: expire open tasks past their due date."""
    filters = {"is_open": 1, "due_on": ["<", nowdate()]}
    if campaign:
        filters["campaign"] = campaign
    expired = []
    for name in frappe.get_all("Attestation Task", filters=filters, pluck="name"):
        task = frappe.get_doc("Attestation Task", name)
        task.status = "Expired"
        task.save(ignore_permissions=True)
        expired.append(name)
    return expired
