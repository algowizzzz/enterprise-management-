"""The portal's help assistant: two endpoints behind the floating Help button.

    POST /api/method/consilium.consilium_core.assistant.ask
         question: str, context: {route, query, title, page_context}
    GET  /api/method/consilium.consilium_core.assistant.suggestions
         context: {route, query, title, page_context}

Both are for signed-in people only; the widget is not shown to a visitor.

How a question is answered:

1. The context the browser sent is reduced to hints and re-established on the
   server (``context.py``): the page, the asker's roles, and — only through the
   permission engine — the record on screen, its state and the actions open to
   the asker on it.
2. The built-in answer is always worked out (``answer.py``), from the page map
   (``pages.py``) and a BM25 index over the guides (``corpus.py``). It needs no
   network and no model, which is the point: the platform runs where there is
   no internet access.
3. If an administrator has connected an AI endpoint (``Assistant Settings``),
   the server asks it to phrase an answer grounded in exactly what step 2
   found (``remote.py``). On any failure the built-in answer is shown instead.
4. Every question is logged to ``Assistant Interaction``, which is also what
   the per-person hourly limit counts.

The limit exists to protect a paid endpoint, but it applies to built-in answers
too: one limit is simpler to explain than two, and 30 an hour is far beyond
what a person reading the answers asks.
"""

from __future__ import annotations

import time

import frappe
from frappe import _

from consilium.consilium_core.assistant import answer as answer_mod
from consilium.consilium_core.assistant import context as ctxmod
from consilium.consilium_core.assistant import remote

MAX_QUESTION_LENGTH = 500
DEFAULT_RATE_LIMIT = 30
SETTINGS = "Assistant Settings"
LOG = "Assistant Interaction"


class AssistantRateLimited(frappe.TooManyRequestsError):
	"""The asker has used this hour's questions. HTTP 429."""


def _require_signed_in() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Sign in to use the help assistant."), frappe.PermissionError)


def get_settings():
	"""The settings, or a stand-in with every default when the DocType is not
	migrated yet — the assistant must work on a site that has never seen it."""
	if frappe.db.exists("DocType", SETTINGS):
		return frappe.get_cached_doc(SETTINGS)
	return frappe._dict(ai_enabled=0, rate_limit_per_hour=DEFAULT_RATE_LIMIT, data_sharing="Guidance only")


def _check_rate(settings) -> None:
	limit = int(settings.get("rate_limit_per_hour") or DEFAULT_RATE_LIMIT)
	if not frappe.db.exists("DocType", LOG):
		return
	since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)
	used = frappe.db.count(LOG, {"user": frappe.session.user, "asked_on": [">", since]})
	if used >= limit:
		frappe.throw(
			_("You have asked {0} questions in the last hour, which is the limit. Please try again later.").format(used),
			AssistantRateLimited,
			title=_("Question Limit Reached"),
		)


def _log(question: str, ctx: dict, result: dict, *, mode: str, ai_used: bool, provider: str | None,
         fallback_reason: str | None, service_request: str | None, latency_ms: int) -> str | None:
	if not frappe.db.exists("DocType", LOG):
		return None
	record = ctx.get("record") or {}
	# A restricted record is never named in the log: its readers (administrators
	# and audit) may not be cleared to know it exists.
	named = record.get("visible") and not record.get("restricted")
	doc = frappe.get_doc({
		"doctype": LOG,
		"user": frappe.session.user,
		"asked_on": frappe.utils.now_datetime(),
		"route": ctx["route"],
		"subject_doctype": record.get("doctype") if named else None,
		"subject_name": record.get("name") if named else None,
		"intent": result.get("intent"),
		"question": question,
		"answer": answer_mod.to_plain(result["blocks"])[:20000],
		"sources": ", ".join(s["id"] for s in result.get("sources") or [])[:1000],
		"mode": mode,
		"ai_used": 1 if ai_used else 0,
		"provider": provider,
		"fallback_reason": (fallback_reason or "")[:1000] or None,
		"ai_service_request": service_request,
		"latency_ms": latency_ms,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def _public(result: dict) -> dict:
	"""What the browser receives: never the retrieved section texts or the facts."""
	return {
		"intent": result["intent"],
		"blocks": result["blocks"],
		"sources": result["sources"],
		"next": result["next"],
	}


@frappe.whitelist(methods=["POST"])
def ask(question: str | None = None, context=None) -> dict:
	"""Answer one question about the page the asker is on."""
	_require_signed_in()
	question = " ".join((question or "").split())[:MAX_QUESTION_LENGTH]
	if not question:
		frappe.throw(_("Type a question first."), title=_("No Question"))

	settings = get_settings()
	_check_rate(settings)

	started = time.monotonic()
	ctx = ctxmod.resolve(context)
	result = answer_mod.builtin(question, ctx)

	mode, ai_used, provider, fallback_reason, service_request, notice = "Built-in", False, None, None, None, None
	if settings.get("ai_enabled"):
		mode, provider = "AI-assisted", settings.get("provider")
		outcome = remote.answer(question, ctx, result, settings)
		service_request = outcome["service_request"]
		if outcome["blocks"]:
			ai_used = True
			result = {**result, "blocks": outcome["blocks"]}
		else:
			fallback_reason = outcome["error"] or "no usable answer"
			notice = _("The AI service did not answer, so this is the built-in answer.")

	latency_ms = int((time.monotonic() - started) * 1000)
	interaction = _log(question, ctx, result, mode=mode, ai_used=ai_used, provider=provider,
	                   fallback_reason=fallback_reason, service_request=service_request, latency_ms=latency_ms)
	out = _public(result)
	out.update({
		"mode": "ai" if ai_used else "builtin",
		"notice": notice,
		"interaction": interaction,
	})
	return out


@frappe.whitelist(methods=["GET"])
def suggestions(context=None) -> dict:
	"""Starter questions for the page, and which answer mode is in force."""
	_require_signed_in()
	given = ctxmod.parse_input(context)
	from consilium.consilium_core.assistant import pages as page_map  # noqa: PLC0415

	route = page_map.normalise_route(given["route"])
	page = page_map.PAGES.get(route)
	starters = list((page or {}).get("starters") or ["What can I do here?", "What access do I have?"])
	if page and page.get("admin_only") and not ctxmod.is_admin():
		starters = ["What can I do here?", "What access do I have?"]
	settings = get_settings()
	return {
		"page": page["title"] if page else None,
		"starters": starters[:4],
		"mode": "ai" if settings.get("ai_enabled") else "builtin",
	}
