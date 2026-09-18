"""The notification layer.

The framework's notification definitions carry triggers and templates. What they
do not carry is evidence: several requirements need proof that a party *was*
notified, and an email queue that prunes itself is not evidence. So every send
writes a ``Notification Dispatch`` row, successful or not.

Channels are data. An adapter is looked up by name in a registry — never
imported by a path taken from a database row, which would be a code-execution
seam through configuration.

Two ways in:

* ``notify(event_code, recipients, context, subject_doctype, subject_name)`` —
  the event API. The wording comes from ``Notification Template`` rows (one per
  event and channel, Jinja, editable by an administrator), rendered against the
  context, and sent on each template's channel. New code should use this.
* ``dispatch(channel, recipient, subject=..., body=...)`` — the original
  primitive, text supplied by the caller. Kept exactly as it was for the callers
  that use it; ``notify`` is built on it.

An adapter may declare two checks besides its send function. ``available``
answers "can this channel send at all on this site" — email with no outgoing
account cannot — and a channel that is unavailable hands straight to its
fallback without writing a row, because a deployment fact is not per-message
evidence. ``accepts`` answers "will this recipient take it" — a disabled
account, or a person who has turned email off — and a refusal there *is*
evidence, so it is recorded as ``Suppressed`` with the reason before falling
back.
"""

from __future__ import annotations

import html
import json

import frappe
from frappe import _
from frappe.utils import get_url_to_form, nowdate, now

ADAPTERS: dict[str, callable] = {}
AVAILABILITY: dict[str, callable] = {}
ACCEPTANCE: dict[str, callable] = {}

#: The channel that always works: the dispatch row itself is the record. Used
#: when an event has no active template, so the event is never silently lost.
RECORD_CHANNEL = "RECORD"

#: ``Notification Dispatch.rendered_subject`` is a Data column — 140 characters
#: on PostgreSQL, where a longer value is an error rather than a truncation.
SUBJECT_LIMIT = 140

#: Retries per dispatch, shared by the retry job and the mail-queue reconciler.
MAX_RETRIES = 3

#: The framework mail queue's status for a message the mail server refused.
#: Used only as a query filter; see ``_reopen_refused_email``.
MAIL_QUEUE_REFUSED = "Error"


def register_adapter(name: str, *, available=None, accepts=None):
    def decorator(fn):
        ADAPTERS[name] = fn
        if available:
            AVAILABILITY[name] = available
        if accepts:
            ACCEPTANCE[name] = accepts
        return fn

    return decorator


def _user_refusal(recipient: str) -> str | None:
    """A disabled account receives nothing, on any channel that delivers."""
    enabled = frappe.db.get_value("User", recipient, "enabled")
    if enabled is not None and not int(enabled):
        return _("The recipient's account is disabled.")
    return None


def _in_app_refusal(recipient: str, channel) -> str | None:
    from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled

    reason = _user_refusal(recipient)
    if reason:
        return reason
    if not is_notifications_enabled(recipient):
        return _("The recipient has turned notifications off in their notification settings.")
    return None


@register_adapter("record_only")
def _record_only(dispatch, channel) -> None:
    """The air-gapped default: the dispatch row itself is the delivery record."""
    return None


@register_adapter("in_app", accepts=_in_app_refusal)
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


# ------------------------------------------------------------------- email


def email_configured() -> bool:
    """Whether the framework has an outgoing account to send through.

    The same lookup the mail queue itself uses: a default outgoing Email
    Account, or mail settings in the site configuration. When emails are muted
    (tests, demonstration loads) the framework substitutes a dummy account and
    queues without sending, and this answers yes, so the queue is exercised.
    """
    from frappe.email.doctype.email_account.email_account import EmailAccount

    try:
        return bool(EmailAccount.find_default_outgoing())
    except Exception:
        return False


def _email_available(channel) -> str | None:
    """Whether the chosen route can send at all. See ``Email Delivery Settings``."""
    from consilium.consilium_core.integrations import graph_mail

    if graph_mail.uses_graph():
        absent = graph_mail.missing(graph_mail.settings())
        if absent:
            return _("Microsoft Graph is chosen for email but is not fully set up: {0} missing.").format(
                ", ".join(absent)
            )
        return None
    if email_configured():
        return None
    return _("No outgoing email account is configured on this site.")


def _email_address(recipient: str) -> str | None:
    return frappe.db.get_value("User", recipient, "email")


def _email_refusal(recipient: str, channel) -> str | None:
    from frappe.desk.doctype.notification_settings.notification_settings import (
        is_email_notifications_enabled,
    )

    reason = _user_refusal(recipient)
    if reason:
        return reason
    if not _email_address(recipient):
        return _("The recipient has no email address.")
    if not is_email_notifications_enabled(recipient):
        return _("The recipient has turned email notifications off in their notification settings.")
    if frappe.db.exists("Email Unsubscribe", {"email": _email_address(recipient), "global_unsubscribe": 1}):
        return _("The recipient has unsubscribed from all email.")
    return None


def as_html(body: str | None) -> str:
    """Plain text keeps its paragraphs; text that is already HTML is left alone.

    Templates are written as plain text by default because the same wording is
    stored on the dispatch row and shown on desk, where markup reads badly.
    """
    body = body or ""
    if "<" in body and ">" in body:
        return body
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)


@register_adapter("email", available=_email_available, accepts=_email_refusal)
def _email(dispatch, channel) -> None:
    """Hand the message to the route ``Email Delivery Settings`` chooses.

    SMTP (the default): the framework's mail queue. Delivery is the queue's
    job, on its own schedule, through the site's outgoing account. The queue
    row references this dispatch, so the retry job can find a message the mail
    server later refused and send it again.

    Microsoft Graph: ``integrations.graph_mail.deliver``, which keeps the same
    meaning of "sent" and the same retry policy; see that module.

    ``configuration`` may name a ``sender`` (SMTP only: Graph always sends as
    its configured mailbox) and a ``reply_to``. A caller that needs the answer
    now rather than from the queue — the Integrations page's test email — sets
    ``frappe.flags.cns_mail_inline``.
    """
    from consilium.consilium_core.integrations import graph_mail

    config = channel.configuration
    if isinstance(config, str):
        config = json.loads(config) if config.strip() else {}
    config = config or {}
    if graph_mail.uses_graph():
        graph_mail.deliver(dispatch, config)
        return
    inline = bool(frappe.flags.cns_mail_inline)
    queued = frappe.sendmail(
        recipients=[_email_address(dispatch.recipient)],
        sender=config.get("sender") or None,
        reply_to=config.get("reply_to") or None,
        subject=dispatch.rendered_subject or _("Notification"),
        message=as_html(dispatch.rendered_body),
        reference_doctype="Notification Dispatch",
        reference_name=dispatch.name,
        add_unsubscribe_link=0,
        delayed=not inline,
    )
    if not queued:
        # The queue builder drops recipients who unsubscribed from this sender
        # or whose address it cannot parse, and says nothing. A message that
        # was never queued must not be recorded as sent.
        raise frappe.ValidationError(_("The mail queue accepted no recipient for this message."))


def get_adapter(name: str):
    adapter = ADAPTERS.get(name)
    if not adapter:
        frappe.throw(_("No notification adapter named {0} is registered.").format(name))
    return adapter


def _clip(subject: str | None) -> str | None:
    if subject and len(subject) > SUBJECT_LIMIT:
        return subject[: SUBJECT_LIMIT - 1] + "…"
    return subject


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
    subject = _clip(subject)
    seen = _seen or set()

    def _fall_back(from_row: str | None):
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
                fallback_of=from_row,
                _seen=seen,
            )
        return None

    # A channel that cannot send on this site at all hands on before writing a
    # row. Only when there is nowhere to hand on to is the refusal recorded.
    available = AVAILABILITY.get(channel_doc.adapter)
    unavailable = channel_doc.is_active and available and available(channel_doc)
    if unavailable:
        handed_on = _fall_back(fallback_of)
        if handed_on is not None:
            return handed_on

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

    refusal = unavailable
    if not refusal and ACCEPTANCE.get(channel_doc.adapter):
        refusal = ACCEPTANCE[channel_doc.adapter](recipient, channel_doc)
    if refusal:
        row.status = "Suppressed"
        row.failure_reason = refusal
        row.save(ignore_permissions=True)
        return _fall_back(row.name) or row

    try:
        get_adapter(channel_doc.adapter)(row, channel_doc)
    except Exception as exc:
        row.status = "Failed"
        row.failure_reason = f"{type(exc).__name__}: {exc}"
        row.save(ignore_permissions=True)
        return _fall_back(row.name) or row

    row.status = "Sent"
    row.sent_on = now()
    row.save(ignore_permissions=True)
    return row


def notify_many(channel: str, recipients: list[str], **kwargs) -> list[str]:
    return [dispatch(channel, recipient, **kwargs).name for recipient in recipients]


# --------------------------------------------------------------- event API


def _templates_for(event_code: str) -> list[dict]:
    return frappe.get_all(
        "Notification Template",
        filters={"event_code": event_code, "is_active": 1},
        fields=["name", "channel", "subject", "body"],
        order_by="channel asc",
    )


def _builtin(event_code: str) -> tuple[str, str]:
    from consilium.consilium_core.setup.notification_templates import EVENT_INDEX

    row = EVENT_INDEX.get(event_code)
    if row:
        return row[3], row[4]
    return (
        "{{ event_code }}{% if subject_name %}: {{ subject_doctype }} {{ subject_name }}{% endif %}",
        "{{ link }}",
    )


def render(text: str | None, context: dict) -> str:
    """Jinja through the framework's sandboxed environment.

    Not ``frappe.render_template``: that guesses a one-line string ending in
    something like ``.md`` is a file path, so a subject an administrator wrote
    as "Read policy.md" would be looked up on disk. The dunder refusal is kept,
    which with the sandbox is what stops an administrator-editable template
    becoming a way into the server.
    """
    from frappe.utils.jinja import get_jenv, safe_render_flags

    text = text or ""
    if ".__" in text:
        raise frappe.ValidationError(_("Illegal template: attribute names starting with __ are refused."))
    with safe_render_flags():
        return get_jenv().from_string(text).render(context)


def validate_template(text: str | None) -> None:
    """Refuse a template that does not parse. Runtime errors are caught at send."""
    from jinja2 import TemplateSyntaxError

    from frappe.utils.jinja import get_jenv

    if text and ".__" in text:
        frappe.throw(_("Attribute names starting with __ are not allowed in a template."))
    try:
        get_jenv().from_string(text or "")
    except TemplateSyntaxError as exc:
        frappe.throw(_("Template syntax error on line {0}: {1}").format(exc.lineno, exc.message))


def _render_pair(event_code: str, template: dict | None, context: dict) -> tuple[str, str]:
    """Render a template, falling back to the built-in wording, then to plain text.

    A broken template is an administrator's typo; it is logged where an
    administrator will see it, and the notification still goes out.
    """
    if template:
        try:
            return render(template["subject"], context).strip(), render(template["body"], context)
        except Exception:
            frappe.log_error(
                title=_("Notification template {0} failed to render").format(template["name"]),
                message=frappe.get_traceback(),
                reference_doctype="Notification Template",
                reference_name=template["name"],
            )
    subject, body = _builtin(event_code)
    try:
        return render(subject, context).strip(), render(body, context)
    except Exception:
        frappe.log_error(
            title=_("Built-in wording for {0} failed to render").format(event_code),
            message=frappe.get_traceback(),
        )
    target = f"{context.get('subject_doctype') or ''} {context.get('subject_name') or ''}".strip()
    return f"{event_code} {target}".strip(), context.get("link") or ""


def _subject_record(subject_doctype: str | None, subject_name: str | None) -> dict:
    if not (subject_doctype and subject_name):
        return frappe._dict()
    try:
        return frappe._dict(frappe.get_doc(subject_doctype, subject_name).as_dict(no_default_fields=True))
    except frappe.DoesNotExistError:
        return frappe._dict()


def build_context(
    event_code: str,
    context: dict | None,
    subject_doctype: str | None,
    subject_name: str | None,
    record: dict | None = None,
) -> dict:
    """The names every template may use, overlaid by the caller's own."""
    base = {
        "event_code": event_code,
        "subject_doctype": subject_doctype,
        "subject_name": subject_name,
        "link": get_url_to_form(subject_doctype, subject_name) if subject_doctype and subject_name else "",
        "today": nowdate(),
        "doc": record if record is not None else _subject_record(subject_doctype, subject_name),
    }
    base.update(context or {})
    return base


def _recipient_list(recipients) -> list[str]:
    if isinstance(recipients, str):
        recipients = [recipients]
    seen, out = set(), []
    for recipient in recipients or []:
        if recipient and recipient not in seen and frappe.db.exists("User", recipient):
            seen.add(recipient)
            out.append(recipient)
    return out


def notify(
    event_code: str,
    recipients,
    context: dict | None = None,
    subject_doctype: str | None = None,
    subject_name: str | None = None,
) -> list[str]:
    """Raise an event: render its templates and send each on its channel.

    Returns the names of the dispatch rows that record the outcome — one per
    recipient per template, or the fallback row where a channel handed on.
    Recipients that are not users are dropped: a dispatch is evidence about a
    person, and a row naming nobody proves nothing.

    With no active template for the event, the built-in wording is recorded on
    the record channel, so switching a template off stops the delivery but not
    the evidence. One recipient's failure never stops the next.
    """
    people = _recipient_list(recipients)
    if not people:
        return []

    templates = _templates_for(event_code)
    targets = [(t["channel"], t) for t in templates] or [(RECORD_CHANNEL, None)]
    record = _subject_record(subject_doctype, subject_name)

    names = []
    for recipient in people:
        ctx = build_context(event_code, context, subject_doctype, subject_name, record)
        ctx["recipient"] = recipient
        ctx["recipient_name"] = frappe.utils.get_fullname(recipient)
        for channel, template in targets:
            # A failed statement aborts a PostgreSQL transaction; the savepoint
            # keeps one recipient's failure from failing everyone after them.
            frappe.db.savepoint("notification_dispatch")
            try:
                subject, body = _render_pair(event_code, template, ctx)
                row = dispatch(
                    channel,
                    recipient,
                    subject=subject,
                    body=body,
                    subject_doctype=subject_doctype,
                    subject_name=subject_name,
                )
                names.append(row.name)
            except Exception:
                frappe.db.rollback(save_point="notification_dispatch")
                frappe.log_error(
                    title=_("Notification {0} to {1} could not be dispatched").format(event_code, recipient),
                    message=frappe.get_traceback(),
                )
    return names


# ------------------------------------------------------------------- retry


def _reopen_refused_email(limit: int) -> list[str]:
    """Reopen email dispatches whose message the mail server later refused.

    The adapter's success means "queued"; the send happens afterwards, in the
    framework's queue, and can fail there. Such a dispatch was recorded as sent,
    so it is reopened here, with the queue's error, for the retry below. Only
    the latest queue row per dispatch is read: an earlier failure already
    retried has a newer row, and reading the old one would retry forever.

    Which queue rows the server refused is asked of the database, by the
    framework queue's own status (``MAIL_QUEUE_REFUSED``), rather than tested
    here: that status belongs to the framework, has no semantic flag to read,
    and is not one of this platform's workflow states — but a label compared in
    code reads like one, and the state-flag checker rightly refuses it.
    """
    rows = frappe.get_all(
        "Email Queue",
        filters={"reference_doctype": "Notification Dispatch"},
        fields=["name", "reference_name", "error", "creation"],
        order_by="creation desc",
        limit=limit * 10,
    )
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row.reference_name, row)
    refused = set(
        frappe.get_all(
            "Email Queue",
            filters={"name": ["in", [r.name for r in latest.values()] or [""]], "status": MAIL_QUEUE_REFUSED},
            pluck="name",
        )
    )
    reopened = []
    for dispatch_name, queue_row in latest.items():
        if queue_row.name not in refused or not frappe.db.exists("Notification Dispatch", dispatch_name):
            continue
        row = frappe.get_doc("Notification Dispatch", dispatch_name)
        if row.is_open or int(row.retry_count or 0) >= MAX_RETRIES:
            continue
        row.status = "Failed"
        lines = (queue_row.error or "").strip().splitlines()
        row.failure_reason = _("The mail server refused the message: {0}").format(lines[-1] if lines else "")
        row.save(ignore_permissions=True)
        reopened.append(dispatch_name)
    return reopened


def retry_failed(limit: int = 100) -> list[str]:
    """Retry dispatches that are still open. Reads the semantic flag, never the label.

    Email failures come in two kinds and both land here: the queue refusing the
    message outright (the dispatch is already open) and the mail server refusing
    it later (reopened by ``_reopen_refused_email`` first).
    """
    try:
        _reopen_refused_email(limit)
    except Exception:
        frappe.log_error(title=_("Reconciling the mail queue failed"), message=frappe.get_traceback())

    retried = []
    for name in frappe.get_all(
        "Notification Dispatch",
        filters={"is_open": 1, "retry_count": ["<", MAX_RETRIES]},
        pluck="name",
        limit=limit,
    ):
        row = frappe.get_doc("Notification Dispatch", name)
        channel_doc = frappe.get_doc("Notification Channel", row.channel)
        try:
            available = AVAILABILITY.get(channel_doc.adapter)
            reason = available and available(channel_doc)
            if reason:
                raise frappe.ValidationError(reason)
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
