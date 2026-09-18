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
    if campaign.participant_source == REGISTERED_SOURCE:
        return _registered_participants(campaign, record)
    return _record_field_participants(campaign, record)


#: A population a module resolves itself — everyone a governing document
#: applies to, say — which neither a record field nor a seat table expresses.
REGISTERED_SOURCE = "Registered Source"
PARTICIPANT_HOOK = "consilium_attestation_participants"


def registered_resolvers() -> dict[str, str]:
    """Resolver name -> dotted path, from the modules' hooks.

    The campaign stores only the *name*. The code path comes from hooks, which
    are code, so configuration can pick among resolvers but never name one —
    the same rule the notification adapters follow.
    """
    out: dict[str, str] = {}
    for name, paths in (frappe.get_hooks(PARTICIPANT_HOOK) or {}).items():
        if isinstance(paths, list | tuple):
            paths = paths[-1] if paths else None
        if paths:
            out[name] = paths
    return out


def _registered_participants(campaign, record: str) -> list[dict]:
    path = registered_resolvers().get(campaign.participant_resolver or "")
    if not path:
        frappe.throw(
            _("Campaign {0} names participant resolver {1}, which no installed module registers.").format(
                campaign.name, campaign.participant_resolver
            )
        )
    seen, out = set(), []
    for row in frappe.get_attr(path)(campaign, record) or []:
        user = row.get("user")
        if user and user not in seen:
            seen.add(user)
            out.append({"user": user, "seat_role": row.get("seat_role")})
    return out


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

    Returns ``{"created": [...], "skipped": [...], "unconfigured": [...], "population": n}``.

    ``skipped`` are records that already have an open task — regeneration is
    safe and does not duplicate. ``unconfigured`` are records the campaign
    cannot ask about yet, because a dual-signature campaign found no second
    signatory on them. They are reported rather than raised, so one record
    missing a field does not stop the whole population being asked.
    """
    if isinstance(campaign, str):
        campaign = frappe.get_doc("Attestation Campaign", campaign)

    if not campaign.is_open:
        frappe.throw(
            _("Campaign {0} is not open, so tasks cannot be generated.").format(campaign.name),
            title=_("Campaign Not Open"),
        )

    created, skipped, unconfigured = [], [], []
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
                # A second signatory who is the participant themselves is no
                # second signature at all, and the task would refuse to save —
                # which, raised here, stopped every other record being asked.
                if not second or second == participant["user"]:
                    # The record has no second signatory, so its task cannot be
                    # created. Skip it and report it rather than failing the
                    # campaign: an annual attestation covers the whole
                    # population, and one record missing a field should not stop
                    # everyone else from being asked. The gap is returned so it
                    # can be chased, and regenerating once it is filled in picks
                    # the record up.
                    unconfigured.append(record)
                    continue
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
    return {
        "created": created,
        "skipped": skipped,
        "unconfigured": sorted(set(unconfigured)),
        "population": len(records),
    }


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


# ---------------------------------------------------------------------------
# Portal endpoints — responding, counter-signing and running a campaign.
#
# Attesters used to answer by editing the task on the desk, which only
# administrators can open: the DocType grants nobody else a right over it, and
# rightly so, because the right to answer a task comes from being asked, not
# from a role. So these endpoints do not ask the permission engine. They ask
# the only question that matters — is the caller the person the task names, or
# someone that person has delegated attestation to — and refuse, with an audit
# record, anyone else.
# ---------------------------------------------------------------------------

#: The Delegable Action a delegate needs to answer someone else's task.
ATTEST_ACTION = "ATTEST"


def response_choices() -> list[dict]:
    """The statuses a participant may answer with, read from the flag map.

    An answer is a status that closes the task (``is_open`` clear) and leaves it
    in effect (``is_active`` set) — which is what separates an answer from a
    lapse. Deriving the list this way keeps it right when a status is renamed or
    a new kind of answer is configured; nothing here names one.
    """
    from consilium.consilium_core import state_flags

    field = frappe.get_meta("Attestation Task").get_field("status")
    choices = []
    for value in [option for option in (field.options or "").split("\n") if option]:
        flags = state_flags.flags_for("Attestation Task", "status", value) or {}
        if flags.get("is_open") or not flags.get("is_active"):
            continue
        choices.append(
            {
                "status": value,
                "requires_statement": bool(flags.get("requires_statement")),
                "requires_review": bool(flags.get("requires_review")),
            }
        )
    return choices


def acting_resolution(task, user: str | None = None) -> dict:
    """Whether ``user`` may answer ``task``: the assignee, or a live delegate.

    Core's delegation engine answers it, so a delegation's dates, its actions and
    its scope are judged the same way here as for an approval decision.
    """
    from consilium.consilium_core import delegation

    return delegation.resolve_actor(
        task.assigned_to,
        ATTEST_ACTION,
        acting_user=user or frappe.session.user,
        doctype=task.subject_doctype,
        name=task.subject_name,
    )


def task_summary(task) -> dict:
    """What the inbox shows of one task after it changes."""
    return {
        "name": task.name,
        "status": task.status,
        "is_open": int(task.is_open or 0),
        "responded_on": str(task.responded_on) if task.responded_on else None,
        "second_signatory": task.second_signatory,
        "second_signed_on": str(task.second_signed_on) if task.second_signed_on else None,
        "acting_delegation": task.acting_delegation,
    }


@frappe.whitelist(methods=["POST"])
def respond_to_task(task: str, status: str, statement: str | None = None) -> dict:
    """Answer an attestation task from the portal.

    Only the person the task names, or someone holding a live delegation of
    attestation from them covering the record, may answer. Anyone else is
    refused and the refusal is audited, as it is for an approval decision.
    """
    from consilium.consilium_core import audit

    doc = frappe.get_doc("Attestation Task", task)
    resolution = acting_resolution(doc)
    if not resolution["permitted"]:
        audit.refuse(
            _("{0} may not answer attestation task {1}: {2}").format(
                frappe.session.user, doc.name, resolution["reason"]
            ),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="attestation participant",
            context={"status": status},
        )
    if not doc.is_open:
        frappe.throw(
            _("Task {0} has already been answered or has lapsed, so it cannot be answered again.").format(doc.name),
            title=_("Task Closed"),
        )
    choices = {choice["status"]: choice for choice in response_choices()}
    if status not in choices:
        frappe.throw(_("{0} is not an answer a task accepts.").format(status), title=_("Unknown Answer"))
    statement = (statement or "").strip() or None
    if choices[status]["requires_statement"] and not statement:
        frappe.throw(
            _("This answer needs a written statement explaining it."), title=_("Statement Required")
        )
    respond(doc, status, statement=statement, acting_delegation=resolution["delegation"])
    return task_summary(doc)


@frappe.whitelist(methods=["POST"])
def second_sign_task(task: str) -> dict:
    """Counter-sign a dually-signed task. Only its named second signatory may.

    A second signature is personal by design — it is the check on the first —
    so no delegation is honoured here, matching the engine's own rule.
    """
    from consilium.consilium_core import audit

    doc = frappe.get_doc("Attestation Task", task)
    if not doc.second_signatory or doc.second_signatory != frappe.session.user:
        audit.refuse(
            _("{0} is not the second signatory of attestation task {1}.").format(frappe.session.user, doc.name),
            subject_doctype=doc.doctype,
            subject_name=doc.name,
            attempted_action="Other",
            control="attestation second signatory",
        )
    if doc.second_signed_on:
        frappe.throw(_("Task {0} is already counter-signed.").format(doc.name), title=_("Already Signed"))
    if not doc.is_open and not doc.responded_on:
        # Closed without an answer: the task lapsed, and there is nothing to
        # counter-sign. A fact on the task, not its status label.
        frappe.throw(_("Task {0} lapsed without an answer, so there is nothing to counter-sign.").format(doc.name),
                     title=_("Task Lapsed"))
    second_sign(doc, frappe.session.user)
    return task_summary(doc)


def may_administer_campaigns(user: str | None = None) -> bool:
    """Running any campaign is an administrator's right over the campaign record.

    A module may widen this for its own campaigns — the governance office runs
    the forum campaigns — but does so in its own module, where the role belongs.
    """
    return bool(frappe.has_permission("Attestation Campaign", "write", user=user or frappe.session.user))


def _subject_label(doctype: str, name: str) -> str:
    title_field = frappe.get_meta(doctype).get_title_field()
    if title_field and title_field != "name":
        return frappe.db.get_value(doctype, name, title_field) or name
    return name


def unconfigured_detail(campaign, names: list[str]) -> list[dict]:
    """The records a campaign could not ask about, named so they can be chased."""
    return [{"name": name, "label": _subject_label(campaign.target_doctype, name)} for name in names]


def campaign_board(filters: dict | None = None) -> list[dict]:
    """Each campaign with where its tasks stand. Counts read flags and dates.

    The status counts are returned by label for display only; the figures that
    drive anything (open, overdue, answered, awaiting a second signature) are
    read from the ``is_open`` flag and from facts on the task. A task carries no
    ``is_active`` field, so an answer is told from a lapse by ``responded_on``:
    the expiry sweep closes a task without ever setting it.
    """
    today = frappe.utils.getdate(nowdate())
    out = []
    for campaign in frappe.get_all(
        "Attestation Campaign",
        filters=filters or {},
        fields=["name", "campaign_title", "campaign_type", "period_label", "target_doctype", "status",
                "is_open", "opens_on", "due_on", "generated_on", "requires_dual_signature"],
        order_by="opens_on desc, creation desc",
    ):
        tasks = frappe.get_all(
            "Attestation Task",
            filters={"campaign": campaign["name"]},
            fields=["status", "is_open", "due_on", "responded_on", "second_signatory", "second_signed_on"],
        )
        by_status: dict[str, int] = {}
        for row in tasks:
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        campaign.update(
            {
                "tasks": len(tasks),
                "open": sum(1 for row in tasks if row["is_open"]),
                "overdue": sum(
                    1 for row in tasks if row["is_open"] and row["due_on"] and frappe.utils.getdate(row["due_on"]) < today
                ),
                "answered": sum(1 for row in tasks if not row["is_open"] and row["responded_on"]),
                "lapsed": sum(1 for row in tasks if not row["is_open"] and not row["responded_on"]),
                "awaiting_second_signature": sum(
                    1 for row in tasks
                    if row["second_signatory"] and row["responded_on"] and not row["is_open"]
                    and not row["second_signed_on"]
                ),
                "by_status": by_status,
            }
        )
        for key in ("opens_on", "due_on", "generated_on"):
            campaign[key] = str(campaign[key]) if campaign[key] else None
        out.append(campaign)
    return out


@frappe.whitelist(methods=["GET"])
def campaign_overview() -> dict:
    """Every campaign, for those who may read campaigns (administrators and audit)."""
    if not frappe.has_permission("Attestation Campaign", "read"):
        frappe.throw(_("Attestation campaigns are not open to you."), frappe.PermissionError)
    return {"campaigns": campaign_board(), "may_generate": may_administer_campaigns()}


def generate_and_report(campaign) -> dict:
    """Generate a campaign's tasks and name the records it could not ask about."""
    if isinstance(campaign, str):
        campaign = frappe.get_doc("Attestation Campaign", campaign)
    result = generate_tasks(campaign)
    return {
        "campaign": campaign.name,
        "target_doctype": campaign.target_doctype,
        "created": len(result["created"]),
        "skipped": len(result["skipped"]),
        "population": result["population"],
        "unconfigured": unconfigured_detail(campaign, result["unconfigured"]),
    }


@frappe.whitelist(methods=["POST"])
def generate_campaign_tasks(campaign: str) -> dict:
    """Materialise an open campaign's tasks from the portal. Safe to repeat."""
    doc = frappe.get_doc("Attestation Campaign", campaign)
    if not may_administer_campaigns():
        frappe.throw(_("Only an administrator may generate this campaign's tasks."), frappe.PermissionError)
    return generate_and_report(doc)
