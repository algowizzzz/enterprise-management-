"""The governance analysis features (O-6, O-7): rule-based engines, the AI gate,
the shared audited client, and suggestion acceptance.

Nothing here reaches the network. The AI paths run against the stand-in
endpoint the help assistant's tests use — a tiny HTTP server on 127.0.0.1 —
which can answer, stall past the timeout, or fail. The API key is a dummy
string. Test users are standing personas with fixed example.com addresses,
made once per site, because a shared test site soon reaches the framework's
hourly limit on new users.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import importing
from consilium.consilium_core.ai import client, gaps, guard, impact, regulatory, scoring, trends
from consilium.consilium_core.tests import test_assistant as ta
from consilium.escalation.setup import install
from consilium.policy.tests.utils import PolicyTestCase, make_document, make_org_unit, make_risk_category, unique

SETTINGS = "Assistant Settings"
DOCUMENT = "Governing Document"
REQUEST = "AI Service Request"
ACCEPTANCE = "AI Suggestion Acceptance"

PERSONAS = {
	"ai-analyst": ("Enterprise Policy Office", "Governance Viewer"),
	"ai-reader": ("Policy Reviewer",),
	"ai-outsider": ("Escalation Owner",),
}


class AITestCase(PolicyTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		install.ensure_roles()
		install.ensure_state_flags()
		frappe.db.commit()
		cls.users = {}
		for key, roles in PERSONAS.items():
			cls.users[key] = ta._with_retry(lambda key=key, roles=roles: ta.persona(key, roles))
			frappe.db.commit()

	def setUp(self):
		super().setUp()
		self.configure(ai_enabled=0, features_enabled=0, data_sharing="Guidance only", classification_ceiling="Internal",
		               rate_limit_per_hour=30, risk_score_weights=None)

	def tearDown(self):
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
		defaults = {"features_enabled": 1, "provider": client.ANTHROPIC, "endpoint_url": url, "model": "claude-sonnet-5",
		            "api_key": "dummy-test-key", "timeout_seconds": 1, "feature_max_tokens": 600}
		defaults.update(values)
		return self.configure(**defaults)

	def as_user(self, key):
		frappe.set_user(self.users[key])

	def document(self, **values):
		values.setdefault("owner_user", self.users["ai-analyst"])
		values.setdefault("document_approver", self.users["ai-analyst"])
		return make_document(**values)

	def requests_since(self, capability: str) -> list:
		return frappe.get_all(REQUEST, filters={"capability": capability, "requested_by": frappe.session.user},
		                      fields=["name", "status", "context_sent", "context_classification", "response_payload",
		                              "subject_name", "error_detail"], order_by="creation desc")


# ------------------------------------------------------------------ client


class TestClient(AITestCase):
	def test_endpoint_paths_for_both_formats(self):
		s = frappe._dict(provider=client.ANTHROPIC)
		for base, want in (("https://h", "https://h/v1/messages"), ("https://h/v1", "https://h/v1/messages"),
		                   ("https://h/v1/messages/", "https://h/v1/messages")):
			s.endpoint_url = base
			self.assertEqual(client.endpoint_url(s), want)
		s.provider = client.OPENAI_COMPATIBLE
		s.endpoint_url = "https://gw/v1"
		self.assertEqual(client.endpoint_url(s), "https://gw/v1/chat/completions")

	def test_parse_reads_only_text_and_refuses_what_it_cannot_use(self):
		s = frappe._dict(provider=client.ANTHROPIC)
		payload = {"content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": " Answer. "}], "stop_reason": "end_turn"}
		self.assertEqual(client.parse_response(s, payload), "Answer.")
		with self.assertRaises(client.AIRefused):
			client.parse_response(s, {"content": [], "stop_reason": "refusal"})
		with self.assertRaises(client.AIServiceError):
			client.parse_response(s, {"content": [{"type": "thinking", "thinking": ""}], "stop_reason": "max_tokens"})

	def test_the_assistant_and_the_features_share_one_path(self):
		from consilium.consilium_core.assistant import remote

		self.assertIs(remote.call, client.call)
		self.assertIs(remote.AssistantAIError, client.AIServiceError)


# ------------------------------------------------------------------- guard


class TestGuard(AITestCase):
	def test_ceiling_and_the_classes_that_never_leave(self):
		cfg = frappe._dict(classification_ceiling="Internal")
		self.assertTrue(guard.may_leave("Public", cfg))
		self.assertTrue(guard.may_leave("Internal", cfg))
		self.assertFalse(guard.may_leave("Confidential", cfg))
		cfg.classification_ceiling = "Confidential"
		self.assertTrue(guard.may_leave("Confidential", cfg))
		self.assertFalse(guard.may_leave("Restricted", cfg))
		cfg.classification_ceiling = "Restricted"  # not a permitted ceiling: read as Internal
		self.assertFalse(guard.may_leave("Confidential", cfg))
		self.assertEqual(guard.classification_of("Escalation Matter", {"sensitive": 1}), "Restricted")
		self.assertEqual(guard.classification_of(DOCUMENT, {"handling_classification": "Internal", "confidential": 1}), "Confidential")

	def test_tokens_are_stable_one_way_and_distinct(self):
		a, b = guard.token(DOCUMENT, "GDOC-1"), guard.token(DOCUMENT, "GDOC-2")
		self.assertEqual(a, guard.token(DOCUMENT, "GDOC-1"))
		self.assertNotEqual(a, b)
		self.assertNotIn("GDOC", a)
		self.assertRegex(a, r"^D-[0-9a-f]{8}$")

	def test_guidance_mode_sends_tokens_not_titles_and_counts_what_it_withheld(self):
		p = guard.Payload(frappe._dict(data_sharing="Guidance only", classification_ceiling="Internal"))
		tok = p.record(DOCUMENT, "GDOC-9", "Internal", title="Secret title", summary="Secret abstract", tags={"type": "Policy"})
		self.assertIsNone(p.record(DOCUMENT, "GDOC-10", "Confidential", title="Held back"))
		text = p.text()
		self.assertIn(tok, text)
		self.assertIn("Policy", text)
		self.assertNotIn("Secret", text)
		self.assertNotIn("Held back", text)
		self.assertIn("1 further record", text)

		p = guard.Payload(frappe._dict(data_sharing="Include visible record summary", classification_ceiling="Internal"))
		p.record(DOCUMENT, "GDOC-9", "Internal", title="Shared title", summary="Shared abstract")
		self.assertIn("Shared title", p.text())
		self.assertIn("Shared abstract", p.text())

	def test_model_text_links_only_tokens_the_platform_sent(self):
		links = {"D-0123abcd": {"doctype": DOCUMENT, "name": "GDOC-1", "label": "Known", "href": "/policy?name=GDOC-1"}}
		blocks = guard.narrative_blocks("See [D-0123abcd] and D-ffffffff and https://example.com/x", links)
		parts = [p for b in blocks for p in b.get("parts", [])]
		self.assertIn({"text": "Known", "href": "/policy?name=GDOC-1"}, parts)
		self.assertFalse([p for p in parts if "example.com" in p["text"] or p.get("href", "").startswith("http")])
		self.assertIn("D-ffffffff", "".join(p["text"] for p in parts))


# ------------------------------------------------------------------ impact


class TestImpact(AITestCase):
	def _graph(self, **doc_values):
		from consilium.governance.tests.utils import make_forum

		forum = make_forum(forum_name=unique("Approvers"))
		parent = self.document(document_name=unique("Parent Policy"), approving_forum_doctype="Governance Forum",
		                       approving_forum=forum.name, **doc_values)
		child = self.document(document_name=unique("Child Standard"), parent_document=parent.name)
		req = frappe.get_doc({"doctype": "Regulatory Requirement", "regulatory_requirement_code": unique("REQ").upper(),
		                      "regulatory_requirement_name": "Outsourcing notification rule", "citation": "Rule 9",
		                      "is_active": 1}).insert(ignore_permissions=True)
		parent.append("regulatory_references", {"regulatory_requirement": req.name})
		parent.save(ignore_permissions=True)
		activity = frappe.get_doc({"doctype": "Monitoring Activity", "document": parent.name, "activity_title": "Quarterly check",
		                           "frequency": "Quarterly", "responsible": self.users["ai-analyst"],
		                           "control_reference": "CTRL-42", "is_active": 1}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Monitoring Result", "monitoring_activity": activity.name, "document": parent.name,
		                "period_label": "Q1", "performed_by": self.users["ai-analyst"], "performed_on": nowdate(),
		                "outcome": "Not Effective", "findings": "The control did not operate."}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Policy Violation", "document": parent.name, "violation_type": "Process", "severity": "Low",
		                "identified_on": nowdate(), "description": "A step was skipped.",
		                "violation_status": "Logged"}).insert(ignore_permissions=True)
		return parent, child, req, forum

	def test_the_rule_based_impact_reaches_lineage_regulation_forums_monitoring_and_violations(self):
		parent, child, req, forum = self._graph()
		self.as_user("ai-analyst")
		a = impact.assess(parent.name)
		self.assertEqual([c["name"] for c in a["lineage"]["children"]], [child.name])
		self.assertEqual(a["regulatory"][0]["requirement"], req.name)
		self.assertEqual(a["forums"][0]["name"], forum.name)
		self.assertTrue(a["monitoring"][0]["last_adverse"])
		self.assertEqual(len(a["open_violations"]), 1)
		kinds = {p["kind"] for p in a["review_points"]}
		self.assertTrue({"lineage", "regulatory", "forum", "monitoring", "violations"} <= kinds, kinds)
		self.assertIn("CTRL-42", json.dumps(a["review_points"]))
		self.assertFalse(a["ai"]["available"])

	def test_sections_touched_by_a_change(self):
		old = "1. Scope\nApplies to all staff.\n2. Reporting\nReport monthly.\n3. Retired Clause\nOld text."
		new = "1. Scope\nApplies to all staff and contractors.\n2. Reporting\nReport monthly."
		diff = impact.compare(old, new)
		touched = {s["section"] for s in diff["sections_touched"]}
		self.assertIn("1. Scope", touched)
		self.assertNotIn("2. Reporting", touched)
		self.assertEqual(diff["sections_removed"], ["3. Retired Clause"])
		self.assertEqual(diff["sections_added"], [])

	def test_a_reader_without_access_to_the_document_is_refused(self):
		parent, *_ = self._graph()
		self.as_user("ai-outsider")
		with self.assertRaises(frappe.PermissionError):
			impact.assess(parent.name)

	def test_ai_off_means_nothing_is_sent_and_nothing_recorded(self):
		parent, *_ = self._graph()
		with ta.stub_endpoint() as (server, url):
			self.configure(features_enabled=0, endpoint_url=url, model="m")
			self.as_user("ai-analyst")
			out = impact.ai_commentary(parent.name)
		self.assertFalse(out["ai"]["used"])
		self.assertEqual(server.requests, [])
		self.assertFalse(self.requests_since(guard.capability_name("impact")))
		self.assertTrue(out["assessment"]["review_points"])  # the rule-based result is whole

	def test_a_role_that_may_not_spend_requests_is_refused(self):
		parent, *_ = self._graph()
		with ta.stub_endpoint() as (server, url):
			self.enable_ai(url)
			self.as_user("ai-reader")
			with self.assertRaises(frappe.PermissionError):
				impact.ai_commentary(parent.name)
		self.assertEqual(server.requests, [])

	def test_happy_path_is_audited_links_tokens_and_sends_no_titles_in_guidance_mode(self):
		parent, child, *_ = self._graph()
		tok = guard.token(DOCUMENT, child.name)
		reply = f"The change reaches [{tok}] first.\nReview points:\n- Check [{tok}] clause wording."
		with ta.stub_endpoint(reply=reply) as (server, url):
			self.enable_ai(url)
			self.as_user("ai-analyst")
			out = impact.ai_commentary(parent.name, change_summary="Secret change wording")
		self.assertTrue(out["ai"]["used"], out["ai"])
		parts = [p for b in out["ai"]["blocks"] for p in b.get("parts", []) + [x for item in b.get("items", []) for x in item]]
		self.assertTrue([p for p in parts if p.get("href") == f"/policy?name={child.name}"])

		sent = server.requests[0]
		self.assertEqual(sent["path"], "/v1/messages")
		self.assertEqual(sent["headers"].get("x-api-key"), "dummy-test-key")
		self.assertEqual(sent["body"]["max_tokens"], 600)
		body = json.dumps(sent["body"])
		self.assertIn(tok, body)
		for secret in (parent.document_name, child.document_name, "Secret change wording", parent.name):
			self.assertNotIn(secret, body)

		[row] = self.requests_since(guard.capability_name("impact"))
		self.assertEqual(row.status, "Succeeded")
		self.assertEqual(row.context_classification, "Internal")
		self.assertEqual(row.subject_name, parent.name)
		self.assertNotIn("dummy-test-key", row.context_sent)
		self.assertIn(tok, row.context_sent)

	def test_summary_mode_includes_titles_the_reader_may_read(self):
		parent, child, *_ = self._graph()
		with ta.stub_endpoint(reply="Fine.") as (server, url):
			self.enable_ai(url, data_sharing="Include visible record summary")
			self.as_user("ai-analyst")
			impact.ai_commentary(parent.name, change_summary="Shared change wording")
		body = json.dumps(server.requests[0]["body"])
		self.assertIn(child.document_name, body)
		self.assertIn("Shared change wording", body)

	def test_a_subject_above_the_ceiling_is_refused_and_the_refusal_recorded(self):
		parent, *_ = self._graph(handling_classification="Confidential")
		with ta.stub_endpoint() as (server, url):
			self.enable_ai(url, classification_ceiling="Internal")
			self.as_user("ai-analyst")
			out = impact.ai_commentary(parent.name)
		self.assertEqual(server.requests, [])
		self.assertFalse(out["ai"]["used"])
		self.assertEqual(out["ai"]["status"], "Refused")
		[row] = self.requests_since(guard.capability_name("impact"))
		self.assertEqual((row.status, row.context_classification), ("Refused", "Confidential"))
		self.assertFalse(json.loads(row.context_sent)["sent"])

	def test_a_timeout_falls_back_to_the_rule_based_result(self):
		parent, *_ = self._graph()
		with ta.stub_endpoint(mode="slow") as (server, url):
			self.enable_ai(url, timeout_seconds=1)
			self.as_user("ai-analyst")
			out = impact.ai_commentary(parent.name)
		self.assertFalse(out["ai"]["used"])
		self.assertIn("seconds", out["ai"]["notice"])
		self.assertTrue(out["assessment"]["review_points"])
		[row] = self.requests_since(guard.capability_name("impact"))
		self.assertEqual(row.status, "Timed Out")

	def test_an_error_or_refusal_falls_back(self):
		parent, *_ = self._graph()
		for mode, status in (("error", "Failed"), ("refusal", "Refused")):
			with ta.stub_endpoint(mode=mode) as (server, url):
				self.enable_ai(url)
				self.as_user("ai-analyst")
				out = impact.ai_commentary(parent.name)
			self.assertFalse(out["ai"]["used"])
			self.assertEqual(self.requests_since(guard.capability_name("impact"))[0].status, status)
			frappe.set_user("Administrator")

	def test_the_hourly_limit_covers_analysis_requests(self):
		parent, *_ = self._graph()
		with ta.stub_endpoint(reply="Fine.") as (server, url):
			self.enable_ai(url, rate_limit_per_hour=1)
			self.as_user("ai-analyst")
			impact.ai_commentary(parent.name)
			with self.assertRaises(frappe.TooManyRequestsError):
				impact.ai_commentary(parent.name)
		self.assertEqual(len(server.requests), 1)


# -------------------------------------------------------------------- gaps


class TestGaps(AITestCase):
	def test_forum_policy_regulatory_and_coverage_gaps_are_found(self):
		from consilium.governance.tests.utils import make_forum

		category = make_risk_category()
		group = make_org_unit("Operating Group")
		forum = make_forum(forum_name=unique("Bare Forum"), primary_risk_category=category,
		                   owning_operating_group=make_org_unit("Operating Group"))
		# A quorum rule cannot be saved incomplete; an old or imported row can be.
		forum.db_set({"quorum_rule_type": None, "quorum_value": 0})
		doc = self.document(document_name=unique("Orphan Policy"))
		req = frappe.get_doc({"doctype": "Regulatory Requirement", "regulatory_requirement_code": unique("UNCITED").upper(),
		                      "regulatory_requirement_name": "Nobody cites this", "is_active": 1}).insert(ignore_permissions=True)
		self.as_user("ai-analyst")
		found = gaps.detect()["gaps"]

		def kinds_for(name):
			return {g["kind"] for g in found if g.get("name") == name}

		self.assertTrue({"forum_charter", "forum_quorum", "forum_pathway"} <= kinds_for(forum.name), kinds_for(forum.name))
		self.assertIn("policy_forum", kinds_for(doc.name))
		self.assertIn("regulatory_uncited", kinds_for(req.name))
		self.assertTrue([g for g in found if g["kind"] == "coverage" and g["category"] == category and g["group"] == group])

		frappe.set_user("Administrator")
		forum.db_set("owning_operating_group", group)
		self.as_user("ai-analyst")
		found = gaps.detect()["gaps"]
		self.assertFalse([g for g in found if g["kind"] == "coverage" and g["category"] == category and g["group"] == group])

	def test_an_escalation_type_no_rule_names_is_reported(self):
		code = unique("ETYPE").upper()
		frappe.get_doc({"doctype": "Escalation Type", "escalation_type_code": code, "escalation_type_name": f"Type {code}",
		                "is_active": 1}).insert(ignore_permissions=True)
		self.as_user("ai-analyst")
		kinds = {g["kind"] for g in gaps.detect()["gaps"] if g.get("name") == code}
		self.assertTrue(kinds & {"escalation_unrouted", "escalation_general_only"}, kinds)

	def test_commentary_is_sent_with_tokens_and_falls_back_on_failure(self):
		self.document(document_name=unique("Gap Policy Title"))
		with ta.stub_endpoint(reply="- Fix the forums first.") as (server, url):
			self.enable_ai(url)
			self.as_user("ai-analyst")
			out = gaps.ai_commentary()
		self.assertTrue(out["ai"]["used"])
		self.assertNotIn("Gap Policy Title", json.dumps(server.requests[0]["body"]))
		with ta.stub_endpoint(mode="error") as (server, url):
			self.enable_ai(url)
			self.as_user("ai-analyst")
			out = gaps.ai_commentary()
		self.assertFalse(out["ai"]["used"])
		self.assertTrue(out["detection"]["gaps"])


# ------------------------------------------------------------------ trends


class TestTrends(AITestCase):
	def test_classification_of_a_series(self):
		self.assertTrue(trends.classify([0, 0, 0, 0, 0, 3])["rising"])  # a spike over a flat history
		self.assertTrue(trends.classify([0, 1, 1, 2, 3, 4])["rising"])  # a steady climb
		self.assertFalse(trends.classify([2, 2, 2, 2, 2, 2])["rising"])
		self.assertFalse(trends.classify([0, 0, 0, 0, 0, 1])["rising"])  # too small to call
		self.assertAlmostEqual(trends.slope([1, 2, 3, 4]), 1.0)

	def test_a_burst_of_violations_in_one_category_is_rising(self):
		category = make_risk_category()
		doc = self.document(primary_risk_category=category)
		for _i in range(3):
			frappe.get_doc({"doctype": "Policy Violation", "document": doc.name, "violation_type": "Process", "severity": "Low",
			                "identified_on": nowdate(), "description": "Again.", "violation_status": "Logged"}).insert(ignore_permissions=True)
		self.as_user("ai-analyst")
		result = trends.analyse(12)
		[s] = [s for s in result["series"] if s["stream"] == "violations" and s["value"] == category]
		self.assertEqual(s["latest"], 3)
		self.assertTrue(s["rising"])
		self.assertIn(s, result["rising"])
		labels = {i["kind"] for i in result["indicators"]}
		self.assertIn("repeat_violation", labels)
		self.assertIn(doc.name, json.dumps(result["indicators"]))

	def test_a_sensitive_escalation_is_shown_to_a_cleared_reader_but_never_counted_in_what_leaves(self):
		from consilium.escalation.tests.utils import EscalationTestCase, make_taxonomy

		tier_1 = make_taxonomy("Risk Type", "risk_type_code", "risk_type_name", tier=1)
		reference = {
			"risk_type": tier_1,
			"organizational_level": make_taxonomy("Organizational Level", "organizational_level_code", "organizational_level_name", level_rank=3),
			"legal_entity": make_taxonomy("Legal Entity", "legal_entity_code", "legal_entity_name"),
			"escalation_type": make_taxonomy("Escalation Type", "escalation_type_code", "escalation_type_name"),
			"user": self.users["ai-outsider"],
		}
		for _i in range(3):
			frappe.get_doc(EscalationTestCase.matter_values(self, reference, sensitive=1, escalation_identification_date=nowdate())
			               ).insert(ignore_permissions=True)
		visible = trends.analyse(12)  # as Administrator, who may see sensitive matters
		self.assertTrue([x for x in visible["series"] if x["value"] == tier_1 and x["latest"] == 3])
		sent = trends.build_payload(12)
		self.assertNotIn(tier_1, sent.text())
		self.assertNotIn(frappe.db.get_value("Risk Type", tier_1, "risk_type_name"), sent.text())
		self.assertGreaterEqual(sent.withheld, 3)

	def test_the_narrative_payload_is_counts_and_taxonomy_only(self):
		doc = self.document(document_name=unique("Trend Secret Title"))
		frappe.get_doc({"doctype": "Policy Violation", "document": doc.name, "violation_type": "Process", "severity": "Low",
		                "identified_on": nowdate(), "description": "Secret description text.", "violation_status": "Logged"}).insert(ignore_permissions=True)
		with ta.stub_endpoint(reply="Themes are thin.") as (server, url):
			self.enable_ai(url)
			self.as_user("ai-analyst")
			out = trends.ai_commentary(12)
		self.assertTrue(out["ai"]["used"])
		body = json.dumps(server.requests[0]["body"])
		self.assertNotIn("Trend Secret Title", body)
		self.assertNotIn("Secret description", body)


# ----------------------------------------------------------------- scoring


class TestScoring(AITestCase):
	def test_weights_are_configuration_and_bad_values_are_reported(self):
		cfg, problems = scoring.weights(json.dumps({"policy": {"review_overdue": {"weight": 40}, "nope": {}},
		                                            "forum": {"review_overdue": {"weight": 500}}}))
		self.assertEqual(cfg["policy"]["review_overdue"]["weight"], 40)
		self.assertEqual(cfg["forum"]["review_overdue"]["weight"], 15)
		self.assertEqual(len(problems), 2)
		self.assertEqual(scoring.weights("{not json")[1][0][:20], "The configured weigh")
		self.assertEqual(scoring.points({"kind": "count", "weight": 8, "cap": 24}, 5), 24)
		self.assertEqual(scoring.points({"kind": "share", "weight": 15}, 0.5), 7.5)

	def test_a_policy_score_shows_its_working_and_follows_the_weights(self):
		doc = self.document(document_name=unique("Scored Policy"))
		frappe.db.set_value(DOCUMENT, doc.name, {"next_review_on": add_days(nowdate(), -10), "is_active": 1})
		self.as_user("ai-analyst")
		row = next(s for s in scoring.assess()["policies"] if s["name"] == doc.name)
		factors = {f["factor"]: f for f in row["factors"]}
		self.assertEqual(factors["review_overdue"]["points"], 20)
		self.assertEqual(factors["no_approving_forum"]["points"], 10)
		self.assertEqual(row["score"], sum(f["points"] for f in row["factors"]))

		frappe.set_user("Administrator")
		self.configure(risk_score_weights=json.dumps({"policy": {"review_overdue": {"weight": 50}}}))
		self.as_user("ai-analyst")
		row2 = next(s for s in scoring.assess()["policies"] if s["name"] == doc.name)
		self.assertEqual(row2["score"], row["score"] + 30)

	def test_a_factor_the_reader_cannot_see_scores_nothing(self):
		self.document(document_name=unique("Reader Policy"))
		self.as_user("ai-reader")
		result = scoring.assess()
		for row in result["policies"]:
			sla = next(f for f in row["factors"] if f["factor"] == "breached_slas")
			self.assertFalse(sla["available"])
			self.assertEqual(sla["points"], 0)


# -------------------------------------------------------------- regulatory


BODY = """1. Purpose
This policy governs our suppliers.
2. Outsourcing Arrangements
Material outsourcing arrangements need notification to the supervisor before signing.
3. Records
Keep records for seven years."""


class TestRegulatory(AITestCase):
	def _setup(self):
		req = frappe.get_doc({"doctype": "Regulatory Requirement", "regulatory_requirement_code": unique("OUTS").upper(),
		                      "regulatory_requirement_name": "Outsourcing notification", "citation": "Rule 12",
		                      "summary": "Material outsourcing arrangements require supervisor notification.",
		                      "is_active": 1}).insert(ignore_permissions=True)
		citing = self.document(document_name=unique("Supplier Policy"), body_text=BODY)
		citing.append("regulatory_references", {"regulatory_requirement": req.name, "obligation_summary": "Existing note."})
		citing.save(ignore_permissions=True)
		candidate = self.document(document_name=unique("Vendor Standard"),
		                          body_text="1. Scope\nOutsourcing arrangements with material suppliers.\n2. Notification\nSupervisor notification is prompt.")
		return req, citing, candidate

	def test_citing_records_and_rule_based_candidates_with_sections(self):
		req, citing, candidate = self._setup()
		self.as_user("ai-analyst")
		o = regulatory.overview(req.name)
		[doc_row] = [c for c in o["citing"] if c["name"] == citing.name]
		self.assertEqual(doc_row["sections"][0]["section"], "2. Outsourcing Arrangements")
		self.assertIn(candidate.name, [c["name"] for c in o["candidates"]])
		self.assertEqual(o["ai_runs"], [])

	def test_recording_a_change_saves_through_the_controller_and_its_fan_out(self):
		req, *_ = self._setup()
		from consilium.consilium_core.doctype.regulatory_requirement import regulatory_requirement as controller

		# The framework keeps no change log under test unless told to; the
		# page reads "what changed" from that log.
		with patch.object(controller, "notify_citing_owners") as fan_out, patch.dict(frappe.local.flags, in_test=False):
			out = regulatory.record_change(req.name, {"citation": "Rule 12 (amended)"})
		fan_out.assert_called_once()
		self.assertEqual(out["change"]["changes"][0]["new"], "Rule 12 (amended)")
		self.assertEqual(str(frappe.db.get_value("Regulatory Requirement", req.name, "last_change_on")), nowdate())

		self.as_user("ai-reader")
		with self.assertRaises(frappe.PermissionError):
			regulatory.record_change(req.name, {"citation": "Rule 13"})

	def test_a_change_imported_by_file_goes_through_the_same_fan_out(self):
		req, *_ = self._setup()
		from consilium.consilium_core.doctype.regulatory_requirement import regulatory_requirement as controller

		profile = regulatory.ensure_profile()
		self.assertEqual(regulatory.ensure_profile(), profile)
		batch = frappe.get_doc({"doctype": "Import Batch", "batch_reference": unique("reg"), "source_system": regulatory.IMPORT_SYSTEM,
		                        "import_profile": profile, "target_doctype": "Regulatory Requirement",
		                        "received_on": frappe.utils.now(), "status": "Uploaded"}).insert(ignore_permissions=True)
		importing.validate_batch(batch, [{"Code": req.name, "Name": "Outsourcing notification", "Citation": "Rule 12A"}])
		with patch.object(controller, "notify_citing_owners") as fan_out:
			result = importing.commit_batch(batch.name)
		self.assertEqual(len(result["committed"]), 1, result)
		self.assertEqual(frappe.db.get_value("Regulatory Requirement", req.name, "citation"), "Rule 12A")
		fan_out.assert_called_once()

	def _suggest(self, req, citing, candidate, url):
		self.enable_ai(url)
		self.as_user("ai-analyst")
		return regulatory.ai_suggest(req.name)

	def _reply(self, citing, candidate):
		return json.dumps({"summary": "Outsourcing now needs prior notice.", "suggestions": [
			{"document": guard.token(DOCUMENT, candidate.name), "sections": ["1. Scope"], "reason": "It governs the same suppliers."},
			{"document": guard.token(DOCUMENT, citing.name), "sections": ["2. Outsourcing Arrangements"], "reason": "Cites the rule."},
			{"document": "D-deadbeef", "sections": ["x"], "reason": "A record the platform never sent."},
		]})

	def test_suggestions_are_recorded_and_nothing_is_written_until_a_person_accepts(self):
		req, citing, candidate = self._setup()
		with ta.stub_endpoint(reply=self._reply(citing, candidate)) as (server, url):
			out = self._suggest(req, citing, candidate, url)
		self.assertTrue(out["ai_result"]["used"], out["ai_result"])
		[run] = out["ai_runs"]
		self.assertEqual(run["summary"], "Outsourcing now needs prior notice.")
		self.assertEqual({s["document"] for s in run["suggestions"]}, {citing.name, candidate.name})
		self.assertTrue(all(s["decision"] is None and s["may_decide"] for s in run["suggestions"]))
		candidate.reload()
		self.assertFalse(candidate.get("regulatory_references"))
		self.assertNotIn(candidate.document_name, json.dumps(server.requests[0]["body"]))

		# Accept, edited: a citation row is written with the person's text.
		out = regulatory.decide(run["service_request"], candidate.name, "accept", accepted_value="Check the scope clause.")
		candidate.reload()
		[ref] = candidate.regulatory_references
		self.assertEqual((ref.regulatory_requirement, ref.obligation_summary), (req.name, "Check the scope clause."))
		row = frappe.get_doc(ACCEPTANCE, {"ai_service_request": run["service_request"], "subject_name": candidate.name})
		self.assertEqual(row.accepted_by, self.users["ai-analyst"])
		self.assertTrue(row.edited_before_accept)
		self.assertIn("1. Scope", row.suggested_value)
		self.assertEqual(row.applied_to_version, candidate.current_version)
		self.assertEqual(row.target_fieldname, "regulatory_references")
		with self.assertRaises(frappe.ValidationError):
			regulatory.decide(run["service_request"], candidate.name, "reject")

		# Accept as suggested on a document that already cites it: appended, not replaced.
		regulatory.decide(run["service_request"], citing.name, "accept")
		citing.reload()
		note = citing.regulatory_references[0].obligation_summary
		self.assertTrue(note.startswith("Existing note.\n\n"))
		self.assertIn("2. Outsourcing Arrangements", note)
		row = frappe.get_doc(ACCEPTANCE, {"ai_service_request": run["service_request"], "subject_name": citing.name})
		self.assertFalse(row.edited_before_accept)
		self.assertEqual(row.target_fieldname, "regulatory_references.obligation_summary")

	def test_a_rejection_is_recorded_and_writes_nothing(self):
		req, citing, candidate = self._setup()
		with ta.stub_endpoint(reply=self._reply(citing, candidate)) as (server, url):
			out = self._suggest(req, citing, candidate, url)
		run = out["ai_runs"][0]
		out = regulatory.decide(run["service_request"], candidate.name, "reject")
		candidate.reload()
		self.assertFalse(candidate.get("regulatory_references"))
		row = frappe.get_doc(ACCEPTANCE, {"ai_service_request": run["service_request"], "subject_name": candidate.name})
		self.assertIsNone(row.accepted_value)
		decided = next(s for s in out["ai_runs"][0]["suggestions"] if s["document"] == candidate.name)
		self.assertFalse(decided["decision"]["accepted"])

	def test_only_someone_who_may_change_the_document_may_decide(self):
		req, citing, candidate = self._setup()
		with ta.stub_endpoint(reply=self._reply(citing, candidate)) as (server, url):
			out = self._suggest(req, citing, candidate, url)
		run = out["ai_runs"][0]
		self.as_user("ai-reader")
		with self.assertRaises(frappe.PermissionError):
			regulatory.decide(run["service_request"], candidate.name, "accept")
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists(ACCEPTANCE, {"ai_service_request": run["service_request"]}))

	def test_an_answer_that_is_not_json_is_not_shown(self):
		req, citing, candidate = self._setup()
		with ta.stub_endpoint(reply="Here are my thoughts, in prose.") as (server, url):
			out = self._suggest(req, citing, candidate, url)
		self.assertFalse(out["ai_result"]["used"])
		self.assertEqual(out["ai_runs"], [])
		self.assertEqual(self.requests_since(guard.capability_name("regulatory"))[0].status, "Failed")

	def test_openai_compatible_gateway(self):
		req, citing, candidate = self._setup()
		with ta.stub_endpoint(mode="openai", reply=self._reply(citing, candidate)) as (server, url):
			self.enable_ai(url + "/v1", provider=client.OPENAI_COMPATIBLE)
			self.as_user("ai-analyst")
			out = regulatory.ai_suggest(req.name)
		self.assertTrue(out["ai_result"]["used"])
		self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")
		self.assertEqual(server.requests[0]["headers"].get("authorization"), "Bearer dummy-test-key")


class TestPages(AITestCase):
	def test_the_pages_render_for_a_signed_in_reader(self):
		from frappe.website.serve import get_response

		doc = self.document()
		self.as_user("ai-analyst")
		for path in ("governance-gaps", "emerging-risks", "regulatory-updates", f"policy-impact?name={doc.name}"):
			route, _, query = path.partition("?")
			frappe.local.form_dict = frappe._dict(dict(p.split("=") for p in query.split("&")) if query else {})
			response = get_response(route)
			self.assertEqual(response.status_code, 200, path)
			html = response.get_data(as_text=True)
			self.assertIn("consilium-ai.js", html, path)
		self.assertIn("ai-impact", html)
