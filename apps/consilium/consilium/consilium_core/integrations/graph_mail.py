"""Notification email through Microsoft Graph, for organisations without SMTP.

Some organisations do not let a server speak SMTP to their mail service at all;
the only way to send as a mailbox is the Graph API, as an application
registered in their directory. This module is that route. It is chosen on
``Email Delivery Settings`` and used by the notification layer's ``email``
adapter (``consilium_core.notification``), which is the only caller that sends.

How a message goes
------------------
1. **A token**, by the OAuth 2.0 client-credentials grant:
   ``POST {authority}/{tenant}/oauth2/v2.0/token`` with the application's id and
   secret and the scope ``{graph}/.default``. The token is kept in this process
   until a minute before it expires, keyed by everything that went into it (a
   changed secret gets a new token, not the old one).
2. **The message**: ``POST {graph}/v1.0/users/{sender}/sendMail``, HTML body,
   one recipient. Graph answers 202 when it has accepted it.

Both base addresses are settings, so a national cloud works and so the tests
can point at a stand-in server on the loopback address.

Retries, and why they look like this
------------------------------------
The notification layer already has a retry policy: a failed dispatch stays
open and ``notification.retry_failed`` tries it again hourly, up to
``notification.MAX_RETRIES`` times. Graph mail keeps exactly that policy, so a
dispatch row means the same thing whichever route carried it. Inside one
attempt, only answers that say "not taken, try again" are retried at once:

* **401** — the token was revoked or expired early: it is dropped, a new one
  fetched, and the message sent once more;
* **429, 503, 504** — throttled or briefly unavailable: waited out (the
  ``Retry-After`` the service gives, capped at ``MAX_WAIT_SECONDS``) up to
  ``MAX_RETRIES`` times.

A **timeout** is not retried at once. Graph may have accepted a message whose
answer never arrived, and sending again could deliver it twice; the dispatch is
marked failed with the reason and the hourly retry decides, as it would for a
message the SMTP server refused after queueing.

When the send happens
---------------------
SMTP mail is queued (``frappe.sendmail(delayed=True)``) so nobody's page waits
for a mail server. Graph mail keeps that: inside a web request the send is
handed to a background job and the dispatch reads as sent-to-the-queue, the
same statement the SMTP route makes; the job records a failure on the dispatch
row, which reopens it for the hourly retry. Outside a request — the scheduler,
the retry job, a test, the console — it is sent there and then.

Standard library only (``urllib``): nothing to vendor, no compiler, and the
system proxy settings apply, which is what a corporate network needs.
"""

from __future__ import annotations

import email.utils
import hashlib
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import frappe
from frappe import _

SETTINGS = "Email Delivery Settings"
#: The stored route values. They are configuration data (Email Delivery
#: Settings.delivery_route, set by the deployment kit too), so they are kept as
#: they are; what people read is ``route_label``.
SMTP_ROUTE = "SMTP (framework mail queue)"
GRAPH_ROUTE = "Microsoft Graph"

#: The route as a person reads it on the Integrations page and in a test email.
#: "framework mail queue" described the implementation, not the choice.
ROUTE_LABELS = {
	SMTP_ROUTE: "Your organisation's mail server (SMTP)",
	GRAPH_ROUTE: "Microsoft Graph",
}


def route_label(value: str | None) -> str:
	"""The words for a stored route value; an unknown value is shown as stored."""
	if not value:
		return _(ROUTE_LABELS[SMTP_ROUTE])
	return _(ROUTE_LABELS.get(value, value))

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
DEFAULT_GRAPH = "https://graph.microsoft.com"

#: Answers that mean the service did not take the message and asks for another try.
RETRYABLE = frozenset({429, 503, 504})
#: The longest a single wait for a throttled send may be, whatever Retry-After says.
MAX_WAIT_SECONDS = 30
#: A token is renewed this long before the service says it expires.
TOKEN_SKEW_SECONDS = 60
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_RANGE = (1, 120)

#: Tokens by (authority, tenant, client, secret digest, scope): (token, expires at).
_TOKENS: dict[tuple, tuple[str, float]] = {}

#: Replaced in tests so a throttling test does not wait.
_sleep = time.sleep


class GraphMailError(Exception):
	"""Graph did not accept the message. The text says why."""


class GraphTimeout(GraphMailError):
	"""No answer in time. The message may or may not have been accepted."""


# ------------------------------------------------------------------ settings


def settings():
	return frappe.get_single(SETTINGS)


def route() -> str:
	"""The chosen route. SMTP on a site that has not migrated this in yet."""
	try:
		return frappe.db.get_single_value(SETTINGS, "delivery_route") or SMTP_ROUTE
	except Exception:
		return SMTP_ROUTE


def uses_graph() -> bool:
	return route() == GRAPH_ROUTE


def missing(s) -> list[str]:
	"""The labels of the settings Graph cannot send without."""
	absent = [s.meta.get_label(field) for field in ("graph_tenant_id", "graph_client_id", "graph_sender")
	          if not (s.get(field) or "").strip()]
	if not s.get("graph_client_secret"):
		absent.append(s.meta.get_label("graph_client_secret"))
	return absent


def _base(value: str | None, default: str) -> str:
	return ((value or "").strip() or default).rstrip("/")


def token_url(s) -> str:
	tenant = urllib.parse.quote((s.graph_tenant_id or "").strip(), safe="")
	return f"{_base(s.graph_authority_url, DEFAULT_AUTHORITY)}/{tenant}/oauth2/v2.0/token"


def scope(s) -> str:
	return f"{_base(s.graph_api_url, DEFAULT_GRAPH)}/.default"


def send_url(s) -> str:
	sender = urllib.parse.quote((s.graph_sender or "").strip(), safe="@")
	return f"{_base(s.graph_api_url, DEFAULT_GRAPH)}/v1.0/users/{sender}/sendMail"


def _timeout(s) -> int:
	low, high = TIMEOUT_RANGE
	return min(high, max(low, int(s.get("graph_timeout_seconds") or 20)))


def _secret(s) -> str:
	return s.get_password("graph_client_secret", raise_exception=False) or ""


# ---------------------------------------------------------------------- wire


def _post(url: str, body: bytes, headers: dict, timeout: int) -> tuple[int, dict, bytes]:
	"""One POST. Returns (status, headers, body) for any HTTP answer."""
	request = urllib.request.Request(url, data=body, headers=headers, method="POST")
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — admin-configured http(s) only
			return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read(MAX_RESPONSE_BYTES)
	except urllib.error.HTTPError as e:
		raw = e.read(MAX_RESPONSE_BYTES) if hasattr(e, "read") else b""
		return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, raw
	except (TimeoutError, socket.timeout) as e:
		raise GraphTimeout(_("no answer from {0} within {1} seconds").format(_host(url), timeout)) from e
	except urllib.error.URLError as e:
		if isinstance(e.reason, TimeoutError | socket.timeout):
			raise GraphTimeout(_("no answer from {0} within {1} seconds").format(_host(url), timeout)) from e
		raise GraphMailError(_("could not reach {0}: {1}").format(_host(url), e.reason)) from e


def _host(url: str) -> str:
	return urllib.parse.urlsplit(url).netloc


def _json(raw: bytes) -> dict:
	try:
		value = json.loads((raw or b"{}").decode("utf-8", "replace"))
	except ValueError:
		return {}
	return value if isinstance(value, dict) else {}


def _describe(status: int, raw: bytes) -> str:
	"""Graph's own error code and message, short enough for a dispatch row."""
	payload = _json(raw)
	error = payload.get("error")
	if isinstance(error, dict):
		detail = f"{error.get('code') or ''}: {error.get('message') or ''}".strip(": ")
	else:
		# The sign-in service's shape: error / error_description, whose first
		# line is the useful one (the rest is trace and correlation ids).
		description = (payload.get("error_description") or "").strip().splitlines()
		detail = f"{error or ''}: {description[0] if description else ''}".strip(": ")
	return f"HTTP {status}" + (f" {detail[:300]}" if detail else "")


def _wait(headers: dict, attempt: int) -> float:
	"""Seconds to wait before retrying a throttled send."""
	value = (headers.get("retry-after") or "").strip()
	seconds = None
	if value.isdigit():
		seconds = int(value)
	elif value:
		try:
			seconds = email.utils.parsedate_to_datetime(value).timestamp() - time.time()
		except (TypeError, ValueError):
			seconds = None
	if seconds is None:
		seconds = 2 ** attempt
	return max(0.0, min(float(seconds), MAX_WAIT_SECONDS))


# -------------------------------------------------------------------- token


def _token_key(s) -> tuple:
	digest = hashlib.sha256(_secret(s).encode()).hexdigest()[:16]
	return (token_url(s), (s.graph_client_id or "").strip(), digest, scope(s))


def forget_tokens() -> None:
	_TOKENS.clear()


def get_token(s, *, force: bool = False) -> str:
	"""An access token for the application, from this process's cache if still good."""
	key = _token_key(s)
	cached = _TOKENS.get(key)
	if cached and not force and cached[1] - TOKEN_SKEW_SECONDS > time.time():
		return cached[0]
	body = urllib.parse.urlencode({
		"client_id": (s.graph_client_id or "").strip(),
		"client_secret": _secret(s),
		"scope": scope(s),
		"grant_type": "client_credentials",
	}).encode()
	status, _headers, raw = _post(token_url(s), body,
	                              {"content-type": "application/x-www-form-urlencoded", "accept": "application/json"},
	                              _timeout(s))
	if status != 200:
		raise GraphMailError(_("the sign-in service refused the application ({0})").format(_describe(status, raw)))
	payload = _json(raw)
	token = payload.get("access_token")
	if not token:
		raise GraphMailError(_("the sign-in service answered without an access token"))
	try:
		lifetime = int(payload.get("expires_in") or 3599)
	except (TypeError, ValueError):
		lifetime = 3599
	_TOKENS[key] = (token, time.time() + lifetime)
	return token


# --------------------------------------------------------------------- send


def build_message(to: list[str], subject: str, html: str, reply_to: str | None = None) -> dict:
	message = {
		"subject": subject,
		"body": {"contentType": "HTML", "content": html},
		"toRecipients": [{"emailAddress": {"address": address}} for address in to],
	}
	if reply_to:
		message["replyTo"] = [{"emailAddress": {"address": reply_to}}]
	return {"message": message}


def send(s, *, to: list[str], subject: str, html: str, reply_to: str | None = None) -> dict:
	"""Send one message as the sender mailbox. Returns ``{"status", "attempts"}``.

	Raises ``GraphTimeout`` when an answer does not come in time and
	``GraphMailError`` for everything else Graph or the sign-in service said no to.
	"""
	from consilium.consilium_core.notification import MAX_RETRIES

	absent = missing(s)
	if absent:
		raise GraphMailError(_("Microsoft Graph is not fully set up: {0} missing").format(", ".join(absent)))
	body = json.dumps(build_message(to, subject, html, reply_to)).encode("utf-8")
	refreshed, throttled, attempts = False, 0, 0
	while True:
		attempts += 1
		token = get_token(s)
		status, headers, raw = _post(send_url(s), body, {
			"authorization": f"Bearer {token}",
			"content-type": "application/json",
			"accept": "application/json",
		}, _timeout(s))
		if status in (200, 202):
			return {"status": status, "attempts": attempts}
		if status == 401 and not refreshed:
			_TOKENS.pop(_token_key(s), None)
			refreshed = True
			continue
		if status in RETRYABLE and throttled < MAX_RETRIES:
			throttled += 1
			_sleep(_wait(headers, throttled))
			continue
		raise GraphMailError(_("Graph did not accept the message ({0})").format(_describe(status, raw)))


# ------------------------------------------------ the notification adapter


def _address(recipient: str) -> str | None:
	return frappe.db.get_value("User", recipient, "email")


def send_dispatch(dispatch, config: dict | None = None) -> dict:
	"""Send one Notification Dispatch now. Raises on any failure.

	The sender is always the configured mailbox: the application access policy
	that limits the registration to that mailbox would refuse any other. A
	channel's ``reply_to`` is honoured.
	"""
	from consilium.consilium_core.notification import as_html

	address = _address(dispatch.recipient)
	if not address:
		raise GraphMailError(_("The recipient has no email address."))
	return send(
		settings(),
		to=[address],
		subject=dispatch.rendered_subject or _("Notification"),
		html=as_html(dispatch.rendered_body),
		reply_to=(config or {}).get("reply_to") or None,
	)


def _deferred() -> bool:
	"""Inside a web request, unless a caller asked for an answer now."""
	return bool(getattr(frappe.local, "request", None)) and not frappe.flags.cns_mail_inline


def deliver(dispatch, config: dict | None = None) -> None:
	"""The ``email`` adapter's Graph route: send now, or hand to the queue."""
	if _deferred():
		frappe.enqueue(
			"consilium.consilium_core.integrations.graph_mail.deliver_queued",
			queue="short",
			enqueue_after_commit=True,
			dispatch=dispatch.name,
		)
		return
	send_dispatch(dispatch, config)


def deliver_queued(dispatch: str) -> None:
	"""Background job: send a dispatch that a web request handed on.

	The dispatch already reads as sent to the queue. A failure here marks it
	failed with the reason, which reopens it for the hourly retry — the same
	thing ``notification._reopen_refused_email`` does for a message the SMTP
	server refused after it was queued.
	"""
	if not frappe.db.exists("Notification Dispatch", dispatch):
		return
	row = frappe.get_doc("Notification Dispatch", dispatch)
	config = frappe.db.get_value("Notification Channel", row.channel, "configuration")
	if isinstance(config, str):
		config = json.loads(config) if config.strip() else {}
	try:
		send_dispatch(row, config or {})
	except Exception as exc:
		row.status = "Failed"
		row.failure_reason = f"{type(exc).__name__}: {exc}"
		row.save(ignore_permissions=True)
