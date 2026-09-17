"""Resolution: service levels, closure and automatic escalation on breach.

Three things live here, and none of them reads a status label:

* **Closure (E-10, E17-S3).** A matter whose semantic flags say it is no longer
  open must carry an `Escalation Closure` with a recorded outcome, and the
  response template must be complete. A state that commits the matter to an
  external system of record must also carry the external reference that
  identifies it there.
* **Service levels (E17-S4).** Timing is Core's. A matter opens a `SLA Clock`
  against the definition its matrix rule imposed, and the clock is stopped when
  the matter stops being open. Nothing here computes a duration or a calendar.
* **Breach (E17-S4).** Core's sweep marks a clock breached. This module records
  the breach on the matter, raises the matter's severity, re-runs the matrix so
  the raised matter can reach a higher destination, and notifies — through
  Core's notification layer, so the dispatch row is the evidence.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now

from consilium.consilium_core import notification, sla
from consilium.escalation import routing

MATTER = "Escalation Matter"

#: The air-gapped default channel Core seeds. A dispatch row is the evidence.
DEFAULT_CHANNEL = "RECORD"


# --------------------------------------------------------------------- closure

def closure_of(matter_name: str) -> str | None:
    return frappe.db.get_value("Escalation Closure", {"escalation_matter": matter_name}, "name")


def validate_closure(matter) -> None:
    """A matter at rest must carry its outcome. Reads the flags, not the label."""
    if matter.is_open:
        matter.closed_on = None
        return

    closure = closure_of(matter.name)
    summary = frappe.db.get_value("Escalation Closure", closure, "closure_summary") if closure else None
    if matter.requires_statement and not (closure and summary):
        frappe.throw(
            _(
                "This matter cannot be closed without a recorded outcome. "
                "Record an Escalation Closure with a closure type and a closure summary first."
            ),
            title=_("Outcome Required"),
        )
    if not matter.response_template_completed:
        frappe.throw(
            _("The response template must be completed before a matter is closed, including one tracked externally."),
            title=_("Response Template Incomplete"),
        )
    if matter.is_committable and not matter.external_reference:
        frappe.throw(
            _("A matter tracked outside the platform must carry the external reference that identifies it there."),
            title=_("External Reference Required"),
        )
    if not matter.closed_on:
        matter.closed_on = now()


def validate_closure_record(closure) -> None:
    """The closure's own rules: criteria that are required must be met."""
    unmet = [row.criterion for row in closure.criteria_met if row.required and not row.met]
    if unmet:
        frappe.throw(
            _("Closure criteria not met: {0}.").format(", ".join(unmet)),
            title=_("Closure Criteria"),
        )
    if closure.closure_type == "Transferred Externally" and not closure.external_reference:
        frappe.throw(
            _("A closure that transfers tracking elsewhere must record the external reference."),
            title=_("External Reference Required"),
        )


# --------------------------------------------------------------- service level

def sync_clock(matter) -> None:
    """Open a clock while the matter is open; stop it when it comes to rest."""
    if not matter.sla_definition:
        return

    if matter.is_open:
        clock = sla.start_clock(matter.sla_definition, MATTER, matter.name, started_on=matter.opened_on)
        if matter.sla_clock != clock.name:
            frappe.db.set_value(MATTER, matter.name, "sla_clock", clock.name, update_modified=False)
            matter.sla_clock = clock.name
        return

    open_clock = frappe.db.get_value(
        "SLA Clock", {"subject_doctype": MATTER, "subject_name": matter.name, "is_open": 1}, "name"
    )
    if open_clock:
        sla.stop_clock(open_clock, stopped_on=matter.closed_on or now())


# ---------------------------------------------------------------------- breach

def breached_clocks() -> list[dict]:
    """Clocks Core's sweep has marked breached. `breached_on` is data, not a label.

    The emptiness test is done in Python rather than as an ``is set`` filter:
    on PostgreSQL the framework renders that filter as ``!= ''``, which the
    server rejects for a timestamp column (`03-schema.md` §13 note 5).
    """
    rows = frappe.get_all(
        "SLA Clock",
        filters={"subject_doctype": MATTER},
        fields=["name", "subject_name", "breached_on"],
        order_by="modified asc",
    )
    return sorted((row for row in rows if row.breached_on), key=lambda row: str(row.breached_on))


def sweep_breaches(as_of: str | None = None) -> list[str]:
    """Record every new breach and escalate the matter it belongs to."""
    sla.sweep(as_of)

    escalated = []
    for clock in breached_clocks():
        if not frappe.db.exists(MATTER, clock.subject_name):
            continue
        matter = frappe.get_doc(MATTER, clock.subject_name)
        if not matter.is_open:
            continue
        if matter.last_breach_on and str(matter.last_breach_on) >= str(clock.breached_on):
            continue
        record_breach(matter, clock.name, clock.breached_on)
        escalated.append(matter.name)
    return escalated


def record_breach(matter, clock: str, breached_on) -> None:
    """The breach is recorded on the matter, the matter is raised, and people are told."""
    matter.threshold_breached = 1
    matter.breach_count = int(matter.breach_count or 0) + 1
    matter.last_breach_on = breached_on
    matter.auto_escalated = 1
    matter.severity = routing.raised_severity(matter.severity)
    matter.sla_clock = clock
    matter.save(ignore_permissions=True)

    notify_breach(matter)


def breach_recipients(matter) -> list[str]:
    """The people a breach must reach: the named accountabilities, plus the groups
    the matched matrix rule names."""
    recipients = [matter.accountable_executive, matter.response_owner, matter.identified_by]
    if matter.escalation_matrix and matter.matched_matrix_rule:
        groups = frappe.get_all(
            "Escalation Matrix Notification",
            filters={
                "parent": matter.escalation_matrix,
                "parenttype": "Escalation Matrix",
                "rule_code": matter.matched_matrix_rule,
            },
            pluck="user_group",
        )
        for group in groups:
            recipients.extend(
                frappe.get_all("User Group Member", filters={"parent": group}, pluck="user")
            )
    seen, ordered = set(), []
    for recipient in recipients:
        if recipient and recipient not in seen:
            seen.add(recipient)
            ordered.append(recipient)
    return ordered


def notify_breach(matter) -> list[str]:
    subject = _("Escalation {0} has breached its time threshold").format(matter.escalation_id or matter.name)
    body = _(
        "{0} has passed its configured threshold and has been raised to severity {1}. "
        "Breach {2} recorded on {3}."
    ).format(matter.escalation_title, matter.severity, matter.breach_count, matter.last_breach_on)
    return notification.notify_many(
        DEFAULT_CHANNEL,
        breach_recipients(matter),
        subject=subject,
        body=body,
        subject_doctype=MATTER,
        subject_name=matter.name,
    )


def notify_material_entity_impact(matter) -> list[str]:
    """E-8: flagging material-entity impact tells the pathway's forums."""
    subject = _("Escalation {0} reports material entity impact").format(matter.escalation_id or matter.name)
    return notification.notify_many(
        DEFAULT_CHANNEL,
        breach_recipients(matter),
        subject=subject,
        body=matter.escalation_title,
        subject_doctype=MATTER,
        subject_name=matter.name,
    )
