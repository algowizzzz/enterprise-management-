"""The help assistant: built-in answers, permission-awareness, audit, the
hourly limit, and the optional AI mode against a local stand-in endpoint.

Nothing here reaches the network. AI mode is exercised against a tiny HTTP
server started on 127.0.0.1 inside the test, which answers in the Messages API
shape (or the OpenAI-compatible shape), stalls past the timeout, or fails —
so the fallback path is tested as carefully as the happy one. The API key used
is a dummy string; no real key appears anywhere.

The assistant must never describe a record the asker cannot read, so the
sensitive-escalation tests compare the whole answer for a hidden record with
the answer for a reference that does not exist: they must be identical.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import frappe

from consilium.consilium_core import assistant
from consilium.consilium_core.assistant import answer as answer_mod
from consilium.consilium_core.assistant import context as ctxmod
from consilium.consilium_core.assistant import corpus
from consilium.consilium_core.tests.utils import purge_refusals
from consilium.escalation import sensitivity
from consilium.escalation.tests.utils import EscalationTestCase, make_forum, make_user

SETTINGS = "Assistant Settings"
LOG = "Assistant Interaction"


# ---------------------------------------------------------------- stand-in


class _StubHandler(BaseHTTPRequestHandler):
	"""Answers like an AI endpoint would. Behaviour is set on the server."""

	def log_message(self, *args):  # keep test output clean
		pass

	def do_POST(self):  # noqa: N802 — the stdlib's name
		length = int(self.headers.get("content-length") or 0)
		body = json.loads(self.rfile.read(length) or b"{}")
		# urllib capitalises header names on the way out; compare them lower-cased.
		headers = {k.lower(): v for k, v in self.headers.items()}
		self.server.requests.append({"path": self.path, "headers": headers, "body": body})
		mode = self.server.mode
		if mode == "slow":
			time.sleep(3)
		if mode == "error":
			self._send(500, {"type": "error", "error": {"type": "api_error", "message": "stand-in failure"}})
			return
		if mode == "refusal":
			self._send(200, {"type": "message", "role": "assistant", "content": [],
			                 "stop_reason": "refusal", "stop_details": {"type": "refusal"}})
			return
		text = self.server.reply
		if mode == "openai":
			self._send(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})
			return
		self._send(200, {
			"id": "msg_stub", "type": "message", "role": "assistant", "model": body.get("model"),
			"content": [{"type": "text", "text": text}],
			"stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 10},
		})

	def _send(self, status, payload):
		raw = json.dumps(payload).encode()
		try:
			self.send_response(status)
			self.send_header("content-type", "application/json")
			self.send_header("content-length", str(len(raw)))
			self.end_headers()
			self.wfile.write(raw)
		except (BrokenPipeError, ConnectionResetError):
			pass  # the client gave up (the timeout test), which is the point


@contextlib.contextmanager
def stub_endpoint(mode="anthropic", reply="From the stand-in. See [the forum inventory](/forums) and [elsewhere](https://example.com/x)."):
	server = HTTPServer(("127.0.0.1", 0), _StubHandler)
	server.mode, server.reply, server.requests = mode, reply, []
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	try:
		yield server, f"http://127.0.0.1:{server.server_address[1]}"
	finally:
		server.shutdown()
		server.server_close()


# ------------------------------------------------------------------- tests


def _with_retry(fn, attempts=6):
	"""Run a fixture step, retrying a deadlock.

	Creating a user makes the framework rewrite one shared defaults row, so
	test processes that create users at the same moment on the same site can
	deadlock each other. That is contention between runs, not a fault here;
	the step is simply tried again.
	"""
	for attempt in range(attempts):
		try:
			return fn()
		except frappe.QueryDeadlockError:
			frappe.db.rollback()
			if attempt == attempts - 1:
				raise
			time.sleep(0.5 * (attempt + 1))


def persona(key: str, roles: tuple[str, ...]) -> str:
	"""A standing test user, made once per site and reused by every run.

	The framework throttles how many users a site may create in an hour, and a
	shared test site reaches that quickly; reusing fixed addresses (example.com
	is reserved for exactly this) keeps these tests out of that limit.
	"""
	email = f"assistant-{key}@example.com"
	if not frappe.db.exists("User", email):
		# The framework refuses a new user once more than sixty were made in
		# the last hour, a guard against sign-up abuse that every test process
		# on a shared test site counts towards. It stands aside for imports;
		# a persona is created once per site, so it is created as one.
		previous = frappe.flags.in_import
		frappe.flags.in_import = True
		try:
			make_user(email=email)
		finally:
			frappe.flags.in_import = previous
	user = frappe.get_doc("User", email)
	missing = set(roles) - {r.role for r in user.roles}
	extra = {r.role for r in user.roles} - set(roles) - {"All", "Guest"}
	if extra:
		user.remove_roles(*extra)
	if missing:
		user.add_roles(*missing)
	return email


#: The standing forum the tests' matters route to; see AssistantTestCase._reference.
REFERENCE_FORUM = "Assistant test reference forum"


def _standing(doctype: str, code_field: str, name_field: str, code: str, **extra) -> str:
	"""A reference row with a fixed code, made the first time and reused after."""
	if frappe.db.exists(doctype, {code_field: code}):
		return frappe.db.get_value(doctype, {code_field: code})
	return frappe.get_doc(
		{"doctype": doctype, code_field: code, name_field: "Reference value", **extra}
	).insert(ignore_permissions=True).name


#: The people the tests ask as, by the roles they hold.
PERSONAS = {
	"viewer": ("Governance Viewer",),
	"viewer2": ("Governance Viewer",),
	"secretary": ("Committee Secretary",),
	"administrator": ("Consilium Administrator",),
	"owner": ("Escalation Owner",),
	"cleared": ("Escalation Owner", sensitivity.SENSITIVE_ROLE),
}


class AssistantTestCase(EscalationTestCase):
	"""Users and reference data are made once per class and committed, so each
	test only creates the records it is about (and rolls them back)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for role in {r for roles in PERSONAS.values() for r in roles}:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
		frappe.db.commit()
		cls.users = {}
		for key, roles in PERSONAS.items():
			cls.users[key] = _with_retry(lambda key=key, roles=roles: persona(key, roles))
			frappe.db.commit()
		cls.reference = _with_retry(cls._reference)
		frappe.db.commit()

	@classmethod
	def _reference(cls) -> dict:
		"""The taxonomy a matter needs — as the escalation tests build it, but
		standing, like the personas: made once per site and reused by every run.

		It is committed so each test only creates the records it is about. Made
		afresh for every class, the committed rows were never removed: each run
		left six forums and thirty taxonomy rows behind on the test site.
		"""
		tier_1 = _standing("Risk Type", "risk_type_code", "risk_type_name", "ASSISTANT-RT1", tier=1)
		forum = frappe.db.get_value("Governance Forum", {"forum_name": REFERENCE_FORUM})
		if not forum:
			forum = make_forum()
			frappe.db.set_value("Governance Forum", forum, "forum_name", REFERENCE_FORUM)
		return {
			"risk_type": tier_1,
			"risk_type_2": _standing("Risk Type", "risk_type_code", "risk_type_name", "ASSISTANT-RT2", tier=2,
			                         parent_risk_type=tier_1),
			"organizational_level": _standing("Organizational Level", "organizational_level_code",
			                                  "organizational_level_name", "ASSISTANT-OL", level_rank=3),
			"legal_entity": _standing("Legal Entity", "legal_entity_code", "legal_entity_name", "ASSISTANT-LE"),
			"escalation_type": _standing("Escalation Type", "escalation_type_code", "escalation_type_name",
			                             "ASSISTANT-ET"),
			"forum": forum,
			"user": cls.users["owner"],
		}

	def setUp(self):
		super().setUp()
		corpus.clear_cache()
		self.configure(ai_enabled=0, rate_limit_per_hour=30, data_sharing="Guidance only")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		super().tearDown()

	def configure(self, **values):
		frappe.set_user("Administrator")
		settings = frappe.get_doc(SETTINGS)
		settings.update(values)
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		return settings

	def enable_ai(self, url, **values):
		defaults = {
			"ai_enabled": 1, "provider": "Anthropic Messages API", "endpoint_url": url,
			"model": "claude-sonnet-5", "api_key": "dummy-test-key", "timeout_seconds": 1, "max_tokens": 300,
		}
		defaults.update(values)
		return self.configure(**defaults)

	def ask(self, user, question, route="/", query=""):
		frappe.set_user(user)
		try:
			return assistant.ask(question, json.dumps({"route": route, "query": query, "title": "x"}))
		finally:
			frappe.set_user("Administrator")

	@staticmethod
	def text(result) -> str:
		return answer_mod.to_plain(result["blocks"])


class TestBuiltInAnswers(AssistantTestCase):
	def test_what_can_i_do_here_lists_the_pages_tasks_by_permission(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "What can I do here?", "/forums")
		text = self.text(result)
		self.assertEqual(result["intent"], "what_here")
		self.assertIn("Forum inventory", text)
		self.assertIn("Filter or search the inventory", text)
		# A viewer cannot raise a formation request, and is told who can.
		self.assertIn("Not open to you here", text)
		self.assertRegex(text, r"Request a new forum.*Committee Secretary")
		self.assertEqual(result["mode"], "builtin")

	def test_how_do_i_is_answered_with_steps_for_someone_allowed(self):
		secretary = self.users["secretary"]
		result = self.ask(secretary, "How do I request a new forum?", "/forums")
		text = self.text(result)
		self.assertEqual(result["intent"], "how_to")
		self.assertIn("formation request", text)
		self.assertNotIn("You can't", text)
		self.assertTrue(any(step.get("href") == "/create-forum" for step in result["next"]))

	def test_how_do_i_tells_someone_without_the_role_why_not(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "How do I request a new forum?", "/forums")
		text = self.text(result)
		self.assertIn("You can't request a new forum", text)
		self.assertIn("Committee Secretary", text)
		self.assertIn("ask your administrator", text)

	def test_why_cant_names_the_missing_role_for_an_area(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "Why can't I see escalations?", "/")
		text = self.text(result)
		self.assertEqual(result["intent"], "why_cant")
		self.assertIn("You can't open Escalation register", text)
		self.assertIn("Escalation Owner", text)

	def test_what_does_a_term_mean_uses_the_glossary(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "What does quorum mean?", "/forums")
		self.assertEqual(result["intent"], "define")
		self.assertIn("minimum participation", self.text(result))

	def test_a_published_glossary_term_record_is_used(self):
		if not frappe.db.exists("DocType", "Glossary Term"):
			self.skipTest("the Policy module is not installed")
		frappe.get_doc({
			"doctype": "Glossary Term", "term": "Zeta Control", "definition": "A test-only control term.",
			"scope_level": "Enterprise", "term_status": "Published",
		}).insert(ignore_permissions=True)
		result = self.ask(self.users["viewer"], "What is a zeta control?", "/")
		self.assertIn("A test-only control term.", self.text(result))

	def test_where_do_i_find_points_to_the_page(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "Where do I find the forum inventory?", "/")
		self.assertEqual(result["intent"], "where")
		links = [p["href"] for b in result["blocks"] for item in b.get("items", []) for p in item if p.get("href")]
		self.assertIn("/forums", links)

	def test_every_link_in_an_answer_is_a_same_origin_path(self):
		viewer = self.users["viewer"]
		for question in ("What can I do here?", "How do I request a new forum?", "What is a risk acceptance?"):
			result = self.ask(viewer, question, "/forums")
			hrefs = [p["href"] for b in result["blocks"] for p in (b.get("parts") or [x for i in b.get("items", []) for x in i]) if p.get("href")]
			hrefs += [s["href"] for s in result["sources"] if s.get("href")]
			hrefs += [n["href"] for n in result["next"] if n.get("href")]
			for href in hrefs:
				self.assertTrue(href.startswith("/") and not href.startswith("//"), href)

	def test_suggestions_are_per_page(self):
		frappe.set_user(self.users["viewer"])
		data = assistant.suggestions(json.dumps({"route": "/escalations"}))
		self.assertIn("How do I raise an escalation?", data["starters"])
		self.assertEqual(data["mode"], "builtin")

	def test_a_signed_out_visitor_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			assistant.ask("What can I do here?", "{}")
		with self.assertRaises(frappe.PermissionError):
			assistant.suggestions("{}")

	def test_an_empty_question_is_refused(self):
		frappe.set_user(self.users["viewer"])
		with self.assertRaises(frappe.ValidationError):
			assistant.ask("   ", "{}")

	def test_malformed_context_is_ignored_not_trusted(self):
		viewer = self.users["viewer"]
		frappe.set_user(viewer)
		# A forged context naming an arbitrary DocType is not looked up at all.
		result = assistant.ask("What can I do here?", json.dumps({
			"route": "/", "page_context": {"doctype": "User", "name": "Administrator"}}))
		self.assertNotIn("Administrator", self.text(result))
		result = assistant.ask("What can I do here?", "not json at all")
		self.assertEqual(result["intent"], "what_here")


class TestRecordAwareness(AssistantTestCase):
	def setUp(self):
		super().setUp()
		self.ordinary = _with_retry(lambda: self.make_matter(self.reference, escalation_title="An ordinary matter for help"))
		# The people a sensitive matter names may see it, so the hidden matter
		# names only the cleared user: to the owner it is a stranger's matter.
		self.hidden = _with_retry(lambda: self.make_matter(
			self.reference, escalation_title="A hidden matter for help", sensitive=1,
			identified_by=self.users["cleared"], accountable_executive=self.users["cleared"]))
		self.owner = self.users["owner"]
		self.cleared = self.users["cleared"]

	def test_the_record_and_the_actions_open_on_it_are_described(self):
		result = self.ask(self.owner, "What can I do here?", "/escalation", f"?name={self.ordinary.name}")
		text = self.text(result)
		self.assertIn("An ordinary matter for help", text)
		self.assertIn(self.ordinary.name, text)
		self.assertIn("Add an action plan", text)

	def test_a_sensitive_matter_is_never_surfaced_to_someone_who_cannot_read_it(self):
		hidden = self.ask(self.owner, "What can I do here?", "/escalation", f"?name={self.hidden.name}")
		missing = self.ask(self.owner, "What can I do here?", "/escalation", "?name=ESC-0000-99999")
		payload = json.dumps(hidden)
		self.assertNotIn("A hidden matter for help", payload)
		self.assertNotIn(self.hidden.name, payload)
		# Hidden and non-existent read the same, so the answer confirms nothing.
		self.assertEqual(hidden["blocks"], missing["blocks"])
		row = frappe.get_all(LOG, filters={"name": hidden["interaction"]}, fields=["subject_name", "subject_doctype"])[0]
		self.assertFalse(row.subject_name)
		self.assertFalse(row.subject_doctype)

	def test_why_cant_on_a_hidden_record_reveals_nothing(self):
		hidden = self.ask(self.owner, "Why can't I close this matter?", "/escalation", f"?name={self.hidden.name}")
		missing = self.ask(self.owner, "Why can't I close this matter?", "/escalation", "?name=ESC-0000-99999")
		self.assertEqual(hidden["blocks"], missing["blocks"])
		self.assertNotIn("A hidden matter for help", json.dumps(hidden))

	def test_a_cleared_reader_sees_the_sensitive_matter_but_the_log_does_not_name_it(self):
		result = self.ask(self.cleared, "What can I do here?", "/escalation", f"?name={self.hidden.name}")
		self.assertIn("A hidden matter for help", self.text(result))
		row = frappe.get_all(LOG, filters={"name": result["interaction"]}, fields=["subject_name"])[0]
		self.assertFalse(row.subject_name)

	def test_an_ordinary_record_is_named_in_the_log(self):
		result = self.ask(self.owner, "What can I do here?", "/escalation", f"?name={self.ordinary.name}")
		row = frappe.get_all(LOG, filters={"name": result["interaction"]}, fields=["subject_name", "subject_doctype"])[0]
		self.assertEqual(row.subject_name, self.ordinary.name)
		self.assertEqual(row.subject_doctype, "Escalation Matter")

	def test_the_server_decides_the_record_not_the_page_context(self):
		frappe.set_user(self.owner)
		ctx = ctxmod.resolve({"route": "/", "page_context": {"doctype": "Escalation Matter", "name": self.hidden.name}})
		self.assertFalse(ctx["record"]["visible"])
		self.assertNotIn("title", ctx["record"])


class TestAdminDocumentation(AssistantTestCase):
	def setUp(self):
		super().setUp()
		if not corpus.docs_dir():
			self.skipTest("the guides are not present in this installation (see corpus.docs_dir)")

	def test_admin_guide_sections_are_hidden_from_non_administrators(self):
		question = "How do I impersonate a user to see what they see?"
		viewer = self.ask(self.users["viewer"], question, "/")
		self.assertFalse([s for s in viewer["sources"] if s["id"].startswith("admin-guide:")])
		self.assertNotIn("Impersonate", json.dumps(viewer))

		admin = self.ask(self.users["administrator"], question, "/")
		self.assertTrue([s for s in admin["sources"] if s["id"].startswith("admin-guide:")])

	def test_the_index_is_rebuilt_when_a_source_changes(self):
		first = corpus.get_index()
		self.assertIs(first, corpus.get_index())
		frappe.get_doc({
			"doctype": "Guide Article", "slug": f"assist-{frappe.generate_hash(length=6)}",
			"title": "Quokka escalation etiquette", "category": "Getting Started",
			"applies_to_module": "All", "body": "<p>Always greet the quokka.</p>", "is_published": 1,
		}).insert(ignore_permissions=True)
		second = corpus.get_index()
		self.assertIsNot(first, second)
		result = self.ask(self.users["viewer"], "quokka etiquette", "/")
		self.assertTrue(any("Quokka" in s["title"] for s in result["sources"]))


class TestAuditAndLimits(AssistantTestCase):
	def test_every_question_is_logged(self):
		viewer = self.users["viewer"]
		result = self.ask(viewer, "What can I do here?", "/forums", "?standing=active")
		row = frappe.get_doc(LOG, result["interaction"])
		self.assertEqual(row.user, viewer)
		self.assertEqual(row.route, "/forums")
		self.assertEqual(row.mode, "Built-in")
		self.assertEqual(row.ai_used, 0)
		self.assertEqual(row.intent, "what_here")
		self.assertIn("Forum inventory", row.answer)
		self.assertIsNotNone(row.latency_ms)

	def test_the_log_is_append_only(self):
		result = self.ask(self.users["viewer"], "What can I do here?", "/")
		row = frappe.get_doc(LOG, result["interaction"])
		self.addCleanup(purge_refusals, LOG, row.name)
		row.answer = "rewritten"
		with self.assertRaises(frappe.PermissionError):
			row.save(ignore_permissions=True)

	def test_ordinary_users_cannot_read_the_log(self):
		viewer = self.users["viewer"]
		self.ask(viewer, "What can I do here?", "/")
		frappe.set_user(viewer)
		self.assertFalse(frappe.has_permission(LOG, "read"))
		self.assertFalse(frappe.has_permission(SETTINGS, "read"))

	def test_the_hourly_limit_is_enforced(self):
		self.configure(rate_limit_per_hour=2)
		viewer = self.users["viewer"]
		self.ask(viewer, "What can I do here?", "/")
		self.ask(viewer, "What does quorum mean?", "/")
		with self.assertRaises(assistant.AssistantRateLimited):
			self.ask(viewer, "Where do I find policies?", "/")
		# Someone else is unaffected.
		self.ask(self.users["viewer2"], "What can I do here?", "/")


class TestSettings(AssistantTestCase):
	def test_ai_cannot_be_enabled_without_an_endpoint(self):
		with self.assertRaises(frappe.ValidationError):
			self.configure(ai_enabled=1, endpoint_url="")

	def test_only_http_endpoints_are_accepted(self):
		for bad in ("file:///etc/passwd", "ftp://host/x", "gateway.internal", "https://host/x?key=1"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				self.configure(endpoint_url=bad)

	def test_limits_are_bounded(self):
		with self.assertRaises(frappe.ValidationError):
			self.configure(timeout_seconds=0)
		with self.assertRaises(frappe.ValidationError):
			self.configure(max_tokens=100000)

	def test_defaults_are_offline(self):
		meta = frappe.get_meta(SETTINGS)
		self.assertEqual(meta.get_field("ai_enabled").default, "0")
		self.assertEqual(meta.get_field("data_sharing").default, "Guidance only")
		self.assertEqual(meta.get_field("model").default, "claude-sonnet-5")


class TestAIMode(AssistantTestCase):
	def test_happy_path_uses_the_endpoint_and_records_what_left(self):
		with stub_endpoint() as (server, url):
			self.enable_ai(url)
			result = self.ask(self.users["viewer"], "How do I request a new forum?", "/forums")
		self.assertEqual(result["mode"], "ai")
		self.assertIsNone(result["notice"])
		text = self.text(result)
		self.assertIn("From the stand-in.", text)
		parts = [p for b in result["blocks"] for p in b.get("parts", [])]
		# An offered path stays a link; a foreign URL is reduced to its label.
		self.assertIn({"text": "the forum inventory", "href": "/forums"}, parts)
		self.assertFalse([p for p in parts if "example.com" in json.dumps(p)])

		sent = server.requests[0]
		self.assertEqual(sent["path"], "/v1/messages")
		self.assertEqual(sent["headers"].get("x-api-key"), "dummy-test-key")
		self.assertEqual(sent["headers"].get("anthropic-version"), "2023-06-01")
		self.assertEqual(sent["body"]["model"], "claude-sonnet-5")
		self.assertEqual(sent["body"]["max_tokens"], 300)
		self.assertIn("only the guidance", sent["body"]["system"])
		self.assertIn("How do I request a new forum?", sent["body"]["messages"][0]["content"])

		row = frappe.get_doc(LOG, result["interaction"])
		self.assertEqual((row.mode, row.ai_used), ("AI-assisted", 1))
		self.assertEqual(row.provider, "Anthropic Messages API")
		request = frappe.get_doc("AI Service Request", row.ai_service_request)
		self.assertEqual(request.status, "Succeeded")
		self.assertEqual(request.capability, "Help assistant")
		self.assertNotIn("dummy-test-key", request.context_sent)
		self.assertIn("From the stand-in.", request.response_payload)

	def test_guidance_only_sends_no_record_contents(self):
		matter = _with_retry(lambda: self.make_matter(self.reference, escalation_title="Guidance-mode secret title"))
		owner = self.users["owner"]
		with stub_endpoint() as (server, url):
			self.enable_ai(url, data_sharing="Guidance only")
			self.ask(owner, "What can I do here?", "/escalation", f"?name={matter.name}")
		body = json.dumps(server.requests[0]["body"])
		self.assertNotIn("Guidance-mode secret title", body)
		self.assertNotIn(matter.name, body)
		self.assertNotIn(owner, body)  # nor who is asking
		self.assertIn("Escalation Owner", body)  # role names are part of guidance

	def test_record_summary_mode_sends_readable_fields_but_never_a_sensitive_record(self):
		def matters():
			return (self.make_matter(self.reference, escalation_title="Shareable summary title"),
			        self.make_matter(self.reference, escalation_title="Never leaves the platform", sensitive=1))

		ordinary, hidden = _with_retry(matters)
		cleared = self.users["cleared"]
		with stub_endpoint() as (server, url):
			self.enable_ai(url, data_sharing="Include visible record summary")
			self.ask(cleared, "What can I do here?", "/escalation", f"?name={ordinary.name}")
			self.ask(cleared, "What can I do here?", "/escalation", f"?name={hidden.name}")
		self.assertIn("Shareable summary title", json.dumps(server.requests[0]["body"]))
		second = json.dumps(server.requests[1]["body"])
		self.assertNotIn("Never leaves the platform", second)
		self.assertNotIn(hidden.name, second)

	def test_timeout_falls_back_to_the_built_in_answer(self):
		with stub_endpoint(mode="slow") as (server, url):
			self.enable_ai(url, timeout_seconds=1)
			result = self.ask(self.users["viewer"], "How do I request a new forum?", "/forums")
		self.assertEqual(result["mode"], "builtin")
		self.assertTrue(result["notice"])
		self.assertIn("You can't request a new forum", self.text(result))
		row = frappe.get_doc(LOG, result["interaction"])
		self.assertEqual((row.mode, row.ai_used), ("AI-assisted", 0))
		self.assertIn("seconds", row.fallback_reason)
		request = frappe.db.get_value("AI Service Request", row.ai_service_request, ["status", "duration_ms"], as_dict=True)
		self.assertEqual(request.status, "Timed Out")
		# The stand-in stalls for 3 s; the one-second limit cut the wait short.
		self.assertLess(request.duration_ms, 2500)

	def test_an_error_response_falls_back(self):
		with stub_endpoint(mode="error") as (server, url):
			self.enable_ai(url)
			result = self.ask(self.users["viewer"], "What does quorum mean?", "/forums")
		self.assertEqual(result["mode"], "builtin")
		self.assertIn("minimum participation", self.text(result))
		row = frappe.get_doc(LOG, result["interaction"])
		self.assertIn("HTTP 500", row.fallback_reason)
		self.assertEqual(frappe.db.get_value("AI Service Request", row.ai_service_request, "status"), "Failed")

	def test_a_refusal_falls_back(self):
		with stub_endpoint(mode="refusal") as (server, url):
			self.enable_ai(url)
			result = self.ask(self.users["viewer"], "What does quorum mean?", "/forums")
		self.assertEqual(result["mode"], "builtin")
		row = frappe.get_doc(LOG, result["interaction"])
		self.assertEqual(frappe.db.get_value("AI Service Request", row.ai_service_request, "status"), "Refused")

	def test_an_unreachable_endpoint_falls_back(self):
		with stub_endpoint() as (server, url):
			pass  # closed again: nothing listens there now
		self.enable_ai(url)
		result = self.ask(self.users["viewer"], "What does quorum mean?", "/forums")
		self.assertEqual(result["mode"], "builtin")
		self.assertIn("minimum participation", self.text(result))

	def test_openai_compatible_gateway(self):
		with stub_endpoint(mode="openai", reply="Gateway answer.") as (server, url):
			self.enable_ai(url + "/v1", provider="OpenAI-compatible (internal gateway)")
			result = self.ask(self.users["viewer"], "What does quorum mean?", "/forums")
		self.assertEqual(result["mode"], "ai")
		self.assertIn("Gateway answer.", self.text(result))
		sent = server.requests[0]
		self.assertEqual(sent["path"], "/v1/chat/completions")
		self.assertEqual(sent["headers"].get("authorization"), "Bearer dummy-test-key")
		self.assertEqual(sent["body"]["messages"][0]["role"], "system")
