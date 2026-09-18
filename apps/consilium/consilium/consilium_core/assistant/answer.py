"""The built-in answer: no model, no network, always available.

A question is first sorted into one of a handful of kinds that people actually
ask — "what can I do here", "how do I…", "why can't I…", "where do I find…",
"what does … mean", "what access do I have" — by plain patterns. Each kind has
a deterministic answer assembled from the page map, the asker's real
permissions and, on a record's page, the record's own state and actions. Then,
whatever the kind, the two or three guide sections that best match the question
are attached, each with a short quotation and a link to where it applies.

Anything that does not fit a kind is answered from the guides alone. When
nothing in the guides matches, the answer says so and offers the page's
suggested questions — it does not guess.

**Output is structure, not HTML.** An answer is a list of blocks (paragraphs
and lists) whose parts are text or ``{text, href}`` links. The browser builds
the DOM from that with ``textContent``, so nothing here can inject markup, and
the only links are the ones this module produced — same-origin paths from the
page map, a record's own page, or a guide section's portal page.

Alongside the blocks it returns ``facts``: the same findings as plain
sentences, split into those about the asker's access (safe to share with an AI
endpoint under "Guidance only") and those about the record on screen (shared
only when an administrator allows a record summary). ``remote.py`` builds its
prompt from those, never from the page.
"""

from __future__ import annotations

import re

import frappe

from consilium.consilium_core.assistant import context as ctxmod
from consilium.consilium_core.assistant import corpus
from consilium.consilium_core.assistant import pages as page_map

_WHAT_HERE = re.compile(
	r"what can i do( here| on this page| now)?\b|what (is|'s) this page|what does this page|"
	r"what is (this|here) for|what('s| is) this for|where am i|what am i looking at|"
	r"^help\??$|^\?$|what('s| is) (on )?this (page|screen)|how does this page work"
)
_MY_ACCESS = re.compile(
	r"\b(my|what) (roles?|access|permissions?)\b|what roles do i|which roles do i|who am i|what am i allowed"
)
_WHY_CANT = re.compile(
	r"why (can'?t|cannot|can not|am i (unable|not able|blocked)|is(n'?t| not)|don'?t i|do i not|was .* refused)|"
	r"\bi can'?t\b|\bi cannot\b|\bunable to\b|\bnot allowed\b|\bno access\b|\baccess denied\b|"
	r"\b(disabled|greyed|grayed)\b|\bwhy (was|is) .* (refused|blocked|rejected)"
)
_WHERE = re.compile(
	r"^where (do|can|is|are|would|should)|\bwhere to (find|see)|\bhow do i (get to|find|navigate)|"
	r"\bwhich page\b|\bwhere('s| is) the\b"
)
_DEFINE = (
	re.compile(r"what (?:does|do) (?:the (?:term|word) )?[\"']?(.+?)[\"']? (?:mean|stand for)\b"),
	re.compile(r"(?:meaning|definition) of [\"']?(.+?)[\"']?\s*\??$"),
	re.compile(r"^define [\"']?(.+?)[\"']?\s*\??$"),
	re.compile(r"^what(?:'s| is| are) (?:an? |the )?[\"']?(.+?)[\"']?\s*\??$"),
)
_HOW = re.compile(
	r"^how\b|\bhow (do|can|should|would) i\b|\bhow to\b|^can i\b|^could i\b|\bsteps to\b|"
	r"\bi (want|need) to\b|^is it possible"
)

#: Two words that stand for the whole page rather than a term.
_PAGE_WORDS = {"this page", "this screen", "here", "this", "it", "that"}


# ------------------------------------------------------------------- blocks


def _text(value) -> dict:
	return {"text": str(value)}


def _link(label, href) -> dict:
	return {"text": str(label), "href": href}


def _p(*parts) -> dict:
	return {"type": "p", "parts": [p if isinstance(p, dict) else _text(p) for p in parts]}


def _ul(items) -> dict:
	return {"type": "ul", "items": [[p if isinstance(p, dict) else _text(p) for p in (item if isinstance(item, list) else [item])] for item in items]}


def _ol(items) -> dict:
	block = _ul(items)
	block["type"] = "ol"
	return block


def to_plain(blocks: list[dict]) -> str:
	"""An answer as plain text, for the audit log and for AI mode's prompt."""
	lines = []
	for block in blocks:
		if block["type"] == "p":
			lines.append("".join(part["text"] for part in block["parts"]))
		else:
			for n, item in enumerate(block["items"], 1):
				bullet = f"{n}." if block["type"] == "ol" else "-"
				lines.append(f"{bullet} " + "".join(part["text"] for part in item))
	return "\n".join(lines)


# ------------------------------------------------------------------ helpers


def classify(question: str) -> str:
	q = question.lower().strip()
	if _MY_ACCESS.search(q):
		return "my_access"
	if _WHAT_HERE.search(q):
		return "what_here"
	if _WHY_CANT.search(q):
		return "why_cant"
	if _WHERE.search(q):
		return "where"
	if define_phrase(q):
		return "define"
	if _HOW.search(q):
		return "how_to"
	return "search"


def define_phrase(q: str) -> str | None:
	for pattern in _DEFINE:
		match = pattern.search(q.lower().strip())
		if match:
			phrase = match.group(1).strip(" ?.!\"'")
			if phrase and phrase not in _PAGE_WORDS and len(phrase.split()) <= 6:
				return phrase
	return None


def _page_href(route: str | None, ctx: dict) -> str | None:
	"""A link target the asker can use: installed portal pages and the workspace."""
	if not route:
		return None
	if route.startswith("/app"):
		return route if ctx["desk"] else None
	base = page_map.normalise_route(route)
	if base in ctx["installed"] or base not in page_map.PAGES:
		return route
	return None


def _task_candidates(ctx: dict) -> list[tuple[str, dict]]:
	"""(route, task) for every task the asker could be asking about."""
	out = []
	for route, page in page_map.PAGES.items():
		# Administrator tasks stay in: "you can't, it needs an administrator
		# role" is a better answer to a non-administrator than silence.
		if route != ctx["route"] and route not in ctx["installed"]:
			continue
		for task in page.get("tasks", []):
			out.append((route, task))
	for task in page_map.GLOBAL_TASKS:
		out.append((None, task))
	return out


def match_task(question: str, ctx: dict) -> tuple[str | None, dict] | None:
	"""The task a question is most likely about, favouring the current page."""
	wanted = set(corpus.tokens(question))
	if not wanted:
		return None
	best, best_score = None, 0.0
	for route, task in _task_candidates(ctx):
		label = set(corpus.tokens(task["label"]))
		keys = set(corpus.tokens(task["keywords"]))
		score = 2.0 * len(wanted & label) + 1.0 * len(wanted & (keys - label))
		if not score:
			continue
		if route == ctx["route"]:
			score *= 1.6
		elif route is None:
			score *= 0.9
		if score > best_score:
			best, best_score = (route, task), score
	# One shared keyword ("answer", "review") is not enough to claim a match.
	return best if best_score >= 3.0 else None


def _area_named(question: str, ctx: dict, index) -> tuple[str, dict] | None:
	"""The working area a question names ("why can't I see policies"), if any."""
	allow = (lambda c: c["kind"] == "page" and c["href"] in page_map.AREA_ROUTES
	         and page_map.PAGES[c["href"]].get("doctype") and c["href"] in ctx["installed"])
	ranked = index.search(question, allow=allow, limit=1)
	if ranked and ranked[0][0] >= 1.5:
		route = ranked[0][1]["href"]
		return route, page_map.PAGES[route]
	return None


def _record_sentence(record: dict) -> dict:
	if not record["visible"]:
		# Identical for "no such record" and "not yours to see", by design.
		article = "an" if record["kind"][:1] in "aeiou" else "a"
		return _p(
			f"The address names {article} {record['kind']} I can't show you: either there is no such "
			"record, or you don't have access to it. If you expected to see it, ask your administrator."
		)
	parts = [f"You are looking at the {record['kind']} “{record['title']}” ({record['name']})."]
	if record.get("state"):
		parts.append(f" Where it stands: {record['state']}.")
	return _p(*parts)


def _record_actions_blocks(record: dict) -> list[dict]:
	actions = record.get("actions")
	if not record.get("visible") or not actions:
		return []
	blocks = []
	if actions["available"]:
		blocks.append(_p("Open to you on this record now:"))
		blocks.append(_ul(actions["available"]))
	else:
		blocks.append(_p("Nothing on this record is waiting on you at the moment."))
	if actions["unavailable"]:
		blocks.append(_p("Offered at this stage, but not to you:"))
		blocks.append(_ul([f"{a['label']} — {a['why']}" for a in actions["unavailable"]]))
	if actions.get("blockers"):
		blocks.append(_p("What stands in the way:"))
		blocks.append(_ul(actions["blockers"]))
	return blocks


def _record_facts(record: dict | None) -> list[str]:
	if not record or not record.get("visible"):
		return []
	facts = [f"The record on screen is a {record['kind']}."]
	for item in (record.get("summary") or {}).values():
		facts.append(f"{item['label']}: {item['value']}")
	actions = record.get("actions") or {}
	if actions.get("available"):
		facts.append("Actions open to the user on it now: " + "; ".join(actions["available"]))
	for entry in actions.get("unavailable") or []:
		facts.append(f"Not open to the user: {entry['label']} ({entry['why']})")
	if actions.get("blockers"):
		facts.append("Blocking: " + "; ".join(actions["blockers"]))
	return facts


def _task_answer(route: str | None, task: dict, ctx: dict, access_facts: list[str]) -> list[dict]:
	ok, why = ctxmod.check_requirement(task.get("requires") or {}, ctx)
	blocks = []
	elsewhere = route and route != ctx["route"]
	page = page_map.PAGES.get(route) if route else None
	if ok:
		access_facts.append(f"The user may: {task['label']}.")
		blocks.append(_p(f"To {task['label'][0].lower() + task['label'][1:]}:"))
		blocks.append(_ol(task["steps"]))
		if elsewhere and page:
			listing = page_map.LIST_FOR_RECORD_PAGE.get(route)
			if listing:
				href = _page_href(listing, ctx)
				title = page_map.PAGES[listing]["title"]
				blocks.append(_p(f"This is done on a {page['title'].lower()}'s own page — open one from the ",
				                 _link(title, href) if href else title, "."))
			else:
				href = _page_href(route, ctx)
				blocks.append(_p("This is done on ", _link(page["title"], href) if href else page["title"], "."))
	else:
		access_facts.append(f"The user may not: {task['label']} — {why}.")
		blocks.append(_p(
			f"You can't {task['label'][0].lower() + task['label'][1:]} with your current access: {why}."
		))
		if task.get("why"):
			blocks.append(_p(task["why"]))
		blocks.append(_p("If you need it, ask your administrator."))
	return blocks


def _page_tasks_blocks(ctx: dict, access_facts: list[str]) -> list[dict]:
	"""The page's tasks, split by whether the asker may do them.

	A task with no requirement of its own (explaining a tab, say) is neither a
	promise nor a refusal, so it is offered as something to ask about. On a
	record whose owning module has said which actions are open, that module's
	answer is the authority; the page's tasks are then only offered as topics,
	so the two lists cannot disagree.
	"""
	page = ctx["page"]
	if not page or not page.get("tasks"):
		return []
	record = ctx.get("record") or {}
	authoritative = bool(record.get("visible") and record.get("actions"))
	can, cannot, topics = [], [], []
	for task in page["tasks"]:
		requires = task.get("requires") or {}
		href = _page_href(task.get("href"), ctx) if task.get("href") and task["href"] != ctx["route"] else None
		if authoritative or not requires:
			topics.append(task["label"])
			continue
		ok, why = ctxmod.check_requirement(requires, ctx)
		if ok:
			can.append([_link(task["label"], href)] if href else [_text(task["label"])])
			access_facts.append(f"On this page the user may: {task['label']}.")
		else:
			cannot.append(f"{task['label']} — {why}")
			access_facts.append(f"On this page the user may not: {task['label']} — {why}.")
	blocks = []
	if can:
		blocks.append(_p("What you can do here:"))
		blocks.append(_ul(can))
	if cannot:
		blocks.append(_p("Not open to you here:"))
		blocks.append(_ul(cannot))
	if topics:
		blocks.append(_p("You can also ask me how to: " + "; ".join(t[0].lower() + t[1:] for t in topics) + "."))
	return blocks


# ------------------------------------------------------------------ sources


def sources_for(question: str, ctx: dict, index: corpus.Index, *, limit: int = 3) -> list[dict]:
	can_read_articles = bool(frappe.has_permission("Guide Article", "read")) if frappe.db.table_exists(
		"Guide Article") else False

	def allow(chunk):
		if chunk["kind"] != "guide":
			return False
		if chunk["audience"] == "admin" and not ctx["is_admin"]:
			return False
		if chunk["source"] == "guide-article" and not can_read_articles:
			return False
		return True

	module = (ctx["page"] or {}).get("module")

	def boost(chunk):
		if chunk.get("href") and page_map.normalise_route(chunk["href"]) == ctx["route"]:
			return 1.3
		if module and module.lower() in (chunk["title"] + chunk.get("extra", "")).lower():
			return 1.1
		return 1.0

	ranked = index.search(question, allow=allow, boost=boost, limit=limit + 2)
	if not ranked:
		return []
	top = ranked[0][0]
	if top < 2.5:
		return []
	query_tokens = corpus.tokens(question)
	out = []
	for score, chunk in ranked:
		if score < top * 0.45 or len(out) >= limit:
			break
		out.append({
			"id": chunk["id"],
			"label": chunk["label"],
			"title": chunk["title"],
			"excerpt": corpus.excerpt(chunk["text"], query_tokens),
			"href": _page_href(chunk.get("href"), ctx),
			"text": corpus.plain(chunk["text"])[:1800],
		})
	return out


def _next_steps(question: str, ctx: dict, links: list[tuple[str, str]]) -> list[dict]:
	out, seen = [], set()
	for label, href in links:
		if href and href not in seen:
			seen.add(href)
			out.append({"label": label, "href": href})
	asked = question.strip().lower().rstrip("?")
	for starter in (ctx["page"] or {}).get("starters", [])[:4]:
		if starter.lower().rstrip("?") != asked and len(out) < 5:
			out.append({"label": starter, "ask": starter})
	return out


# ------------------------------------------------------------------- answer


def builtin(question: str, ctx: dict) -> dict:
	index = corpus.get_index()
	intent = classify(question)
	blocks: list[dict] = []
	access_facts: list[str] = []
	links: list[tuple[str, str]] = []
	record = ctx.get("record")
	page = ctx["page"]

	if intent == "my_access":
		roles = ctx["roles"]
		blocks.append(_p("Your roles: " + (", ".join(roles) if roles else "none beyond basic sign-in") + "."))
		access_facts.append("The user's roles: " + (", ".join(roles) or "none") + ".")
		readable = []
		for route in page_map.AREA_ROUTES:
			area = page_map.PAGES[route]
			if route not in ctx["installed"]:
				continue
			if area.get("admin_only") and not ctx["is_admin"]:
				continue
			if area.get("doctype") and not ctxmod.check_requirement(
					{"doctype": area["doctype"], "ptype": "read"}, ctx)[0]:
				continue
			readable.append((area["title"], route))
		if readable:
			blocks.append(_p("Areas you can open:"))
			blocks.append(_ul([[_link(title, route)] for title, route in readable]))
		blocks.append(_p("What each role allows is in the user guide's “Roles at a glance”. "
		                 "Your administrator assigns roles."))

	elif intent == "what_here":
		if page:
			blocks.append(_p(f"This is {page['title']}. {page['purpose']}"))
			if page.get("admin_only") and not ctx["is_admin"]:
				blocks.append(_p("This area is for administrators; your account does not hold an administrator role."))
		else:
			blocks.append(_p(f"I don't have a description of “{ctx['page_title']}” yet. The guides below may help."))
		if record:
			blocks.append(_record_sentence(record))
			blocks.extend(_record_actions_blocks(record))
		blocks.extend(_page_tasks_blocks(ctx, access_facts))

	elif intent == "why_cant":
		handled = False
		if record and record.get("visible") and record.get("actions"):
			wanted = set(corpus.tokens(question))
			for entry in record["actions"]["unavailable"]:
				if wanted & set(corpus.tokens(entry["label"])):
					# Record-derived, so it is shared (in AI mode) only with the
					# record summary; the summary facts already carry it.
					blocks.append(_p(f"“{entry['label']}” is not open to you on this record: {entry['why']}."))
					handled = True
					break
			if not handled:
				for label in record["actions"]["available"]:
					if wanted & set(corpus.tokens(label)):
						blocks.append(_p(f"“{label}” is open to you on this record now."))
						handled = True
						break
			if not handled:
				for label in record["actions"].get("not_offered") or []:
					if wanted & set(corpus.tokens(label)):
						stands = f" (it is {record['state']})" if record.get("state") else ""
						blocks.append(_p(f"“{label}” is not offered at this record's current stage{stands}."))
						handled = True
						break
			if record["actions"].get("blockers") and handled:
				blocks.append(_p("What stands in the way:"))
				blocks.append(_ul(record["actions"]["blockers"]))
		if not handled:
			found = match_task(question, ctx)
			if found:
				route, task = found
				ok, _why = ctxmod.check_requirement(task.get("requires") or {}, ctx)
				if ok and task.get("requires"):
					blocks.append(_p(
						"Your access allows this. If it is still refused or not offered, the reason is the "
						"record's stage or something that has to be done first — the refusal message names the rule."
					))
				blocks.extend(_task_answer(route, task, ctx, access_facts))
				if task.get("href"):
					links.append((task["label"], _page_href(task["href"], ctx)))
				handled = True
		if not handled:
			area = _area_named(question, ctx, index)
			if area:
				route, target = area
				ok, why = ctxmod.check_requirement({"doctype": target["doctype"], "ptype": "read"}, ctx)
				if ok:
					blocks.append(_p("You do have access to ", _link(target["title"], route), "."))
					blocks.append(_p(
						"If a particular record is missing from it, it may be restricted (confidential "
						"documents and sensitive escalations are hidden from anyone without the right), or "
						"outside the units your administrator has limited you to."
					))
					links.append((target["title"], route))
				else:
					blocks.append(_p(f"You can't open {target['title']}: {why}. Ask your administrator if you need it."))
					access_facts.append(f"The user may not open {target['title']}: {why}.")
				handled = True
		if not handled:
			roles = ctx["roles"]
			blocks.append(_p(
				"What you can see and do depends on your roles, and on any record-level restrictions "
				"your administrator has set. Your roles: " + (", ".join(roles) if roles else "none beyond basic sign-in") + "."
			))
			blocks.append(_p(
				"Some records are restricted and do not appear at all without a particular role. "
				"A refused save names the rule that refused it. Ask your administrator to check your access."
			))
		if record and not record.get("visible"):
			blocks.insert(0, _record_sentence(record))

	elif intent == "where":
		allow = (lambda c: c["kind"] == "page" and (c["audience"] == "all" or ctx["is_admin"])
		         and c["href"] in ctx["installed"])
		ranked = index.search(question, allow=allow, limit=3)
		if ranked and ranked[0][0] >= 1.5:
			top = ranked[0][0]
			hits = [c for s, c in ranked if s >= top * 0.75]
			blocks.append(_p("You'll find that here:"))
			items = []
			for chunk in hits:
				target = page_map.PAGES[chunk["href"]]
				ok, why = (True, None)
				if target.get("doctype") and not target.get("record_param"):
					ok, why = ctxmod.check_requirement({"doctype": target["doctype"], "ptype": "read"}, ctx)
				note = "" if ok else f" (not open to you: {why})"
				items.append([_link(target["title"], chunk["href"]), _text(f" — {target['purpose'].split('. ')[0]}.{note}")])
				links.append((target["title"], chunk["href"]))
			blocks.append(_ul(items))
		else:
			found = match_task(question, ctx)
			if found:
				blocks.extend(_task_answer(*found, ctx, access_facts))

	elif intent == "define":
		phrase = define_phrase(question)
		entry = corpus.define(index, phrase) if phrase else None
		if entry:
			origin = "the policy office's glossary" if entry["source"] == "Glossary Term" else "the glossary"
			blocks.append(_p(_text(entry["term"]), _text(": "), _text(entry["definition"])))
			blocks.append(_p(f"(From {origin}.)"))
		else:
			intent = "search"

	elif intent == "how_to":
		found = match_task(question, ctx)
		if found:
			route, task = found
			blocks.extend(_task_answer(route, task, ctx, access_facts))
			if task.get("href") and task["href"] != ctx["route"]:
				href = _page_href(task["href"], ctx)
				if href:
					links.append((task["label"], href))

	sources = sources_for(question, ctx, index)
	if not blocks:
		intent = intent if intent != "define" else "search"
		if sources:
			blocks.append(_p("Here is what the guides say about that:"))
		else:
			blocks.append(_p(
				"I couldn't find that in the guides. Try asking in other words, or ask about this "
				"page — for example “What can I do here?”."
			))
	for source in sources:
		if source.get("href"):
			links.append((source["title"].split(" › ")[-1], source["href"]))
	return {
		"intent": intent,
		"blocks": blocks,
		"sources": [{k: s[k] for k in ("id", "label", "title", "excerpt", "href")} for s in sources],
		"source_texts": sources,
		"next": _next_steps(question, ctx, links),
		"facts": {"access": access_facts, "record": _record_facts(record)},
	}
