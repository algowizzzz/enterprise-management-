"""Scheduled reminders and service-level warnings.

Registered in hooks.py on the daily and hourly schedules.

Daily, each obligation that has a date is looked at and the person who owes it
is told — before it is due, when it is overdue, and, when it stays overdue, the
person above them:

======================================  ===============================  ==================================
What                                    Told                             Escalated to
======================================  ===============================  ==================================
Document review (P-10)                  document owner                   document approver
Document review cycle (P-10)            reviewer and document owner      document approver
Monitoring activity (P-11)              person responsible               owner of the monitored document
Risk acceptance reassessment (E-9)      accountable executive            —
Risk acceptance end date (E-9)          accountable executive            —
Periodic return (E-11)                  the return's owner               —
Forum annual review and attestation     forum owner, assignee,           —
                                        second signatory
Action plan end date                    plan owner                       accountable executive (overdue)
Attestation task, on the campaign's     person asked, then the           —
reminder schedule                       second signatory
======================================  ===============================  ==================================

Hourly, the service-level clocks are brought up to date and swept (warnings
and breaches, P-7, E-13).

**Never twice.** Every reminder sent is written to ``Reminder Log`` under a
unique key of event, record, recipient, due date and day. A "due soon" notice
is sent once per due date; an overdue notice at most once every
``REPEAT_OVERDUE_DAYS``. Running the job twice in a day — two schedulers, a
manual run, a retry — sends nothing the second time, and the unique key holds
even when two runs race.

**Nothing branches on a state label.** "In force", "open" and "live" are the
semantic flags the modules maintain (``is_active``, ``is_open``).

**One failure is one failure.** Each section, and each record within it, is
isolated: a record that cannot be read or a notification that cannot be sent
is logged and the rest carry on.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import add_days, get_last_day, getdate, nowdate

from consilium.consilium_core import notification, sla

#: Days before a due date that the first notice goes out, per obligation.
NOTICE_DAYS = {
    "document_review": 30,
    "review_cycle": 14,
    "review_cycle_start": 7,
    "monitoring": 7,
    "reassessment": 14,
    "risk_expiry": 30,
    "periodic_return": 7,
    "action_plan": 7,
}

#: An overdue item is chased at most this often.
REPEAT_OVERDUE_DAYS = 7

#: After this many days overdue, the person above the owner is told as well.
ESCALATE_AFTER_DAYS = 14

#: A quarter's periodic return is due this many days after the quarter ends.
PERIODIC_RETURN_GRACE_DAYS = 15

#: Who owns a periodic return when there is no earlier return to inherit an
#: owner from: the role that may create returns.
PERIODIC_RETURN_ROLE = "Escalation Owner"


# ------------------------------------------------------------------ plumbing


def _key(*parts) -> str:
    """A fixed-length key: the natural one can exceed the 140-character column."""
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()


def already_sent(event_code, subject_doctype, subject_name, recipient, due_on, as_of, repeat_days) -> bool:
    """Whether this reminder went out recently enough not to go again.

    ``repeat_days`` None: once per due date, ever. Otherwise not again until
    that many days have passed. Either way, never twice on the same day.
    """
    filters = {
        "event_code": event_code,
        "subject_doctype": subject_doctype,
        "subject_name": subject_name,
        "recipient": recipient,
    }
    if due_on:
        filters["due_on"] = due_on
    last = frappe.get_all("Reminder Log", filters=filters, fields=["sent_for_date"],
                          order_by="sent_for_date desc", limit=1)
    if not last:
        return False
    if repeat_days is None:
        return True
    return (getdate(as_of) - getdate(last[0]["sent_for_date"])).days < repeat_days


def remind(
    event_code: str,
    recipients,
    *,
    subject_doctype: str,
    subject_name: str,
    due_on,
    as_of,
    context: dict | None = None,
    repeat_days: int | None = None,
) -> list[str]:
    """Send one reminder to each recipient who has not had it. Returns dispatch names.

    The log row is written *before* the notification, under the unique key, so
    a second run racing this one fails to claim the key and sends nothing.
    """
    if isinstance(recipients, str):
        recipients = [recipients]
    sent = []
    seen = set()
    for recipient in recipients or []:
        if not recipient or recipient in seen or not frappe.db.exists("User", recipient):
            continue
        seen.add(recipient)
        if already_sent(event_code, subject_doctype, subject_name, recipient, due_on, as_of, repeat_days):
            continue
        key = _key(event_code, subject_doctype, subject_name, recipient, due_on, as_of)
        if frappe.db.exists("Reminder Log", {"reminder_key": key}):
            continue
        log = frappe.get_doc(
            {
                "doctype": "Reminder Log",
                "reminder_key": key,
                "event_code": event_code,
                "subject_doctype": subject_doctype,
                "subject_name": subject_name,
                "recipient": recipient,
                "due_on": due_on,
                "sent_for_date": getdate(as_of),
            }
        )
        # On PostgreSQL a failed insert poisons the whole transaction, so the
        # claim is made inside a savepoint that a lost race can roll back to.
        frappe.db.savepoint("reminder_claim")
        try:
            log.insert(ignore_permissions=True)
        except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
            frappe.db.rollback(save_point="reminder_claim")
            continue
        rows = notification.notify(event_code, [recipient], context or {}, subject_doctype, subject_name)
        if rows:
            log.db_set("dispatch", rows[0], update_modified=False)
        sent.extend(rows)
    return sent


def _days(from_date, to_date) -> int:
    return (getdate(to_date) - getdate(from_date)).days


def _in(names, value) -> bool:
    return names is None or value in names


def _run(label: str, fn, *args, **kwargs):
    """One section, isolated. The savepoint matters on PostgreSQL, where a
    failed statement aborts the transaction and every later section with it."""
    frappe.db.savepoint("reminder_section")
    try:
        return fn(*args, **kwargs)
    except Exception:
        frappe.db.rollback(save_point="reminder_section")
        frappe.log_error(title=_("Scheduled reminders: {0} failed").format(label), message=frappe.get_traceback())
        return []


def _each(label: str, rows, fn) -> list[str]:
    """One record at a time, each isolated like a section."""
    out = []
    for row in rows:
        frappe.db.savepoint("reminder_record")
        try:
            out.extend(fn(row) or [])
        except Exception:
            frappe.db.rollback(save_point="reminder_record")
            frappe.log_error(title=_("Scheduled reminders: {0} {1} failed").format(label, row.get("name")),
                             message=frappe.get_traceback())
    return out


def _due_or_overdue(stage_codes: tuple[str, str], recipients, *, doctype, name, due_on, as_of, context):
    """The common shape: a notice before the date, a weekly chase after it."""
    days_until = _days(as_of, due_on)
    soon, late = stage_codes
    if days_until > 0:
        return remind(soon, recipients, subject_doctype=doctype, subject_name=name, due_on=due_on,
                      as_of=as_of, context={**context, "due_on": str(due_on), "days_until": days_until})
    return remind(late, recipients, subject_doctype=doctype, subject_name=name, due_on=due_on, as_of=as_of,
                  context={**context, "due_on": str(due_on), "days_overdue": -days_until},
                  repeat_days=REPEAT_OVERDUE_DAYS)


# ----------------------------------------------------------- P-10 reviews


def _open_cycle_documents() -> set[str]:
    return set(frappe.get_all("Document Review Cycle", filters={"is_open": 1}, pluck="document"))


def remind_document_reviews(as_of=None, documents=None) -> list[str]:
    """Documents in force whose next review date is near or past, with no cycle open.

    A document with a review cycle already open is being reviewed; the cycle's
    own reminders take over, so the owner is not told twice about one review.
    """
    as_of = getdate(as_of or nowdate())
    horizon = add_days(as_of, NOTICE_DAYS["document_review"])
    in_review = _open_cycle_documents()
    rows = [
        row for row in frappe.get_all(
            "Governing Document",
            filters={"is_active": 1, "docstatus": ["<", 2], "next_review_on": ["<=", horizon]},
            fields=["name", "document_name", "next_review_on", "document_owner", "document_approver"],
        )
        if row.next_review_on and row.name not in in_review and _in(documents, row.name)
    ]

    def one(row):
        context = {"document_name": row.document_name, "document_owner": row.document_owner}
        sent = _due_or_overdue(("policy.review.due_soon", "policy.review.overdue"), [row.document_owner],
                               doctype="Governing Document", name=row.name, due_on=row.next_review_on,
                               as_of=as_of, context=context)
        days_overdue = _days(row.next_review_on, as_of)
        if days_overdue >= ESCALATE_AFTER_DAYS and row.document_approver not in (None, "", row.document_owner):
            sent += remind("policy.review.escalated", [row.document_approver],
                           subject_doctype="Governing Document", subject_name=row.name,
                           due_on=row.next_review_on, as_of=as_of, repeat_days=REPEAT_OVERDUE_DAYS,
                           context={**context, "due_on": str(row.next_review_on), "days_overdue": days_overdue})
        return sent

    return _each("document review", rows, one)


def remind_review_cycles(as_of=None, cycles=None) -> list[str]:
    """Open review cycles: about to start, due soon, overdue, escalated."""
    as_of = getdate(as_of or nowdate())
    rows = [
        row for row in frappe.get_all(
            "Document Review Cycle",
            filters={"is_open": 1},
            fields=["name", "document", "cycle_year", "scheduled_start", "due_on", "reviewer"],
        )
        if _in(cycles, row.name)
    ]

    def one(row):
        document = frappe.db.get_value(
            "Governing Document", row.document,
            ["document_name", "document_owner", "document_approver"], as_dict=True,
        ) or frappe._dict()
        people = [row.reviewer, document.document_owner]
        context = {"document_name": document.document_name or row.document,
                   "scheduled_start": str(row.scheduled_start or ""), "due_on": str(row.due_on or "")}
        sent = []
        start = row.scheduled_start
        if start and 0 <= _days(as_of, start) <= NOTICE_DAYS["review_cycle_start"]:
            sent += remind("policy.review_cycle.starting", people, subject_doctype="Document Review Cycle",
                           subject_name=row.name, due_on=start, as_of=as_of, context=context)
        if row.due_on and _days(as_of, row.due_on) <= NOTICE_DAYS["review_cycle"]:
            sent += _due_or_overdue(("policy.review_cycle.due_soon", "policy.review_cycle.overdue"), people,
                                    doctype="Document Review Cycle", name=row.name, due_on=row.due_on,
                                    as_of=as_of, context=context)
            days_overdue = _days(row.due_on, as_of)
            approver = document.document_approver
            if days_overdue >= ESCALATE_AFTER_DAYS and approver and approver not in people:
                sent += remind("policy.review_cycle.escalated", [approver], subject_doctype="Document Review Cycle",
                               subject_name=row.name, due_on=row.due_on, as_of=as_of,
                               repeat_days=REPEAT_OVERDUE_DAYS, context={**context, "days_overdue": days_overdue})
        return sent

    return _each("review cycle", rows, one)


# -------------------------------------------------------- P-11 monitoring


def remind_monitoring(as_of=None, activities=None) -> list[str]:
    as_of = getdate(as_of or nowdate())
    horizon = add_days(as_of, NOTICE_DAYS["monitoring"])
    rows = [
        row for row in frappe.get_all(
            "Monitoring Activity",
            filters={"is_active": 1, "next_due_on": ["<=", horizon]},
            fields=["name", "document", "activity_title", "responsible", "next_due_on"],
        )
        if row.next_due_on and _in(activities, row.name)
    ]

    def one(row):
        document = frappe.db.get_value("Governing Document", row.document,
                                       ["document_name", "document_owner"], as_dict=True) or frappe._dict()
        context = {"document_name": document.document_name or row.document, "responsible": row.responsible}
        sent = _due_or_overdue(("policy.monitoring.due_soon", "policy.monitoring.overdue"), [row.responsible],
                               doctype="Monitoring Activity", name=row.name, due_on=row.next_due_on,
                               as_of=as_of, context=context)
        days_overdue = _days(row.next_due_on, as_of)
        owner = document.document_owner
        if days_overdue >= ESCALATE_AFTER_DAYS and owner and owner != row.responsible:
            sent += remind("policy.monitoring.escalated", [owner], subject_doctype="Monitoring Activity",
                           subject_name=row.name, due_on=row.next_due_on, as_of=as_of,
                           repeat_days=REPEAT_OVERDUE_DAYS,
                           context={**context, "due_on": str(row.next_due_on), "days_overdue": days_overdue})
        return sent

    return _each("monitoring activity", rows, one)


# -------------------------------------------------- E-9 risk acceptance


def remind_risk_acceptances(as_of=None, acceptances=None) -> list[str]:
    """Acceptances in force: reassessment due or overdue; end date near or past.

    An acceptance past its end date that is still in force is chased rather
    than expired here: expiring it is the escalation module's decision, and a
    reminder that it has not been made is what this job can add.
    """
    as_of = getdate(as_of or nowdate())
    rows = [
        row for row in frappe.get_all(
            "Risk Acceptance",
            filters={"is_active": 1},
            fields=["name", "risk_acceptance_name", "accountable_executive", "next_reassessment_on", "end_date"],
        )
        if _in(acceptances, row.name)
    ]

    def one(row):
        sent = []
        who = [row.accountable_executive]
        if row.next_reassessment_on and _days(as_of, row.next_reassessment_on) <= NOTICE_DAYS["reassessment"]:
            sent += _due_or_overdue(
                ("escalation.risk_acceptance.reassessment_due", "escalation.risk_acceptance.reassessment_overdue"),
                who, doctype="Risk Acceptance", name=row.name, due_on=row.next_reassessment_on, as_of=as_of,
                context={},
            )
        if row.end_date and _days(as_of, row.end_date) <= NOTICE_DAYS["risk_expiry"]:
            days_until = _days(as_of, row.end_date)
            if days_until >= 0:
                sent += remind("escalation.risk_acceptance.expiring", who, subject_doctype="Risk Acceptance",
                               subject_name=row.name, due_on=row.end_date, as_of=as_of,
                               context={"end_date": str(row.end_date), "days_until": days_until})
            else:
                sent += remind("escalation.risk_acceptance.expired", who, subject_doctype="Risk Acceptance",
                               subject_name=row.name, due_on=row.end_date, as_of=as_of,
                               repeat_days=REPEAT_OVERDUE_DAYS,
                               context={"end_date": str(row.end_date), "days_overdue": -days_until})
        return sent

    return _each("risk acceptance", rows, one)


# ----------------------------------------------- E-11 periodic returns


def quarter_of(day) -> tuple[str, object, object]:
    """``(label, first day, last day)`` of the calendar quarter containing ``day``."""
    day = getdate(day)
    first_month = 3 * ((day.month - 1) // 3) + 1
    start = day.replace(month=first_month, day=1)
    end = get_last_day(start.replace(month=first_month + 2))
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}", start, getdate(end)


def _scope_key(value) -> str:
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    return json.dumps(value or {}, sort_keys=True)


def return_owners(submission) -> list[str]:
    """Who owns a return: whoever created it, else holders of the returns role.

    A return the scheduler created is owned by the owner of the same scope's
    previous return (set when it is created), so in practice the fallback is
    reached only on a site that has never filed one.
    """
    owner = submission.get("owner")
    if owner and owner not in ("Administrator", "Guest"):
        return [owner]
    return frappe.get_all(
        "Has Role", filters={"role": PERIODIC_RETURN_ROLE, "parenttype": "User"}, pluck="parent"
    )


def open_quarter(as_of=None) -> list[str]:
    """Create this quarter's periodic returns when the quarter opens. Safe to run daily.

    One return per scope the previous quarter had (a site filing returns per
    business line keeps doing so), or one unscoped return on a site that has
    none. The new return's owner is the previous one's, so the reminders reach
    a person rather than a role.
    """
    as_of = getdate(as_of or nowdate())
    label, start, end = quarter_of(as_of)
    existing = {
        _scope_key(row.scope_filter)
        for row in frappe.get_all("Periodic Submission", filters={"period_start": start},
                                  fields=["scope_filter"])
    }
    previous = frappe.get_all(
        "Periodic Submission",
        filters={"period_end": ["<", start]},
        fields=["name", "scope_filter", "owner", "period_end"],
        order_by="period_end desc",
    )
    scopes: dict[str, str | None] = {}
    if previous:
        latest_end = previous[0].period_end
        for row in previous:
            if row.period_end == latest_end:
                scopes.setdefault(_scope_key(row.scope_filter), row.owner)
    else:
        scopes[_scope_key({})] = None

    created = []
    for scope, owner in scopes.items():
        if scope in existing:
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Periodic Submission",
                "period_label": label,
                "period_start": start,
                "period_end": end,
                "scope_filter": json.loads(scope),
            }
        ).insert(ignore_permissions=True)
        if owner:
            frappe.db.set_value("Periodic Submission", doc.name, "owner", owner, update_modified=False)
        created.append(doc.name)
        doc.owner = owner or doc.owner
        remind("escalation.periodic_return.opened", return_owners(doc), subject_doctype="Periodic Submission",
               subject_name=doc.name, due_on=add_days(end, PERIODIC_RETURN_GRACE_DAYS), as_of=as_of,
               context={"period_label": label, "period_start": str(start), "period_end": str(end),
                        "due_on": str(add_days(end, PERIODIC_RETURN_GRACE_DAYS))})
    return created


def remind_periodic_returns(as_of=None, submissions=None) -> list[str]:
    """Open returns whose due date (quarter end plus grace) is near or past."""
    as_of = getdate(as_of or nowdate())
    rows = [
        row for row in frappe.get_all(
            "Periodic Submission",
            filters={"is_open": 1},
            fields=["name", "period_label", "period_end", "owner"],
        )
        if row.period_end and _in(submissions, row.name)
    ]

    def one(row):
        due = add_days(row.period_end, PERIODIC_RETURN_GRACE_DAYS)
        if _days(as_of, due) > NOTICE_DAYS["periodic_return"]:
            return []
        return _due_or_overdue(
            ("escalation.periodic_return.due_soon", "escalation.periodic_return.overdue"), return_owners(row),
            doctype="Periodic Submission", name=row.name, due_on=due, as_of=as_of,
            context={"period_label": row.period_label},
        )

    return _each("periodic return", rows, one)


# ---------------------------------------------------------- forum reviews


def remind_forum_reviews(as_of=None, forums=None) -> list[str]:
    """Turn the governance module's overdue-review exception list into notices.

    ``governance.reviews.overdue_reviews`` computes the list; this sends it.
    The reasons it returns are that module's own codes, not workflow states.
    """
    try:
        from consilium.governance import reviews
    except ImportError:
        return []
    as_of = getdate(as_of or nowdate())
    events = {
        "review_overdue": "governance.forum_review.overdue",
        "attestation_open": "governance.forum_attestation.open",
        "second_signature_missing": "governance.forum_attestation.second_signature_missing",
    }
    rows = [row for row in reviews.overdue_reviews(as_of) if _in(forums, row.get("forum"))]

    def one(row):
        event = events.get(row.get("reason"))
        if not event:
            return []
        forum = frappe.db.get_value("Governance Forum", row["forum"], ["forum_name", "forum_owner"],
                                    as_dict=True) or frappe._dict()
        people = [forum.forum_owner]
        subject_doctype, subject_name = "Governance Forum", row["forum"]
        if row.get("task"):
            task = frappe.db.get_value("Attestation Task", row["task"], ["assigned_to", "second_signatory"],
                                       as_dict=True) or frappe._dict()
            people.insert(0, task.second_signatory if event.endswith("second_signature_missing")
                          else task.assigned_to)
            subject_doctype, subject_name = "Attestation Task", row["task"]
        return remind(event, people, subject_doctype=subject_doctype, subject_name=subject_name,
                      due_on=row.get("due_on"), as_of=as_of, repeat_days=REPEAT_OVERDUE_DAYS,
                      context={"forum_name": forum.forum_name or row["forum"], "task": row.get("task"),
                               "due_on": row.get("due_on"),
                               "days_overdue": _days(row.get("due_on") or as_of, as_of)})

    return _each("forum review", [frappe._dict(r, name=r.get("task") or r.get("forum")) for r in rows], one)


# ------------------------------------------------- attestation campaigns


def remind_attestation_campaigns(as_of=None, campaigns=None) -> list[str]:
    """Remind people with outstanding attestation tasks, on the campaign's own schedule.

    A campaign carries a reminder schedule — rows of "so many days before the
    due date" — and nothing read it: the only attestation reminders were the
    forum module's weekly overdue chase, so a campaign configured to remind at
    fourteen and three days out sent nothing until it was already late. Each
    schedule row is now a point at which the people a task is waiting on are
    told: the person asked, while the task is unanswered; the second
    signatory, once it is answered and until they counter-sign.

    **Once per point.** A point that has passed is sent once: the Reminder Log
    is asked whether this reminder went to this person on or after the day the
    point fell (``remind`` with a window reaching back to it). A day the job did
    not run is caught up the next day, and when two points have passed since
    the last run only one reminder goes — the nearer point's. Overdue tasks are
    left to the overdue chase and the expiry sweep; a negative offset (a point
    after the due date) is honoured all the same, because it is configuration.
    """
    as_of = getdate(as_of or nowdate())
    schedules: dict[str, list] = {}
    for row in frappe.get_all(
        "Attestation Reminder",
        filters={"parenttype": "Attestation Campaign", "parentfield": "reminder_schedule"},
        fields=["parent", "offset_days", "note"],
    ):
        if _in(campaigns, row.parent):
            schedules.setdefault(row.parent, []).append(row)
    if not schedules:
        return []
    open_campaigns = {
        row.name: row
        for row in frappe.get_all(
            "Attestation Campaign",
            filters={"name": ["in", list(schedules)], "is_open": 1},
            fields=["name", "campaign_title"],
        )
    }
    if not open_campaigns:
        return []
    tasks = frappe.get_all(
        "Attestation Task",
        # Not `["is", "set"]`: on PostgreSQL that compares a date with the empty
        # string and fails. A task without a due date is skipped below.
        filters={"campaign": ["in", list(open_campaigns)]},
        fields=["name", "campaign", "due_on", "is_open", "assigned_to", "responded_on", "second_signatory",
                "second_signed_on"],
    )

    def one(task):
        if not task.due_on:
            return []
        if task.is_open:
            recipient, awaiting = task.assigned_to, _("attestation")
        elif task.second_signatory and task.responded_on and not task.second_signed_on:
            recipient, awaiting = task.second_signatory, _("counter-signature")
        else:
            return []
        due_on = getdate(task.due_on)
        reached = [
            row for row in schedules[task.campaign]
            if add_days(due_on, -int(row.offset_days or 0)) <= as_of
        ]
        if not reached:
            return []
        # The nearest point passed: the one that fell most recently.
        point = max(reached, key=lambda row: add_days(due_on, -int(row.offset_days or 0)))
        fell_on = add_days(due_on, -int(point.offset_days or 0))
        return remind(
            "attestation.task.reminder", [recipient],
            subject_doctype="Attestation Task", subject_name=task.name, due_on=due_on, as_of=as_of,
            repeat_days=_days(fell_on, as_of) + 1,
            context={"campaign_title": open_campaigns[task.campaign].campaign_title, "task": task.name,
                     "due_on": str(due_on), "days_until": _days(as_of, due_on), "awaiting": awaiting,
                     "note": point.note or ""},
        )

    return _each("attestation campaign", tasks, one)


# ----------------------------------------------------------- action plans


def remind_action_plans(as_of=None, plans=None) -> list[str]:
    """Open plans nearing or past their end date. Overdue also reaches the executive."""
    as_of = getdate(as_of or nowdate())
    horizon = add_days(as_of, NOTICE_DAYS["action_plan"])
    rows = [
        row for row in frappe.get_all(
            "Action Plan",
            filters={"is_open": 1, "end_date": ["<=", horizon]},
            fields=["name", "action_plan_name", "end_date", "owner_user", "accountable_executive"],
        )
        if row.end_date and _in(plans, row.name)
    ]

    def one(row):
        days_until = _days(as_of, row.end_date)
        context = {"end_date": str(row.end_date)}
        if days_until > 0:
            return remind("escalation.action_plan.due_soon", [row.owner_user], subject_doctype="Action Plan",
                          subject_name=row.name, due_on=row.end_date, as_of=as_of,
                          context={**context, "days_until": days_until})
        return remind("escalation.action_plan.overdue", [row.owner_user, row.accountable_executive],
                      subject_doctype="Action Plan", subject_name=row.name, due_on=row.end_date, as_of=as_of,
                      repeat_days=REPEAT_OVERDUE_DAYS, context={**context, "days_overdue": -days_until})

    return _each("action plan", rows, one)


# -------------------------------------------------------------- schedules


def _doctype_ready(doctype: str) -> bool:
    """A module that is not installed contributes nothing, rather than an error."""
    return bool(frappe.db.exists("DocType", doctype)) and frappe.db.table_exists(doctype)


DAILY = (
    ("document reviews", "Governing Document", remind_document_reviews),
    ("review cycles", "Document Review Cycle", remind_review_cycles),
    ("monitoring", "Monitoring Activity", remind_monitoring),
    ("risk acceptances", "Risk Acceptance", remind_risk_acceptances),
    ("quarter opening", "Periodic Submission", open_quarter),
    ("periodic returns", "Periodic Submission", remind_periodic_returns),
    ("forum reviews", "Governance Forum", remind_forum_reviews),
    ("attestation campaigns", "Attestation Campaign", remind_attestation_campaigns),
    ("action plans", "Action Plan", remind_action_plans),
)


def daily(as_of=None) -> dict[str, int]:
    """Every daily reminder. Returns how many dispatches each section wrote."""
    as_of = getdate(as_of or nowdate())
    counts = {}
    for label, doctype, fn in DAILY:
        if not _doctype_ready(doctype):
            continue
        counts[label] = len(_run(label, fn, as_of) or [])
    return counts


def hourly() -> dict[str, int]:
    """Status-driven clocks brought up to date, then the sweep's warnings and breaches."""
    synced = _run("service-level clocks", sla.sync_state_clocks)
    swept = _run("service-level sweep", sla.sweep)
    return {"clocks": len(synced or []), "breached": len(swept or [])}
