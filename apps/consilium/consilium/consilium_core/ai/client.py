"""The one audited path to the administrator-configured AI endpoint.

Everything in the platform that talks to a model — the help assistant and the
governance analysis features — goes through ``audited()`` here, so there is
exactly one place that:

* builds the request for the configured wire format (the Anthropic Messages
  API, or the OpenAI-compatible shape an internal gateway usually speaks);
* writes an ``AI Service Request`` **before** anything leaves, holding exactly
  what is sent (less the API key, which travels only as a header), and
  completes it with what came back, how long it took and how it ended;
* turns every failure — refusal, timeout, a non-2xx status, an unreadable body,
  an empty answer, an answer the caller cannot use — into an outcome with no
  text, so the caller shows its deterministic result instead.

Why the standard library and not a vendor SDK. The platform installs with no
internet access and no compiler (CLAUDE.md rules 1 and 5), and it has to speak
to an internal gateway as readily as to the vendor's own service. ``urllib``
does both with nothing to vendor. The price is that the request and response
shapes are written out here by hand; they are small and they are tested
against a stand-in server.

What this module does **not** decide is what may be sent. ``policy.py`` makes
that decision (data-sharing mode, classification ceiling, sensitive records)
and the feature modules build their payloads through it. ``audited()`` records
the classification it is told and refuses nothing on its own — except that it
will not send while the endpoint is incompletely configured.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid

import frappe

ANTHROPIC = "Anthropic Messages API"
OPENAI_COMPATIBLE = "OpenAI-compatible (internal gateway)"

#: The Messages API's version header. It versions the request and response
#: shapes, not the model; this is the current and only stable value.
ANTHROPIC_VERSION = "2023-06-01"

#: A response larger than this is not an answer to any request made here.
MAX_RESPONSE_BYTES = 512 * 1024

SERVICE_REQUEST = "AI Service Request"


class AIServiceError(Exception):
	"""The endpoint did not produce a usable answer. The message says why."""


class AIRefused(AIServiceError):
	"""The model declined to answer (a policy refusal, not a fault)."""


# ------------------------------------------------------------------ the wire


def endpoint_url(settings) -> str:
	"""The full request URL for the configured format.

	An administrator gives a base address; the path for the format is added
	unless it is already there, so ``https://host``, ``https://host/v1`` and
	``https://host/v1/messages`` all work.
	"""
	base = (settings.endpoint_url or "").strip().rstrip("/")
	if settings.provider == ANTHROPIC:
		if base.endswith("/messages"):
			return base
		return base + "/messages" if base.endswith("/v1") else base + "/v1/messages"
	if base.endswith("/chat/completions"):
		return base
	return base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"


def build_request(settings, system: str, user_text: str, max_tokens: int | None = None) -> tuple[dict, bytes]:
	"""The HTTP request for the configured format, as (headers, body).

	One system instruction and one user turn: every caller here asks a single
	grounded question and reads a single answer. No prefill (current models
	reject it), no sampling parameters and no reasoning configuration: the
	model's defaults are what an administrator chose when naming the model, and
	a gateway in front of an older model would reject parameters it does not
	know.
	"""
	max_tokens = int(max_tokens or settings.max_tokens or 800)
	api_key = settings.get_password("api_key", raise_exception=False) if settings.get("api_key") else None
	headers = {"content-type": "application/json", "accept": "application/json"}
	if settings.provider == ANTHROPIC:
		headers["anthropic-version"] = ANTHROPIC_VERSION
		if api_key:
			headers["x-api-key"] = api_key
		body = {
			"model": settings.model,
			"max_tokens": max_tokens,
			"system": system,
			"messages": [{"role": "user", "content": user_text}],
		}
	else:
		if api_key:
			headers["authorization"] = f"Bearer {api_key}"
		body = {
			"model": settings.model,
			"max_tokens": max_tokens,
			"messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
		}
	return headers, json.dumps(body).encode("utf-8")


def parse_response(settings, payload: dict) -> str:
	"""The answer's text. Raises ``AIServiceError`` when there is none.

	On the Messages API the refusal check comes before reading any content,
	and only ``text`` blocks are read: a model that reasons first returns
	``thinking`` blocks ahead of the text, and those are not the answer.
	"""
	if settings.provider == ANTHROPIC:
		if payload.get("type") == "error":
			raise AIServiceError(str((payload.get("error") or {}).get("message") or "error response"))
		if payload.get("stop_reason") == "refusal":
			raise AIRefused("the model declined to answer")
		text = "".join(block.get("text", "") for block in payload.get("content") or []
		               if isinstance(block, dict) and block.get("type") == "text")
		if not text.strip() and payload.get("stop_reason") == "max_tokens":
			raise AIServiceError("the answer ran out of room before it began; raise the maximum length")
	else:
		choices = payload.get("choices") or []
		text = ((choices[0] or {}).get("message") or {}).get("content") if choices else ""
		if isinstance(text, list):  # some gateways return content parts
			text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
	text = (text or "").strip()
	if not text:
		raise AIServiceError("the endpoint returned an empty answer")
	return text


def call(settings, system: str, user_text: str, max_tokens: int | None = None) -> str:
	"""One request, with the configured timeout. Returns the answer text.

	Raises ``TimeoutError`` when the endpoint does not answer in time and
	``AIServiceError`` for everything else, so a caller needs two handlers.
	"""
	headers, body = build_request(settings, system, user_text, max_tokens)
	request = urllib.request.Request(endpoint_url(settings), data=body, headers=headers, method="POST")
	timeout = max(1, int(settings.timeout_seconds or 15))
	try:
		with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — admin-configured http(s) only
			raw = response.read(MAX_RESPONSE_BYTES)
	except urllib.error.HTTPError as e:
		detail = e.read(2000).decode("utf-8", "replace") if hasattr(e, "read") else ""
		raise AIServiceError(f"HTTP {e.code}: {detail[:300]}") from e
	except (TimeoutError, socket.timeout) as e:
		raise TimeoutError(f"no answer within {timeout} seconds") from e
	except urllib.error.URLError as e:
		if isinstance(e.reason, TimeoutError | socket.timeout):
			raise TimeoutError(f"no answer within {timeout} seconds") from e
		raise AIServiceError(f"could not reach the endpoint: {e.reason}") from e
	try:
		payload = json.loads(raw.decode("utf-8"))
	except ValueError as e:
		raise AIServiceError("the endpoint's answer was not JSON") from e
	if not isinstance(payload, dict):
		raise AIServiceError("the endpoint's answer had an unexpected shape")
	return parse_response(settings, payload)


# ---------------------------------------------------------------- the audit


def is_configured(settings) -> bool:
	"""An endpoint and a model are named. The key may legitimately be blank
	(a gateway that authenticates the server another way)."""
	return bool((settings.get("endpoint_url") or "").strip() and (settings.get("model") or "").strip())


def _new_request(capability: str, classification: str, subject: dict | None, context_sent: str):
	subject = subject or {}
	return frappe.get_doc({
		"doctype": SERVICE_REQUEST,
		"request_reference": uuid.uuid4().hex,
		"capability": capability,
		"requested_by": frappe.session.user,
		"requested_on": frappe.utils.now_datetime(),
		"context_sent": context_sent,
		"context_classification": classification,
		"subject_doctype": subject.get("doctype"),
		"subject_name": subject.get("name"),
		"status": "Sent",
	}).insert(ignore_permissions=True)


def record_refusal(capability: str, classification: str, reason: str, subject: dict | None = None) -> str:
	"""Record an analysis that was **not** sent, and why.

	Nothing left the platform, which is exactly what the row says. It exists
	so that an auditor asking "did anyone try to send a confidential record"
	finds the attempt and the control that stopped it.
	"""
	subject = subject or {}
	return frappe.get_doc({
		"doctype": SERVICE_REQUEST,
		"request_reference": uuid.uuid4().hex,
		"capability": capability,
		"requested_by": frappe.session.user,
		"requested_on": frappe.utils.now_datetime(),
		"context_sent": json.dumps({"sent": False, "reason": reason}, indent=1),
		"context_classification": classification,
		"subject_doctype": subject.get("doctype"),
		"subject_name": subject.get("name"),
		"response_received_on": frappe.utils.now_datetime(),
		"status": "Refused",
		"error_detail": reason[:2000],
		"duration_ms": 0,
	}).insert(ignore_permissions=True).name


def audited(settings, *, capability: str, system: str, user_text: str, classification: str,
            subject: dict | None = None, max_tokens: int | None = None, accept=None) -> dict:
	"""Send one request through the audit. Never raises for an endpoint fault.

	``accept``, if given, is called with the answer text and returns what the
	caller will use (blocks, parsed suggestions); raising ``AIServiceError``
	from it marks the request Failed, because an answer the platform cannot
	use is a failed answer even when the endpoint said 200.

	Returns ``{text, value, status, error, service_request, duration_ms}``;
	``value`` is set only when the answer may be shown.
	"""
	outcome = {"text": None, "value": None, "status": None, "error": None, "service_request": None, "duration_ms": 0}
	if not is_configured(settings):
		outcome.update(status="Not Configured", error="no AI endpoint is configured")
		return outcome

	context_sent = json.dumps({
		"endpoint": endpoint_url(settings),
		"format": settings.provider,
		"model": settings.model,
		"system": system,
		"user": user_text,
	}, indent=1)
	request_doc = _new_request(capability, classification, subject, context_sent)
	outcome["service_request"] = request_doc.name

	started = time.monotonic()
	status, response_text, error = "Succeeded", None, None
	try:
		response_text = call(settings, system, user_text, max_tokens)
		outcome["value"] = accept(response_text) if accept else response_text
		outcome["text"] = response_text
	except TimeoutError as e:
		status, error = "Timed Out", str(e)
	except AIRefused as e:
		status, error = "Refused", str(e)
	except AIServiceError as e:
		status, error = "Failed", str(e)
	except Exception as e:  # any other failure still falls back
		status, error = "Failed", f"{type(e).__name__}: {e}"
	if status != "Succeeded":
		outcome["value"] = None
	duration = int((time.monotonic() - started) * 1000)

	request_doc.reload()
	request_doc.response_received_on = frappe.utils.now_datetime()
	request_doc.response_payload = (response_text or "")[:20000]
	request_doc.status = status
	request_doc.error_detail = (error or "")[:2000] or None
	request_doc.duration_ms = duration
	request_doc.save(ignore_permissions=True)
	outcome.update(status=status, error=error, duration_ms=duration)
	return outcome
