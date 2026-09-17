"""The notification layer.

The framework's notification definitions carry triggers and templates. What they
do not carry is evidence: several requirements need proof that a party *was*
notified, and an email queue that prunes itself is not evidence. So every send
writes a ``Notification Dispatch`` row, successful or not.

Channels are data. An adapter is looked up by name in a registry — never
imported by a path taken from a database row, which would be a code-execution
seam through configuration.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now

ADAPTERS: dict[str, callable] = {}


def register_adapter(name: str):
    def decorator(fn):
        ADAPTERS[name] = fn
        return fn

    return decorator


@register_adapter("record_only")
def _record_only(dispatch, channel) -> None:
    """The air-gapped default: the dispatch row itself is the delivery record."""
    return None


@register_adapter("in_app")
def _in_app(dispatch, channel) -> None:
    frappe.get_doc(
        {
            "doctype": "Notification Log",
            "for_user": dispatch.recipient,
            "type": "Alert",
            "subject": dispatch.rendered_subject or _("Notification"),
            "email_content": dispatch.rendered_body,
            "document_type": dispatch.subject_doctype,
            "document_name": dispatch.subject_name,
        }
    ).insert(ignore_permissions=True)


def get_adapter(name: str):
    adapter = ADAPTERS.get(name)
    if not adapter:
        frappe.throw(_("No notification adapter named {0} is registered.").format(name))
    return adapter


def dispatch(
    channel: str,
    recipient: str,
    *,
    subject: str | None = None,
    body: str | None = None,
    subject_doctype: str | None = None,
    subject_name: str | None = None,
    notification_definition: str | None = None,
    fallback_of: str | None = None,
    _seen: set | None = None,
):
    """Send through one channel, recording the attempt. Falls back on failure."""
    channel_doc = frappe.get_doc("Notification Channel", channel)
    row = frappe.get_doc(
        {
            "doctype": "Notification Dispatch",
            "notification_definition": notification_definition,
            "channel": channel_doc.name,
            "recipient": recipient,
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "rendered_subject": subject,
            "rendered_body": body,
            "queued_on": now(),
            "status": "Queued",
            "fallback_of": fallback_of,
        }
    ).insert(ignore_permissions=True)

    if not channel_doc.is_active:
        row.status = "Suppressed"
        row.failure_reason = _("Channel {0} is not active.").format(channel_doc.name)
        row.save(ignore_permissions=True)
        return row

    try:
        get_adapter(channel_doc.adapter)(row, channel_doc)
    except Exception as exc:
        row.status = "Failed"
        row.failure_reason = f"{type(exc).__name__}: {exc}"
        row.save(ignore_permissions=True)

        seen = _seen or set()
        seen.add(channel_doc.name)
        fallback = channel_doc.fallback_channel
        if fallback and fallback not in seen:
            return dispatch(
                fallback,
                recipient,
                subject=subject,
                body=body,
                subject_doctype=subject_doctype,
                subject_name=subject_name,
                notification_definition=notification_definition,
                fallback_of=row.name,
                _seen=seen,
            )
        return row

    row.status = "Sent"
    row.sent_on = now()
    row.save(ignore_permissions=True)
    return row


def notify_many(channel: str, recipients: list[str], **kwargs) -> list[str]:
    return [dispatch(channel, recipient, **kwargs).name for recipient in recipients]


def retry_failed(limit: int = 100) -> list[str]:
    """Retry dispatches that are still open. Reads the semantic flag, never the label."""
    retried = []
    for name in frappe.get_all(
        "Notification Dispatch", filters={"is_open": 1, "retry_count": ["<", 3]}, pluck="name", limit=limit
    ):
        row = frappe.get_doc("Notification Dispatch", name)
        channel_doc = frappe.get_doc("Notification Channel", row.channel)
        try:
            get_adapter(channel_doc.adapter)(row, channel_doc)
        except Exception as exc:
            row.retry_count = int(row.retry_count or 0) + 1
            row.failure_reason = f"{type(exc).__name__}: {exc}"
            row.save(ignore_permissions=True)
            continue
        row.status = "Sent"
        row.sent_on = now()
        row.retry_count = int(row.retry_count or 0) + 1
        row.save(ignore_permissions=True)
        retried.append(name)
    return retried
