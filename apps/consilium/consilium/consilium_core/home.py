"""The home page: one card per thing a person comes to the portal for.

The page used to open on the organisation's banner, four tiles and a dashboard
of forum counts, and then run into a long guide written for someone who had
never seen the system. People who use it every day scrolled past both. Home now
answers, in order, what enterprise service and records platforms answer on
theirs: who am I and what is waiting on me, what can I start, how does each
area I work in stand, what did I look at last, and where do I learn more.

Everything here is assembled on the server, so the figures are in the page as
it arrives (no counters spinning up) and each is computed by the same rule the
page it links to applies:

* a module figure counts, with the viewer's own read permission, exactly the
  filter the linked list page applies for that address (``/forums?standing=
  review`` is ``requires_review = 1`` here and in forums.html);
* the My work summary is ``inbox.collect``, the function /tasks is drawn from;
* the Insights figures are ``ai.gaps.detection``, the payload /governance-gaps
  draws its headline counts from.

A module appears only when its menu does: the module list is built from
``navigation.cns_nav``, which applies the same permission checks as the pages,
so a card never offers what the viewer cannot open.

Recently viewed and pinned records are kept in the browser (see
consilium.js), not here: they are a convenience of one person on one device,
and keeping them out of the database means opening a record writes nothing.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.utils import get_fullname, getdate, nowdate

FORUM = "Governance Forum"
DOCUMENT = "Governing Document"
MATTER = "Escalation Matter"

#: A date comparison on a column that may be empty needs a lower bound: the
#: framework reads an empty date as the earliest possible day for "<", so a
#: record with no review date would otherwise count as overdue. The list pages
#: carry the same bound (forums.html, policies.html).
HAS_REVIEW_DATE = ["next_review_on", ">", "1900-01-01"]

#: The inbox's kinds, grouped as the "By kind" views of /tasks group them
#: (KIND_VIEWS in tasks.html), so a chip opens the view that shows its items.
TASK_VIEWS = {
	"approval": "approvals", "second_signature": "approvals", "formation_step": "approvals",
	"forum_compliance": "reviews", "forum_review": "reviews", "document_review": "reviews",
	"escalation_review": "reviews",
	"attestation": "attestations",
	"escalation_queue": "unowned",
}

#: How many of the most urgent items the My work card lists.
TOP_ITEMS = 5


# ------------------------------------------------------------------ helpers


def _count(doctype: str, filters: list) -> int:
	"""Records of a type matching ``filters``, as the viewer may read them.

	``get_list`` applies the same permission rules as the list pages' own
	requests (the REST list and the report-view count), so the figure is the
	number the linked page shows.
	"""
	return len(frappe.get_list(doctype, filters=filters, pluck="name", limit_page_length=0))


def _menus() -> dict[str, dict]:
	from consilium.consilium_core.navigation import cns_nav

	return {menu["id"]: menu for menu in cns_nav("home")}


def _menu_links(menu: dict | None, skip: set[str], limit: int = 4) -> list[dict]:
	"""A module card's links: its menu's items, less those its figures open."""
	if not menu:
		return []
	links = []
	for group in menu["groups"]:
		for item in group["items"]:
			if item["url"] in skip or any(link["url"] == item["url"] for link in links):
				continue
			links.append({"label": item["label"], "url": item["url"], "icon": item.get("icon")})
	return links[:limit]


def _date_label(value: str | None) -> str:
	"""A due date as people read it: 3 Oct 2026."""
	if not value:
		return ""
	day = getdate(value)
	return f"{day.day} {day.strftime('%b %Y')}"


def _figure(label: str, value: int | None, url: str, tone: str = "") -> dict:
	return {"label": label, "value": value, "url": url, "tone": tone if value else ""}


# ------------------------------------------------------------------ sections


def greeting(user: str) -> dict:
	"""Good morning / afternoon / evening, in the zone the person reads times in."""
	from consilium.consilium_core.branding import viewer_time_zone

	try:
		now = datetime.now(ZoneInfo(viewer_time_zone()))
	except Exception:  # an unknown zone name: the server's own clock still greets
		now = datetime.now()
	part = _("Good morning") if now.hour < 12 else _("Good afternoon") if now.hour < 18 else _("Good evening")
	return {
		"salutation": part,
		"name": get_fullname(user) or user,
		"date": f"{now.strftime('%A')} {now.day} {now.strftime('%B %Y')}",
	}


def my_work(user: str) -> dict:
	"""The My work card: counts by kind, and the most urgent items."""
	from consilium.consilium_core import inbox

	items = inbox.collect(user)
	groups = []
	for group in inbox.grouped(items):
		view = TASK_VIEWS.get(group["kind"])
		groups.append({
			"kind": group["kind"],
			"label": group["label"],
			"count": len(group["items"]),
			"overdue": group["overdue"],
			"url": f"/tasks?show={view}" if view else "/tasks",
		})
	labels = {group["kind"]: group["label"] for group in groups}
	top = [
		{
			"title": item["title"],
			"url": item["url"],
			"kind": labels.get(item["kind"], ""),
			"context": item.get("context") or "",
			"due_on": item["due_on"],
			"due_label": _date_label(item["due_on"]),
			"overdue": item["overdue"],
			"due_soon": item["due_soon"],
		}
		for item in items[:TOP_ITEMS]
	]
	return {
		"count": len(items),
		"overdue": sum(1 for item in items if item["overdue"]),
		"due_soon": sum(1 for item in items if item["due_soon"]),
		"groups": groups,
		"top": top,
	}


def quick_actions() -> list[dict]:
	"""The things a person can start from home, each only if they may."""
	actions = [
		(MATTER, "/raise-escalation", _("Raise an escalation"),
			_("Describe what happened; severity and forums are proposed for you."), "bi-exclamation-diamond"),
		("Document Intake Request", "/policy-intake", _("Request a policy or change"),
			_("Ask for a new document, a change or a retirement."), "bi-file-earmark-plus"),
		("Committee Formation Request", "/create-forum", _("Request a new forum"),
			_("A guided request, evaluated before anything is created."), "bi-people"),
	]
	return [
		{"url": url, "label": label, "description": description, "icon": icon}
		for doctype, url, label, description, icon in actions
		if frappe.has_permission(doctype, "create")
	]


def modules() -> list[dict]:
	"""One card per area the viewer may open, with its live figures."""
	menus = _menus()
	today = nowdate()
	out = []

	if "governance" in menus and frappe.has_permission(FORUM, "read"):
		figures = [
			_figure(_("Active forums"), _count(FORUM, [["is_active", "=", 1]]), "/forums"),
			_figure(_("Awaiting compliance review"), _count(FORUM, [["requires_review", "=", 1]]),
				"/forums?standing=review", "warning"),
			_figure(_("Review overdue"), _count(FORUM, [HAS_REVIEW_DATE, ["next_review_on", "<", today],
				["is_active", "=", 1]]), "/forums?standing=overdue", "danger"),
		]
		out.append({
			"id": "governance", "title": _("Governance"), "url": "/forums", "icon": "bi-people",
			"description": _("Forums and committees: members, meetings, decisions and standing."),
			"figures": figures,
			"links": _menu_links(menus["governance"], {f["url"] for f in figures}),
		})

	if "policies" in menus and frappe.has_permission(DOCUMENT, "read"):
		figures = [
			_figure(_("In force"), _count(DOCUMENT, [["is_active", "=", 1]]), "/policies?standing=inforce"),
			_figure(_("Awaiting review"), _count(DOCUMENT, [["requires_review", "=", 1]]),
				"/policies?standing=review", "warning"),
			_figure(_("Review overdue"), _count(DOCUMENT, [HAS_REVIEW_DATE, ["next_review_on", "<", today],
				["is_active", "=", 1]]), "/policies?standing=overdue", "danger"),
		]
		out.append({
			"id": "policies", "title": _("Policies"), "url": "/policies", "icon": "bi-file-earmark-text",
			"description": _("Governing documents, their versions, reviews and attestations."),
			"figures": figures,
			"links": _menu_links(menus["policies"], {f["url"] for f in figures} | {"/policies"}),
		})

	if "escalations" in menus and frappe.has_permission(MATTER, "read"):
		figures = [
			_figure(_("Open matters"), _count(MATTER, [["is_open", "=", 1]]), "/escalations"),
			_figure(_("Time threshold breached"), _count(MATTER, [["is_open", "=", 1], ["threshold_breached", "=", 1]]),
				"/escalations?standing=breached", "danger"),
			_figure(_("High severity, open"), _count(MATTER, [["is_open", "=", 1], ["severity", "=", "High"]]),
				"/escalations?severity=High", "warning"),
		]
		out.append({
			"id": "escalations", "title": _("Escalations"), "url": "/escalations", "icon": "bi-exclamation-diamond",
			"description": _("Matters raised, who owns them, how severe and how late."),
			"figures": figures,
			"links": _menu_links(menus["escalations"], {f["url"] for f in figures}),
		})

	if "insights" in menus:
		figures = []
		try:
			from consilium.consilium_core.ai import gaps

			counts = gaps.detection()["counts"]
			figures = [
				_figure(_("High-severity gaps"), counts.get("High", 0), "/governance-gaps", "danger"),
				_figure(_("Medium-severity gaps"), counts.get("Medium", 0), "/governance-gaps", "warning"),
			]
		except Exception:
			# The figures are a courtesy; the card and its links stand without them.
			frappe.log_error(title="Home: the gap counts could not be worked out")
		out.append({
			"id": "insights", "title": _("Insights"), "url": "/reports", "icon": "bi-bar-chart",
			"description": _("The picture across all three: reporting, coverage, gaps and trends."),
			"figures": figures,
			"links": _menu_links(menus["insights"], {"/governance-gaps"}),
		})
	return out


# ------------------------------------------------------------------ guides


#: The chapters of the illustrated guide, used when the guide itself cannot be
#: read (a deployment without the docs folder). Kept in step with
#: docs/guides/README.md, which is read in preference when it is there.
FALLBACK_CHAPTERS = [
	("00-welcome", "0. Welcome", "What the platform does for you, signing in, and your first five minutes"),
	("01-finding-your-way", "1. Finding your way", "Search, menus, My work, Help, text size, theme, lists and filters"),
	("02-my-work", "2. My work", "Everything waiting on you: approvals, reviews, attestations and escalations"),
	("03-governance", "3. Governance", "Forums and committees, from the inventory to meetings, motions and reviews"),
	("04-policies", "4. Policies", "The policy library, approvals, versions, reviews, requests and attestations"),
	("05-escalations", "5. Escalations", "Raising a matter, ownership, action plans, risk acceptance and closure"),
	("06-insights", "6. Insights", "Management reporting, coverage, gaps and risk, emerging risks"),
	("07-help-and-ai", "7. The Help assistant and AI", "What to ask, and how answers show their sources"),
	("08-your-first-day", "8. Your first day, by role", "What your role uses, a checklist and common tasks"),
	("09-administration", "9. Administration without code", "Branding, lists, imports, users, notifications and more"),
	("10-questions-and-answers", "10. Questions and answers", "\"How do I…?\" and \"Why can't I…?\""),
	("11-glossary", "Glossary", "The platform's words, in plain English"),
]

#: Chapters only administrators act on (the assistant's corpus hides the same one).
ADMIN_CHAPTERS = ("09-",)

_ROW = re.compile(r"^\|\s*\[(?P<title>[^\]]+)\]\((?P<file>[0-9]{2}-[a-z0-9-]+)\.md\)\s*\|\s*(?P<summary>[^|]+?)\s*\|\s*$")


def _readme_chapters() -> list[tuple[str, str, str]]:
	from consilium.consilium_core.assistant import corpus

	directory = corpus.docs_dir()
	readme = os.path.join(str(directory), "guides", "README.md") if directory else ""
	if not readme or not os.path.exists(readme):
		return []
	rows = []
	with open(readme, encoding="utf-8") as handle:
		for line in handle:
			match = _ROW.match(line.strip())
			if match:
				rows.append((match["file"], match["title"].strip(), match["summary"].strip()))
	return rows


def guides(user: str, is_admin: bool) -> dict:
	"""The guide cards, from the in-platform guide reader (/guide).

	The reader owns the chapter list (``guide.cns_guide_chapters``): the
	chapters the signed-in viewer may read, with their titles, summaries,
	icons and /guide?chapter=… addresses, so a card always opens the chapter
	the reader shows. It never raises and returns nothing when the guide is not
	installed; the page then lists the chapters from the guide's README (or
	the list above) without links, so it never offers an address that does not
	open. ``user`` is the viewer the reader reads for (the session's).
	"""
	try:
		from consilium.consilium_core.guide import cns_guide_chapters
	except ImportError:
		cns_guide_chapters = None
	provided = cns_guide_chapters() if cns_guide_chapters and frappe.session.user == user else []
	if provided:
		chapters = [
			{"title": c["title"], "summary": c.get("short") or c.get("summary") or "", "url": c["url"],
			 "icon": c.get("icon")}
			for c in provided if c.get("title") and c.get("url")
		]
		return {"available": True, "url": "/guide", "chapters": chapters}

	rows = _readme_chapters() or FALLBACK_CHAPTERS
	chapters = [
		{"title": title, "summary": summary, "url": "", "icon": None}
		for slug, title, summary in rows
		if is_admin or not slug.startswith(ADMIN_CHAPTERS)
	]
	return {"available": False, "url": "", "chapters": chapters}


# ------------------------------------------------------------------ the page


def _section(build, fallback, title: str):
	"""One card's data, or its fallback when working it out fails.

	Home draws from every area of the platform; a fault in one (a query a
	half-finished upgrade cannot answer, say) must cost that card its figures,
	not everyone their home page. The fault is logged for an administrator.
	"""
	try:
		return build()
	except Exception:
		frappe.log_error(title=f"Home: {title} could not be worked out")
		return fallback


def context(user: str) -> dict:
	"""Everything the home page draws, for ``user`` (the signed-in person)."""
	roles = set(frappe.get_roles(user))
	is_admin = bool(roles & {"System Manager", "Consilium Administrator"})
	unavailable_work = {"count": 0, "overdue": 0, "due_soon": 0, "groups": [], "top": [], "unavailable": True}
	return {
		"greeting": greeting(user),
		"work": _section(lambda: my_work(user), unavailable_work, "My work"),
		"actions": _section(quick_actions, [], "the quick actions"),
		"modules": _section(modules, [], "the area cards"),
		"guides": _section(lambda: guides(user, is_admin), {"available": False, "url": "", "chapters": []}, "the guides"),
		"can_map": bool(frappe.has_permission(FORUM, "read")),
	}
