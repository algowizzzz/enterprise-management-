"""The portal's primary navigation: top-level menus, each a panel of sub-pages.

The header used to be a flat row of tabs, one per area. With the formation
queue, the analysis pages, imports, campaigns and the filtered views people are
sent to ("overdue reviews", "breached escalations") there were more places to go
than a row of tabs could name, and the filtered views were reachable only from
tiles on the home page. So each area is now a menu, and each menu lists the
pages and the filtered views that belong to it, with a line saying what each is.

Why this lives in Python rather than in the template:

* **Who sees what is a permission decision.** A menu or an item someone cannot
  use is a dead end, so each is shown only to those who may read the records it
  lists (``frappe.has_permission``) or who hold the role the page is for — the
  same checks the pages and their endpoints make. Written here, each rule is one
  readable line and can be tested; written in Jinja it was a pile of list
  surgery on ``_nav_items``.
* **The template sandbox cannot see the query string**, so it cannot tell which
  item of a menu is the current page. This can.

``cns_nav`` is exposed to templates through the ``jinja`` hook. It never raises
for a signed-out visitor; it returns nothing and the header shows no menus.

Backwards compatibility: pages set ``active_nav`` to the id of their area. The
old tab ids (``inbox``, ``forums``, ``requests``, ``reports``) are mapped to the
menus that replaced them, so a page that still sets one keeps its highlight.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import frappe

#: Tab ids from the flat navigation, and the menu each became.
LEGACY_IDS = {
	"inbox": "mywork",
	"tasks": "mywork",
	"forums": "governance",
	"requests": "governance",
	"reports": "insights",
	"analysis": "insights",
}

ADMIN_ROLES = ("System Manager", "Consilium Administrator")
FORMATION_QUEUE_ROLES = ("Risk Governance Office", "Head of Risk Governance", "System Manager")


def menu_id(active_nav: str | None) -> str:
	"""The menu a page's ``active_nav`` names, old ids included."""
	value = (active_nav or "").strip()
	return LEGACY_IDS.get(value, value)


class _Viewer:
	"""The permission questions the menus ask, each answered once per render."""

	def __init__(self, user: str):
		self.user = user
		self.roles = set(frappe.get_roles(user))
		self._cache: dict = {}

	def can(self, doctype: str, ptype: str = "read") -> bool:
		key = (doctype, ptype)
		if key not in self._cache:
			try:
				self._cache[key] = bool(frappe.has_permission(doctype, ptype, user=self.user))
			except Exception:
				# A record type that is not installed on this site is one nobody
				# may use; the menu drops the item rather than failing the page.
				self._cache[key] = False
		return self._cache[key]

	def has_any(self, *roles: str) -> bool:
		return bool(self.roles.intersection(roles))

	@property
	def is_admin(self) -> bool:
		return self.has_any(*ADMIN_ROLES)

	@property
	def desk_user(self) -> bool:
		if "desk_user" not in self._cache:
			self._cache["desk_user"] = (
				frappe.get_cached_value("User", self.user, "user_type") == "System User"
			)
		return self._cache["desk_user"]

	@property
	def runs_campaigns(self) -> bool:
		"""The rule the inbox uses for its campaigns button: the governance office,
		an administrator of campaigns, or anyone who may read campaigns."""
		if "campaigns" not in self._cache:
			try:
				from consilium.governance import reviews

				allowed = reviews.may_run_forum_campaigns(self.user)
			except Exception:
				allowed = False
			self._cache["campaigns"] = bool(allowed or self.can("Attestation Campaign"))
		return self._cache["campaigns"]


def _item(label, url, description, icon, show=True, new_tab=False):
	return {"label": label, "url": url, "description": description, "icon": icon, "show": bool(show),
		"new_tab": bool(new_tab)}


def _horizon() -> dict:
	"""The horizon-scanning tool as an administrator has set it up: its label,
	whether it is switched on, and whether it opens in a new tab. The same
	answer the page buttons use (``integrations.external_tools``), so the menu
	item and the buttons never disagree. A site not migrated to the settings
	yet has no item rather than a broken header."""
	try:
		from consilium.consilium_core.integrations import external_tools

		horizon = dict(external_tools.cns_external_tools().get("horizon") or {})
		horizon["connected"] = horizon.get("state") == external_tools.CONNECTED
		return horizon
	except Exception:
		return {}


def _menus(v: _Viewer) -> list[dict]:
	"""Every menu and item, each with the condition it is shown on.

	Filtered views link to the list pages' own address filters (read by each
	page's script from ``?standing=``, ``?show=`` and so on), so a view here is
	exactly the view the page's filter bar would give.
	"""
	forums = v.can("Governance Forum")
	documents = v.can("Governing Document")
	matters = v.can("Escalation Matter")
	request_forum = v.can("Committee Formation Request", "create")
	horizon = _horizon()
	return [
		{
			"id": "home", "label": "Home", "icon": "bi-house",
			"groups": [
				{"label": "", "items": [
					_item("Overview", "/", "Where the inventory stands today, at a glance.", "bi-speedometer2"),
					_item("Forum map", "/#forum-map", "How every forum connects, drawn as a hierarchy.",
						"bi-diagram-3", forums),
					_item("How it works", "/#guide-heading", "Guides to forums, policies and escalation.",
						"bi-book"),
				]},
			],
		},
		{
			"id": "mywork", "label": "My work", "icon": "bi-inbox", "badge": True,
			"groups": [
				{"label": "Inbox", "items": [
					_item("All my tasks", "/tasks", "Everything waiting on you, across every area.", "bi-inbox"),
					_item("Due soon", "/tasks?show=soon", "Overdue, or due within the next week.", "bi-alarm"),
				]},
				{"label": "By kind", "items": [
					_item("Approvals", "/tasks?show=approvals",
						"Decisions and second signatures assigned to you.", "bi-check2-square"),
					_item("Reviews", "/tasks?show=reviews",
						"Forum, policy and escalation reviews that fall to you.", "bi-shield-check"),
					_item("Attestations", "/tasks?show=attestations",
						"Confirm a record is accurate, or say where it is not.", "bi-clipboard-check"),
					_item("Escalations waiting for an owner", "/tasks?show=unowned",
						"Matters routed to your role or group. Take one on.", "bi-person-raised-hand", matters),
				]},
			],
		},
		{
			"id": "governance", "label": "Governance", "icon": "bi-diagram-3",
			"groups": [
				{"label": "Forums", "items": [
					_item("Forum inventory", "/forums", "Every forum, its mandate, members and standing.",
						"bi-collection", forums),
					_item("Forum map", "/#forum-map", "The hierarchy and the links between forums.",
						"bi-diagram-3", forums),
					_item("Awaiting compliance review", "/forums?standing=review",
						"Forums whose standing needs a compliance decision.", "bi-hourglass-split", forums),
					_item("Overdue reviews", "/forums?standing=overdue",
						"Active forums past their recorded review date.", "bi-exclamation-circle", forums),
					_item("Disbanded forums", "/forums?standing=disbanded",
						"Forums retired from service, kept on record.", "bi-archive", forums),
				]},
				{"label": "Formation", "items": [
					_item("Request a new forum", "/create-forum",
						"A guided request, evaluated before anything is created.", "bi-plus-circle",
						request_forum),
					_item("Formation requests", "/formation-requests",
						"Evaluate, question and decide requests to form a forum.", "bi-inboxes",
						v.has_any(*FORMATION_QUEUE_ROLES)),
				]},
			],
		},
		{
			"id": "policies", "label": "Policies", "icon": "bi-file-earmark-text", "show": documents,
			"groups": [
				{"label": "Library", "items": [
					_item("Policy library", "/policies", "Every governing document and where it stands.",
						"bi-journal-text"),
					_item("In review", "/policies?standing=review", "Documents awaiting a review decision.",
						"bi-hourglass-split"),
					_item("Reviews due in 90 days", "/policies?standing=due90",
						"Periodic reviews coming up next.", "bi-calendar-event"),
					_item("Overdue reviews", "/policies?standing=overdue",
						"In force, past the recorded review date.", "bi-exclamation-circle"),
				]},
				{"label": "Change", "items": [
					_item("Request a policy or change", "/policy-intake",
						"Ask for a new document, a change or a retirement.", "bi-file-earmark-plus"),
					_item("Attestation campaigns", "/attestation-campaigns",
						"Open annual attestations and chase the answers.", "bi-clipboard-check",
						v.runs_campaigns),
					_item("Regulatory updates", "/regulatory-updates",
						"Record a regulatory change and work through what it touches.", "bi-bank"),
					# /horizon-scanning forwards to the platform the settings name.
					# Until it is connected, the page there only says so: the item
					# says it too, and opens in place rather than in a new tab.
					_item(horizon.get("label") or "Horizon scanning", "/horizon-scanning",
						"Upcoming regulatory change, before it lands." if horizon.get("connected")
						else "Not connected yet.", "bi-binoculars",
						horizon.get("shown"), horizon.get("new_tab") and horizon.get("connected")),
				]},
			],
		},
		{
			"id": "escalations", "label": "Escalations", "icon": "bi-exclamation-diamond", "show": matters,
			"groups": [
				{"label": "Register", "items": [
					_item("Escalation register", "/escalations", "Every open matter, how severe and how old.",
						"bi-list-ul"),
					_item("Breached", "/escalations?standing=breached",
						"Open matters past their time threshold.", "bi-alarm"),
					_item("Awaiting review", "/escalations?standing=review",
						"Matters waiting on a second-line review.", "bi-hourglass-split"),
					_item("Closed", "/escalations?standing=closed", "Matters decided and closed.",
						"bi-check2-circle"),
				]},
				{"label": "Act", "items": [
					_item("Raise an escalation", "/raise-escalation",
						"A guided form; the matrix proposes severity and forums.", "bi-plus-circle",
						v.can("Escalation Matter", "create")),
					_item("Escalation reporting", "/reports#escalations",
						"Ageing, severity and time-limit position.", "bi-bar-chart"),
				]},
			],
		},
		{
			"id": "insights", "label": "Insights", "icon": "bi-bar-chart",
			"groups": [
				{"label": "Reporting", "items": [
					_item("Management reporting", "/reports",
						"Where forums, documents and escalations stand today.", "bi-bar-chart"),
					_item("Coverage matrix", "/reports#coverage",
						"Which risks each forum and document covers.", "bi-grid-3x3"),
				]},
				{"label": "Analysis", "items": [
					_item("Gaps and risk", "/governance-gaps",
						"Missing coverage, and a risk score for every record.", "bi-shield-exclamation"),
					_item("Emerging risks", "/emerging-risks",
						"Rising trends and the indicators that come first.", "bi-graph-up-arrow"),
					_item("Regulatory updates", "/regulatory-updates",
						"Requirement changes and everything that cites them.", "bi-bank"),
				]},
			],
		},
		{
			"id": "admin", "label": "Admin", "icon": "bi-sliders", "show": v.is_admin,
			"groups": [
				{"label": "People and data", "items": [
					_item("Administration", "/admin", "Users, roles and reference data.", "bi-sliders"),
					_item("Imports", "/imports", "Bring records in from a file, review, then commit.",
						"bi-upload", v.can("Import Batch")),
					_item("Attestation campaigns", "/attestation-campaigns",
						"Open, generate and chase attestation campaigns.", "bi-clipboard-check",
						v.runs_campaigns),
				]},
				{"label": "Configuration", "items": [
					_item("Branding", "/app/portal-branding", "Name, logo, colours and the home banner.",
						"bi-palette", v.can("Portal Branding") and v.desk_user),
					_item("Integrations", "/integrations", "AI, document AI, horizon scanning and email.",
						"bi-plug"),
					_item("Advanced configuration", "/app", "The full workspace, for everything else.",
						"bi-gear", v.desk_user),
				]},
			],
		},
	]


def _current_path() -> tuple[str, dict]:
	request = getattr(frappe.local, "request", None)
	if not request:
		return "/", {}
	query = request.query_string.decode("latin-1") if request.query_string else ""
	return request.path or "/", dict(parse_qsl(query))


def _mark_current(menus: list[dict]) -> None:
	"""Mark the item that is the page being shown, if any.

	An item whose address matches the path and query exactly wins; failing
	that, the plain list page (an item with no query and no fragment) stands
	for any filtered view of itself. A fragment link ("/#forum-map") is a place
	on a page, never the page itself.
	"""
	path, query = _current_path()
	items = [item for menu in menus for group in menu["groups"] for item in group["items"]]
	exact, plain = None, None
	for item in items:
		parts = urlsplit(item["url"])
		if parts.fragment or parts.path != path:
			continue
		asked = dict(parse_qsl(parts.query))
		if asked and all(query.get(k) == v for k, v in asked.items()) and exact is None:
			exact = item
		elif not asked and plain is None:
			plain = item
	chosen = exact or plain
	if chosen:
		chosen["current"] = True


def cns_nav(active_nav: str | None = None) -> list[dict]:
	"""The menus the signed-in viewer may use, for the portal header.

	Each menu: ``id``, ``label``, ``icon``, ``active`` (the page is under it),
	``badge`` (carries the inbox count) and ``groups`` — each a ``label`` and its
	``items`` (``label``, ``url``, ``description``, ``icon``, ``current``). Empty
	groups and menus left with no item are dropped.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return []
	viewer = _Viewer(user)
	active = menu_id(active_nav)
	menus = []
	for menu in _menus(viewer):
		if not menu.pop("show", True):
			continue
		groups = []
		for group in menu["groups"]:
			items = [item for item in group["items"] if item.pop("show")]
			if items:
				groups.append({"label": group["label"], "items": items})
		if not groups:
			continue
		menu["groups"] = groups
		menu["active"] = menu["id"] == active
		menu.setdefault("badge", False)
		# One column per group on a wide screen; a single short list stays narrow.
		menu["wide"] = len(groups) > 1
		menus.append(menu)
	_mark_current(menus)
	return menus
