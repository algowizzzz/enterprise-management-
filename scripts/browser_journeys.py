#!/usr/bin/env python3
"""Key user journeys, driven through a real browser (E26-S3).

    cd <bench>/sites
    FRAPPE_BENCH_ROOT=<bench> <repo>/.venv/bin/python <repo>/scripts/browser_journeys.py \\
        --site consilium.localhost --url http://consilium.localhost:8000

    ... browser_journeys.py --site ... --only 'policy-*'   # some journeys only
    ... browser_journeys.py --site ... --list              # print the journeys
    ... browser_journeys.py --site ... --shots <folder>    # keep a picture of each

Why it exists. The unit tests render pages on the server, and
``scripts/ui_regression.py`` checks what the server sends. Neither runs the
page's JavaScript, and most of what a person sees on these pages is drawn by
it: the tables, the tabs, the inbox count, the help assistant. A blank-page bug
shipped once behind an "API returned 200"; these journeys catch that class of
failure by doing what a person does and looking at the result.

How it signs in — without a password. It creates an ordinary server-side
session for each person with the framework's own session machinery
(``frappe.sessions.Session``, the object a real sign-in creates) and gives the
browser nothing but that session's ``sid`` cookie. No password is entered,
typed, stored or needed. Every session it created is deleted at the end, even
when a journey fails. (A session does stamp the person's last-login time; that
is what a session is.)

Who it signs in as. Nobody is named here. Each journey looks up, on the target
site, a person who fits it — the owner of a governing document that has a
version, the secretary of a forum, someone with something in their inbox — so
the same journeys run against the demonstration site, a test site or a
customer's acceptance environment.

It changes nothing. Journeys only navigate, switch tabs, choose filters and open
panels. No form is submitted and no question is put to the help assistant
(questions are logged, and a log entry is a change).

How it drives the browser. Playwright, pointed at the Google Chrome already on
the machine (``channel="chrome"``). It never downloads a browser, which matters
on a locked-down workstation. An uncaught script error on any page fails the
journey it happened in, whatever the journey was checking.

Exit status is non-zero if any journey failed. A journey the site has no data
for (no forum with a secretary, say) is reported as skipped, not failed.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VIEWPORT = {"width": 1440, "height": 900}
ADMIN_ROLES = ("System Manager", "Consilium Administrator")


class Skip(Exception):
	"""The site has no data this journey needs."""


# ---------------------------------------------------------------------------
# Finding people and records on the target site (reads only)
# ---------------------------------------------------------------------------

class Site:
	def __init__(self, frappe):
		self.frappe = frappe
		self.inbox_failures: list[str] = []

	def _enabled(self, user: str | None) -> bool:
		return bool(user) and user != "Guest" and bool(self.frappe.db.get_value("User", user, "enabled"))

	def roles(self, user: str) -> set[str]:
		return set(self.frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"))

	def holders(self, role: str) -> list[str]:
		users = self.frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
		return sorted(u for u in set(users) if u != "Administrator" and self._enabled(u))

	def policy_with_version(self) -> dict:
		"""A governing document whose owner can open its current version."""
		rows = self.frappe.get_all(
			"Governing Document",
			filters={"current_version": ["is", "set"], "document_owner": ["is", "set"]},
			fields=["name", "document_name", "document_owner", "current_version", "handling_classification"],
			order_by="modified desc",
		)
		# Prefer a document with a stored body (a file the viewer can frame) and
		# ordinary handling, so the viewer is shown working rather than refusing.
		def rank(row):
			body = self.frappe.db.get_value("Document Version", row.current_version, "body_file") or ""
			return (not body, row.handling_classification in ("Restricted",), not body.lower().endswith(".pdf"))
		rows = sorted((r for r in rows if self._enabled(r.document_owner)), key=rank)
		if not rows:
			raise Skip("no governing document with a current version and an enabled owner")
		return rows[0]

	def forum_with_secretary(self) -> dict:
		rows = self.frappe.get_all(
			"Governance Forum",
			filters={"secretary": ["is", "set"]},
			fields=["name", "forum_name", "secretary", "is_active"],
			order_by="is_active desc, modified desc",
		)
		rows = [r for r in rows if self._enabled(r.secretary)]
		preferred = [r for r in rows if "Committee Secretary" in self.roles(r.secretary)]
		if not (preferred or rows):
			raise Skip("no forum with an enabled secretary")
		return (preferred or rows)[0]

	def escalation_person(self) -> str:
		accountable = self.frappe.get_all(
			"Escalation Matter", filters={"accountable_executive": ["is", "set"]}, pluck="accountable_executive"
		)
		for user in accountable:
			if self._enabled(user) and "Escalation Owner" in self.roles(user):
				return user
		holders = self.holders("Escalation Owner")
		if not holders:
			raise Skip("no one holds the Escalation Owner role")
		return holders[0]

	def person_with_inbox(self) -> tuple[str, int]:
		"""Someone with something waiting, and how many things, as the server counts them."""
		from consilium.consilium_core import inbox

		frappe = self.frappe
		candidates = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="name")
		best, failures = None, []
		for user in sorted(candidates):
			if user in ("Administrator", "Guest"):
				continue
			frappe.set_user(user)
			try:
				count = inbox.my_task_count()["count"]
			except Exception as exc:
				# A failed query aborts the transaction; nothing was written, so
				# rolling back only clears the error for the next person.
				frappe.db.rollback()
				first = next((line for line in str(exc).splitlines() if line.strip() and "Error in query" not in line), "")
				failures.append(f"{type(exc).__name__}: {first.strip()[:160]}")
				continue
			finally:
				frappe.set_user("Administrator")
			if count and (best is None or count > best[1]):
				best = (user, count)
				if count >= 3:
					break
		self.inbox_failures = failures
		if not best and failures:
			# The badge is drawn from the same call; if it fails here it fails in
			# the browser too, and the badge silently never appears.
			raise AssertionError(f"the server could not count the inbox for {len(failures)} people: {failures[0]}")
		if not best:
			raise Skip("no one has anything in their inbox")
		return best

	def everyday_person(self) -> str:
		for role in ("Governance Viewer", "Policy Owner", "Escalation Owner", "Committee Secretary"):
			for user in self.holders(role):
				if not (self.roles(user) & set(ADMIN_ROLES)):
					return user
		raise Skip("no signed-in person without an administration role")


# ---------------------------------------------------------------------------
# Sessions — created server-side, never with a password
# ---------------------------------------------------------------------------

class Sessions:
	"""One framework session per person, created on first use and deleted at
	the end. The browser is given only the resulting ``sid`` cookie."""

	def __init__(self, frappe):
		self.frappe = frappe
		self.sids: dict[str, str] = {}

	def sid_for(self, user: str) -> str | None:
		if user == "Guest":
			return None
		if user in self.sids:
			return self.sids[user]
		frappe = self.frappe
		from frappe.sessions import Session
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		# Session() reads the current request for an existing cookie and the
		# caller's address; give it an empty local request to read.
		frappe.local.request = Request(EnvironBuilder(path="/", base_url="http://" + frappe.local.site).get_environ())
		frappe.local.request_ip = "127.0.0.1"
		frappe.local.form_dict = frappe._dict()
		details = frappe.db.get_value("User", user, ["enabled", "full_name", "user_type"], as_dict=True)
		if not details or not details.enabled:
			raise RuntimeError(f"{user} does not exist or is disabled on this site")
		session = Session(user, resume=False, full_name=details.full_name, user_type=details.user_type)
		frappe.db.commit()
		frappe.local.request = None
		self.sids[user] = session.sid
		return session.sid

	def close(self):
		from frappe.sessions import delete_session

		for user, sid in self.sids.items():
			try:
				delete_session(sid, user=user, reason="Logged Out")
			except Exception as exc:  # keep deleting the rest
				print(f"  could not delete the session for {user}: {exc}", file=sys.stderr)
		self.frappe.db.commit()
		self.sids.clear()


# ---------------------------------------------------------------------------
# The browser side
# ---------------------------------------------------------------------------

class Browser:
	def __init__(self, pw_browser, sessions: Sessions, base_url: str, shots: Path | None):
		self.browser = pw_browser
		self.sessions = sessions
		self.base_url = base_url
		self.host = base_url.split("//", 1)[1].split("/")[0].split(":")[0]
		self.shots = shots
		self.errors: list[str] = []

	def page_as(self, user: str, viewport: dict | None = None):
		phone = bool(viewport and viewport["width"] < 768)
		context = self.browser.new_context(viewport=viewport or VIEWPORT, device_scale_factor=1, locale="en-GB",
			is_mobile=phone, has_touch=phone)
		sid = self.sessions.sid_for(user)
		if sid:
			context.add_cookies([{"name": "sid", "value": sid, "domain": self.host, "path": "/"}])
		# Theme and text size are per-browser preferences; start each journey clean.
		context.add_init_script("try{localStorage.removeItem('cns:theme');localStorage.removeItem('cns:fontsize')}catch(e){}")
		page = context.new_page()
		page.on("pageerror", lambda exc: self.errors.append(f"script error on {page.url}: {exc}"))
		return page

	def open(self, page, route: str, expect_status: int = 200):
		response = page.goto(self.base_url + route, wait_until="load", timeout=45000)
		status = response.status if response else 0
		if status != expect_status:
			raise AssertionError(f"{route}: HTTP {status}, expected {expect_status}")
		try:
			page.wait_for_load_state("networkidle", timeout=15000)
		except Exception:
			pass  # a long-polling socket keeps the network busy; the checks below wait for what they need
		return response

	def snap(self, page, name: str):
		if self.shots:
			self.shots.mkdir(parents=True, exist_ok=True)
			page.screenshot(path=str(self.shots / f"{name}.png"))


def visible_text(page, selector: str) -> str:
	return page.locator(selector).first.inner_text(timeout=15000)


def nav_links(page) -> list[str]:
	"""Every address the header's menus offer, open or not."""
	return page.eval_on_selector_all(
		".cns-menubar .cns-menu-item, .cns-menubar a.cns-menu-trigger", "els => els.map(e => e.getAttribute('href'))"
	)


def menu_names(page) -> list[str]:
	return page.eval_on_selector_all(".cns-menubar .cns-menu-label", "els => els.map(e => e.textContent.trim())")


def open_tab(page, tab_id: str, panel_id: str):
	page.locator(f"#{tab_id}").click(timeout=10000)
	page.wait_for_selector(f"#{panel_id}:not([hidden])", state="visible", timeout=10000)


# ---------------------------------------------------------------------------
# The journeys
# ---------------------------------------------------------------------------

@dataclass
class Journey:
	name: str
	description: str
	run: Callable
	persona: str = ""
	detail: str = ""
	outcome: str = ""
	notes: list = field(default_factory=list)


def home_loads(site: Site, b: Browser, j: Journey):
	j.persona = "Administrator"
	page = b.page_as(j.persona)
	b.open(page, "/")
	page.wait_for_selector("h1", state="visible")
	assert page.locator(".cns-menubar .cns-menu-trigger").count() >= 3, "the primary navigation did not render"
	assert page.locator(".cns-signin-card").count() == 0, "a signed-in administrator was asked to sign in"
	title = page.title()
	assert title.startswith("Home"), f"unexpected page title {title!r}"
	assert "/admin" in nav_links(page), "the administrator has no Admin menu"
	assert page.locator("#cns-gsearch-input").is_visible(), "the header has no search box"
	# The home cards: My work, and an area card for each area, each figure a link.
	assert page.locator("#work-heading").is_visible(), "the My work card is missing"
	areas = page.eval_on_selector_all(".cns-home-module-title", "els => els.map(e => e.textContent.trim())")
	assert {"Governance", "Policies", "Escalations"} <= set(areas), f"an administrator's area cards: {areas}"
	b.snap(page, j.name)
	# A figure and the list it opens show the same number. One figure per list
	# page, the filtered one: the list's own count badge is the other side.
	figures = page.eval_on_selector_all(
		".cns-home-figure", "els => els.map(e => [e.getAttribute('href'), e.getAttribute('data-home-figure')])")
	checked = []
	for href, value in figures:
		if "?" not in href or href.startswith("/governance-gaps"):
			continue
		if any(href.split("?")[0] == done.split("?")[0] for done in checked):
			continue
		b.open(page, href)
		page.wait_for_function(
			"() => { const c = document.querySelector('.cns-dt-count'); return c && !c.hidden && c.textContent.trim() !== ''; }",
			timeout=20000,
		)
		listed = visible_text(page, ".cns-dt-count").strip()
		assert listed == value, f"{href}: the home figure says {value}, the list shows {listed}"
		checked.append(href)
	assert checked, "no filtered figure to follow"
	j.detail = (f"title {title!r}, menus {menu_names(page)}, areas {areas}; "
		f"figures match their lists for {', '.join(checked)}")


def policy_owner_views_a_version(site: Site, b: Browser, j: Journey):
	doc = site.policy_with_version()
	j.persona = doc.document_owner
	page = b.page_as(j.persona)
	b.open(page, f"/policy?name={doc.name}")
	heading = visible_text(page, "h1")
	assert doc.document_name in heading or doc.name in heading, f"heading {heading!r} does not name the document"
	open_tab(page, "tab-versions", "panel-versions")
	page.wait_for_selector("#versions-table tbody tr", timeout=20000)
	versions = page.locator("#versions-table tbody tr").count()
	assert versions >= 1, "the version chain is empty"
	# History: the record's change log, drawn by script under the version chain.
	page.wait_for_function(
		"() => { const l = document.getElementById('change-list'); return l && l.children.length && !/Loading/.test(l.textContent); }",
		timeout=20000,
	)
	history = page.locator("#change-list li").count()
	b.snap(page, j.name + "-versions")

	link = page.locator("#versions-table a[href*='/document-view?version=']").first
	assert link.count(), "no version links to the document viewer"
	href = link.get_attribute("href")
	b.open(page, href)
	stage = page.locator(".cns-docview-stage")
	stage.wait_for(state="visible", timeout=15000)
	kind = page.evaluate(
		"""() => { const s = document.querySelector('.cns-docview-stage');
			if (s.querySelector('iframe.cns-docview-frame--text')) return 'text';
			if (s.querySelector('iframe.cns-docview-frame')) return 'pdf';
			if (s.querySelector('img.cns-docview-image')) return 'image';
			if (s.querySelector('article.cns-docview-html')) return 'html';
			return 'none'; }"""
	)
	if kind in ("pdf", "text"):
		src = page.locator(".cns-docview-frame").first.get_attribute("src")
		# Fetched from inside the page, with its cookie: the frame is only useful
		# if the body it points at is served to this reader.
		status, content_type = page.evaluate(
			"async (src) => { const r = await fetch(src, {credentials: 'same-origin'});"
			" return [r.status, r.headers.get('content-type') || '?']; }",
			src,
		)
		assert status == 200, f"the viewer's frame source answered HTTP {status}"
		j.notes.append(f"frame source {content_type}")
	elif kind == "html":
		assert page.locator("article.cns-docview-html").inner_text().strip(), "the HTML body is empty"
	else:
		j.notes.append("this version has no displayable body")
	b.snap(page, j.name + "-viewer")
	j.detail = f"{doc.name}: {versions} version(s), {history} history entr(y/ies), viewer shows {kind}"


def secretary_opens_forum_and_review(site: Site, b: Browser, j: Journey):
	forum = site.forum_with_secretary()
	j.persona = forum.secretary
	page = b.page_as(j.persona)
	b.open(page, f"/forum?name={forum.name}")
	page.wait_for_function(
		"(t) => document.body.innerText.includes(t)", arg=forum.forum_name, timeout=20000
	)
	open_tab(page, "tab-members", "panel-members")
	open_tab(page, "tab-history", "panel-history")
	b.snap(page, j.name + "-forum")
	b.open(page, f"/forum-review?forum={forum.name}")
	page.wait_for_selector("h1", state="visible")
	body = page.locator("main").first.inner_text()
	assert forum.forum_name in body or forum.name in body, "the review page does not name the forum"
	assert page.locator(".cns-signin-card").count() == 0, "the secretary was asked to sign in"
	has_form = page.locator("#review-form").count() > 0
	page.wait_for_selector("#reviews-table", state="attached", timeout=15000)
	b.snap(page, j.name + "-review")
	j.detail = f"{forum.name}: forum tabs open; review page {'offers the form' if has_form else 'is read-only for them'}"


def escalation_list_filters(site: Site, b: Browser, j: Journey):
	j.persona = site.escalation_person()
	page = b.page_as(j.persona)
	b.open(page, "/escalations")
	status = page.locator("#escalation-table .cns-dt-status")

	def total() -> int:
		page.wait_for_function(
			"() => { const s = document.querySelector('#escalation-table .cns-dt-status');"
			" return s && !/Loading/.test(s.textContent) && s.textContent.trim(); }",
			timeout=20000,
		)
		text = status.inner_text()
		match = re.search(r"of (\d+) record", text)
		return int(match.group(1)) if match else 0

	page.select_option("#f-standing", "all")
	everything = total()
	options = [o for o in page.eval_on_selector_all("#f-severity option", "els => els.map(e => e.value)") if o]
	assert options, "the severity filter has no options"
	counts = {}
	for option in options:
		page.select_option("#f-severity", option)
		page.wait_for_timeout(300)
		counts[option] = total()
		assert counts[option] <= everything, f"filtering by {option} showed more matters than no filter"
		shown = page.eval_on_selector_all("#escalation-table tbody tr", "rows => rows.length")
		assert shown <= counts[option]
	page.select_option("#f-severity", "")
	assert total() == everything, "clearing the filter did not bring every matter back"
	b.snap(page, j.name)
	assert sum(counts.values()) <= everything, "severity bands overlap"
	j.detail = f"{everything} matters in all standings; by severity {counts}"


def inbox_badge_shows_count(site: Site, b: Browser, j: Journey):
	user, count = site.person_with_inbox()
	j.persona = user
	if site.inbox_failures:
		j.notes.append(f"the count failed on the server for {len(site.inbox_failures)} other people: {site.inbox_failures[0]}")
	page = b.page_as(user)
	b.open(page, "/")
	badge = page.locator("[data-cns-inbox-badge]")
	badge.wait_for(state="visible", timeout=20000)
	text = badge.inner_text().strip()
	expected = "99+" if count > 99 else str(count)
	assert text == expected, f"badge shows {text!r}, the server counts {count}"
	b.snap(page, j.name)
	j.detail = f"badge {text!r} matches the server's count"


def help_assistant_opens(site: Site, b: Browser, j: Journey):
	j.persona = site.everyday_person()
	page = b.page_as(j.persona)
	b.open(page, "/forums")
	toggle = page.locator(".cns-assistant-toggle")
	toggle.wait_for(state="visible", timeout=15000)
	toggle.click()
	panel = page.locator("#cns-assistant-panel")
	panel.wait_for(state="visible", timeout=10000)
	assert page.locator("#cns-assistant-input").is_visible(), "the panel has no question box"
	assert toggle.get_attribute("aria-expanded") == "true", "the toggle does not report the panel open"
	b.snap(page, j.name)
	page.keyboard.press("Escape")
	page.wait_for_timeout(300)
	j.detail = "panel opened with its question box (no question asked: questions are logged)"


def guest_sees_sign_in(site: Site, b: Browser, j: Journey):
	j.persona = "Guest"
	page = b.page_as("Guest")
	for route in ("/", "/forums", "/policies", "/escalations"):
		b.open(page, route)
		card = page.locator(".cns-signin-card")
		assert card.count() and card.first.is_visible(), f"{route}: no sign-in card for a signed-out visitor"
		assert page.locator("table tbody tr").count() == 0, f"{route}: a signed-out visitor was shown rows"
		assert page.locator(".cns-assistant-toggle:visible").count() == 0, f"{route}: the assistant offered itself to a visitor"
	b.snap(page, j.name)
	b.open(page, "/policy?name=anything", expect_status=403)
	j.detail = "sign-in card on 4 pages, no rows; a record page refuses with 403"


def non_admin_has_no_admin_nav(site: Site, b: Browser, j: Journey):
	j.persona = site.everyday_person()
	page = b.page_as(j.persona)
	b.open(page, "/")
	links = nav_links(page)
	assert links, "no navigation rendered"
	assert "/admin" not in links, "an everyday user is offered the Admin menu"
	menus = menu_names(page)
	assert menus, "no menus rendered"
	assert "Admin" not in menus, "an everyday user is shown the Admin menu"
	assert page.locator("a[href='/ui-kit']").count() == 0, "an everyday user is offered the interface reference"
	b.open(page, "/admin", expect_status=403)
	b.snap(page, j.name)
	j.detail = f"menus {menus}; /admin refuses with 403"


def menu_keyboard_walk(site: Site, b: Browser, j: Journey):
	"""A dropdown menu, driven by the keyboard alone."""
	j.persona = site.everyday_person()
	page = b.page_as(j.persona)
	b.open(page, "/")
	trigger = page.locator("button.cns-menu-trigger").nth(1)
	panel_id = trigger.get_attribute("aria-controls")
	trigger.focus()
	page.keyboard.press("Enter")
	assert trigger.get_attribute("aria-expanded") == "true", "Enter did not open the menu"
	assert page.locator(f"#{panel_id}").is_visible(), "the menu panel is not shown"
	first = page.evaluate("() => document.activeElement.textContent.trim().split(/\\s{2,}/)[0]")
	assert page.evaluate("() => document.activeElement.classList.contains('cns-menu-item')"), "focus did not move into the menu"
	page.keyboard.press("ArrowDown")
	second = page.evaluate("() => document.activeElement.textContent.trim().split(/\\s{2,}/)[0]")
	assert second != first, "ArrowDown did not move to the next item"
	page.keyboard.press("End")
	page.keyboard.press("Home")
	assert page.evaluate("() => document.activeElement.textContent.trim().split(/\\s{2,}/)[0]") == first, "Home did not return to the first item"
	page.keyboard.press("ArrowRight")
	nxt = page.locator("button.cns-menu-trigger").nth(2)
	assert nxt.get_attribute("aria-expanded") == "true", "ArrowRight did not open the next menu"
	assert trigger.get_attribute("aria-expanded") == "false", "the first menu stayed open"
	page.keyboard.press("Escape")
	assert nxt.get_attribute("aria-expanded") == "false", "Escape did not close the menu"
	assert page.evaluate("(id) => document.activeElement.id === id", nxt.get_attribute("id")), "Escape did not return focus to the menu button"
	b.snap(page, j.name)
	j.detail = f"Enter opened, Down/Home/End moved, Right moved to the next menu, Escape closed and returned focus ({first!r}, {second!r})"


def global_search_opens_a_result(site: Site, b: Browser, j: Journey):
	"""Search from the header, move with the arrows, open with Enter."""
	j.persona = site.everyday_person()
	page = b.page_as(j.persona)
	b.open(page, "/forums")
	page.keyboard.press("/")
	box = page.locator("#cns-gsearch-input")
	assert page.evaluate("() => document.activeElement.id") == "cns-gsearch-input", "'/' did not focus the search"
	# A forum this person may read, found the way the endpoint finds it.
	name = site.frappe.get_list("Governance Forum", fields=["name", "forum_name"], limit_page_length=1,
		order_by="modified desc", user=j.persona)
	if not name:
		raise Skip("no forum on this site to search for")
	word = name[0].forum_name.split()[0]
	box.fill(word)
	page.wait_for_selector("#cns-gsearch-results [role='option']", timeout=15000)
	assert box.get_attribute("aria-expanded") == "true", "the box does not report its results as shown"
	groups = page.eval_on_selector_all("#cns-gsearch-results .cns-gsearch-group-label", "els => els.map(e => e.textContent)")
	page.keyboard.press("ArrowDown")
	active = box.get_attribute("aria-activedescendant")
	assert active, "ArrowDown did not select a result"
	href = page.locator(f"#{active}").get_attribute("href")
	b.snap(page, j.name)
	page.keyboard.press("Enter")
	page.wait_for_url("**" + href, timeout=15000)
	j.detail = f"'{word}' found in {groups}; Enter opened {href}"


def phone_menu_opens(site: Site, b: Browser, j: Journey):
	"""At phone width the menus fold into a slide-out panel with sections."""
	j.persona = site.everyday_person()
	page = b.page_as(j.persona, viewport={"width": 390, "height": 844})
	b.open(page, "/")
	assert not page.locator(".cns-mainnav").is_visible(), "the menu panel shows before it is opened"
	toggle = page.locator("[data-cns-nav-toggle]")
	toggle.click()
	page.wait_for_timeout(300)
	assert toggle.get_attribute("aria-expanded") == "true", "the menu button does not report the panel open"
	assert page.locator(".cns-mainnav").is_visible(), "the panel did not open"
	# Pinned by id: a lazy "first collapsed section" locator would move on to
	# the next collapsed one as soon as this one opens.
	section_id = page.locator("button.cns-menu-trigger[aria-expanded='false']").first.get_attribute("id")
	section = page.locator(f"#{section_id}")
	section.click()
	assert section.get_attribute("aria-expanded") == "true", "a section did not expand"
	assert page.locator(f"#{section.get_attribute('aria-controls')} .cns-menu-item").first.is_visible()
	width = page.evaluate("() => document.documentElement.scrollWidth")
	assert width <= 390, f"the page scrolls sideways ({width}px)"
	label = section.locator(".cns-menu-label").inner_text().strip()
	b.snap(page, j.name)
	page.keyboard.press("Escape")
	page.wait_for_timeout(300)
	assert toggle.get_attribute("aria-expanded") == "false", "Escape did not close the panel"
	assert not page.locator(".cns-mainnav").is_visible(), "the panel is still shown after Escape"
	j.detail = f"panel opened, {label!r} expanded, Escape closed it; no sideways scroll"


JOURNEYS = [
	Journey("home-loads", "The home page loads for an administrator with its cards, and its figures match their lists", home_loads),
	Journey("policy-owner-version-history", "A policy owner opens their document, its versions and history, and views a version", policy_owner_views_a_version),
	Journey("secretary-forum-review", "A forum secretary opens their forum and its compliance review page", secretary_opens_forum_and_review),
	Journey("escalation-filters", "The escalation register narrows by severity and widens again", escalation_list_filters),
	Journey("inbox-badge", "The My work menu shows the number of things waiting", inbox_badge_shows_count),
	Journey("menu-keyboard", "A header menu opens, moves and closes from the keyboard", menu_keyboard_walk),
	Journey("global-search", "The header search finds a forum and opens it from the keyboard", global_search_opens_a_result),
	Journey("phone-menu", "At phone width the menus open in a slide-out panel", phone_menu_opens),
	Journey("help-assistant", "The help assistant panel opens", help_assistant_opens),
	Journey("guest-sign-in", "A signed-out visitor is shown the sign-in card and no records", guest_sees_sign_in),
	Journey("non-admin-no-admin-nav", "An everyday user is not offered administration", non_admin_has_no_admin_nav),
]


def run(frappe, base_url: str, journeys: list[Journey], shots: Path | None, headed: bool) -> list[Journey]:
	from playwright.sync_api import sync_playwright

	site = Site(frappe)
	sessions = Sessions(frappe)
	try:
		with sync_playwright() as pw:
			browser = pw.chromium.launch(channel="chrome", headless=not headed)
			b = Browser(browser, sessions, base_url, shots)
			try:
				for journey in journeys:
					b.errors = []
					started = time.time()
					try:
						journey.run(site, b, journey)
						if b.errors:
							raise AssertionError("; ".join(b.errors[:3]))
						journey.outcome = "passed"
					except Skip as exc:
						journey.outcome, journey.detail = "skipped", str(exc)
					except Exception as exc:
						journey.outcome = "failed"
						journey.detail = (str(exc).splitlines() or [type(exc).__name__])[0][:300]
					finally:
						for context in list(browser.contexts):
							context.close()
					notes = f" ({'; '.join(journey.notes)})" if journey.notes else ""
					print(f"  {journey.outcome.upper():7} {journey.name:30} {time.time() - started:4.1f}s  as {journey.persona or '-'}")
					print(f"          {journey.detail}{notes}")
			finally:
				browser.close()
	finally:
		sessions.close()
	return journeys


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--site", default="consilium.localhost")
	parser.add_argument("--sites-path", default=".")
	parser.add_argument("--url", default="http://consilium.localhost:8000")
	parser.add_argument("--only", action="append", help="only journeys whose name matches this glob (repeatable)")
	parser.add_argument("--shots", type=Path, help="keep a screenshot of each journey in this folder")
	parser.add_argument("--headed", action="store_true", help="show the browser")
	parser.add_argument("--list", action="store_true", help="print the journeys and exit")
	args = parser.parse_args()

	journeys = JOURNEYS
	if args.only:
		journeys = [j for j in journeys if any(fnmatch.fnmatch(j.name, g) for g in args.only)]
	if args.list:
		for j in journeys:
			print(f"{j.name:30} {j.description}")
		return 0

	import frappe

	frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
	frappe.connect()
	frappe.set_user("Administrator")
	started = time.time()
	try:
		print(f"Running {len(journeys)} journeys against {args.url}")
		results = run(frappe, args.url.rstrip("/"), journeys, args.shots, args.headed)
	finally:
		frappe.destroy()
	counts = {k: sum(1 for j in results if j.outcome == k) for k in ("passed", "skipped", "failed")}
	print(f"\n{counts['passed']} passed, {counts['skipped']} skipped, {counts['failed']} failed in {time.time() - started:.0f}s")
	return 1 if counts["failed"] else 0


if __name__ == "__main__":
	raise SystemExit(main())
