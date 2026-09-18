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


# ---------------------------------------------------------------------------
# G-10: the inventory attestation is conducted in the first quarter.
#
# "Conducted in the first quarter" is read as: the campaign is due by the end
# of a first quarter (1 January to 31 March). When it opens is left free — an
# office may open it in December so that people have the whole quarter — but
# the date by which everyone must have attested falls inside the quarter.
#
# Three things enforce it. A daily job opens the year's campaign in the first
# quarter when nobody has (``open_first_quarter_inventory``). Opening one due
# outside a first quarter is refused and the refusal audited, unless the office
# records why an off-cycle campaign is needed — a catch-up after a missed
# quarter, a population added mid-year — and the reason is kept on the
# campaign. And a year with no first-quarter campaign is reported
# (``inventory_q1_standing``), on the campaign screen and in reporting, so a
# missed quarter is visible rather than inferred.
# ---------------------------------------------------------------------------

#: The last month of the quarter the inventory attestation is conducted in.
FIRST_QUARTER_LAST_MONTH = 3

#: Days before the due date that the first-quarter campaign reminds people,
#: with the note each reminder carries. The opening notice is added per
#: campaign (it falls on the day the campaign opens).
FIRST_QUARTER_REMINDERS = (
    (14, "Two weeks before the first-quarter deadline."),
    (3, "Final reminder: the attestation closes at the end of the quarter."),
)


def first_quarter(year: int) -> tuple:
    """First and last day of ``year``'s first quarter."""
    return getdate(f"{int(year)}-01-01"), getdate(f"{int(year)}-03-31")


def in_first_quarter(day) -> bool:
    return getdate(day).month <= FIRST_QUARTER_LAST_MONTH


def next_first_quarter_due(from_day=None):
    """The first-quarter deadline on or after ``from_day``: this year's 31 March
    while still in the quarter, next year's after it."""
    day = getdate(from_day or nowdate())
    year = day.year if in_first_quarter(day) else day.year + 1
    return first_quarter(year)[1]


def inventory_window_problem(due_on) -> str | None:
    """Why an inventory campaign due on ``due_on`` is not a first-quarter one, or None."""
    due = getdate(due_on)
    if in_first_quarter(due):
        return None
    return _(
        "The annual forum inventory attestation is conducted in the first quarter: it must be due between "
        "1 January and 31 March. {0} is outside the quarter."
    ).format(frappe.utils.formatdate(due))


def open_inventory_attestation(period_label: str, *, opens_on=None, due_on=None, population_filter=None,
                               off_cycle_reason: str | None = None):
    """The G-10 annual inventory attestation, to every attesting seat.

    Due by the end of a first quarter (see the note above). A campaign due
    outside one is refused, audited, unless ``off_cycle_reason`` says why it is
    needed; the reason is then kept on the campaign's timeline. With no due
    date the next first-quarter deadline is used.
    """
    opens = getdate(opens_on or nowdate())
    due = getdate(due_on or next_first_quarter_due(opens))
    problem = inventory_window_problem(due)
    off_cycle_reason = (off_cycle_reason or "").strip() or None
    if problem and not off_cycle_reason:
        from consilium.consilium_core import audit

        audit.refuse(
            problem + " " + _("To open an off-cycle campaign, record why it is needed."),
            subject_doctype="Attestation Campaign",
            subject_name=period_label,
            attempted_action="Other",
            control="inventory attestation first quarter",
            context={"opens_on": str(opens), "due_on": str(due)},
            exc=frappe.ValidationError,
        )
    campaign = _insert_inventory_campaign(period_label, opens, due, population_filter)
    if problem:
        campaign.add_comment(
            "Info",
            _("Off-cycle inventory attestation (due {0}, outside the first quarter), opened by {1}. Reason: {2}")
            .format(due, frappe.session.user, off_cycle_reason),
        )
    return campaign


def _insert_inventory_campaign(period_label: str, opens, due, population_filter):
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
            "opens_on": opens,
            "due_on": due,
            "status": "Open",
        }
    ).insert(ignore_permissions=True)
    return campaign


def first_quarter_campaign(year: int) -> str | None:
    """The inventory campaign conducted in ``year``'s first quarter, if one was.

    One due inside the quarter that is open, or that asked anybody (it has
    tasks). A campaign left in draft asked nobody and does not count. Read from
    dates, the ``is_open`` flag and the task rows, never a status label — which
    also means a campaign cancelled after asking people still counts as held.
    """
    start, end = first_quarter(year)
    rows = frappe.get_all(
        "Attestation Campaign",
        filters={"campaign_type": INVENTORY_CAMPAIGN, "target_doctype": "Governance Forum",
                 "due_on": ["between", [start, end]]},
        fields=["name", "is_open"],
        order_by="due_on asc, creation asc",
    )
    for row in rows:
        if row.is_open or frappe.db.exists("Attestation Task", {"campaign": row.name}):
            return row.name
    return None


def inventory_q1_standing(as_of=None) -> dict:
    """Whether each year had its first-quarter inventory attestation (G-10).

    Years run from the first year any inventory campaign was due (or this year,
    on a site that has never run one) to this year. A year is ``held`` with a
    campaign, ``missed`` without one once its quarter is over, and ``due`` while
    its quarter is still under way with none opened yet — the daily job opens
    it. ``off_cycle`` lists the inventory campaigns due outside a first quarter.
    """
    as_of = getdate(as_of or nowdate())
    campaigns = frappe.get_all(
        "Attestation Campaign",
        filters={"campaign_type": INVENTORY_CAMPAIGN, "target_doctype": "Governance Forum"},
        fields=["name", "campaign_title", "period_label", "opens_on", "due_on"],
        order_by="due_on asc",
    )
    due_years = [getdate(row.due_on).year for row in campaigns if row.due_on]
    first = min([*due_years, as_of.year])
    years = []
    for year in range(first, as_of.year + 1):
        campaign = first_quarter_campaign(year)
        if campaign:
            standing = "held"
        elif as_of > first_quarter(year)[1]:
            standing = "missed"
        else:
            standing = "due"
        years.append({"year": year, "campaign": campaign, "standing": standing})
    off_cycle = [
        {"name": row.name, "campaign_title": row.campaign_title, "period_label": row.period_label,
         "opens_on": str(row.opens_on) if row.opens_on else None, "due_on": str(row.due_on)}
        for row in campaigns if row.due_on and not in_first_quarter(row.due_on)
    ]
    return {
        "as_of": str(as_of),
        "years": years,
        "missed": [row["year"] for row in years if row["standing"] == "missed"],
        "due": [row["year"] for row in years if row["standing"] == "due"],
        "off_cycle": off_cycle,
        "next_due_on": str(next_first_quarter_due(as_of)),
    }


@frappe.whitelist(methods=["GET"])
def inventory_attestation_standing() -> dict:
    """``inventory_q1_standing`` for the campaign screen and reporting.

    Campaign names and dates only — nothing about any forum — so anyone who
    may read the forum inventory may see whether its attestation was held.
    """
    if frappe.session.user == "Guest" or not frappe.has_permission("Governance Forum", "read"):
        frappe.throw(_("The forum inventory is not open to you."), frappe.PermissionError)
    return inventory_q1_standing()


def _free_inventory_label(year: int) -> str:
    """A period label no inventory campaign has used: the year, if it is free."""
    label, counter = str(year), 1
    while frappe.db.exists("Attestation Campaign", {"campaign_type": INVENTORY_CAMPAIGN, "period_label": label}):
        counter += 1
        label = f"{year} Q1" if counter == 2 else f"{year} Q1 #{counter - 1}"
    return label


def open_first_quarter_inventory(as_of=None) -> str | None:
    """Scheduled daily (hooks.py). Opens this year's inventory attestation in Q1.

    Does nothing outside the first quarter, when the year's first-quarter
    campaign exists (however it was opened), or when there is no active forum
    to attest — a campaign that asks nobody would look, on every list, exactly
    like one that had been answered. Otherwise the campaign opens today, due on
    31 March, over every active forum, and its tasks are generated at once.

    Its reminder schedule starts with a point on the opening day, so the first
    daily reminder run tells everyone asked that the attestation is open, then
    the ``FIRST_QUARTER_REMINDERS`` points before the deadline.
    """
    as_of = getdate(as_of or nowdate())
    if not in_first_quarter(as_of) or first_quarter_campaign(as_of.year):
        return None
    if not frappe.get_all("Governance Forum", filters=_active_forum_filter(), limit=1, pluck="name"):
        return None
    due = first_quarter(as_of.year)[1]
    campaign = open_inventory_attestation(_free_inventory_label(as_of.year), opens_on=as_of, due_on=due)
    campaign.append("reminder_schedule", {
        "offset_days": (due - as_of).days,
        "note": _("The first-quarter forum inventory attestation is open."),
    })
    for offset, note in FIRST_QUARTER_REMINDERS:
        if offset < (due - as_of).days:
            campaign.append("reminder_schedule", {"offset_days": offset, "note": _(note)})
    campaign.save(ignore_permissions=True)
    generate(campaign)
    return campaign.name


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


def record_annual_review(task, decision: str, *, comments: str | None = None,
                         returned_questions: str | None = None):
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
        returned_questions=returned_questions,
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
        # An empty date compares as the earliest possible day, so a forum that
        # has never had a review date set would otherwise be reported late.
        if not row["next_review_on"]:
            continue
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


# ---------------------------------------------------------------------------
# Running the forum campaigns from the portal.
#
# Opening a campaign and generating its tasks used to have no caller outside
# the tests and the demonstration loader, so the annual inventory attestation
# could only be run by someone with a Python shell. The governance office runs
# the forum campaigns, and holds no right over the campaign record itself (that
# is an administrator's), so the office's standing is granted here, for forum
# campaigns only, rather than by widening the campaign DocType's permissions.
# ---------------------------------------------------------------------------

def _campaign_office_roles() -> tuple[str, ...]:
    """Who runs the forum campaigns, besides an administrator of campaigns: the
    same office that runs formation. Read from the formation module, imported
    late because it imports this package's lifecycle module at load time."""
    from consilium.governance import formation

    return (formation.GOVERNANCE_OFFICE, formation.DESIGNATED_AUTHORITY)

#: The two forum campaigns the portal can open, by the key the page sends.
CAMPAIGN_OPENERS = {
    "inventory": open_inventory_attestation,
    "annual_review": open_annual_review,
}


def may_run_forum_campaigns(user: str | None = None) -> bool:
    user = user or frappe.session.user
    if attestation.may_administer_campaigns(user):
        return True
    return bool(set(frappe.get_roles(user)) & set(_campaign_office_roles()))


def _require_forum_campaign_right() -> None:
    if not may_run_forum_campaigns():
        frappe.throw(
            _("Forum campaigns are run by the governance office or an administrator."), frappe.PermissionError
        )


def _forum_campaign(campaign: str):
    doc = frappe.get_doc("Attestation Campaign", campaign)
    if doc.target_doctype != "Governance Forum":
        # The office's standing covers forum campaigns; any other is an
        # administrator's, through Core's endpoint.
        frappe.throw(
            _("Campaign {0} is not a forum campaign.").format(campaign), frappe.PermissionError
        )
    return doc


@frappe.whitelist(methods=["GET"])
def forum_campaign_overview() -> dict:
    """The forum campaigns and where their tasks stand."""
    _require_forum_campaign_right()
    return {
        "campaigns": attestation.campaign_board({"target_doctype": "Governance Forum"}),
        "may_generate": True,
    }


@frappe.whitelist(methods=["POST"])
def open_forum_campaign(kind: str, period_label: str, due_on: str, opens_on: str | None = None,
                        off_cycle_reason: str | None = None) -> dict:
    """Open one of the two forum campaigns and generate its tasks in one step.

    One step, because a campaign opened with no tasks asks nobody anything and
    looks, on every list, exactly like one that has been answered. If generating
    fails the campaign is not left behind: both happen in the one transaction.

    The inventory attestation is due in a first quarter (G-10); one due outside
    it needs ``off_cycle_reason`` and is refused, audited, without it.
    """
    _require_forum_campaign_right()
    opener = CAMPAIGN_OPENERS.get(kind)
    if not opener:
        frappe.throw(_("{0} is not a campaign the portal can open.").format(kind), title=_("Unknown Campaign"))
    period_label = (period_label or "").strip()
    if not period_label:
        frappe.throw(_("Name the period the campaign covers, such as the year."), title=_("Period Required"))
    if opener is open_inventory_attestation:
        campaign = opener(period_label, opens_on=opens_on or None, due_on=due_on, off_cycle_reason=off_cycle_reason)
    else:
        campaign = opener(period_label, opens_on=opens_on or None, due_on=due_on)
    return attestation.generate_and_report(campaign)


@frappe.whitelist(methods=["POST"])
def generate_forum_campaign_tasks(campaign: str) -> dict:
    """Pick up forums and seats added since a forum campaign opened. Safe to repeat."""
    _require_forum_campaign_right()
    return attestation.generate_and_report(_forum_campaign(campaign))


# ---------------------------------------------------------------------------
# One forum's annual review, from its own page (E8-S4).
#
# The pieces existed — the dually-signed campaign, the owner's response and the
# compliance counter-signature in the inbox, and `record_annual_review` — but
# nothing joined them for a forum: the review could only be opened as a
# campaign over every live forum, and a dually-signed task could only be turned
# into the forum's review from a Python shell. What follows is that join:
#
# 1. the governance office starts the review for one forum, which opens a
#    dually-signed campaign whose population is that forum and asks its owner;
# 2. the owner responds and the compliance contact counter-signs, from the
#    inbox (`/tasks`), exactly as for a campaign over every forum;
# 3. a compliance reviewer records the review against the signed task, which
#    moves the forum's standing and sets its next review date.
#
# Where each forum stands is read from facts on its tasks (who has signed, and
# whether a review names the task), never from a status label.
# ---------------------------------------------------------------------------


def _annual_tasks(forum: str) -> list[dict]:
    campaigns = frappe.get_all(
        "Attestation Campaign",
        filters={"target_doctype": "Governance Forum", "campaign_type": DUAL_CAMPAIGN},
        pluck="name",
    )
    if not campaigns:
        return []
    tasks = frappe.get_all(
        "Attestation Task",
        filters={"campaign": ["in", campaigns], "subject_doctype": "Governance Forum", "subject_name": forum},
        fields=["name", "campaign", "assigned_to", "second_signatory", "due_on", "is_open", "responded_on",
                "second_signed_on", "response_statement", "creation"],
        order_by="creation desc",
    )
    reviews = {
        row["attestation_task"]: row
        for row in frappe.get_all(
            "Forum Compliance Review",
            filters={"attestation_task": ["in", [t["name"] for t in tasks] or [""]]},
            fields=["name", "attestation_task", "decision", "reviewer", "decided_on"],
        )
    }
    for task in tasks:
        review = reviews.get(task["name"])
        task["signed"] = dual_signature_complete(frappe._dict(task))
        task["lapsed"] = not task["is_open"] and not task["responded_on"]
        task["review"] = review["name"] if review else None
        task["review_decision"] = review["decision"] if review else None
        task["review_recorded_on"] = str(review["decided_on"]) if review and review["decided_on"] else None
        # Outstanding: neither lapsed nor turned into a review yet.
        task["outstanding"] = not task["review"] and not task["lapsed"]
        for key in ("due_on", "responded_on", "second_signed_on", "creation"):
            task[key] = str(task[key]) if task[key] else None
    return tasks


def annual_review_state(forum: str, user: str | None = None) -> dict:
    """Where one forum's annual review stands, and what ``user`` may do about it."""
    user = user or frappe.session.user
    row = frappe.db.get_value(
        "Governance Forum", forum,
        ["name", "forum_name", "forum_owner", "compliance_contact", "next_review_on", "is_active"],
        as_dict=True,
    )
    tasks = _annual_tasks(forum)
    outstanding = [task for task in tasks if task["outstanding"]]
    missing = []
    if not row.forum_owner:
        missing.append(_("a forum owner, who responds"))
    if not row.compliance_contact:
        missing.append(_("a compliance contact, who counter-signs"))
    elif row.compliance_contact == row.forum_owner:
        missing.append(_("a compliance contact other than the forum owner"))
    may_start = bool(row.is_active and may_run_forum_campaigns(user) and not outstanding and not missing)
    recordable = [task["name"] for task in outstanding if task["signed"]]
    may_record = bool(row.is_active and recordable and lifecycle.may_record_review(user))
    return {
        "forum": forum,
        "forum_name": row.forum_name,
        "forum_owner": row.forum_owner,
        "compliance_contact": row.compliance_contact,
        "next_review_on": str(row.next_review_on) if row.next_review_on else None,
        "is_active": int(row.is_active or 0),
        "tasks": tasks,
        "missing": missing,
        "may_start": may_start,
        "may_record": may_record,
        "recordable_tasks": recordable if may_record else [],
        "decisions": lifecycle.review_decisions() if may_record else [],
    }


@frappe.whitelist(methods=["GET"])
def forum_annual_review(forum: str) -> dict:
    """The annual-review panel of a forum's review page."""
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    return annual_review_state(forum)


def _default_period_label(forum: str, forum_name: str | None) -> str:
    """A period label no other owner-and-compliance campaign uses.

    A campaign's type and period label are unique together, so the label names
    the forum by its reference (two forums may share a name) and the year, and
    takes a counter when a review of the same forum was started earlier in the
    year and lapsed — otherwise restarting it would be refused as a duplicate.
    """
    base = "{0} ({1}) {2}".format(forum_name or forum, forum, getdate(nowdate()).year)
    label, counter = base, 1
    while frappe.db.exists("Attestation Campaign", {"campaign_type": DUAL_CAMPAIGN, "period_label": label}):
        counter += 1
        label = f"{base} #{counter}"
    return label


@frappe.whitelist(methods=["POST"])
def start_forum_annual_review(forum: str, due_on: str, period_label: str | None = None) -> dict:
    """Open the dually-signed annual review for one forum and ask its owner.

    The governance office's action, as opening any forum campaign is. Refused
    while the forum already has a review under way — a second campaign would
    ask the owner the same question twice — and while the forum lacks either
    signatory, because a dual review with one of them missing cannot complete
    and would only sit on the exception list.
    """
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not may_run_forum_campaigns():
        from consilium.consilium_core import audit

        audit.refuse(
            _("{0} may not start the annual review of forum {1}. Forum reviews are opened by the governance "
              "office.").format(frappe.session.user, forum),
            subject_doctype="Governance Forum",
            subject_name=forum,
            attempted_action="Other",
            control="forum campaign role",
        )
    state = annual_review_state(forum)
    if not state["is_active"]:
        frappe.throw(_("Forum {0} is closed; it is not reviewed again.").format(forum), title=_("Forum Inactive"))
    if state["missing"]:
        frappe.throw(
            _("The annual review of {0} needs {1}. Record them on the forum first.").format(
                state["forum_name"] or forum, _(" and ").join(state["missing"])
            ),
            title=_("Signatory Missing"),
        )
    if any(task["outstanding"] for task in state["tasks"]):
        frappe.throw(
            _("Forum {0} already has an annual review under way.").format(state["forum_name"] or forum),
            title=_("Review Under Way"),
        )
    if not due_on:
        frappe.throw(_("Give the date the review is due."), title=_("Due Date Required"))
    label = (period_label or "").strip() or _default_period_label(forum, state["forum_name"])
    campaign = open_annual_review(label, due_on=due_on, population_filter={"name": forum})
    report = attestation.generate_and_report(campaign)
    return {**annual_review_state(forum), "started": report}


@frappe.whitelist(methods=["POST"])
def record_forum_annual_review(forum: str, task: str, decision: str, comments: str | None = None,
                               returned_questions: str | None = None) -> dict:
    """Turn a dually-signed task into the forum's annual review.

    A compliance decision, so the same role check as any other review, audited
    when refused; the dual-signature rule is ``record_annual_review``'s.
    """
    frappe.has_permission("Governance Forum", "read", doc=forum, throw=True)
    if not lifecycle.may_record_review():
        from consilium.consilium_core import audit

        audit.refuse(
            _("{0} may not record the annual review of forum {1}. Compliance decisions belong to the {2} "
              "role.").format(frappe.session.user, forum, lifecycle.COMPLIANCE_ROLE),
            subject_doctype="Governance Forum",
            subject_name=forum,
            attempted_action="Other",
            control="compliance review role",
        )
    doc = frappe.get_doc("Attestation Task", task)
    if doc.subject_doctype != "Governance Forum" or doc.subject_name != forum:
        frappe.throw(_("Task {0} is not a review of forum {1}.").format(task, forum), title=_("Wrong Task"))
    if frappe.db.exists("Forum Compliance Review", {"attestation_task": task}):
        frappe.throw(_("Task {0} has already been recorded as a review.").format(task),
                     title=_("Already Recorded"))
    if not frappe.db.get_value("Governance Forum", forum, "is_active"):
        frappe.throw(_("Forum {0} is closed; it is not reviewed again.").format(forum), title=_("Forum Inactive"))
    choices = {row["decision"]: row for row in lifecycle.review_decisions()}
    if decision not in choices:
        frappe.throw(_("{0} is not a review decision.").format(decision), title=_("Unknown Decision"))
    if choices[decision]["requires_statement"] and not ((comments or "").strip() or (returned_questions or "").strip()):
        frappe.throw(_("This decision is recorded with its reasons."), title=_("Statement Required"))
    review = record_annual_review(doc, decision, comments=(comments or "").strip() or None,
                                  returned_questions=(returned_questions or "").strip() or None)
    return {**annual_review_state(forum), "review": review.name}
