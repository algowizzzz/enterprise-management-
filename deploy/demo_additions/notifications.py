"""Demonstration: templated notifications, reminders and service-level clocks.

Idempotent ``run(frappe)``, called by ``deploy/demo_data.py`` after the
organisation exists. It shows:

* the email channel carrying a configuration note — how outgoing mail is set
  up — and no mail server. The demonstration site has no outgoing account, so
  every notification is recorded on the record channel, which is what an
  air-gapped installation does too;
* one template per event, as administrators will find them;
* a service level on a lifecycle step of governing documents (P-7), measured
  from each document's own history;
* the daily reminder job, run once, so due and overdue reviews, monitoring,
  risk acceptances, periodic returns, forum reviews and action plans have
  ``Notification Dispatch`` rows behind them.

Nothing here creates an Email Account or names a mail server.
"""

from __future__ import annotations

import json

DOMAIN = "demo.example"

EMAIL_NOTE = {
    "note": (
        "Email is sent through the framework's mail queue, using the site's default outgoing Email "
        "Account (or the mail settings in the site configuration). Configure that account to turn email "
        "on; nothing else changes. Until then the adapter reports itself unavailable and every "
        "notification is recorded on the fallback channel instead. Optional keys: sender, reply_to."
    ),
    "sender": None,
    "reply_to": None,
}

# (code, title, target, measure, state field, state value, hours, warning %)
SERVICE_LEVELS = [
    ("POL-STEP-REVIEW", "Governing document: time in review", "Governing Document", "Time In State",
     "lifecycle_phase", "Review", 240, 75),
    ("POL-STEP-APPROVED", "Governing document: approval to publication", "Governing Document", "Time In State",
     "lifecycle_phase", "Approved", 120, 75),
    ("POL-REVIEW-CYCLE", "Periodic review: time underway", "Document Review Cycle", "Time In State",
     "cycle_status", "Underway", 720, 80),
]


def _owner(frappe) -> str:
    """A demo persona to own configuration this script adds, so the demo's
    removal query (owner LIKE '%@demo.example') finds it."""
    return (
        frappe.db.get_value("User", {"name": ["like", f"%@{DOMAIN}"], "enabled": 1}, "name")
        or "Administrator"
    )


def run(frappe) -> str:
    from consilium.consilium_core import reminders, sla
    from consilium.consilium_core.setup import notification_templates

    notification_templates.seed_all()

    channel = frappe.get_doc("Notification Channel", notification_templates.DEFAULT_TEMPLATE_CHANNEL)
    config = channel.configuration
    if isinstance(config, str):
        config = json.loads(config) if config.strip() else {}
    if not (config or {}).get("note"):
        channel.configuration = json.dumps({**(config or {}), **EMAIL_NOTE}, indent=1)
        channel.save(ignore_permissions=True)

    owner = _owner(frappe)
    added = 0
    for code, title, doctype, measure, field, value, hours, pct in SERVICE_LEVELS:
        if frappe.db.exists("SLA Definition", code) or not frappe.db.exists("DocType", doctype):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "SLA Definition",
                "sla_code": code,
                "title": title,
                "target_doctype": doctype,
                "measure": measure,
                "state_field": field,
                "state_value": value,
                "target_hours": hours,
                "warning_threshold_pct": pct,
                "calendar": "24x7",
                "is_active": 1,
            }
        ).insert(ignore_permissions=True)
        frappe.db.set_value("SLA Definition", doc.name, "owner", owner, update_modified=False)
        added += 1

    # The loader mutes email for the whole run. The reminders run unmuted so
    # the site behaves as it will in use: with no outgoing account, the email
    # channel hands every notice to the record channel, and nothing is left
    # in a mail queue that would fail later.
    muted = frappe.flags.mute_emails
    frappe.flags.mute_emails = False
    try:
        sla.clear_cache()
        clocks = sla.sync_state_clocks()
        sla.sweep()
        counts = reminders.daily()
    finally:
        frappe.flags.mute_emails = muted

    sent = sum(counts.values())
    return (
        f"{frappe.db.count('Notification Template')} templates, {added} service levels added, "
        f"{len(clocks)} status clocks updated, {sent} reminders sent today "
        f"({', '.join(f'{k} {v}' for k, v in counts.items() if v) or 'none due'})"
    )
