"""Every portal page renders, for everyone who can reach it (E32-S6).

The behaviour tests prove what the server does; they say nothing about whether
a screen still draws. That gap is where this project's worst regressions have
lived — a page that returns 200 with a blank body, a template that raises only
for one role, a page that prints an address value back unescaped. This module
renders every ``www/*.html`` page through the framework's own router, inside a
real request, as:

* the administrator — it renders, with no template error, and shows its key
  sections;
* one representative person per business role — it renders or refuses, and
  never errors;
* a signed-out visitor — it refuses or shows the sign-in card, and no record
  data;
* a signed-in person with no business role — the pages that name a record
  refuse them, and the administration pages refuse everyone but administrators.

It also renders every page with a script payload in every address value the
pages read, the probe ``scripts/ui_regression.py`` runs against a live site.

Pages are discovered from the ``www`` folder, so a page added later is covered
without this file changing — a new page without an entry in ``KEY_SECTIONS``
fails the completeness test, which is the point.

Records the pages are rendered against are made per test and rolled back. The
people are committed once for the module (see ``portal_personas``) and removed
when it ends.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import frappe

from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.utils import CoreTestCase, unique

WWW = Path(frappe.get_app_path("consilium", "www"))

#: What each page must show an administrator on an empty site: its heading and
#: the sections that do not depend on data. A marker is literal page text.
KEY_SECTIONS = {
	"": ["My work", "From the governance office", "Guides"],
	"admin": ["Administration", "People and access", "Reference data"],
	"attestation-campaigns": ["Attestation campaigns", "Campaigns"],
	"create-forum": ["Request a new forum", "Before you start"],
	"doc-ai": ["Doc AI", "No document was named"],
	"document-view": ["Document viewer"],
	"emerging-risks": ["Emerging risks", "Leading indicators"],
	"escalation": ["Escalation matter"],
	"escalations": ["Escalation register", "Narrow the list"],
	"exports": ["Exports", "What you can export", "Export log"],
	"formation-request": ["Formation request"],
	"formation-requests": ["Formation requests", "Narrow the list"],
	"forum-disband": ["Disbandment"],
	"forum-motion": ["Motion"],
	"forum-review": ["Compliance review"],
	"forum": ["Forum"],
	"forums": ["Forum inventory", "Narrow the list"],
	"guide": ["About this guide", "User guide", "Search the guide", "Chapters"],
	"governance-gaps": ["Gaps and risk", "Governance risk assessment"],
	"horizon-scanning": ["Horizon scanning", "Regulatory updates"],
	"imports": ["Imports", "Upload a file", "Batches"],
	"integrations": ["Integrations", "AI assistant and analysis", "Doc AI", "Horizon scanning", "Email",
	                 "Single sign-on", "What leaves the platform"],
	"policies": ["Policy library", "Narrow the list"],
	"policy-impact": ["Impact of a change"],
	"policy-intake": ["Request a policy or change", "Request a document"],
	"policy": ["Governing document"],
	"raise-escalation": ["Raise an escalation", "Before you start"],
	"records": ["Records and disposal", "Waiting for a decision", "Legal holds in force", "Disposal log"],
	"regulatory-updates": ["Regulatory updates", "Regulatory requirements"],
	"reports": ["Management reporting", "The headline"],
	"tasks": ["My work", "What to show"],
	"ui-kit": ["Interface reference", "Typography"],
}

#: Pages for platform administrators only; everyone else is refused outright.
ADMIN_ONLY = {"admin", "integrations", "ui-kit"}

#: One representative person per business role. ``nobody`` holds no role at
#: all: a signed-in account that should be able to read nothing.
PERSONAS = {
	"policy_owner": ("Policy Owner",),
	"policy_approver": ("Policy Owner",),
	"policy_reviewer": ("Policy Reviewer",),
	"secretary": ("Committee Secretary",),
	"forum_owner": ("Forum Owner",),
	"escalation_owner": ("Escalation Owner",),
	"escalation_reviewer": ("Escalation Reviewer",),
	"viewer": ("Governance Viewer",),
	"compliance_reviewer": ("Compliance Reviewer",),
	"office": ("Risk Governance Office",),
	"records_manager": ("Records Manager",),
	"consilium_admin": ("Consilium Administrator",),
	"nobody": (),
}
ROLE_PERSONAS = [p for p in PERSONAS if p != "nobody"]

#: A render that failed in the template or the context, rather than refusing.
ERROR = re.compile(r"Traceback \(most recent call last\)|TemplateSyntaxError|UndefinedError|jinja2\.exceptions")

#: Every address value a page reads. A page that ignores one is unaffected.
PARAMS = ("name", "forum", "version", "request", "batch", "requirement", "chapter", "q")
PAYLOAD = '"><script>cnsxss()</script>'

PEOPLE = PersonaPool()


def tearDownModule():
	PEOPLE.remove()


def portal_pages() -> list[str]:
	return sorted("" if html.stem == "index" else html.stem for html in WWW.glob("*.html"))


def render(route: str, user: str, query: dict | None = None) -> tuple[int, str]:
	"""Render a page as ``user``, the way a browser request would reach it.

	The router reads the request's environment, so the page is rendered inside a
	real one. The request is taken down afterwards: code elsewhere treats the
	presence of a request as "serving a browser", and a test that follows must
	not inherit this one's.
	"""
	from frappe.website.serve import get_response
	from werkzeug.test import EnvironBuilder
	from werkzeug.wrappers import Request

	query = query or {}
	previous = getattr(frappe.local, "request", None)
	frappe.set_user(user)
	frappe.local.form_dict = frappe._dict(query)
	path = "/" + route + ("?" + urlencode(query) if query else "")
	frappe.local.request = Request(EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ())
	try:
		response = get_response(route or "/")
		return response.status_code, response.get_data(as_text=True)
	finally:
		frappe.local.request = previous
		frappe.local.form_dict = frappe._dict()
		frappe.clear_messages()


def signed_out(status: int, body: str) -> bool:
	return status in (401, 403) or "Sign in to continue" in body


class PortalPageCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Each module's configuration (flag maps, workflows, roles) is idempotent
		# and normally applied on migrate; applied here so the pages render on a
		# site that has only just been created.
		from consilium.escalation.setup import install as escalation_install
		from consilium.governance import setup as governance_setup
		from consilium.policy.setup import seed as policy_seed

		policy_seed.seed_all()
		escalation_install.ensure_roles()
		escalation_install.ensure_state_flags()
		governance_setup.ensure_configuration(force=True)
		frappe.db.commit()
		PEOPLE.attach(cls, PERSONAS)

	def setUp(self):
		super().setUp()
		# /integrations audits the refusal of everyone but an administrator,
		# on a connection of its own; the rows are removed after each test.
		self.purge_on_teardown("External Tools Settings", "External Tools Settings")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def assertRendered(self, route: str, user: str, status: int, body: str, allowed=(200,)):
		label = f"/{route} as {user}"
		self.assertNotRegex(body, ERROR, f"{label}: the page errored instead of rendering")
		self.assertIn(status, allowed, f"{label}: HTTP {status}")

	# ---------------------------------------------------------------- fixtures

	def forum(self) -> str:
		from consilium.governance.tests.utils import make_forum

		return make_forum(forum_name=unique("Rendered forum")).name

	def document(self):
		from consilium.policy.tests.utils import make_document

		return make_document(
			document_name=unique("Rendered policy"),
			owner_user=self.policy_owner,
			document_approver=self.policy_approver,
		)

	def matter(self):
		from consilium.escalation.tests.utils import make_taxonomy

		return frappe.get_doc(
			{
				"doctype": "Escalation Matter",
				"escalation_title": unique("Rendered matter"),
				"escalation_type": make_taxonomy("Escalation Type", "escalation_type_code", "escalation_type_name"),
				"escalation_identification_date": "2026-01-05",
				"description": "A matter rendered by the page tests.",
				"tier_1_risk_type": make_taxonomy("Risk Type", "risk_type_code", "risk_type_name", tier=1),
				"identified_by": self.escalation_owner,
				"organizational_level": make_taxonomy(
					"Organizational Level", "organizational_level_code", "organizational_level_name", level_rank=3
				),
				"accountable_executive": self.escalation_owner,
				"escalation_trigger": "A control failed twice in one quarter.",
				"severity": "Medium",
				"severity_source": "Manual Override",
				"impacted_entities": [
					{
						"entity_type": "Legal Entity",
						"entity_value": make_taxonomy("Legal Entity", "legal_entity_code", "legal_entity_name"),
					}
				],
			}
		).insert(ignore_permissions=True)


class TestEveryPageIsCovered(PortalPageCase):
	def test_every_www_page_has_its_key_sections_listed(self):
		pages = set(portal_pages())
		self.assertEqual(
			pages - set(KEY_SECTIONS), set(), "a portal page with no entry in KEY_SECTIONS is not tested"
		)
		self.assertEqual(set(KEY_SECTIONS) - pages, set(), "KEY_SECTIONS names a page that no longer exists")


class TestAdministrator(PortalPageCase):
	def test_every_page_renders_with_its_key_sections(self):
		for route in portal_pages():
			with self.subTest(route=route):
				status, body = render(route, "Administrator")
				self.assertRendered(route, "Administrator", status, body)
				for marker in KEY_SECTIONS.get(route, []):
					self.assertIn(marker, body, f"/{route}: key section {marker!r} is missing")

	def test_record_pages_render_a_real_record(self):
		forum = self.forum()
		document = self.document()
		matter = self.matter()
		cases = [
			("forum", {"name": forum}, frappe.db.get_value("Governance Forum", forum, "forum_name")),
			("forum-review", {"forum": forum}, frappe.db.get_value("Governance Forum", forum, "forum_name")),
			("forum-disband", {"forum": forum}, frappe.db.get_value("Governance Forum", forum, "forum_name")),
			("policy", {"name": document.name}, document.document_name),
			("policy-impact", {"name": document.name}, document.document_name),
			("escalation", {"name": matter.name}, matter.escalation_title),
		]
		for route, query, title in cases:
			with self.subTest(route=route):
				status, body = render(route, "Administrator", query)
				self.assertRendered(route, "Administrator", status, body)
				self.assertIn(title, body, f"/{route}: the record's title is not on its page")
				if route != "policy-impact":
					# The theme draws the record's summary card as its highlights
					# panel by this class, not by the card's id.
					self.assertIn("cns-record-summary", body, f"/{route}: the summary card lost its class")

	def test_a_reference_that_does_not_exist_renders_an_empty_state(self):
		for route in ("forum", "policy", "escalation", "formation-request", "document-view", "policy-impact"):
			with self.subTest(route=route):
				param = "version" if route == "document-view" else "name"
				status, body = render(route, "Administrator", {param: unique("MISSING")})
				self.assertRendered(route, "Administrator", status, body, allowed=(200, 404))


class TestSignedOutVisitor(PortalPageCase):
	def test_every_page_refuses_or_asks_to_sign_in(self):
		for route in portal_pages():
			with self.subTest(route=route):
				status, body = render(route, "Guest")
				self.assertRendered(route, "Guest", status, body, allowed=(200, 401, 403))
				self.assertTrue(signed_out(status, body), f"/{route}: HTTP {status} with no sign-in prompt")

	def test_a_visitor_sees_no_record_data(self):
		forum = self.forum()
		document = self.document()
		matter = self.matter()
		titles = {
			frappe.db.get_value("Governance Forum", forum, "forum_name"),
			document.document_name,
			matter.escalation_title,
		}
		cases = [
			("forum", {"name": forum}),
			("forum-review", {"forum": forum}),
			("policy", {"name": document.name}),
			("policy-impact", {"name": document.name}),
			("escalation", {"name": matter.name}),
			("forums", {}),
			("policies", {}),
			("escalations", {}),
			("", {}),
		]
		for route, query in cases:
			with self.subTest(route=route):
				status, body = render(route, "Guest", query)
				self.assertTrue(signed_out(status, body), f"/{route}: HTTP {status} with no sign-in prompt")
				for title in titles:
					self.assertNotIn(title, body, f"/{route}: a signed-out visitor was shown {title!r}")


class TestEveryRole(PortalPageCase):
	def test_every_page_renders_or_refuses_for_every_role(self):
		for persona in ROLE_PERSONAS:
			user = getattr(self, persona)
			for route in portal_pages():
				with self.subTest(persona=persona, route=route):
					status, body = render(route, user)
					self.assertRendered(route, persona, status, body, allowed=(200, 403))

	def test_administration_pages_refuse_everyone_but_administrators(self):
		for route in sorted(ADMIN_ONLY):
			with self.subTest(route=route, persona="consilium_admin"):
				status, body = render(route, self.consilium_admin)
				self.assertRendered(route, "consilium_admin", status, body)
			for persona in ("policy_owner", "secretary", "escalation_owner", "viewer", "nobody"):
				with self.subTest(route=route, persona=persona):
					status, body = render(route, getattr(self, persona))
					self.assertRendered(route, persona, status, body, allowed=(403,))

	def test_a_policy_owner_reads_their_own_document(self):
		document = self.document()
		status, body = render("policy", self.policy_owner, {"name": document.name})
		self.assertRendered("policy", "policy_owner", status, body)
		self.assertIn(document.document_name, body)


class TestReaderWithoutAccess(PortalPageCase):
	"""A signed-in account with no business role reads no record by its page."""

	def test_every_page_renders_or_refuses_without_error(self):
		for route in portal_pages():
			with self.subTest(route=route):
				status, body = render(route, self.nobody)
				self.assertRendered(route, "nobody", status, body, allowed=(200, 403))

	def test_record_pages_do_not_show_the_record(self):
		forum = self.forum()
		document = self.document()
		matter = self.matter()
		forum_title = frappe.db.get_value("Governance Forum", forum, "forum_name")
		cases = [
			("forum", {"name": forum}, forum_title),
			("forum-review", {"forum": forum}, forum_title),
			("policy", {"name": document.name}, document.document_name),
			("policy-impact", {"name": document.name}, document.document_name),
			("escalation", {"name": matter.name}, matter.escalation_title),
		]
		for route, query, title in cases:
			with self.subTest(route=route):
				status, body = render(route, self.nobody, query)
				self.assertRendered(route, "nobody", status, body, allowed=(200, 403))
				self.assertNotIn(title, body, f"/{route}: a reader without access was shown the record")


class TestAddressValuesAreEscaped(PortalPageCase):
	def test_no_page_reflects_a_script_payload(self):
		query = {param: PAYLOAD for param in PARAMS}
		for route in portal_pages():
			with self.subTest(route=route):
				status, body = render(route, "Administrator", query)
				self.assertNotRegex(body, ERROR, f"/{route}: a crafted address made the page error")
				self.assertNotIn(PAYLOAD, body, f"/{route}: the payload came back unescaped")
				self.assertNotIn("<script>cnsxss()", body, f"/{route}: the payload came back unescaped")
