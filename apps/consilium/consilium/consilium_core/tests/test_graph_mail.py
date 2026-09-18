"""Notification email through Microsoft Graph, against a stand-in on 127.0.0.1.

Nothing here reaches the network. A local server plays both the sign-in service
(the token endpoint) and Graph (sendMail), and each test scripts its answers:
a clean send, a cached token, a 401 that forces a new token, throttling with
Retry-After, a stall past the timeout, a refusal. The dispatch tests go through
``notification.dispatch`` and ``notification.retry_failed`` so the evidence
row — "was this person told" — is what is asserted on. The client secret is a
dummy string.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import frappe

from consilium.consilium_core import notification
from consilium.consilium_core.integrations import graph_mail
from consilium.consilium_core.tests import test_assistant as ta
from consilium.consilium_core.tests.http_stub import stub_server
from consilium.consilium_core.tests.utils import CoreTestCase, refusals_for, unique

SETTINGS = graph_mail.SETTINGS
TENANT = "tenant-0001"
SENDER = "governance@example.com"
SECRET = "dummy-client-secret"


class GraphStub:
	"""Scripts the stand-in: a queue of sendMail answers, then 202s."""

	def __init__(self):
		self.send_answers: list[tuple] = []
		self.token_answer: tuple | None = None
		self.tokens_issued = 0
		self.stall_seconds = 0

	def __call__(self, request, server):
		if request["path"].endswith("/oauth2/v2.0/token"):
			if self.token_answer:
				return self.token_answer
			self.tokens_issued += 1
			return 200, {}, {"token_type": "Bearer", "expires_in": 3599, "access_token": f"token-{self.tokens_issued}"}
		if request["path"].endswith("/sendMail"):
			if self.stall_seconds:
				time.sleep(self.stall_seconds)
			if self.send_answers:
				return self.send_answers.pop(0)
			return 202, {}, b""
		return 404, {}, {"error": {"code": "NotFound", "message": request["path"]}}

	@staticmethod
	def sends(server) -> list[dict]:
		return [r for r in server.requests if r["path"].endswith("/sendMail")]

	@staticmethod
	def token_requests(server) -> list[dict]:
		return [r for r in server.requests if r["path"].endswith("/token")]


class GraphTestCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.recipient = ta._with_retry(lambda: ta.persona("graph-recipient", ()))
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		graph_mail.forget_tokens()
		self.waits = []
		patcher = patch.object(graph_mail, "_sleep", self.waits.append)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		graph_mail.forget_tokens()
		frappe.flags.cns_mail_inline = None
		super().tearDown()

	def configure(self, url, **values):
		s = frappe.get_single(SETTINGS)
		s.update({
			"delivery_route": graph_mail.GRAPH_ROUTE,
			"graph_tenant_id": TENANT,
			"graph_client_id": "client-0001",
			"graph_client_secret": SECRET,
			"graph_sender": SENDER,
			"graph_authority_url": url,
			"graph_api_url": url,
			"graph_timeout_seconds": 1,
		})
		s.update(values)
		s.save(ignore_permissions=True)
		return frappe.get_single(SETTINGS)

	def channel(self, **values):
		return frappe.get_doc({
			"doctype": "Notification Channel",
			"channel_code": unique("GRAPH"),
			"title": "Email through Graph",
			"channel_type": "Email",
			"adapter": "email",
			**values,
		}).insert(ignore_permissions=True)


class TestTheWire(GraphTestCase):
	def test_a_token_then_the_message(self):
		stub = GraphStub()
		with stub_server(stub) as (server, url):
			s = self.configure(url)
			result = graph_mail.send(s, to=["person@example.com"], subject="Review due", html="<p>Due soon.</p>",
			                         reply_to="office@example.com")
		self.assertEqual(result, {"status": 202, "attempts": 1})
		token = GraphStub.token_requests(server)[0]
		self.assertEqual(token["path"], f"/{TENANT}/oauth2/v2.0/token")
		self.assertEqual(token["form"]["grant_type"], "client_credentials")
		self.assertEqual(token["form"]["scope"], f"{url}/.default")
		self.assertEqual(token["form"]["client_id"], "client-0001")
		self.assertEqual(token["form"]["client_secret"], SECRET)
		send = GraphStub.sends(server)[0]
		self.assertEqual(send["path"], f"/v1.0/users/{SENDER}/sendMail")
		self.assertEqual(send["headers"]["authorization"], "Bearer token-1")
		message = send["json"]["message"]
		self.assertEqual(message["subject"], "Review due")
		self.assertEqual(message["body"], {"contentType": "HTML", "content": "<p>Due soon.</p>"})
		self.assertEqual(message["toRecipients"], [{"emailAddress": {"address": "person@example.com"}}])
		self.assertEqual(message["replyTo"], [{"emailAddress": {"address": "office@example.com"}}])
		# The secret goes to the sign-in service only, never to Graph.
		self.assertNotIn(SECRET.encode(), send["body"])

	def test_the_token_is_reused_until_it_expires(self):
		stub = GraphStub()
		with stub_server(stub) as (server, url):
			s = self.configure(url)
			graph_mail.send(s, to=["a@example.com"], subject="One", html="x")
			graph_mail.send(s, to=["b@example.com"], subject="Two", html="x")
			self.assertEqual(len(GraphStub.token_requests(server)), 1)
			# A token inside the renewal margin is not used.
			key = graph_mail._token_key(s)
			token, _expires = graph_mail._TOKENS[key]
			graph_mail._TOKENS[key] = (token, time.time() + graph_mail.TOKEN_SKEW_SECONDS - 1)
			graph_mail.send(s, to=["c@example.com"], subject="Three", html="x")
		self.assertEqual(len(GraphStub.token_requests(server)), 2)
		self.assertEqual(GraphStub.sends(server)[-1]["headers"]["authorization"], "Bearer token-2")

	def test_a_401_gets_a_new_token_once(self):
		stub = GraphStub()
		stub.send_answers = [(401, {}, {"error": {"code": "InvalidAuthenticationToken", "message": "expired"}})]
		with stub_server(stub) as (server, url):
			result = graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		self.assertEqual(result["attempts"], 2)
		self.assertEqual(len(GraphStub.token_requests(server)), 2)
		self.assertEqual(GraphStub.sends(server)[1]["headers"]["authorization"], "Bearer token-2")

	def test_a_second_401_is_a_failure_not_a_loop(self):
		stub = GraphStub()
		refused = (401, {}, {"error": {"code": "InvalidAuthenticationToken", "message": "no"}})
		stub.send_answers = [refused, refused, refused]
		with stub_server(stub) as (server, url):
			with self.assertRaises(graph_mail.GraphMailError) as caught:
				graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		self.assertIn("InvalidAuthenticationToken", str(caught.exception))
		self.assertEqual(len(GraphStub.sends(server)), 2)

	def test_throttling_is_waited_out(self):
		stub = GraphStub()
		stub.send_answers = [(429, {"Retry-After": "0"}, {"error": {"code": "TooManyRequests"}}),
		                     (503, {"Retry-After": "600"}, {"error": {"code": "ServiceUnavailable"}})]
		with stub_server(stub) as (server, url):
			result = graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		self.assertEqual(result["attempts"], 3)
		# Retry-After is honoured, and capped.
		self.assertEqual(self.waits, [0.0, float(graph_mail.MAX_WAIT_SECONDS)])

	def test_throttling_gives_up_after_the_notification_retry_limit(self):
		stub = GraphStub()
		stub.send_answers = [(429, {"Retry-After": "0"}, {"error": {"code": "TooManyRequests", "message": "slow down"}})] \
			* (notification.MAX_RETRIES + 1)
		with stub_server(stub) as (server, url):
			with self.assertRaises(graph_mail.GraphMailError) as caught:
				graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		self.assertIn("429", str(caught.exception))
		self.assertEqual(len(GraphStub.sends(server)), notification.MAX_RETRIES + 1)

	def test_a_stall_is_a_timeout_and_is_not_resent_at_once(self):
		stub = GraphStub()
		stub.stall_seconds = 2
		with stub_server(stub) as (server, url):
			with self.assertRaises(graph_mail.GraphTimeout):
				graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		# Graph may have taken it; sending again at once could deliver it twice.
		self.assertEqual(len(GraphStub.sends(server)), 1)

	def test_a_refused_application_says_why(self):
		stub = GraphStub()
		stub.token_answer = (401, {}, {"error": "invalid_client",
		                               "error_description": "AADSTS7000215: Invalid client secret provided.\r\nTrace ID: x"})
		with stub_server(stub) as (server, url):
			with self.assertRaises(graph_mail.GraphMailError) as caught:
				graph_mail.send(self.configure(url), to=["a@example.com"], subject="S", html="x")
		self.assertIn("invalid_client", str(caught.exception))
		self.assertIn("AADSTS7000215", str(caught.exception))
		self.assertNotIn("Trace ID", str(caught.exception))
		self.assertEqual(GraphStub.sends(server), [])


class TestTheDispatchRecord(GraphTestCase):
	def test_a_notification_through_graph_is_recorded_as_sent(self):
		channel = self.channel()
		with stub_server(GraphStub()) as (server, url):
			self.configure(url)
			row = notification.dispatch(channel.name, self.recipient, subject="Attestation due",
			                            body="Please attest by Friday.")
		self.assertEqual(row.status, "Sent")
		self.assertFalse(row.is_open)
		message = GraphStub.sends(server)[0]["json"]["message"]
		self.assertEqual(message["toRecipients"][0]["emailAddress"]["address"],
		                 frappe.db.get_value("User", self.recipient, "email"))
		self.assertEqual(message["subject"], "Attestation due")
		self.assertIn("<p>Please attest by Friday.</p>", message["body"]["content"])

	def test_a_failure_stays_open_and_the_hourly_retry_sends_it(self):
		channel = self.channel()
		stub = GraphStub()
		stub.send_answers = [(500, {}, {"error": {"code": "ErrorInternalServerError", "message": "boom"}})]
		with stub_server(stub) as (server, url):
			self.configure(url)
			row = notification.dispatch(channel.name, self.recipient, subject="Review due", body="Text")
			self.assertEqual(row.status, "Failed")
			self.assertTrue(row.is_open)
			self.assertIn("HTTP 500", row.failure_reason)
			self.assertIn("ErrorInternalServerError", row.failure_reason)

			retried = notification.retry_failed()
		self.assertIn(row.name, retried)
		row.reload()
		self.assertEqual(row.status, "Sent")
		self.assertEqual(row.retry_count, 1)
		self.assertFalse(row.is_open)
		self.assertEqual(len(GraphStub.sends(server)), 2)

	def test_a_timeout_is_recorded_on_the_dispatch(self):
		channel = self.channel()
		stub = GraphStub()
		stub.stall_seconds = 2
		with stub_server(stub) as (server, url):
			self.configure(url)
			row = notification.dispatch(channel.name, self.recipient, subject="Review due", body="Text")
		self.assertEqual(row.status, "Failed")
		self.assertTrue(row.is_open)
		self.assertIn("GraphTimeout", row.failure_reason)

	def test_throttling_then_success_is_one_sent_dispatch(self):
		channel = self.channel()
		stub = GraphStub()
		stub.send_answers = [(429, {"Retry-After": "0"}, {"error": {"code": "TooManyRequests"}})]
		with stub_server(stub) as (server, url):
			self.configure(url)
			row = notification.dispatch(channel.name, self.recipient, subject="Review due", body="Text")
		self.assertEqual(row.status, "Sent")
		self.assertEqual(frappe.db.count("Notification Dispatch", {"channel": channel.name}), 1)

	def test_an_incomplete_graph_route_hands_on_to_the_fallback(self):
		fallback = frappe.get_doc({
			"doctype": "Notification Channel", "channel_code": unique("REC"), "title": "Recorded",
			"channel_type": "In App", "adapter": "record_only",
		}).insert(ignore_permissions=True)
		channel = self.channel(fallback_channel=fallback.name)
		# Written directly: saving the settings would refuse an incomplete route.
		frappe.db.set_single_value(SETTINGS, "delivery_route", graph_mail.GRAPH_ROUTE)
		for field in ("graph_tenant_id", "graph_client_id", "graph_sender"):
			frappe.db.set_single_value(SETTINGS, field, "")
		self.assertIn("not fully set up", notification._email_available(channel))
		row = notification.dispatch(channel.name, self.recipient, subject="Review due", body="Text")
		self.assertEqual(row.channel, fallback.name)
		self.assertEqual(row.status, "Sent")

	def test_inside_a_web_request_the_send_goes_to_the_queue(self):
		channel = self.channel()
		stub = GraphStub()
		stub.send_answers = [(403, {}, {"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})]
		with stub_server(stub) as (server, url):
			self.configure(url)
			queued = []
			previous = getattr(frappe.local, "request", None)
			frappe.local.request = frappe._dict(path="/")
			try:
				with patch.object(frappe, "enqueue", lambda method, **kw: queued.append((method, kw))):
					row = notification.dispatch(channel.name, self.recipient, subject="Review due", body="Text")
			finally:
				frappe.local.request = previous
			# Sent to the queue, as the SMTP route's "sent" means queued.
			self.assertEqual(row.status, "Sent")
			self.assertEqual(GraphStub.sends(server), [])
			jobs = [kw for method, kw in queued if method == "consilium.consilium_core.integrations.graph_mail.deliver_queued"]
			self.assertEqual(len(jobs), 1)
			self.assertEqual(jobs[0]["dispatch"], row.name)
			self.assertTrue(jobs[0]["enqueue_after_commit"])

			# The job runs; Graph refuses; the row reopens for the hourly retry.
			graph_mail.deliver_queued(row.name)
		row.reload()
		self.assertEqual(row.status, "Failed")
		self.assertTrue(row.is_open)
		self.assertIn("ErrorAccessDenied", row.failure_reason)

	def test_smtp_stays_the_default_route(self):
		self.assertEqual(graph_mail.route(), graph_mail.SMTP_ROUTE)
		self.assertFalse(graph_mail.uses_graph())


class TestTheSettings(GraphTestCase):
	def test_graph_cannot_be_chosen_half_configured(self):
		s = frappe.get_single(SETTINGS)
		s.delivery_route = graph_mail.GRAPH_ROUTE
		s.graph_tenant_id = TENANT
		with self.assertRaises(frappe.ValidationError) as caught:
			s.save(ignore_permissions=True)
		self.assertIn("Client Secret", str(caught.exception))

	def test_a_plain_http_address_is_refused_except_on_loopback(self):
		s = frappe.get_single(SETTINGS)
		s.graph_api_url = "http://graph.example.internal"
		with self.assertRaises(frappe.ValidationError):
			s.save(ignore_permissions=True)
		s = frappe.get_single(SETTINGS)
		s.graph_api_url = "http://127.0.0.1:9"
		s.save(ignore_permissions=True)

	def test_a_script_address_is_refused_and_audited(self):
		self.purge_on_teardown(SETTINGS, SETTINGS)
		s = frappe.get_single(SETTINGS)
		s.graph_authority_url = "javascript:alert(1)"
		with self.assertRaises(frappe.ValidationError):
			s.save(ignore_permissions=True)
		self.assertTrue(any(r.control == "external address check" for r in refusals_for(SETTINGS, SETTINGS)))

	def test_a_tenant_cannot_change_the_request_path(self):
		s = frappe.get_single(SETTINGS)
		s.graph_tenant_id = "../common"
		with self.assertRaises(frappe.ValidationError):
			s.save(ignore_permissions=True)

	def test_sovereign_cloud_addresses_are_used_as_given(self):
		s = frappe._dict(graph_tenant_id=TENANT, graph_authority_url="https://login.sovereign.example/",
		                 graph_api_url="https://graph.sovereign.example", graph_sender="a@b.example")
		self.assertEqual(graph_mail.token_url(s), f"https://login.sovereign.example/{TENANT}/oauth2/v2.0/token")
		self.assertEqual(graph_mail.scope(s), "https://graph.sovereign.example/.default")
		self.assertEqual(graph_mail.send_url(s), "https://graph.sovereign.example/v1.0/users/a@b.example/sendMail")
