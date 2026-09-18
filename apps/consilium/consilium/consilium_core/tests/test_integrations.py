"""External tools (Doc AI, horizon scanning) and the Integrations page.

What is proved here, by doing rather than reading:

* the Doc AI address is built from its template with every value URL-encoded,
  and carries identifiers only;
* a ``javascript:`` address (and every other non-http(s) address, and the
  tricks a browser forgives) is refused on save, and the refusal is audited;
* a tool that is not connected still shows its button, which explains itself
  and sends nothing; a switched-off tool shows none;
* a hand-off is refused, audited, to anyone who may not read the document or
  lacks a role the settings list, and recorded in the Access Log otherwise;
* ``/integrations`` and its endpoints are for administrators only, never
  return a saved key, and "Test connection" reports success, latency and
  failure through the audited AI client, against a stand-in on 127.0.0.1.

Test users are standing personas (fixed example.com addresses, made once per
site), because a shared test site soon reaches the framework's hourly limit
on new users.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import frappe

from consilium.consilium_core.ai import client
from consilium.consilium_core.integrations import admin, external_tools
from consilium.consilium_core.tests import test_assistant as ta
from consilium.consilium_core.tests.http_stub import stub_server
from consilium.consilium_core.tests.test_portal_pages import render
from consilium.policy import publication
from consilium.policy.tests.utils import PolicyTestCase, make_document, purge_refusals, refusals_for

#: The framework commits an Access Log written during a GET request, which in a
#: test would commit the test's records too. Page renders patch it out; the
#: hand-off's own log is asserted by calling the hand-off directly.
NO_ACCESS_LOG_COMMIT = "frappe.core.doctype.access_log.access_log.make_access_log"

TOOLS = external_tools.SETTINGS
AI = "Assistant Settings"
DOCUMENT = "Governing Document"

TEMPLATE = "https://docai.example.internal/open?doc={document}&version={version}&label={version_label}" \
           "&title={title}&source={document_url}"

PERSONAS = {
	"int-admin": ("Consilium Administrator",),
	"int-reader": ("Policy Reviewer",),
	"int-office": ("Policy Reviewer", "Enterprise Policy Office"),
	"int-outsider": ("Escalation Owner",),
}


class IntegrationsCase(PolicyTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.users = {}
		for key, roles in PERSONAS.items():
			cls.users[key] = ta._with_retry(lambda key=key, roles=roles: ta.persona(key, roles))
			frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.purge_on_teardown(TOOLS, TOOLS)
		self.purge_on_teardown(AI, AI)
		self.tools(doc_ai_enabled=1, doc_ai_label="", doc_ai_url_template="", doc_ai_new_tab=1, doc_ai_roles=[],
		           horizon_enabled=1, horizon_label="", horizon_url="", horizon_new_tab=1)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()
		frappe.clear_document_cache(TOOLS, TOOLS)
		frappe.clear_document_cache(AI, AI)

	def tools(self, **values):
		frappe.set_user("Administrator")
		s = frappe.get_single(TOOLS)
		s.update(values)
		s.save(ignore_permissions=True)
		frappe.clear_document_cache(TOOLS, TOOLS)
		return s

	def as_user(self, key):
		frappe.set_user(self.users[key])

	def document_with_version(self, **values):
		doc = make_document(owner_user=self.users["int-office"], document_approver=self.users["int-office"],
		                    document_name=values.pop("document_name", "Risk & Control / Policy"), **values)
		publication.upload_version(doc.name, change_summary="First text", body_text="<p>Text</p>", version_label="1.0")
		doc.reload()
		self.purge_on_teardown(DOCUMENT, doc.name)
		return doc

	def access_logs(self, document):
		return frappe.get_all("Access Log", filters={"reference_document": document,
		                                             "method": external_tools.HANDOFF_METHOD},
		                      fields=["user", "export_from", "filters", "page"])


# ------------------------------------------------------------- addresses


class TestAddresses(IntegrationsCase):
	def test_the_doc_ai_address_encodes_every_value(self):
		url = external_tools.build_doc_ai_url(TEMPLATE, {
			"document": "GDOC-0001",
			"version": "DVER 7",
			"version_label": "2.1 draft",
			"title": "Risk & Control / Policy?#",
			"document_url": "https://portal.example.internal/policy?name=GDOC-0001",
		})
		parts = urlsplit(url)
		self.assertEqual((parts.scheme, parts.netloc, parts.path), ("https", "docai.example.internal", "/open"))
		query = parse_qs(parts.query)
		self.assertEqual(query["doc"], ["GDOC-0001"])
		self.assertEqual(query["version"], ["DVER 7"])
		self.assertEqual(query["label"], ["2.1 draft"])
		self.assertEqual(query["title"], ["Risk & Control / Policy?#"])
		self.assertEqual(query["source"], ["https://portal.example.internal/policy?name=GDOC-0001"])
		self.assertIn("title=Risk%20%26%20Control%20%2F%20Policy%3F%23", url)
		self.assertNotIn("#", url)

	def test_a_script_address_is_refused_and_audited(self):
		bad = ("javascript:alert(document.cookie)", "JavaScript:alert(1)", "  javascript:alert(1)",
		       "java\tscript:alert(1)", "java\nscript:alert(1)", "data:text/html,<script>x</script>",
		       "vbscript:msgbox(1)", "file:///etc/passwd", "ftp://files.example.internal/x",
		       "//evil.example/x", "/relative/path", "https://", "https://docai.example.internal/a b")
		for value in bad:
			for field in ("doc_ai_url_template", "horizon_url"):
				with self.subTest(value=value, field=field):
					with self.assertRaises(frappe.ValidationError):
						self.tools(**{field: value})
					frappe.db.rollback()
		reasons = refusals_for(TOOLS, TOOLS)
		self.assertTrue(reasons)
		self.assertTrue(all(r.control == "external address check" for r in reasons))
		self.assertTrue(any("javascript:" in r.refusal_reason for r in reasons))
		self.assertEqual(frappe.db.get_single_value(TOOLS, "horizon_url") or "", "")

	def test_placeholders_may_not_choose_the_host(self):
		with self.assertRaises(frappe.ValidationError):
			self.tools(doc_ai_url_template="https://{title}.example.internal/open")
		frappe.db.rollback()
		with self.assertRaises(frappe.ValidationError):
			self.tools(doc_ai_url_template="https://docai.example.internal/open?x={secret_field}")

	def test_a_template_written_by_hand_is_checked_again_when_used(self):
		with self.assertRaises(frappe.ValidationError):
			external_tools.build_doc_ai_url("{document_url}", {"document_url": "javascript:alert(1)"})

	def test_good_addresses_are_kept(self):
		s = self.tools(doc_ai_url_template="  " + TEMPLATE + " ", horizon_url="https://horizon.example.internal/watch")
		self.assertEqual(s.doc_ai_url_template, TEMPLATE)
		self.assertEqual(s.horizon_url, "https://horizon.example.internal/watch")


# -------------------------------------------------------------- Doc AI


class TestDocAi(IntegrationsCase):
	def test_not_connected_still_shows_the_button_and_sends_nothing(self):
		doc = self.document_with_version()
		self.as_user("int-reader")
		tools = external_tools.cns_external_tools()
		self.assertTrue(tools["doc_ai"]["shown"])
		self.assertEqual(tools["doc_ai"]["state"], external_tools.NOT_CONNECTED)
		self.assertEqual(tools["doc_ai"]["label"], "Open in Doc AI")

		result = external_tools.doc_ai_handoff(doc.name)
		self.assertEqual(result["state"], external_tools.NOT_CONNECTED)
		self.assertIsNone(result["url"])
		self.assertEqual(self.access_logs(doc.name), [])

		status, body = render("doc-ai", self.users["int-reader"], {"name": doc.name})
		self.assertEqual(status, 200)
		self.assertIn("Doc AI isn&rsquo;t connected yet", body)
		self.assertIn("Admin &rarr; Integrations", body)
		self.assertNotIn('href="/integrations"', body)  # the way in is for administrators

		status, body = render("policy", self.users["int-reader"], {"name": doc.name})
		self.assertEqual(status, 200)
		self.assertIn('data-cns-tool-state="not_connected"', body)
		self.assertIn("/doc-ai?name=" + frappe.utils.quote(doc.name), body)

	def test_a_connected_hand_off_is_addressed_logged_and_redirected(self):
		doc = self.document_with_version()
		self.tools(doc_ai_url_template=TEMPLATE, doc_ai_label="Edit in Doc AI")
		self.as_user("int-reader")
		result = external_tools.doc_ai_handoff(doc.name)
		query = parse_qs(urlsplit(result["url"]).query)
		self.assertEqual(query["doc"], [doc.name])
		self.assertEqual(query["version"], [doc.current_version])
		self.assertEqual(query["label"], ["1.0"])
		self.assertEqual(query["title"], [doc.document_name])
		self.assertEqual(query["source"], [external_tools.document_url(doc.name)])
		# Identifiers only: never the text of the version.
		self.assertNotIn("Text", result["url"])

		logs = self.access_logs(doc.name)
		self.assertEqual(len(logs), 1)
		self.assertEqual(logs[0].user, self.users["int-reader"])
		self.assertEqual(logs[0].export_from, DOCUMENT)
		self.assertIn(doc.current_version, logs[0].filters)
		self.assertIn("docai.example.internal", logs[0].filters)

		status, body = render("policy", self.users["int-reader"], {"name": doc.name})
		self.assertIn("Edit in Doc AI", body)
		self.assertIn('data-cns-tool-state="connected"', body)
		self.assertIn('rel="noopener noreferrer"', body)
		self.assertNotIn("docai.example.internal", body)  # the address is built on the way out, never in a page

	def test_the_hand_off_page_redirects(self):
		from frappe.website.serve import get_response
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		doc = self.document_with_version()
		self.tools(doc_ai_url_template=TEMPLATE)
		frappe.set_user(self.users["int-reader"])
		frappe.local.form_dict = frappe._dict(name=doc.name, version=doc.current_version)
		frappe.local.request = Request(EnvironBuilder(path="/doc-ai", base_url="http://" + frappe.local.site).get_environ())
		try:
			with patch(NO_ACCESS_LOG_COMMIT) as logged:
				response = get_response("doc-ai")
			self.assertEqual(logged.call_args.kwargs["method"], external_tools.HANDOFF_METHOD)
		finally:
			frappe.local.request = None
			frappe.local.form_dict = frappe._dict()
			frappe.flags.redirect_location = None
		self.assertEqual(response.status_code, 302)
		self.assertTrue(response.headers["Location"].startswith("https://docai.example.internal/open?doc="))

	def test_a_version_of_another_document_is_not_found(self):
		doc = self.document_with_version()
		other = self.document_with_version(document_name="Another policy")
		with self.assertRaises(frappe.DoesNotExistError):
			external_tools.doc_ai_handoff(doc.name, other.current_version)

	def test_someone_who_cannot_read_the_document_is_refused(self):
		doc = self.document_with_version()
		self.tools(doc_ai_url_template=TEMPLATE)
		self.as_user("int-outsider")
		with self.assertRaises(frappe.PermissionError):
			external_tools.doc_ai_handoff(doc.name)
		frappe.set_user("Administrator")
		self.assertTrue(any(r.control == "document read" for r in refusals_for(DOCUMENT, doc.name)))
		self.assertEqual(self.access_logs(doc.name), [])

	def test_a_role_list_narrows_who_sees_and_uses_it(self):
		doc = self.document_with_version()
		self.tools(doc_ai_url_template=TEMPLATE, doc_ai_roles=[{"role": "Enterprise Policy Office"}])

		self.as_user("int-reader")
		self.assertFalse(external_tools.cns_external_tools()["doc_ai"]["shown"])
		with self.assertRaises(frappe.PermissionError):
			external_tools.doc_ai_handoff(doc.name)
		frappe.set_user("Administrator")
		self.assertTrue(any(r.control == "external tool roles" for r in refusals_for(DOCUMENT, doc.name)))
		status, body = render("policy", self.users["int-reader"], {"name": doc.name})
		self.assertNotIn("/doc-ai?name=", body)

		self.as_user("int-office")
		self.assertTrue(external_tools.cns_external_tools()["doc_ai"]["shown"])
		self.assertTrue(external_tools.doc_ai_handoff(doc.name)["url"])

	def test_switched_off_shows_no_button(self):
		doc = self.document_with_version()
		self.tools(doc_ai_enabled=0, doc_ai_url_template=TEMPLATE)
		self.as_user("int-reader")
		self.assertFalse(external_tools.cns_external_tools()["doc_ai"]["shown"])
		result = external_tools.doc_ai_handoff(doc.name)
		self.assertEqual(result["state"], external_tools.OFF)
		self.assertIsNone(result["url"])
		status, body = render("policy", self.users["int-reader"], {"name": doc.name})
		self.assertNotIn("/doc-ai?name=", body)

	def test_the_viewer_offers_it_beside_the_file(self):
		doc = self.document_with_version()
		with patch(NO_ACCESS_LOG_COMMIT):
			status, body = render("document-view", self.users["int-reader"], {"version": doc.current_version})
		self.assertEqual(status, 200)
		self.assertIn("/doc-ai?name=" + frappe.utils.quote(doc.name) + "&amp;version=" + frappe.utils.quote(doc.current_version), body)
		self.assertIn("Open in Doc AI", body)

	def test_a_signed_out_visitor_gets_nothing(self):
		frappe.set_user("Guest")
		tools = external_tools.cns_external_tools()
		self.assertFalse(tools["doc_ai"]["shown"])
		self.assertFalse(tools["horizon"]["shown"])


# ---------------------------------------------------------- horizon scanning


class TestHorizonScanning(IntegrationsCase):
	def test_not_connected_explains_and_offers_integrations_to_administrators(self):
		status, body = render("horizon-scanning", self.users["int-reader"])
		self.assertEqual(status, 200)
		self.assertIn("Horizon scanning isn&rsquo;t connected yet", body)
		self.assertNotIn('href="/integrations"', body)
		status, body = render("horizon-scanning", self.users["int-admin"])
		self.assertIn('href="/integrations"', body)

	def test_connected_redirects_and_the_label_comes_from_settings(self):
		self.tools(horizon_url="https://horizon.example.internal/watch", horizon_label="Scan the horizon")
		target = external_tools.horizon_target()
		self.assertEqual(target["url"], "https://horizon.example.internal/watch")
		for route in ("policies", "regulatory-updates"):
			with self.subTest(route=route):
				status, body = render(route, self.users["int-reader"])
				self.assertEqual(status, 200)
				# The page's own button (the header menu links there too).
				self.assertRegex(body, r'href="/horizon-scanning"\s+data-cns-tool="Scan the horizon" data-cns-tool-state="connected"')

	def test_switched_off_removes_the_buttons(self):
		self.tools(horizon_enabled=0, horizon_url="https://horizon.example.internal/watch")
		self.assertIsNone(external_tools.horizon_target()["url"])
		status, body = render("policies", self.users["int-reader"])
		self.assertNotRegex(body, r'href="/horizon-scanning"\s+data-cns-tool=')


# ------------------------------------------------------- the Integrations page


class TestIntegrationsPage(IntegrationsCase):
	def configure_ai(self, url, **values):
		frappe.set_user("Administrator")
		s = frappe.get_single(AI)
		s.update({"provider": client.ANTHROPIC, "endpoint_url": url, "model": "stand-in-model",
		          "api_key": "dummy-test-key", "timeout_seconds": 1, "max_tokens": 800,
		          "ai_enabled": 0, "features_enabled": 0})
		s.update(values)
		s.save(ignore_permissions=True)
		frappe.clear_document_cache(AI, AI)

	def test_administrators_only(self):
		for key in ("int-reader", "int-outsider"):
			with self.subTest(persona=key):
				status, _body = render("integrations", self.users[key])
				self.assertEqual(status, 403)
				self.as_user(key)
				for call in (admin.state, lambda: admin.save("horizon", {"horizon_url": "https://x.example"}),
				             admin.test_ai_connection, admin.send_test_email):
					with self.assertRaises(frappe.PermissionError):
						call()
		frappe.set_user("Administrator")
		self.assertTrue(any(r.control == "integrations administration" for r in refusals_for(TOOLS, TOOLS)))
		status, body = render("integrations", self.users["int-admin"])
		self.assertEqual(status, 200)
		for marker in ("AI assistant and analysis", "Doc AI", "Horizon scanning", "Email", "Single sign-on",
		               "What leaves the platform", "Test connection", "Send a test email to me"):
			self.assertIn(marker, body)

	def test_a_saved_key_is_never_returned(self):
		self.as_user("int-admin")
		card = admin.save("ai", {"api_key": "sk-never-shown-12345", "ai_enabled": 1, "endpoint_url": "https://ai.example.internal/v1",
		                         "model": "m", "provider": client.OPENAI_COMPATIBLE})
		self.assertTrue(card["has_key"])
		self.assertEqual(card["status"], external_tools.CONNECTED)
		self.assertNotIn("sk-never-shown-12345", frappe.as_json(admin.state()))
		status, body = render("integrations", self.users["int-admin"])
		self.assertIn("A key is saved", body)
		self.assertNotIn("sk-never-shown-12345", body)
		# Saving without a key keeps it; asking to remove it removes it.
		self.as_user("int-admin")
		self.assertTrue(admin.save("ai", {"model": "m2"})["has_key"])
		card = admin.save("ai", {"clear_api_key": 1})
		self.assertFalse(card["has_key"])
		self.assertTrue(any("no API key is saved" in w for w in card["warnings"]))

	def test_only_the_cards_fields_are_written(self):
		before = frappe.db.get_single_value(AI, "rate_limit_per_hour")
		self.as_user("int-admin")
		admin.save("ai", {"rate_limit_per_hour": 999, "model": "m"})
		self.assertEqual(frappe.db.get_single_value(AI, "rate_limit_per_hour"), before)
		with self.assertRaises(frappe.ValidationError):
			admin.save("nothing-here", {})

	def test_the_doc_ai_card_saves_its_roles(self):
		self.as_user("int-admin")
		card = admin.save("doc_ai", {"doc_ai_url_template": TEMPLATE,
		                             "doc_ai_roles": ["Enterprise Policy Office", "Guest", "No Such Role"]})
		self.assertEqual(card["roles"], ["Enterprise Policy Office"])
		self.assertEqual(card["status"], external_tools.CONNECTED)
		with self.assertRaises(frappe.ValidationError):
			admin.save("horizon", {"horizon_url": "javascript:alert(1)"})

	def test_who_sees_the_button_offers_only_the_platforms_roles(self):
		"""The role list is the roles this platform's own record types grant, plus
		System Manager — not every role the framework ships (a blogger, an
		accounts manager), which would restrict nothing meaningful here."""
		for role in ("Blogger", "Accounts Manager"):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		self.as_user("int-admin")
		offered = admin.doc_ai_card()["roles_offered"]
		self.assertIn("Enterprise Policy Office", offered)
		self.assertIn("Policy Reviewer", offered)
		self.assertIn("System Manager", offered)
		for role in ("Blogger", "Accounts Manager", "Guest", "All", "Administrator"):
			self.assertNotIn(role, offered)
		# Every role offered is named by a permission rule on one of the platform's
		# record types, or is System Manager.
		platform = set(frappe.get_all("DocType", filters={"module": ["in", admin.APP_MODULES]}, pluck="name"))
		for role in offered:
			if role == "System Manager":
				continue
			granted = {row.parent for row in frappe.get_all("DocPerm", filters={"role": role}, fields=["parent"])}
			granted |= {row.parent for row in frappe.get_all("Custom DocPerm", filters={"role": role}, fields=["parent"])}
			self.assertTrue(granted & platform, role)
		# A role outside the list cannot be saved onto the card.
		card = admin.save("doc_ai", {"doc_ai_url_template": TEMPLATE, "doc_ai_roles": ["Blogger", "Policy Reviewer"]})
		self.assertEqual(card["roles"], ["Policy Reviewer"])

	def test_the_email_route_is_named_in_words(self):
		from consilium.consilium_core.integrations import graph_mail

		self.as_user("int-admin")
		card = admin.email_card()
		self.assertEqual(card["route_labels"][graph_mail.SMTP_ROUTE], "Your organisation's mail server (SMTP)")
		self.assertNotIn("framework", card["route_label"].lower())
		status, body = render("integrations", self.users["int-admin"])
		self.assertIn("Your organisation&#39;s mail server (SMTP)", body.replace("'", "&#39;"))
		self.assertNotIn(">SMTP (framework mail queue)<", body)

	def test_connection_test_reports_success_and_latency(self):
		with ta.stub_endpoint(reply="OK") as (server, url):
			self.configure_ai(url)
			self.as_user("int-admin")
			outcome = admin.test_ai_connection()
		self.assertTrue(outcome["ok"], outcome)
		self.assertEqual(outcome["status"], "Succeeded")
		self.assertIsInstance(outcome["latency_ms"], int)
		self.assertEqual(outcome["reply"], "OK")
		self.assertEqual(server.requests[0]["headers"].get("x-api-key"), "dummy-test-key")
		# The configured maximum length is used, so a reasoning model has room.
		self.assertEqual(server.requests[0]["body"]["max_tokens"], 800)
		row = frappe.get_doc("AI Service Request", outcome["service_request"])
		self.assertEqual(row.capability, admin.TEST_CAPABILITY)
		self.assertEqual(row.status, "Succeeded")
		self.assertEqual(admin.ai_card()["last_test"]["status"], "Succeeded")
		self.assertTrue(admin.ai_card()["last_test"]["ok"])
		self.assertEqual(outcome["card"]["last_test"]["reference"], outcome["service_request"])
		# The card remembers it: rendered afresh, the status says when it was tested.
		status, body = render("integrations", self.users["int-admin"])
		self.assertIn("last tested", body)
		self.assertNotIn("not tested yet", body)

	def test_connection_test_reports_the_error(self):
		with ta.stub_endpoint(mode="error") as (server, url):
			self.configure_ai(url)
			self.as_user("int-admin")
			outcome = admin.test_ai_connection()
		self.assertFalse(outcome["ok"])
		self.assertEqual(outcome["status"], "Failed")
		self.assertIn("HTTP 500", outcome["error"])

	def test_connection_test_names_a_reasoning_model_that_ran_out_of_room(self):
		def reasoning(request, server):
			return 200, {}, {"choices": [{"message": {"role": "assistant", "content": "",
			                                          "reasoning_content": "Let me think about this at length"},
			                              "finish_reason": "length"}]}

		with stub_server(reasoning) as (server, url):
			self.configure_ai(url + "/chat/completions", provider=client.OPENAI_COMPATIBLE)
			self.as_user("int-admin")
			outcome = admin.test_ai_connection()
		self.assertEqual(server.requests[0]["path"], "/chat/completions")
		self.assertEqual(server.requests[0]["headers"]["authorization"], "Bearer dummy-test-key")
		self.assertFalse(outcome["ok"])
		self.assertIn("raise the maximum length", outcome["error"])

	def test_connection_test_needs_an_endpoint(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value(AI, "endpoint_url", "")
		frappe.clear_document_cache(AI, AI)
		self.as_user("int-admin")
		outcome = admin.test_ai_connection()
		self.assertFalse(outcome["ok"])
		self.assertEqual(outcome["status"], "Not Configured")

	def test_the_legacy_request_format_still_works(self):
		s = frappe._dict(provider=client.LEGACY_OPENAI_COMPATIBLE, endpoint_url="https://gw.example/v1")
		self.assertEqual(client.endpoint_url(s), "https://gw.example/v1/chat/completions")

	def test_a_test_email_through_graph_reaches_the_administrator(self):
		from consilium.consilium_core.integrations import graph_mail
		from consilium.consilium_core.setup import notification_templates
		from consilium.consilium_core.tests.test_graph_mail import GraphStub

		notification_templates.seed_email_channel()
		stub = GraphStub()
		with stub_server(stub) as (server, url):
			frappe.set_user("Administrator")
			s = frappe.get_single(graph_mail.SETTINGS)
			s.update({"delivery_route": graph_mail.GRAPH_ROUTE, "graph_tenant_id": "t1", "graph_client_id": "c1",
			          "graph_client_secret": "dummy-secret", "graph_sender": "governance@example.com",
			          "graph_authority_url": url, "graph_api_url": url, "graph_timeout_seconds": 2})
			s.save(ignore_permissions=True)
			self.as_user("int-admin")
			outcome = admin.send_test_email()
		graph_mail.forget_tokens()
		self.assertTrue(outcome["ok"], outcome)
		self.assertEqual(outcome["route"], graph_mail.GRAPH_ROUTE)
		sent = GraphStub.sends(server)[0]["json"]["message"]
		self.assertEqual(sent["toRecipients"][0]["emailAddress"]["address"],
		                 frappe.db.get_value("User", self.users["int-admin"], "email"))
		self.assertEqual(frappe.db.get_value("Notification Dispatch", outcome["dispatch"], "status"), "Sent")
		card = admin.email_card()
		self.assertTrue(card["has_secret"])
		self.assertNotIn("dummy-secret", frappe.as_json(card))

	def test_a_test_email_through_smtp_is_sent_now_and_recorded(self):
		from consilium.consilium_core import notification
		from consilium.consilium_core.setup import notification_templates

		notification_templates.seed_email_channel()
		calls = []

		def sendmail(**kwargs):
			calls.append(kwargs)
			return frappe._dict(name="queued")

		# The mail server itself is the framework's to test; what is proved here
		# is that the test email is sent now rather than queued, and recorded.
		with patch.object(notification, "email_configured", return_value=True), \
				patch.object(frappe, "sendmail", sendmail):
			self.as_user("int-admin")
			outcome = admin.send_test_email()
		self.assertTrue(outcome["ok"], outcome)
		self.assertIs(calls[0]["delayed"], False)
		self.assertEqual(calls[0]["recipients"], [frappe.db.get_value("User", self.users["int-admin"], "email")])
		row = frappe.get_doc("Notification Dispatch", outcome["dispatch"])
		self.assertEqual(row.channel, "EMAIL")
		self.assertEqual(row.status, "Sent")
		# Notifications, unlike the test, still go through the queue.
		self.assertFalse(frappe.flags.cns_mail_inline)

	def test_the_single_sign_on_card_shows_the_redirect_address(self):
		frappe.set_user("Administrator")
		card = admin.sso_card()
		self.assertTrue(card["expected_redirect_uri"].endswith(
			"/api/method/frappe.integrations.oauth2_logins.custom/corporate_sso"))
		key = frappe.get_doc({
			"doctype": "Social Login Key", "provider_name": "Test Directory Provider",
			"social_login_provider": "Custom", "enable_social_login": 1, "client_id": "portal-client",
			"client_secret": "dummy", "custom_base_url": 1, "base_url": "https://idp.example.internal",
			"authorize_url": "https://idp.example.internal/oauth2/authorize",
			"access_token_url": "https://idp.example.internal/oauth2/token",
			"api_endpoint": "https://idp.example.internal/oauth2/userinfo",
			"redirect_url": "/api/method/frappe.integrations.oauth2_logins.custom/test_directory_provider",
			"user_id_property": "sub",
		}).insert(ignore_permissions=True)
		card = admin.sso_card()
		provider = next(p for p in card["providers"] if p["key"] == key.name)
		self.assertTrue(provider["enabled"])
		self.assertEqual(provider["redirect_uri"], frappe.utils.get_url(
			"/api/method/frappe.integrations.oauth2_logins.custom/test_directory_provider"))
		self.assertEqual(card["status"], external_tools.CONNECTED)
		self.assertNotIn("dummy", frappe.as_json(card))
