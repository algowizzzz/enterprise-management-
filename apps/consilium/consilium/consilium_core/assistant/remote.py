"""AI-assisted answers: optional, off by default, server-side only.

When an administrator connects an endpoint in ``Assistant Settings``, the
built-in answer is still computed first — it is both the fallback and the
grounding. The server then sends the endpoint a prompt made of:

* a fixed instruction: answer only from the guidance given, say so when it
  does not cover the question, never invent features, keep it short, link only
  to the paths listed;
* the question;
* the **kind** of page (its generic name and path, never the record's title,
  which is record content);
* the asker's role names and the access findings the built-in answer made
  ("the user may not record a compliance review — it needs Compliance
  Reviewer"), which are derived from roles, not from any record;
* the guide sections retrieved for the question;
* and, only when the data-sharing mode is "Include visible record summary" and
  the record is neither sensitive, confidential nor restricted, the few summary
  fields the asker may read and the actions open to them on it.

What is never sent: the record's name or title in guidance mode, any field the
asker cannot read, anything of a restricted record, the asker's name or email,
other people's records, and the API key (it travels only as a header).

The call is made with the standard library (``urllib``) so there is no SDK to
vendor, from the server so no browser ever talks to an external service, and
with the configured timeout. Any failure — refusal, timeout, a non-2xx status,
an unreadable body, an empty answer — returns None and the built-in answer is
shown. Every attempt is written to ``AI Service Request`` first (what left the
platform) and completed with its outcome, because that record exists to answer
"what did we send out, and what came back".
"""

from __future__ import annotations

import re

from consilium.consilium_core.ai import client
from consilium.consilium_core.assistant import answer as answer_mod

ANTHROPIC = client.ANTHROPIC
OPENAI_COMPATIBLE = client.OPENAI_COMPATIBLE
SUMMARY_MODE = "Include visible record summary"
ANTHROPIC_VERSION = client.ANTHROPIC_VERSION

CAPABILITY = "Help assistant"

SYSTEM_PROMPT = """You are the help assistant for an enterprise governance, risk and policy portal.
Answer the user's question using only the guidance and context provided in the message. Rules:
- If the provided guidance does not answer the question, say you don't know and suggest asking an administrator. Do not guess.
- Never invent features, pages, buttons, roles or steps that the guidance does not mention.
- The access findings are authoritative for the actions they name: if they say the user may not do something, say so and name the role it needs. They list only this page's common tasks and do not rule out anything else: for an action they do not mention, give the guidance's steps and say the screen will confirm whether the user may do it.
- Keep the answer short: at most about 120 words, plain sentences or a short list.
- You may link only to the paths listed under "Links you may use", written as [label](/path). Do not write any other links or URLs.
- Do not use headings, tables or code blocks."""


#: The wire format, the call and the audit live in ``consilium_core.ai.client``
#: so the assistant and the analysis features share one audited path. These
#: names are kept because they are this module's public vocabulary.
AssistantAIError = client.AIServiceError
_endpoint_url = client.endpoint_url
_request = client.build_request
_parse = client.parse_response
call = client.call


def allowed_links(builtin: dict, ctx: dict) -> dict[str, str]:
	"""href → label for every link the built-in answer produced, plus the page itself."""
	links = {}
	for block in builtin["blocks"]:
		parts = block.get("parts") or [p for item in block.get("items", []) for p in item]
		for part in parts:
			if part.get("href"):
				links[part["href"]] = part["text"]
	for source in builtin["sources"]:
		if source.get("href"):
			links.setdefault(source["href"], source["title"].split(" › ")[-1])
	for step in builtin["next"]:
		if step.get("href"):
			links.setdefault(step["href"], step["label"])
	page = ctx.get("page")
	if page and not page.get("record_param"):
		links.setdefault(ctx["route"], page["title"])
	# A record's own link carries its reference; only offered when its summary may be shared.
	return {href: label for href, label in links.items() if href.startswith("/") and not href.startswith("//")}


def build_prompt(question: str, ctx: dict, builtin: dict, sharing: str) -> tuple[str, str, dict[str, str], bool]:
	"""The user message, the links it may use, and whether record data is in it."""
	page = ctx.get("page")
	lines = [f"Question: {question}", ""]
	lines.append(f"Page: {page['title'] if page else 'a portal page'} ({ctx['route']})")
	if page:
		lines.append(f"What the page is for: {page['purpose']}")
	lines.append("User's roles: " + (", ".join(ctx["roles"]) or "none beyond basic sign-in"))
	if builtin["facts"]["access"]:
		lines.append("")
		lines.append("Access findings (authoritative for the actions named; other actions are not ruled out):")
		lines.extend(f"- {fact}" for fact in builtin["facts"]["access"])

	record = ctx.get("record")
	includes_record = bool(
		sharing == SUMMARY_MODE and record and record.get("visible") and not record.get("restricted")
		and builtin["facts"]["record"]
	)
	if includes_record:
		lines.append("")
		lines.append("Record on screen (fields the user may read):")
		lines.extend(f"- {fact}" for fact in builtin["facts"]["record"])
	elif record:
		lines.append("")
		lines.append("The page shows a record; its contents are not shared with you.")

	lines.append("")
	lines.append("Guidance:")
	if builtin["source_texts"]:
		for source in builtin["source_texts"]:
			lines.append(f"### {source['label']}: {source['title']}")
			lines.append(source["text"])
	else:
		lines.append("(No guide section matched this question.)")
	direct = answer_mod.to_plain(builtin["blocks"])
	if direct:
		lines.append("")
		lines.append("Built-in answer already worked out from the page map (use it; do not contradict it):")
		lines.append(_strip_record_bits(direct, record) if not includes_record else direct)

	links = allowed_links(builtin, ctx)
	if includes_record and record.get("href"):
		links[record["href"]] = record.get("kind", "record")
	lines.append("")
	lines.append("Links you may use:")
	lines.extend(f"- [{label}]({href})" for href, label in links.items())
	if not links:
		lines.append("(none)")
	return SYSTEM_PROMPT, "\n".join(lines), links, includes_record


def _strip_record_bits(text: str, record: dict | None) -> str:
	"""Drop any line of the built-in answer that carries the record's identity."""
	if not record or not record.get("visible"):
		return text
	needles = [str(record.get("name") or ""), str(record.get("title") or "")]
	needles = [n for n in needles if n]
	kept = [line for line in text.splitlines()
	        if not any(n in line for n in needles) and "on this record" not in line]
	# Record-specific action lists are record content too.
	actions = record.get("actions") or {}
	record_lines = set(actions.get("available") or []) | {
		f"{a['label']} — {a['why']}" for a in actions.get("unavailable") or []} | set(actions.get("blockers") or [])
	return "\n".join(line for line in kept if line.lstrip("-0123456789. ") not in record_lines
	                 and not line.startswith(("Open to you on this record", "Offered at this stage",
	                                          "What stands in the way", "Nothing on this record")))


# ------------------------------------------------------------ AI text → blocks

_LINK = re.compile(r"\[([^\]\n]{1,120})\]\(([^)\s]{1,300})\)")
_BARE_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+")


def _inline(text: str, links: dict[str, str]) -> list[dict]:
	"""Text with markdown links; a link survives only if it is one we offered."""
	parts, pos = [], 0
	for match in _LINK.finditer(text):
		if match.start() > pos:
			parts.append({"text": text[pos:match.start()]})
		label, href = match.group(1), match.group(2)
		if href in links:
			parts.append({"text": label, "href": href})
		else:
			parts.append({"text": label})
		pos = match.end()
	if pos < len(text):
		parts.append({"text": text[pos:]})
	cleaned = []
	for part in parts:
		value = part["text"].replace("**", "").replace("`", "")
		if "href" not in part:
			value = _BARE_URL.sub("", value)
		if value:
			cleaned.append({**part, "text": value})
	return cleaned


def to_blocks(text: str, links: dict[str, str]) -> list[dict]:
	blocks: list[dict] = []
	current_list: dict | None = None
	for raw_line in text.strip().splitlines():
		line = raw_line.strip()
		if not line:
			current_list = None
			continue
		bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$", line)
		if bullet:
			kind = "ol" if line[0].isdigit() else "ul"
			if not current_list or current_list["type"] != kind:
				current_list = {"type": kind, "items": []}
				blocks.append(current_list)
			current_list["items"].append(_inline(bullet.group(1), links))
			continue
		current_list = None
		line = line.lstrip("#").strip()
		blocks.append({"type": "p", "parts": _inline(line, links)})
	return blocks[:30]


# -------------------------------------------------------------------- driver


def answer(question: str, ctx: dict, builtin: dict, settings) -> dict:
	"""Try the endpoint. Returns a dict describing the outcome; ``blocks`` is set
	only when an AI answer may be shown."""
	system, user_text, links, includes_record = build_prompt(question, ctx, builtin, settings.data_sharing)
	record = ctx.get("record") or {}

	def usable(text: str) -> list[dict]:
		blocks = to_blocks(text, links)
		if not blocks:
			raise AssistantAIError("the answer had no usable text")
		return blocks

	result = client.audited(
		settings,
		capability=CAPABILITY,
		system=system,
		user_text=user_text,
		# Restricted records are never included, so nothing above Internal leaves.
		classification="Internal",
		subject={"doctype": record.get("doctype"), "name": record.get("name")} if includes_record else None,
		accept=usable,
	)
	return {"blocks": result["value"], "error": result["error"], "service_request": result["service_request"]}
