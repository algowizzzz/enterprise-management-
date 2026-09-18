"""The leadership briefing's slides, in order: text, layout and speaker notes.

Numbers come from facts.json through ``<<name>>`` placeholders (see
build_deck.compute_values). Slides that describe the coverage (the chart, the
heatmap, the "still open" list, the roadmap's first phase and the appendix
trace table) are generated from the per-requirement classes, so a re-grade
changes them without touching this file.

Markup in slide text: ``**bold**``, ``{{accent}}``. Layout units are inches on a
13.333 × 7.5 in slide; ``M`` is the side margin and ``CW`` the content width.
"""

from __future__ import annotations

from deckkit import (ACCENT, ACCENT_T, CARD, CLASS_COLOURS, CW, ICE, INK, LINE, M, MUTED, NAVY, NAVY2,
                     SLATE, TINT, WHITE, W, badge, bar_chart, card, chevrons, divider, frame, kpi, label,
                     notes_, rule, shape, shot, table, tx)

IMG = "docs/guides/images/"

#: Screenshots by key: the file under docs/guides/images, what it shows, and an
#: optional crop [x, y, w, h] in pixels. The capture script scrubs the AI
#: endpoint and model on the Integrations screenshots, so they are used whole.
SHOTS = {
	"home": {"file": IMG + "policies/library.png", "desc": "Policy library: filters, search and Export CSV under the header"},
	"nav_menu": {"file": IMG + "navigation/menu-governance.png", "desc": "The Governance menu open: pages and filtered views, each explained"},
	"search": {"file": IMG + "navigation/search.png", "desc": "Global search from the header, grouped by record type"},
	"mywork": {"file": IMG + "mywork/approvals.png", "desc": "My work: approvals described in words", "crop": [0, 0, 1440, 900]},
	"integrations": {"file": IMG + "admin/integrations.png", "desc": "Admin, Integrations"},
	"docai_modal": {"file": IMG + "policies/doc-ai.png", "desc": "Open in Doc AI: explains itself until an address is set"},
	"help_answer": {"file": IMG + "assistant/help-answer.png", "desc": "The Help assistant answering with its sources"},
	"gaps": {"file": IMG + "insights/gaps-ai.png", "desc": "Gaps and risk, with AI commentary labelled as machine-generated"},
	"formation": {"file": IMG + "governance/formation-blocked.png", "desc": "Formation request: Approve disabled, with what still blocks it"},
	"forum": {"file": IMG + "governance/forum.png", "desc": "Forum page: standing, officers and actions"},
	"policy": {"file": IMG + "policies/policy.png", "desc": "Policy page: the actions open now, including Open in Doc AI"},
	"escalation": {"file": IMG + "escalations/move-status.png", "desc": "Escalation page: the actions open at this stage"},
	"history": {"file": IMG + "governance/forum-tab-history.png", "desc": "Forum History tab: revisions and the record history", "crop": [0, 0, 1440, 900]},
	"cfg1": {"file": IMG + "verification/step-transitions.png", "desc": "The Legal Review stage and its transitions, added as configuration"},
	"cfg2": {"file": IMG + "verification/step-flag.png", "desc": "The flag row that says what the stage means", "crop": [0, 0, 1440, 900]},
	"cfg3": {"file": IMG + "verification/step-in-legal-review.png", "desc": "The document in Legal Review"},
}

MANDATORY = ("G", "P", "E")
MOD_SIZE = {"G": 19, "P": 26, "E": 19, "O": 7}


# ---------------------------------------------------------------- coverage helpers
def ids_in_class(d, klass: str, prefixes=("G", "P", "E", "O")) -> list[str]:
	cov = d.facts["coverage"]
	return [f"{p}-{i}" for p in prefixes for i in range(1, MOD_SIZE[p] + 1) if cov.get(f"{p}-{i}") == klass]


def topic_list(d, ids: list[str]) -> list[str]:
	"""['topic (G-14, O-4)', 'other topic (P-8)']: ids grouped by their gap
	topic, in first-seen order. An id with no topic is listed on its own."""
	names = d.facts.get("gap_topics", {})
	groups: dict[str, list[str]] = {}
	for i in ids:
		groups.setdefault(names.get(i, i), []).append(i)
	return [f"{t} ({', '.join(g)})" if t not in g else t for t, g in groups.items()]


def topics(d, ids: list[str]) -> str:
	return ", ".join(topic_list(d, ids))


def title_topics(d) -> list[str]:
	"""Short names for the kinds of class-d gap still showing, for the heatmap title."""
	d_ids = set(ids_in_class(d, "d"))
	return [name for name, ids in d.facts.get("title_topics", {}).items() if d_ids.intersection(ids)]


def join_words(items: list[str]) -> str:
	return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# =====================================================================
def build(d) -> None:
	title_slide(d)
	executive_summary(d)
	decisions(d)
	divider(d, "A", "Why this exists", "Three governance questions, and the evidence they must produce",
	        "Section A sets out the problem: what the organisation must be able to prove, and why one platform answers it better than three separate systems.")
	three_questions(d)
	evidence_bar(d)
	from_to(d)
	lines_of_defence(d)
	divider(d, "B", "What we built", "The capability, the design choices behind it, and the platform it runs on",
	        "Section B covers what exists: the capability map, the four design principles, why we chose this platform, the constraints it meets, the architecture, the data model, the redesigned portal and the integrations screen.")
	capability_map(d)
	design_principles(d)
	platform_choice(d)
	constraints(d)
	architecture(d)
	data_model(d)
	portal_and_workspace(d)
	ux_redesign(d)
	integrations(d)
	divider(d, "C", "How it works", "A day in the life, from forming a committee to proving a year later what happened",
	        "Section C walks through one journey using the demonstration organisation. Every record reference on these slides exists in the demonstration database.")
	journey(d)
	walkthroughs(d)
	audit_as_at(d)
	divider(d, "D", "Evidence", "Measured coverage, test results, defects found and fixed, and the controls we attacked directly",
	        "Section D is the evidence. Coverage is measured, not asserted. The tests are real runs. The defects and fixes are documented with regression tests.")
	coverage_chart(d)
	heatmap(d)
	quality(d)
	defects(d)
	controls(d)
	configuration_proof(d)
	divider(d, "E", "What is not done", "Feature gaps, the AI features, go-live conditions and the assumptions that carry most risk",
	        "Section E is the honest list: what is missing, what we have deliberately not built, and what must be true before go-live.")
	backlog(d)
	workstreams(d)
	ai(d)
	readiness(d)
	assumptions(d)
	divider(d, "F", "Road to production", "A gated plan, clear ownership, the risks and the framework-version recommendation",
	        "Section F is the plan. Phases exit on evidence, not dates. Durations are ranges and will be re-baselined once the target environment exists.")
	roadmap(d)
	raci(d)
	risks(d)
	v16(d)
	asks(d)
	appendix(d)


# =====================================================================
# 1 — Title
def title_slide(d):
	s = d.new_slide(NAVY)
	label(d, s, [("CONSILIUM", {"size": 14, "bold": True, "color": ACCENT, "spacing": 4})], M, 1.0, 6, 0.4)
	label(d, s, [("One platform for who decides, what the rules are, and what happens when something goes wrong",
	              {"size": 34, "bold": True, "color": WHITE})], M, 1.55, 7.4, 2.2, valign="top")
	label(d, s, [("What we built, what the evidence shows, and what it takes to reach production", {"size": 18, "color": ICE})],
	      M, 3.9, 7.2, 0.8, valign="top")
	label(d, s, [], M, 5.3, 7.2, 0.7, paragraphs=[
		[(d.fill("Leadership briefing  ·  <<briefing_date>>"), {"size": 13, "bold": True, "color": WHITE})],
		[(d.fill("Pre-read for decision. Release <<release>>: every figure measured on the final build."), {"size": 13, "color": ICE})],
	])
	bx, by, bw = 8.55, 1.6, 4.25
	mw = (bw - 0.3) / 3
	for i, (m, sub, ids) in enumerate([("Forums", "Who decides", "G-1…19"), ("Policy", "What the rules are", "P-1…26"),
	                                    ("Escalation", "When things go wrong", "E-1…19")]):
		x = bx + i * (mw + 0.15)
		shape(s, "rect", x, by, mw, 1.9, NAVY2, line="4E6390", line_w=1)
		label(d, s, [(m, {"size": 14, "bold": True, "color": WHITE})], x, by + 0.15, mw, 0.4, align="center")
		label(d, s, [(sub, {"size": 11, "color": ICE})], x, by + 0.65, mw, 0.6, valign="top", align="center", margin=0.05)
		label(d, s, [(ids, {"size": 11, "color": ICE})], x, by + 1.35, mw, 0.35, align="center")
	shape(s, "rect", bx, by + 2.05, bw, 0.9, ACCENT)
	label(d, s, [], bx, by + 2.05, bw, 0.9, align="center", paragraphs=[
		[("Shared Core", {"size": 14, "bold": True, "color": WHITE})],
		[("one data model · one permission model · one audit trail", {"size": 11, "color": WHITE})],
	])
	label(d, s, [("Offline install  ·  Windows and Linux  ·  PostgreSQL  ·  no per-seat licence", {"size": 11, "color": ICE})],
	      bx - 0.3, by + 3.1, bw + 0.3, 0.35, align="center")
	notes_(d, s, "Purpose of this session: take a decision on the path to production for Consilium. The deck follows the answer-first structure: the executive summary and the decisions come first; sections A to F are the supporting evidence; the appendix holds the detail. Every number carries its source in the footnote. All figures are final: they were measured on release <<release>> after the last build wave.")


# 2 — Executive summary
def executive_summary(d):
	v = d.values
	remain = (f"and the {v['missing_word']} that remain are named" if v["missing"] else "and no mandatory requirement is missing a clause")
	s = frame(d, "Consilium is built and credibly tested; reaching production now depends on rehearsal in the target environment and five leadership decisions", None,
	          "Sources: docs/delivery/REQUIREMENTS-COVERAGE.md §1–2 (final measurement, <<measured>>); docs/delivery/EPICS.md; docs/delivery/DEPLOYMENT-READINESS.md; HANDOVER.md §4, §7.",
	          "Answer first. Four points, each supported later in the deck. One: we built one platform on infrastructure the organisation already runs, with no per-seat licence. Two: we measured coverage honestly, requirement by requirement; the first measurement exposed real gaps, the final build closed most of them, " + remain + ". Three: the quality evidence is strong, and it became stronger when we loaded a realistic organisation and found nine real defects, including a control bypass on policy publication, which is fixed. Four: installation, migration and upgrade are rehearsed offline on a stand-in server; what is left is mainly environment work on the real target — certificates, sign-on, SMTP, load, a real Windows run — plus the framework-version decision. The recommendation is on the right.")
	rows = [
		("We built one governance platform on infrastructure the organisation already runs.",
		 "Forums, policy and escalation share one Core: **<<ent_total>> entities over <<ent_tables>> tables**. Installs with no internet access on Windows and Linux, on PostgreSQL. Open-source framework, **no per-seat licence**, not forked."),
		("Coverage is measured, not asserted, and the final build closed most of the gaps.",
		 "All **64** mandatory requirements re-measured on release <<release>>: **<<full>>** fully reachable, **<<partly>>** partly, **<<missing>>** missing a mandatory clause. On 17 Sep it was 22 / 24 / 18. Of <<stories_total>> backlog stories, **<<stories_done>>** are done and none is in progress."),
		("Quality evidence is strong, and realistic data made it stronger.",
		 "**<<tests_passed>> of <<tests_run>>** automated tests pass on a clean site. **<<ui_sweep>>/<<ui_sweep>>** interface checks and **<<journeys>>/<<journeys>>** browser journeys pass. A realistic demonstration organisation exposed **9 defects**, including a publication-approval bypass. All are fixed, with **21** regression tests."),
		("What remains before go-live is mainly environment work, not design.",
		 "Install, migration and upgrade are rehearsed air-gapped on Rocky Linux 9 (**verify <<verify>>/<<verify>>**). Still open: the target itself, certificates, sign-on, SMTP, load and a real Windows run. The framework version we use (v15) treats PostgreSQL as second-class."),
	]
	y = 1.75
	for i, (h, b) in enumerate(rows):
		badge(d, s, i + 1, M, y + 0.05)
		tx(d, s, h, M + 0.5, y, 3.3, 1.1, base={"size": 13, "bold": True, "color": NAVY})
		tx(d, s, b, M + 3.95, y, 4.55, 1.12, base={"size": 11.5})
		if i < len(rows) - 1:
			rule(s, M + 0.5, y + 1.2, 8.0, 0, LINE, 0.75)
		y += 1.28
	card(s, 9.35, 1.75, 3.48, 4.95, NAVY)
	tx(d, s, [
		{"t": "RECOMMENDATION", "size": 11, "bold": True, "color": ACCENT, "gap": 8},
		{"t": "Approve the move to target-environment rehearsal, gated on evidence:", "size": 13, "bold": True, "color": WHITE, "gap": 8},
		{"t": "Rebase onto framework v16 before go-live", "bullet": True, "color": WHITE, "gap": 5},
		{"t": "Provide the target environment and name its infrastructure owners", "bullet": True, "color": WHITE, "gap": 5},
		{"t": "Confirm the single sign-on protocol", "bullet": True, "color": WHITE, "gap": 5},
		{"t": "Name business owners for rules and reference data", "bullet": True, "color": WHITE, "gap": 5},
		{"t": "Approve an AI endpoint and data boundary, or leave AI off: nothing depends on it", "bullet": True, "color": WHITE, "gap": 10},
		{"t": "Go-live is conditional on the exit criteria on slide 40, not on a date.", "size": 11, "color": ICE, "italic": True},
	], 9.6, 1.95, 3.05, 4.6, base={"size": 12})


# 3 — Decisions today
def decisions(d):
	s = frame(d, "We ask for five decisions today; each one removes a named blocker on the path to production", None,
	          "Sources: HANDOVER.md §7–8; docs/product/07-assumptions-and-gaps.md A-1–A-4, B-1, B-4–B-6; docs/product/01-requirements-baseline.md App. A; docs/delivery/DEPLOYMENT-READINESS.md. Owners are a proposal for confirmation.",
	          "These are the asks. Each one is tied to a specific blocker. Decision 1, the framework version, is an architecture call the handover explicitly reserved for people rather than engineers. Decision 2 matters most for the schedule: nothing can be rehearsed until the target environment exists and someone owns certificates, service accounts, write-once storage and backups. Decision 3 matters because LDAP and OIDC are configuration, while SAML is a separate build. Decision 4: the engines exist, but the business rules they run on do not yet. Decision 5 keeps AI from becoming a go-live dependency.")
	n = lambda k: {"t": k, "bold": True, "align": "center"}  # noqa: E731
	table(d, s, [
		["#", "Decision", "Why it is needed now", "Recommendation", "Proposed owner"],
		[n("1"), "**Framework version:** rebase onto v16 before go-live", "In v15 the framework calls its PostgreSQL support limited and says fixes for earlier versions will not be added. Our porting work carries over to v16 unchanged.", "**Approve** the rebase before target rehearsal", "Executive sponsor, with engineering lead"],
		[n("2"), "**Target environment:** provide it and name its infrastructure owners", "Migration, upgrade and load can only be rehearsed on the target. Certificates, ports, service accounts, the mail route (SMTP relay or Microsoft Graph app registration), write-once storage and backup ownership are all undecided.", "**Approve** access; name one infrastructure owner", "Infrastructure lead"],
		[n("3"), "**Single sign-on:** confirm the protocol", "LDAP and OIDC are configuration. SAML does not exist in the framework, so it would be a separate build with its own estimate.", "**Confirm** LDAP or OIDC if possible", "Information security"],
		[n("4"), "**Business rules:** name owners for rules and reference data", "The engines are built but run on data nobody has supplied yet: major/minor classification rules, real taxonomy values, escalation closure criteria, and a regulatory-change file sample.", "**Name** owners in the governance and policy offices", "Business sponsors"],
		[n("5"), "**AI position:** approve an endpoint, or leave it off", "Tested end to end with an OpenAI-compatible provider. Every analysis also works with AI off. Production needs an approved endpoint, an outbound path and a data boundary.", "**Approve** an endpoint and ceiling, or keep AI off", "Executive sponsor, with security"],
	], M, 1.75, CW, [0.45, 2.75, 4.6, 2.5, 2.03], font_size=11.5, row_h=[0.4, 0.88, 0.88, 0.8, 0.95, 0.88])


# 5 — three questions
def three_questions(d):
	s = frame(d, "Governance comes down to three questions. Consilium answers each one in a single place, on a shared Core", "A",
	          "Source: docs/product/01-requirements-baseline.md §3 and Appendices A–B (64 mandatory requirements, all marked Mandatory in the source; 7 supplementary O-1…O-7 brought into scope); HANDOVER.md §0.",
	          "The programme's 64 mandatory requirements reduce to three questions. Who decides is the forum inventory: committees, councils and working groups, and how they are formed, composed, reviewed and disbanded. What the rules are is the governing-document lifecycle. What happens when something goes wrong is escalation. The key design choice was to treat these as three modules of one product rather than three systems to integrate.")
	cols = [
		("Who decides?", "Governance forums", "G-1 … G-19", "19", ["Inventory of boards, committees, councils, working groups", "Formation requests evaluated and approved", "Membership, meetings, motions and votes", "Compliance standing, annual attestation, disbandment"]),
		("What are the rules?", "Policy", "P-1 … P-26", "26", ["Frameworks, policies, standards, procedures", "Intake, drafting, review, approval, publication", "Applicability, exemptions, monitoring, violations", "Periodic review, attestation, retirement"]),
		("What happens when something goes wrong?", "Escalation", "E-1 … E-19", "19", ["Intake against configurable templates", "Severity and routing from an approved matrix", "Action plans, risk acceptances, time limits", "Closure with evidence, or handed off externally"]),
	]
	cw = (CW - 0.6) / 3
	for i, (q, mod, ids, n, items) in enumerate(cols):
		x = M + i * (cw + 0.3)
		tx(d, s, q, x, 1.75, cw, 0.6, base={"size": 15, "bold": True, "color": ACCENT}, valign="bottom")
		card(s, x, 2.45, cw, 3.3)
		tx(d, s, [{"t": mod, "size": 18, "bold": True, "color": NAVY, "gap": 2},
		          {"t": f"{n} mandatory requirements  ·  {ids}", "size": 11, "color": MUTED, "gap": 10}], x + 0.25, 2.6, cw - 0.5, 0.9)
		tx(d, s, [{"t": t, "bullet": True, "gap": 8} for t in items], x + 0.25, 3.45, cw - 0.5, 2.25, base={"size": 13.5})
	card(s, M, 5.95, CW, 0.75, NAVY)
	tx(d, s, "**Shared Core, built once:** taxonomy, identity and delegation, attestation, classification rules, versioning and revert, retention, import and export, notification, service levels.   **64** mandatory  +  **7** supplementary requirements",
	   M + 0.25, 5.95, CW - 0.5, 0.75, base={"size": 12.5, "color": WHITE}, valign="middle")


# 6 — evidential bar
def evidence_bar(d):
	s = frame(d, "The requirements set a high bar for evidence: every decision, approval and refusal must be provable after the fact", "A",
	          "Source: docs/product/01-requirements-baseline.md §3 (requirement statements, paraphrased). All 64 requirements are Mandatory in the source documents.",
	          "This slide explains why the platform is built the way it is. Read down the left column: these are the things an auditor or supervisor will test. Each maps to specific mandatory requirements. They drive most of the build effort: revert, write-once retention and enforcement on every read path are not framework features. They had to be built.")
	table(d, s, [
		["What must be provable", "What the requirements demand", "Requirements", "Why it is hard"],
		["**Who did what, and when**", "Every change and user action logged with timestamp and actor. Prior versions retained, and an authorised user can revert.", "G-9, P-9, E-12", "Revert is not a framework feature. It is built forward-only, so history is never rewritten."],
		["**Nothing published without approval**", "Every approval required for the change's classification is complete before publication. No bypass without a documented exception.", "P-25, P-16", "The gate must hold on every route, not just the intended one (see the defect on slide 30)."],
		["**Challenge happened**", "Second-line review and challenge, with service levels, before escalation to executives or forums.", "E-9", "Needs time limits per step, not just per matter."],
		["**People confirmed the facts**", "Annual first-quarter attestation of the forum inventory; annual policy attestation.", "G-10, P-8", "Three attestation events share one engine."],
		["**Restricted means restricted**", "Confidential documents and sensitive escalations limited to authorised users for view, download, print and share.", "P-1, P-13, E-16", "Must hold on list, form, report, search, export and API."],
		["**Records cannot be altered**", "Data and documents retained per policy, in write-once, read-many form for the period.", "G-16, P-18, E-18", "Moved from an external hook to in-platform: the largest single scope increase."],
	], M, 1.75, CW, [2.45, 4.85, 1.6, 3.43], font_size=11.5, row_h=[0.4, 0.75, 0.75, 0.62, 0.62, 0.72, 0.72])


# 7 — from/to + deltas chart
def from_to(d):
	s = frame(d, "Stakeholder decisions turned three separately scoped systems and four live connectors into one platform, reshaping 37 of the 64 requirements", "A",
	          "Source: docs/product/01-requirements-baseline.md §2 (decisions S-1…S-11), §4 and requirement tables (Δ markers; the tables are authoritative per 07 'Known inconsistencies' — the 06 summary states 15 and 26); E-11 statement.",
	          "The source requirements described three separately scoped systems with live connectors to four external systems nobody had specified. Eleven stakeholder decisions reshaped that into something deliverable. Fourteen requirements changed materially and twenty-three were clarified. The biggest trade: live connectors became one governed file import pipeline, which keeps the control and loses only timeliness. Retention moved in-house, which is the largest single scope increase.")
	rows = [
		("Three separately scoped systems", "One platform, three modules, shared Core", "S-1"),
		("Live connectors to the risk register, risk appetite system, GRC platform and regulatory-change feed", "One governed file import and export pipeline, with mapping, validation and a full audit trail", "S-2"),
		("Retention handed off to an external records system", "Retention classes, legal hold and a hash-chained archive, built in the platform", "S-3"),
		("Collaborative editing built here", "External editor. We hold the authoritative document body and its version chain, with revert", "S-4, S-5"),
		("Periodic escalation submissions compiled by hand", "Reports generated directly, with quarterly tracking and nil returns", "E-11"),
	]
	tx(d, s, "FROM", M, 1.75, 3.4, 0.3, base={"size": 10, "bold": True, "color": MUTED})
	tx(d, s, "TO", M + 3.85, 1.75, 3.6, 0.3, base={"size": 10, "bold": True, "color": MUTED})
	y = 2.1
	for a, b, rid in rows:
		card(s, M, y, 3.45, 0.82)
		tx(d, s, a, M + 0.15, y, 3.2, 0.82, base={"size": 11.5, "color": SLATE}, valign="middle")
		shape(s, "right_arrow", M + 3.5, y + 0.28, 0.3, 0.26, ACCENT)
		card(s, M + 3.85, y, 3.65, 0.82, TINT)
		tx(d, s, [{"t": b, "gap": 0}], M + 4.0, y, 3.0, 0.82, base={"size": 11.5, "color": NAVY, "bold": True}, valign="middle")
		tx(d, s, rid, M + 7.0, y, 0.45, 0.82, base={"size": 9, "color": MUTED}, valign="middle", align="right")
		y += 0.92
	tx(d, s, "Effect of stakeholder decisions on the 64 mandatory requirements", 8.45, 1.75, 4.4, 0.5, base={"size": 12, "bold": True, "color": NAVY})
	bar_chart(d, s, 8.35, 2.2, 4.5, 3.2, ["Materially changed", "Clarified or narrowed", "Unchanged"], [("Requirements", [14, 23, 27])],
	          colours=[NAVY], label_size=12, cat_size=11, reverse=True, gap=60, vmax=32)
	card(s, 8.45, 5.5, 4.4, 1.2, ACCENT_T)
	tx(d, s, "**So what:** the largest unknown (four undiscovered external interfaces) was removed. The largest scope increase (in-platform retention) was accepted.",
	   8.6, 5.55, 4.1, 1.1, base={"size": 11.5}, valign="middle")


# 8 — three lines of defence
def lines_of_defence(d):
	s = frame(d, "Consilium puts all three lines of defence on the same record, so challenge and assurance happen where the work is done", "A",
	          "Sources: docs/guides/08-your-first-day.md (roles); docs/product/05-glossary.md §B–C; docs/delivery/REQUIREMENTS-COVERAGE.md P-13 (permission tests). The mapping of roles to lines of defence is illustrative.",
	          "The same record carries first-line ownership, second-line challenge and third-line assurance. Segregation of duties is enforced on the server, not by hiding buttons. Tests attempt each forbidden action as the wrong role. The audit role reads everything and changes nothing. Every refusal is logged, so assurance can see attempted breaches as well as completed actions.")
	cols = [
		("1st line", "Own and manage", ["Policy Owner — drafts and maintains governing documents", "Escalation Owner — raises and works matters, action plans, closures", "Committee Secretary / Forum Owner — meetings, motions, votes, membership"]),
		("2nd line", "Oversee and challenge", ["Risk Governance Office — evaluates formation requests", "Compliance Reviewer — records forum compliance decisions", "Escalation Reviewer — challenges and reviews matters", "Enterprise Policy Office — approves, publishes, retires"]),
		("3rd line", "Independent assurance", ["Consilium Audit — reads everything, changes nothing", "Governance Refusal Log — every refused action, with reason", "Field-level change history on every governed record"]),
	]
	cw = (CW - 0.6) / 3
	for i, (lvl, sub, items) in enumerate(cols):
		x = M + i * (cw + 0.3)
		card(s, x, 1.75, cw, 0.85, [NAVY, NAVY2, SLATE][i])
		tx(d, s, [{"t": lvl, "size": 18, "bold": True, "color": WHITE, "gap": 0}, {"t": sub, "size": 12, "color": ICE}], x + 0.25, 1.8, cw - 0.5, 0.75, valign="middle")
		card(s, x, 2.6, cw, 2.75)
		tx(d, s, [{"t": t, "bullet": True, "gap": 9} for t in items], x + 0.2, 2.78, cw - 0.4, 2.5, base={"size": 13})
	tx(d, s, "Segregation of duties is enforced on the server and tested by attempting forbidden actions:", M, 5.55, CW, 0.3, base={"size": 12, "bold": True, "color": NAVY})
	tw = (CW - 0.45) / 4
	for i, t in enumerate(["A reviewer cannot create a document", "A policy owner cannot delete a document", "An auditor may read but not write", "A viewer cannot create a forum"]):
		card(s, M + i * (tw + 0.15), 5.95, tw, 0.7, TINT)
		tx(d, s, "✓  " + t, M + i * (tw + 0.15) + 0.15, 5.95, tw - 0.3, 0.7, base={"size": 11.5, "color": NAVY}, valign="middle")


# 10 — capability map
def capability_map(d):
	s = frame(d, "One platform, three modules and a shared Core: the engines every module needs are built once and reused", "B",
	          "Sources: entity and table counts measured on the demonstration site, <<measured>> (a scratch record type excluded); docs/delivery/SESSION-SUMMARY.md; docs/product/02-data-model.md §2.1.",
	          "This is the capability map. Across the top are the three business modules with their entity counts. Underneath is the Core: the services all three need. Attestation, notification, versioning, retention and service-level timing appear in all three modules' requirements with slightly different wording. Building them three times is the most likely way a programme like this becomes inconsistent. We built each one once.")
	mods = [
		("Governance", "<<ent_governance>> entities", ["Forum inventory and hierarchy", "Committee formation and evaluation", "Compliance lifecycle and watched fields", "Membership with history, delegation, quorum", "Meetings, motions, votes, minutes", "Disbandment"]),
		("Policy", "<<ent_policy>> entities", ["Repository, lineage, applicability", "Lifecycle, approval routing, gates", "Intake and major/minor classification", "Versions, publication, exemptions", "Horizon scanning, monitoring, violations", "Glossary"]),
		("Escalation", "<<ent_escalation>> entities", ["Matters with three configurable templates", "Matrix-driven severity and routing", "Action plans, risk acceptances", "Time limits and breach escalation", "Closure criteria and evidence", "Analysis and periodic returns"]),
	]
	cw = 3.05
	for i, (n, c, items) in enumerate(mods):
		x = M + i * (cw + 0.2)
		card(s, x, 1.75, cw, 2.85)
		tx(d, s, [{"t": n, "size": 16, "bold": True, "color": NAVY, "gap": 0}, {"t": c, "size": 11, "color": ACCENT, "bold": True, "gap": 6}], x + 0.2, 1.85, cw - 0.4, 0.65)
		tx(d, s, [{"t": t, "bullet": True, "gap": 3} for t in items], x + 0.2, 2.5, cw - 0.4, 2.05, base={"size": 11.5})
	cx, cy, cwid = M, 4.8, 3 * cw + 0.4
	card(s, cx, cy, cwid, 1.9, NAVY)
	tx(d, s, [{"t": "Consilium Core", "size": 16, "bold": True, "color": WHITE, "gap": 0},
	          {"t": "<<ent_core>> entities · built once, used by all three modules", "size": 11, "color": ICE}], cx + 0.2, cy + 0.1, 5, 0.6)
	chips = ["Taxonomy (17 lists)", "Identity & delegation", "Attestation engine", "Classification rules", "Version chain & revert",
	         "Retention & legal hold", "Import & export", "Notification templates", "Service levels & reminders", "Approval decisions",
	         "AI guard & provenance", "Navigation & integrations"]
	chw = (cwid - 0.4 - 0.15 * 5) / 6
	for i, c in enumerate(chips):
		r, k = divmod(i, 6)
		x, y = cx + 0.2 + k * (chw + 0.15), cy + 0.78 + r * 0.52
		shape(s, "rect", x, y, chw, 0.42, NAVY2)
		tx(d, s, c, x, y, chw, 0.42, base={"size": 10.5, "color": WHITE}, align="center", valign="middle")
	rx = M + cwid + 0.35
	rw = W - M - rx
	kpi(d, s, rx, 1.75, rw, "<<ent_total>>", "entities across Core and three modules")
	kpi(d, s, rx, 3.05, rw, "<<ent_tables>>", "PostgreSQL tables on one site")
	kpi(d, s, rx, 4.35, rw, "1", "data model, permission model and audit trail")
	tx(d, s, "No module keeps its own copy of a shared list: every tag links to the Core taxonomies.", rx, 5.75, rw, 0.9, base={"size": 11, "color": SLATE, "italic": True})


# 11 — design principles
def design_principles(d):
	s = frame(d, "Four design principles make the platform auditable and cheap to change", "B",
	          "Sources: docs/OPERATIONS.md §A–B; docs/delivery/SESSION-SUMMARY.md; docs/product/02-data-model.md §2.3 (M-1, M-4); docs/delivery/REQUIREMENTS-COVERAGE.md G-6, G-9.",
	          "These four principles are why the platform should stay cheap to run. One: the code never reads a workflow state's name. It reads flags, so adding a Legal Review step is configuration, not a release, and a checker enforces this. Two: nothing is deleted, so we can reconstruct any date. Three: every refusal is logged, which gives assurance the attempted breaches too. Four: one engine per concern. For example, three annual attestation events run on one engine.")
	P = [
		("States are configuration; flags are logic", "Code never compares a workflow state's name. It reads flags (editable, active, requires review) that each state sets.", "Renaming a state, or inserting an approval step, is configuration, not a release.", "A checker over 82 state names fails the build. Proven live: a new approval stage added with no release (slide 32)."),
		("Nothing is deleted; history reads as at any date", "Seats are ended, forums disbanded, documents retired, values made inactive. Membership is a dated record of its own.", "The composition of any forum on any past date is a query, not a reconstruction.", "Revert writes a new version; prior versions still exist afterwards (tested)."),
		("Every refusal is recorded", "When a control stops an action, the reason is written to the Governance Refusal Log, even if the action is rolled back.", "Assurance sees attempted breaches, not only completed actions.", "Every refusal message names the rule that refused it."),
		("One engine per concern", "Attestation, notification, versioning, retention, service levels and classification are built once, in Core.", "One consistent answer instead of three subtly different ones.", "Three annual attestation events, one engine."),
	]
	cw, ch = (CW - 0.3) / 2, 2.35
	for i, (h, what, sowhat, ev) in enumerate(P):
		x, y = M + (i % 2) * (cw + 0.3), 1.75 + (i // 2) * (ch + 0.2)
		card(s, x, y, cw, ch)
		badge(d, s, i + 1, x + 0.2, y + 0.2, 0.4, NAVY)
		tx(d, s, h, x + 0.75, y + 0.18, cw - 0.95, 0.45, base={"size": 15, "bold": True, "color": NAVY}, valign="middle")
		tx(d, s, [{"t": what, "gap": 6}, {"t": "**Why it matters:** " + sowhat, "gap": 6}, {"t": "**Evidence:** " + ev, "color": SLATE}],
		   x + 0.75, y + 0.72, cw - 0.95, ch - 0.85, base={"size": 12.5})


# 12 — platform choice
def platform_choice(d):
	s = frame(d, "An open-source framework gave us the governance building blocks without a per-seat licence, and we have not forked it", "B",
	          "Source: HANDOVER.md §1 (framework primitives and uses; objective of no per-seat licensing), §3 (not forked; 8 runtime patches; AST audit), §8; docs/product/04-architecture.md §1.",
	          "The platform choice is an open-source, metadata-driven framework. It ships the building blocks you would otherwise buy a commercial GRC product for: configurable workflow, immutable approval records, field-level history, role and row permissions, notifications, a report builder and an API. The critical discipline is that we have not forked it. Every change is a runtime patch that does nothing on Linux, so upstream security fixes still apply. The moment we fork, we own the framework's security patching forever.")
	table(d, s, [
		["Framework building block", "What Consilium uses it for"],
		["Workflow (states, transitions, role gates)", "Policy approvals and exceptions, sign-off chains"],
		["Workflow action record", "Immutable record of who approved what, and when"],
		["Assignment rule", "Escalation routing"],
		["Role, permission, user permission", "Committee membership, segregation of duties"],
		["Version (audit trail)", "Automatic field-level change history"],
		["Notification", "Alerts on state change or time-limit breach"],
		["Record type definition", "A new record type without writing a migration"],
		["Report, dashboard, web form", "Management reporting and intake forms"],
	], M, 1.75, 7.2, [3.3, 3.9], font_size=12, row_h=0.47, zebra=True)
	cx = 8.1
	cw = W - M - cx
	y = 1.75
	for h, b in [("No per-seat licence", "The objective set at the outset: run the platform on infrastructure the organisation already runs, with no per-seat licence of a commercial GRC product."),
	             ("Not forked", "The framework source stays untouched. **8 runtime patches** are applied at start-up, each doing nothing on Linux, so upstream updates keep applying."),
	             ("Portable by evidence", "A static code audit of the whole framework found **10 Windows blockers, 6 of them in test code**. The rest are patched and tested.")]:
		card(s, cx, y, cw, 1.5, TINT)
		tx(d, s, [{"t": h, "size": 15, "bold": True, "color": NAVY, "gap": 4}, {"t": b, "size": 12.5}], cx + 0.2, y + 0.12, cw - 0.4, 1.3)
		y += 1.65


# 13 — constraints
def constraints(d):
	s = frame(d, "The platform meets five hard enterprise constraints that the framework's standard installation cannot", "B",
	          "Sources: HANDOVER.md §2–4; README.md ('Current state', 'Requirements'); docs/delivery/DEPLOYMENT-READINESS.md §1–3; CLAUDE.md non-negotiable rules 1–7.",
	          "The framework's standard install assumes Linux, internet access, a git clone from GitHub, MariaDB and several POSIX-only tools. None of that works in a locked-down enterprise network. This slide shows each constraint, what we did about it, and the evidence. The honest caveat is in the Windows row. The Windows code paths are covered by tests that simulate Windows, but the product has never run on an actual Windows machine. That is a Phase 2 exit criterion.")
	table(d, s, [
		["Constraint", "Why the standard path fails", "What we built", "Evidence"],
		["**Installs with no internet**", "Assumes git clone from GitHub; the framework is not on the public package index", "One self-verifying bundle: wheels, framework, application, prebuilt assets, installer", "Air-gapped Rocky Linux 9: no route to the internet, 0 network lines in pip's log; verify.sh <<verify>>/<<verify>>, health <<health>>/<<health>>"],
		["**No compiler**", "Some dependencies publish no wheel", "Wheels built when the bundle is made, on a connected machine", "Runtime set: 139 wheels + 6 pure-Python sdists; the builder refuses anything that needs a compiler"],
		["**No package manager for the front end**", "Front-end build needs node and yarn", "Prebuilt asset bundle committed; libraries vendored and checksummed", "Verified with node absent from the path"],
		["**Windows and Linux from one tree**", "Standard tooling (bench, supervisor, nginx, gunicorn) is POSIX-only", "Cross-platform launcher of about 800 lines; pure-Python web server; fork-free worker", "<<compat_windows>> simulated-Windows tests pass. {{Not yet run on real Windows hardware}}"],
		["**PostgreSQL only**", "MariaDB-first", "PostgreSQL 16; no MariaDB-specific SQL", "About 190 framework tests run on PostgreSQL: 3 failures, none ours"],
	], M, 1.75, CW, [2.2, 3.0, 3.6, 3.53], font_size=11.5, row_h=[0.4, 0.88, 0.8, 0.7, 0.88, 0.7])


# 14 — architecture
def architecture(d):
	s = frame(d, "A conventional tiered architecture with no outbound network dependency in the delivered configuration", "B",
	          "Source: docs/product/04-architecture.md §2.1–2.3 (components), §4.2 (AI boundary rules), §9.2 (boundary table), §9.3 (exactly one scheduler); docs/guides/07-help-and-ai.md; docs/guides/09-administration.md §9.14 (Integrations).",
	          "The left box is everything inside the secure zone: a browser-only client, a pure-Python web tier, one application codebase, background workers and a single scheduler, and PostgreSQL, Redis and private file storage. Permission evaluation happens on the server for every path, so a custom screen cannot widen access. On the right is everything outside the trust boundary: the AI service, the document editor and horizon-scanning hand-offs, mail by SMTP or Microsoft Graph, the identity provider and the file drop. Each is optional and connected from one administrator screen, and none of the 64 requirements depends on any of them. The one operational rule to remember: exactly one scheduler process, or every job runs twice.")
	zx, zy, zw, zh = M, 1.75, 8.6, 4.95
	shape(s, "rect", zx, zy, zw, zh, "F7F8FA", line=NAVY, line_w=1.25)
	tx(d, s, "SECURE ZONE — air-gapped Linux server (production) or Windows workstation (development)", zx + 0.15, zy + 0.08, zw - 0.3, 0.3, base={"size": 10, "bold": True, "color": NAVY})
	tiers = [
		("Client", ["Portal screens (daily work)", "Workspace (administration)"]),
		("Web", ["Pure-Python web server", "Static assets served in-process"]),
		("Application", ["Permission check on every request", "Document engine", "Workflow engine", "Core services", "Module logic", "REST API"]),
		("Background", ["Job queues", "Workers", "Scheduler: exactly one"]),
		("Data", ["PostgreSQL 16", "Redis cache and queues", "Private file storage"]),
	]
	ty, th = zy + 0.48, 0.8
	for n, boxes in tiers:
		tx(d, s, n, zx + 0.15, ty, 1.2, th, base={"size": 11.5, "bold": True, "color": SLATE}, valign="middle")
		bx0, bw_all, g = zx + 1.35, zw - 1.5, 0.1
		bw = (bw_all - g * (len(boxes) - 1)) / len(boxes)
		for i, b in enumerate(boxes):
			hot = "exactly one" in b or "Permission" in b
			shape(s, "rect", bx0 + i * (bw + g), ty + 0.08, bw, th - 0.16, ACCENT if hot else NAVY, line=WHITE)
			tx(d, s, b, bx0 + i * (bw + g) + 0.05, ty + 0.08, bw - 0.1, th - 0.16, base={"size": 10.5, "color": WHITE, "bold": hot}, align="center", valign="middle")
		ty += th + 0.08
	ox = zx + zw + 0.35
	ow = W - M - ox
	tx(d, s, "OUTSIDE THE TRUST BOUNDARY", ox, zy, ow, 0.3, base={"size": 10, "bold": True, "color": MUTED})
	ey = zy + 0.36
	for h, b in [("AI service (optional)", "OpenAI-compatible; every request logged before it is sent"),
	             ("Doc AI and horizon scanning", "Browser hand-offs, identifiers only; logged"),
	             ("Mail: SMTP or Microsoft Graph", "Outbound notifications only"),
	             ("Identity provider", "OIDC or LDAP, authentication only"),
	             ("Import / export drop", "Nothing commits without human review")]:
		shape(s, "rect", ox, ey, ow, 0.76, WHITE, line="9AA5B5", line_w=1, dash="dash")
		tx(d, s, [{"t": h, "bold": True, "color": NAVY, "gap": 1}, {"t": b, "size": 10, "color": SLATE}], ox + 0.12, ey + 0.03, ow - 0.24, 0.7, base={"size": 11}, valign="middle")
		rule(s, zx + zw, ey + 0.38, 0.35, 0, "9AA5B5", 1, dash="dash")
		ey += 0.84
	tx(d, s, "No requirement among the 64 depends on anything outside the zone.", ox, ey - 0.02, ow, 0.4, base={"size": 10.5, "italic": True, "color": ACCENT, "bold": True})


# 15 — data model
def data_model(d):
	s = frame(d, "The data model marks every element as specified, decided or inferred, so reviewers know exactly what to challenge", "B",
	          "Sources: docs/product/02-data-model.md §1.1 (provenance marks), §2.2 (114 logical entities: 78 standalone + 36 child), §2.3 (M-1…M-4); docs/product/07-assumptions-and-gaps.md §4 (C-1…C-5); implemented counts measured on the demonstration site, <<measured>>.",
	          "Every entity and field in the data model carries a provenance mark. S means specified in a source document. D means decided by a stakeholder after the fact, and binding. I means inferred: we needed it to satisfy a requirement, but nobody asked for it. Every I item is a review point and is listed with its consequences in the assumptions document. On the right: the logical model defines 114 entities, and the implementation has <<ent_total>> across the four modules. Four structural decisions shape everything else.")
	y = 1.75
	for L, n, desc, ex, col in [
		("S", "Specified", "Named in a source requirement document.", "Committee formation request, charter, horizon scan", NAVY),
		("D", "Decided", "Settled by a stakeholder decision. Binding.", "Membership as its own dated record; one attestation engine; document version chain", NAVY2),
		("I", "Inferred", "In no source and not decided. **Every item is a review point.**", "Shared regulatory-requirement library (C-1); what restricted handling must block (C-3)", ACCENT),
	]:
		card(s, M, y, 6.2, 1.25)
		shape(s, "rect", M + 0.2, y + 0.22, 0.8, 0.8, col)
		tx(d, s, L, M + 0.2, y + 0.22, 0.8, 0.8, base={"size": 28, "bold": True, "color": WHITE}, align="center", valign="middle")
		tx(d, s, [{"t": n, "size": 14, "bold": True, "color": NAVY, "gap": 2}, {"t": desc, "gap": 3}, {"t": "e.g. " + ex, "color": SLATE, "size": 10.5}],
		   M + 1.2, y + 0.1, 4.85, 1.1, base={"size": 11.5}, valign="middle")
		y += 1.37
	tx(d, s, "Four structural decisions: membership is its own dated record · we hold the document body and version chain · four tagging dimensions are multi-valued · nothing keys off a state name",
	   M, 5.95, 6.2, 0.75, base={"size": 11, "color": SLATE, "italic": True})
	tx(d, s, "Implemented entities by module", 7.2, 1.75, 5.6, 0.35, base={"size": 12, "bold": True, "color": NAVY})
	e = d.facts["entities"]
	bar_chart(d, s, 7.1, 2.1, 5.75, 3.0, ["Core", "Policy", "Governance", "Escalation"],
	          [("Entities", [e["core"], e["policy"], e["governance"], e["escalation"]])],
	          colours=[NAVY], label_size=12, cat_size=12, reverse=True, gap=55, vmax=66)
	kpi(d, s, 7.2, 5.1, 1.8, "<<ent_logical>>", "logical entities in the model", size=28, lh=0.5)
	kpi(d, s, 9.1, 5.1, 1.8, "<<ent_total>>", "entities implemented", size=28, lh=0.5)
	kpi(d, s, 11.0, 5.1, 1.8, "<<ent_tables>>", "database tables", size=28, lh=0.5)


# 16 — portal and workspace
def portal_and_workspace(d):
	s = frame(d, "Daily work happens in purpose-built portal screens and administration in the workspace, with one permission model behind both", "B",
	          "Sources: docs/product/04-architecture.md §3; docs/guides/01-finding-your-way.md; docs/guides/09-administration.md §9.5 (branding); delivery-team change log <<measured>> (framework name removed; out-of-scope features hidden).",
	          "The interface is hybrid. People doing daily work use the portal. Administrators use the framework's workspace for roles, reference data, workflow configuration and the report builder, because rebuilding those screens is expensive and is where audit findings come from. Both call the same permission-checked API. The product is now white-labelled: the framework's name is gone from the interface, and an administrator sets the organisation's name, logo, colours and typeface in one record with no deployment. Out-of-scope framework features are hidden.")
	shot(d, s, "home", M, 1.75, 7.4, 4.8)
	x = 8.2
	tx(d, s, [
		{"t": "Portal — for daily work", "size": 14, "bold": True, "color": NAVY, "gap": 3},
		{"t": "Menus by area — Home, My work, Governance, Policies, Escalations, Insights — and search from any page", "bullet": True, "gap": 3},
		{"t": "Every table pages, sorts and searches in the database, and exports to CSV", "bullet": True, "gap": 3},
		{"t": "Light and dark themes; text-size control; a Help assistant on every page", "bullet": True, "gap": 10},
		{"t": "Workspace — for administration", "size": 14, "bold": True, "color": NAVY, "gap": 3},
		{"t": "Roles, reference data, workflow and rule configuration, report builder, audit views", "bullet": True, "gap": 10},
		{"t": "Made to look like the organisation's own", "size": 14, "bold": True, "color": NAVY, "gap": 3},
		{"t": "Framework name removed from the interface", "bullet": True, "gap": 3},
		{"t": "Name, logo, colours, typeface and banner set by an administrator, with no release", "bullet": True, "gap": 3},
		{"t": "Out-of-scope framework features hidden", "bullet": True, "gap": 10},
		{"t": "Hiding is presentation; the server's refusal is the control.", "italic": True, "color": ACCENT, "bold": True},
	], x, 1.75, W - M - x, 4.95, base={"size": 11.5})


# 17 — UX redesign
def ux_redesign(d):
	s = frame(d, "The portal was redesigned around how people work: one header, menus shaped by role, and search from any page", "B",
	          "Sources: consilium_core/navigation.py (cns_nav), consilium_core/search.py, templates/base_portal.html; consilium_core/tests/test_navigation.py (11), test_global_search.py (9); scripts/browser_journeys.py (<<journeys>>/<<journeys>>); docs/delivery/EPICS.md E35.",
	          "After the product owner's review, the header was rebuilt. The top row holds the brand, one search box, text size, theme and the user menu. The second row holds seven menus: Home, My work, Governance, Policies, Escalations, Insights and Admin. Each opens a panel of pages and ready-made filtered views, each with a line saying what it is for. Menus are filtered by role and read permission, so nobody is offered a dead end. Search reaches forums, policies and escalations from any page, through the same permission checks as the lists, so a confidential document or sensitive matter never appears to someone not cleared. Lists export to CSV, empty states say what to do next, and the menus work from the keyboard and on a phone.")
	g3 = 0.25
	w3 = (CW - g3 * 2) / 3
	h3 = w3 * 900 / 1440
	for i, (k, cap) in enumerate([("nav_menu", "A menu opens a panel of pages and ready-made views, each explained"),
	                              ("search", "Search from any page, grouped by forums, policies and escalations"),
	                              ("mywork", "My work: approvals described in words, not codes")]):
		shot(d, s, k, M + i * (w3 + g3), 1.75, w3, h3, cap)
	by = 1.75 + h3 + 0.45
	bh, bw = 6.7 - by, (CW - 0.3) / 4
	for i, (h, t) in enumerate([("Menus by role", "Home, My work, Governance, Policies, Escalations, Insights, Admin; nobody is offered a dead end"),
	                            ("Search is safe", "\"/\" or Ctrl/Cmd+K; results come only from records the viewer may read"),
	                            ("Lists that work", "Filter, sort, search and Export CSV on every list; empty states say what to do next"),
	                            ("Keyboard, phone, clarity", "Menus by keyboard; slide-out on phones; times show their zone; plain names")]):
		x = M + i * (bw + 0.1)
		card(s, x, by, bw, bh, TINT)
		tx(d, s, [{"t": h, "bold": True, "color": NAVY, "size": 12, "gap": 2}, {"t": t, "size": 10.5}], x + 0.12, by + 0.06, bw - 0.24, bh - 0.1)


# 18 — integrations
def integrations(d):
	s = frame(d, "One administrator screen connects the organisation's own systems: AI, the document editor, horizon scanning, mail and sign-on", "B",
	          "Sources: consilium_core/integrations/ (admin.py, external_tools.py, graph_mail.py); www/integrations, www/doc-ai, www/horizon-scanning; consilium_core/tests/test_integrations.py (31), test_graph_mail.py (20); docs/delivery/DEPLOYMENT-READINESS.md 'What the organisation provides'; docs/delivery/EPICS.md E36.",
	          "Everything that connects to another system is on one screen, Admin, Integrations, for administrators only. The AI card takes an OpenAI-compatible endpoint and a key that is never shown back, and tests the connection through the same audited client the product uses. Doc AI is the organisation's document editor: Open in Doc AI checks access, logs the hand-off and sends only identifiers, never the file; until an address is set it explains that it is not connected yet. Horizon scanning is a link to the external platform with a configurable label. Mail goes by SMTP or, where servers may not speak SMTP, by Microsoft Graph with application credentials. Single sign-on shows the redirect address to give the identity team. Nothing here needs a code change.")
	sw = (CW - 0.3) / 2
	sh = sw * 900 / 1440
	shot(d, s, "integrations", M, 1.75, sw, sh)
	shot(d, s, "docai_modal", M + sw + 0.3, 1.75, sw, sh)
	cy = 1.75 + sh + 0.2
	ch, cw = 6.7 - cy, (CW - 0.4) / 5
	for i, (h, b) in enumerate([("AI", "OpenAI-compatible endpoint; write-only key; Test connection; every call logged"),
	                            ("Doc AI", "Open a policy in the document editor; access-checked, logged, identifiers only"),
	                            ("Horizon scanning", "A link to the external platform; label and roles configurable"),
	                            ("Mail", "SMTP, or Microsoft Graph with app-only credentials; send a test to me"),
	                            ("Sign-on", "Shows the redirect URI to register; OIDC or LDAP set at install")]):
		x = M + i * (cw + 0.1)
		card(s, x, cy, cw, ch, TINT)
		tx(d, s, [{"t": h, "bold": True, "color": NAVY, "size": 12, "gap": 2}, {"t": b, "size": 10}], x + 0.12, cy + 0.06, cw - 0.24, ch - 0.1, base={"size": 10})


# 20 — journey overview
def journey(d):
	s = frame(d, "One journey, from forming a committee to proving a year later what happened, runs on one set of records", "C",
	          "Source: docs/delivery/REQUIREMENTS-COVERAGE.md §3 (demonstration records on the rebuilt demo site, queried <<measured>>); docs/guides/ chapters 3–5.",
	          "This is the storyline for the walkthrough. Six steps, each with the control that makes it defensible and a demonstration record you can open in the product. The next five slides take them in turn. The point to land is continuity: the forum formed in step one approves the policy in step three and receives the escalation in step four. In the audit step, all of that can be read back as it stood on any date.")
	chevrons(d, s, ["1  Form a forum", "2  Review compliance", "3  Run the policy lifecycle", "4  Escalate an issue", "5  Close with evidence", "6  Audit as at any date"],
	         M, 1.8, CW, 0.75, size=11.5)
	cols = [
		("Request evaluated on five criteria, approval steps from a configured route; approval creates a draft forum", "CFR-2026-00001 → FRM-2026-00014 Data Governance Council", "Approve stays disabled until nothing blocks it"),
		("Compliance reviewer records a decision; a change to a watched field reopens review", "Operational Risk Committee: watched-field change → review FCR-2026-00006", "A review is its own record and cannot be edited"),
		("Draft → Review → Approved → Published → Implemented → Retired", "Risk Appetite Framework published after 2 approval decisions", "Gates on every route, including the one we found open"),
		("Matrix sets severity and pathway; time limits run", "ESC-2026-00007: severity High, breached 31 Jul 2026, raised", "Sensitive matters invisible to anyone not cleared"),
		("Closure record plus completed response template", "ESC-2026-00006 closed, tracked externally", "Refused until both are done"),
		("Membership, votes, versions and refusals, as at any date", "<<demo_meetings>> meetings, <<demo_minute_versions>> minute versions, <<demo_charter_versions>> charter versions", "Nothing is deleted"),
	]
	n, gap = 6, 0.06
	cw = (CW - gap * (n - 1)) / n
	for i, c in enumerate(cols):
		x = M + i * (cw + gap)
		card(s, x, 2.7, cw - 0.04, 4.0)
		y = 2.8
		for k, t in enumerate(c):
			tx(d, s, ["What happens", "Demo record", "Control"][k].upper(), x + 0.12, y, cw - 0.28, 0.25, base={"size": 9, "bold": True, "color": ACCENT if k == 2 else MUTED})
			tx(d, s, t, x + 0.12, y + 0.25, cw - 0.28, 1.0, base={"size": 11, "color": NAVY if k == 2 else INK, "bold": k == 2})
			y += 1.3


def walk(d, title, key, callouts, evidence, source, notes):
	s = frame(d, title, "C", source, notes)
	sx, sw, sh = M, 7.35, 4.95
	shot(d, s, key, sx, 1.75, sw, sh)
	x = sx + sw + 0.35
	w = W - M - x
	y = 1.75
	for i, c in enumerate(callouts):
		badge(d, s, i + 1, x, y + 0.02, 0.32)
		tx(d, s, c, x + 0.45, y, w - 0.45, 0.95, base={"size": 12.5})
		y += 0.93
	eh = 6.7 - y - 0.05
	card(s, x, y + 0.05, w, eh, TINT)
	tx(d, s, [{"t": "EVIDENCE", "size": 9, "bold": True, "color": MUTED, "gap": 3}] + [{"t": e, "gap": 3} for e in evidence],
	   x + 0.15, y + 0.13, w - 0.3, eh - 0.15, base={"size": 11})


# 21–24 — walkthroughs
def walkthroughs(d):
	cov = d.facts["coverage"]
	g8 = (" The honest gap that remains: the route cannot yet vary by forum type or materiality (G-8)." if cov.get("G-8") == "d" else "")
	walk(d, "Forming a committee is evaluated against five criteria, and approval stays disabled while anything is outstanding", "formation",
	     ["**Guided request:** required fields, guidance and draft save. The governance office confirms the request is complete.",
	      "**Five criteria assessed:** coverage gap, duplication, escalation pathway, framework alignment, resource feasibility.",
	      "**Approval steps come from a configured route,** sequential order enforced, role queues, changed without a release.",
	      "**A bypass needs a recorded authorisation,** waives only its own step, and never by the step's own holder."],
	     ["62 formation tests (27 engine, 35 portal).", "Demo requests at every stage, draft to approved.", "A charter challenge blocks approval (G-7)."],
	     "Sources: docs/guides/03-governance.md §3.4–3.5; docs/delivery/REQUIREMENTS-COVERAGE.md G-5, G-7, G-8, G-17 (tests and demo records).",
	     "Step one. A requester fills in the guided form. The governance office checks completeness, runs the overlap check against the existing inventory, and assesses the five criteria. Approval steps are raised from a configured route. The Approve button stays disabled, and lists what is outstanding, until every criterion is assessed and every step decided. A bypass needs a recorded exception authorised by the Head of Risk Governance. Approval creates the forum in Draft. An open charter challenge now blocks approval, and steps are decided in order." + g8)
	walk(d, "A forum's compliance standing stays current: changing a watched field sends it back for review automatically", "forum",
	     ["**Compliance decision recorded:** Compliant, Non-Compliant (reasons required), Not Applicable, or returned to its creator.",
	      "**The review is its own record** and cannot be edited afterwards.",
	      "**Watched fields are configuration:** a change to, say, the mandate moves the forum back to pending and notifies compliance.",
	      "**Forum page shows everything in one place:** seats, charter, meetings, motions, decisions, approved documents and the connections diagram."],
	     ["FRM-2026-00006: watched-field change → review FCR-2026-00006.", "FRM-2026-00007 recorded Non-Compliant.", "43 membership and voting tests."],
	     "Sources: docs/guides/03-governance.md §3.1–3.3, §3.6; docs/delivery/REQUIREMENTS-COVERAGE.md G-4, G-6, G-11, G-13, §1.1 (screen map).",
	     "Step two. The Compliance Reviewer records a decision on the forum. Each decision is its own record and cannot be edited later. The important behaviour is the watched fields. When someone changes a designated field, such as the mandate, the forum drops back to Pending and compliance is notified. The list of watched fields is configuration, so compliance can change it without a release. The forum page also shows how the forum connects to its parent and child committees.")
	walk(d, "A policy moves through a gated lifecycle and cannot be published without its complete approval set, on any route", "policy",
	     ["**Six phases, each move limited to its role:** policy owner submits; the policy office approves, publishes and retires.",
	      "**Gates checked on every phase change:** complete approval chain, current version, applicability. A written exception is the only bypass.",
	      "**Reopened documents start a fresh approval cycle.** The previous cycle's approvals no longer count (fixed).",
	      "**Version chain held here:** each upload is a new immutable version. Revert writes a new version."],
	     ["10 publication-gate tests, including menu and direct-write refusal.", "GDOC-00002 Risk Appetite Framework published after 2 decisions.", "68 portal-action tests, incl. 15 on the approval chain."],
	     "Sources: docs/guides/04-policies.md; docs/delivery/REQUIREMENTS-COVERAGE.md P-9, P-25 (TestPublicationRefusal ×7, TestGatesOnEveryRoute ×3); policy/tests/test_portal_actions.py.",
	     "Step three. The policy lifecycle runs from Draft to Retired, and each move is limited to the role responsible for it. The important control is P-25, no publication without the full approval set. Lifecycle gates are configuration. Since the fix described in section D, they run on every phase change, whatever route it comes from. Reopened documents cannot reuse the previous cycle's approvals; that was a real defect we found and fixed. Every one of these actions is now on the policy page itself, POST-only, with the failing gate named before you act. A gate exception is approved by the policy office, never by the person asking.")
	walk(d, "Escalations are routed by an approved matrix, timed against limits, and invisible to anyone not cleared for sensitive matters", "escalation",
	     ["**Matrix-driven severity and pathway.** The rule that fired is recorded; a manual override is visible as such.",
	      "**Time limits run on a business calendar.** A breach raises severity and notifies, once.",
	      "**Sensitive matters are hidden** from lists, counts, search, reports and the API. A link reads like a record that does not exist.",
	      "**No closure without its outcome:** a closure record and the completed response template are both required."],
	     ["19 routing and closure tests; 12 sensitivity tests.", "ESC-2026-00007 breached 31 Jul 2026 → raised.", "Portal actions: 43 tests (raise, work, approve, close); time in each status measured against targets."],
	     "Sources: docs/guides/05-escalations.md; docs/delivery/REQUIREMENTS-COVERAGE.md E-4, E-10, E-13, E-16 (tests, demo records); escalation/tests/test_portal_actions.py.",
	     "Steps four and five together. The escalation matrix sets severity and the forum pathway from the facts of the matter, and records which rule fired. Clocks run against configured time limits. A breach raises the matter and notifies once. A defect that re-breached every day was found and fixed. Sensitive escalations are not just hidden on screen. They are excluded from every read path, including counts and the API. Closure needs both the closure record and the completed response template, and a confirmation. Matters are raised, worked, taken from a role or group queue, and closed on the portal; forums and matters can be reverted with a reason.")


# 25 — audit as at
def audit_as_at(d):
	s = frame(d, "A year later, the record shows who sat, who voted, what was approved and what was refused, as at any date", "C",
	          "Sources: docs/product/02-data-model.md §2.3 (M-1, M-2); docs/product/05-glossary.md §D; docs/OPERATIONS.md §A; docs/delivery/REQUIREMENTS-COVERAGE.md G-9, G-13, G-15, G-16 (demo counts, tests).",
	          "Step six is the reason the system exists: a year later, someone asks what happened. Membership is a dated record, so the forum as it stood on the day is a query. Votes are recorded per entitled voter, with quorum stored at the time. Document bodies are immutable versions with a hash. Refusals are logged. Be clear about what is not yet proven. The retention engine is built and tested, and a daily job flags records due for disposal, but no record on the demo site is under retention yet, and an approved disposal cannot yet be carried out from a screen.")
	shot(d, s, "history", M, 1.75, 5.6, 3.6)
	x = M + 5.9
	w = W - M - x
	cw = (w - 0.2) / 2
	for i, (q, a, e) in enumerate([
		("Who sat on the forum?", "Membership is a dated record; seats can be held by position; delegations carry validity windows.", "Composition on any past date is a query"),
		("Who voted, and was there quorum?", "One vote row per entitled voter; quorum calculated and stored when the decision is taken.", "Later membership changes do not rewrite it"),
		("What did the document say?", "Immutable version chain with content hash. Revert writes a new version and is itself audited.", "<<demo_minute_versions>> minute versions; <<demo_charter_versions>> charter versions"),
		("What was refused, and why?", "Governance Refusal Log; field-level change history; exception authorisations for any bypass.", "Refusals logged even when rolled back"),
	]):
		cx, cy = x + (i % 2) * (cw + 0.2), 1.75 + (i // 2) * 1.85
		card(s, cx, cy, cw, 1.7)
		tx(d, s, [{"t": q, "bold": True, "color": NAVY, "size": 12.5, "gap": 4}, {"t": a, "gap": 4}, {"t": e, "color": ACCENT, "bold": True, "size": 10.5}],
		   cx + 0.15, cy + 0.1, cw - 0.3, 1.55, base={"size": 11})
	card(s, M, 5.55, CW, 1.15, ACCENT_T)
	tx(d, s, "**Not yet proven end to end:** the retention and legal-hold engine is built (19 tests pass) and a daily job flags records due for disposal, but no demo record is under retention, carrying out an approved disposal and releasing a hold have no screen, and write-once storage is an open infrastructure decision. Until that decision, describe the control as **tamper-evident with restricted write access**, not write-once. Every record now exports as an evidence pack with a SHA-256 manifest.",
	   M + 0.2, 5.6, CW - 0.4, 1.05, base={"size": 11.5}, valign="middle")


# 27 — coverage chart
def coverage_chart(d):
	v = d.values
	mods = [("Governance", "G"), ("Policy", "P"), ("Escalation", "E"), ("Supplementary", "O")]
	cats = [f"{n} ({ {'G': 19, 'P': 26, 'E': 19, 'O': 7}[p] })" for n, p in mods]
	missing = (f"and {v['missing']} missing one mandatory clause" if v["missing"] else "and none missing a mandatory clause")
	c_ids = ids_in_class(d, "c", MANDATORY)
	d_note = (f"The {v['missing_word']} class-d rows each miss one clause, named on the next slide." if v["missing"] else "No class-d row remains.")
	s = frame(d, f"All 64 mandatory requirements re-measured on the final build: <<full>> fully reachable, <<partly>> partly, {missing}", "D",
	          "Source: docs/delivery/REQUIREMENTS-COVERAGE.md §1.2 (classes), §2 (summary), final measurement <<measured>> against release <<release>> and the demo site; the 17 Sep baseline is the same method before the final wave. Classes: a = portal screen; b = workspace, configuration or job by design; c = partly reachable; d = not implemented in whole or in a mandatory clause.",
	          "This is the final measurement, with the same method and classes as the 17 September baseline shown in the box. A requirement counts as fully reachable only if a user can reach it through a screen, or through configuration where that is the design. Policy moved most: from 3 fully reachable to <<P_full>> of 26, because every policy action is now on the portal and every notice is templated. " + d_note + " Several were re-graded downward on a stricter reading, not because code regressed.")
	series = [("a  Portal screen", "a"), ("b  Workspace / config by design", "b"), ("c  Partly reachable", "c"), ("d  Not implemented (mandatory clause)", "d")]
	bar_chart(d, s, M, 1.75, 8.1, 4.4, cats, [(name, [v[f"{p}_{k}"] for _, p in mods]) for name, k in series],
	          stacked=True, colours=[CLASS_COLOURS[k] for k in "abcd"], label_pos="ctr", label_size=12, label_bold=True,
	          label_colour=WHITE, label_format="0;;;", cat_size=12, reverse=True, legend=True, legend_size=11, gap=45, vmax=26, vmin=0)
	tx(d, s, "Mandatory total:  **a <<mand_a>>  ·  b <<mand_b>>  ·  c <<mand_c>>  ·  d <<mand_d>>**  = 64", M, 6.25, 8.1, 0.35, base={"size": 12, "color": NAVY}, align="center")
	x = 8.95
	w = W - M - x
	c_line = (f"**Class c (<<mand_c>>):** {topics(d, c_ids)}." if c_ids else "**Class c:** none.")
	tx(d, s, [
		{"t": "What the measurement says", "size": 14, "bold": True, "color": NAVY, "gap": 6},
		{"t": "**Policy closed its gap:** <<P_full>> of 26 now in class a or b; every policy action is on the portal.", "bullet": True, "gap": 6},
		{"t": c_line, "bullet": True, "gap": 6},
		{"t": "**64 of 64** have a direct, passing test; for <<partial_n>> the tests cover only part of the requirement.", "bullet": True, "gap": 6},
		{"t": "A passing test proves only what it exercises: the missing clauses of class d are untested by definition.", "bullet": True, "gap": 6},
	], x, 1.75, w, 3.4, base={"size": 11.5})
	shape(s, "rect", x, 5.2, w, 1.5, TINT)
	b0 = d.facts["coverage_baseline_17sep"]
	tx(d, s, [{"t": "17 SEPTEMBER BASELINE (BEFORE THE FINAL WAVE)", "size": 9.5, "bold": True, "color": MUTED, "gap": 4},
	          {"t": f"a {b0['a']}  ·  b {b0['b']}  ·  c {b0['c']}  ·  d {b0['d']}", "size": 13, "bold": True, "color": NAVY, "gap": 3},
	          {"t": f"Same method, same classes: {b0['a'] + b0['b']} fully reachable then, <<full>> now", "size": 10, "color": MUTED}],
	   x + 0.15, 5.28, w - 0.3, 1.35, valign="middle")


# 28 — heatmap
def heatmap(d):
	d_ids, c_ids = ids_in_class(d, "d"), ids_in_class(d, "c")
	names = title_topics(d)
	if names:
		title = "Requirement by requirement, what remains is narrow: " + join_words(names)
	else:
		title = f"Requirement by requirement: no requirement is missing a clause, and {len(c_ids)} are partly reachable"
	reading = "**Reading the tiles:** d = " + (("one missing clause each: " + topics(d, d_ids)) if d_ids else "none") + \
	          ". c = " + (topics(d, c_ids) if c_ids else "none") + "."
	s = frame(d, title, "D",
	          "Source: docs/delivery/REQUIREMENTS-COVERAGE.md §3 (per-requirement 'Reachable' column) and §4 (gaps), final measurement <<measured>>.",
	          "Each tile is one requirement, coloured by its final measured class. "
	          + (("The orange tiles each miss one clause: " + topics(d, d_ids) + ". ") if d_ids else "No tile is orange: every requirement is reachable at least in part. ")
	          + (("The grey tiles are partly reachable: " + topics(d, c_ids) + ".") if c_ids else ""))
	cov = d.facts["coverage"]
	gx = M + 1.55
	gw = CW - 1.55
	tg, th = 0.05, 0.72
	tw = (gw - tg * 25) / 26
	y = 1.85
	for name, p, n in [("Governance", "G", 19), ("Policy", "P", 26), ("Escalation", "E", 19), ("Supplementary", "O", 7)]:
		tx(d, s, [{"t": name, "bold": True, "color": NAVY, "gap": 0}, {"t": f"{n} requirements", "size": 9.5, "color": MUTED}], M, y, 1.5, th, base={"size": 12}, valign="middle")
		for i in range(1, n + 1):
			col = CLASS_COLOURS[cov[f"{p}-{i}"]]
			x = gx + (i - 1) * (tw + tg)
			shape(s, "rect", x, y, tw, th, col)
			label(d, s, [], x, y, tw, th, align="center", paragraphs=[[(f"{p}-", {"size": 8, "color": WHITE})], [(str(i), {"size": 11, "bold": True, "color": WHITE})]])
		y += th + 0.22
	lx = M
	for (k, t), lw in zip([("a", "Portal screen"), ("b", "Workspace / config by design"), ("c", "Partly reachable: a step has no screen"), ("d", "Not implemented in whole or a mandatory clause")],
	                      [2.2, 3.1, 3.55, 3.45]):
		shape(s, "rect", lx, 5.68, 0.26, 0.26, CLASS_COLOURS[k])
		tx(d, s, f"**{k}**  {t}", lx + 0.34, 5.66, lw - 0.4, 0.3, base={"size": 11}, valign="middle")
		lx += lw
	tx(d, s, reading, M, 6.1, CW, 0.66, base={"size": 10.5, "color": SLATE})


# 29 — tests & quality
def quality(d):
	s = frame(d, "Quality evidence is layered, and every figure comes from a run, not an assertion", "D",
	          "Sources: docs/delivery/REQUIREMENTS-COVERAGE.md §1 (final run: <<tests_run>> tests, OK, <<tests_seconds>> s on a clean site; 1372 before the last round; 780 on 17 Sep); docs/delivery/DEPLOYMENT-READINESS.md (722; verify.sh <<verify>>/<<verify>>); docs/delivery/SESSION-SUMMARY.md; README.md (293, Core only).",
	          "Four layers of evidence. Application tests: <<tests_run>> run against a real PostgreSQL database on a clean site, and all pass. During the last round our own state-name checker caught one rule break in new code before release; that is what the checks are for. The interface sweep makes <<ui_sweep>> checks across the portal, signed in and out, for dead links, missing assets and leftover framework branding. Browser journeys drive a real browser, including the menus by keyboard, search and the phone layout. The toolchain has <<pytest>> tests, <<compat_windows>> of which simulate Windows. The chart shows how the suite grew at each point it was recorded. Every portal page now has its own page-context test.")
	K = [("<<tests_passed>> / <<tests_run>>", "application tests pass on PostgreSQL, on a clean site: 0 failures, 0 errors"),
	     ("<<ui_sweep>> / <<ui_sweep>>", "interface regression checks: every portal page, signed in and out, with no dead links or missing assets"),
	     ("<<journeys>> / <<journeys>>", "browser journeys, incl. menus by keyboard, search and the phone layout"),
	     ("<<pytest>> / <<pytest>>", "toolchain tests, <<compat_windows>> of them simulating Windows, plus the deployment kit")]
	kw = (CW - 0.6) / 4
	for i, (val, cap) in enumerate(K):
		x = M + i * (kw + 0.2)
		card(s, x, 1.75, kw, 1.9)
		kpi(d, s, x + 0.2, 1.8, kw - 0.4, val, cap, size=30, lh=1.0)
	tx(d, s, "Application test suite at each recorded measurement", M, 3.9, 7.2, 0.35, base={"size": 12, "bold": True, "color": NAVY})
	hist = d.facts["tests"]["history"] + [["Release " + d.facts["release"], d.facts["tests"]["run"]]]
	bar_chart(d, s, M, 4.2, 7.3, 2.55, [h[0] for h in hist], [("Tests", [h[1] for h in hist])], horizontal=False,
	          colours=[NAVY], label_size=11, cat_size=10, gap=50, vmax=round(d.facts["tests"]["run"] * 1.135 / 50) * 50)
	x = 8.2
	tx(d, s, [
		{"t": "Checks that fail the build", "size": 13, "bold": True, "color": NAVY, "gap": 4},
		{"t": "Any CDN reference; any package-manager step", "bullet": True, "gap": 2},
		{"t": "Vendored files that do not match their checksums", "bullet": True, "gap": 2},
		{"t": "Any client-identifying content", "bullet": True, "gap": 2},
		{"t": "Any logic branching on a workflow state name", "bullet": True, "gap": 8},
		{"t": "What changed in the final wave", "size": 13, "bold": True, "color": NAVY, "gap": 4},
		{"t": "Every portal page has a page-context test, including refusal of a reader without access", "bullet": True, "gap": 2},
		{"t": "Tests run on a separate clean site; the demo site holds no test rows", "bullet": True, "gap": 2},
	], x, 3.9, W - M - x, 2.85, base={"size": 11})


# 30 — defects
def defects(d):
	s = frame(d, "Loading a realistic organisation exposed nine defects that the passing test suite had missed. All are fixed and guarded by regression tests", "D",
	          "Sources: regression-test docstrings in apps/consilium/consilium/{governance,policy,escalation}/tests/test_regressions.py; docs/delivery/REQUIREMENTS-COVERAGE.md §1, P-25; delivery-team summary 18 Sep 2026 (9 defects, 21 regression tests). Selection shown; descriptions paraphrased.",
	          "This is the most important lesson in the deck. Before we loaded realistic data, every test passed. That was true, and it was not enough. Tests exercise what engineers imagine. A realistic organisation exercises what users will actually do. The worst of the nine was a control failure: the workspace's own workflow menu could publish a policy with no approvals. Another reused the previous cycle's approvals. One was a PostgreSQL divergence that stopped any document being marked implemented. All are fixed, each with a regression test, and realistic-data runs are now part of how we verify.")
	for i, (val, cap) in enumerate([("<<demo_personas>>", "role-based personas"), ("<<demo_forums>>", "forums, board to working group"),
	                                 ("<<demo_documents>>", "policies in every lifecycle phase"), ("<<demo_escalations>>", "escalations in every state")]):
		y = 1.75 + i * 1.05
		card(s, M, y, 2.6, 0.95)
		tx(d, s, val, M + 0.15, y, 0.9, 0.95, base={"size": 28, "bold": True, "color": NAVY}, valign="middle")
		tx(d, s, cap, M + 1.05, y, 1.45, 0.95, base={"size": 11, "color": SLATE}, valign="middle")
	tx(d, s, "plus attestation campaigns, meetings, motions and votes", M, 6.0, 2.6, 0.6, base={"size": 10.5, "color": MUTED, "italic": True})
	ctl = {"t": "Control", "bold": True, "color": ACCENT}
	table(d, s, [
		["Defect found", "What could have happened", "Type"],
		["Workspace workflow menu and direct writes skipped publication gates", "**A policy published with no approval chain** (P-25)", ctl],
		["Approvals matched to steps by name only", "A reopened policy republished on **last cycle's approvals**", ctl],
		["Role-based step took the first database row", "Approval assigned to a **disabled account or the built-in administrator**", ctl],
		["Publication gate used a query PostgreSQL refuses", "**No document could be marked implemented**", "Database divergence"],
		["Breached matter restarted its clock on save", "The same matter **breached again every day**", "Reliability"],
		["An unticked box read as 'not given'", "A seat could not be made non-voting; **vote entitlement wrong**", "Data integrity"],
		["Nothing wrote the meeting's minutes link", "**Minutes could not be kept** against a meeting", "Data integrity"],
		["'Opened on' took the browser's clock", "Dates **hours out** for users in other time zones", "Data integrity"],
	], 3.35, 1.75, W - M - 3.35, [3.6, 3.75, 2.13], font_size=11, row_h=[0.38] + [0.5] * 8)
	card(s, 3.35, 6.25, W - M - 3.35, 0.5, ACCENT_T)
	tx(d, s, "**So what:** 'the tests pass' was true and not enough. Runs with realistic data are now part of how we verify.", 3.5, 6.25, W - M - 3.65, 0.5, base={"size": 11.5}, valign="middle")


# 31 — controls
def controls(d):
	s = frame(d, "We tried to break the three controls leadership cares most about. All three now hold on every route", "D",
	          "Sources: docs/delivery/REQUIREMENTS-COVERAGE.md P-1, P-13, P-19, P-25, E-16; policy/tests/test_regressions.py (TestGatesOnEveryRoute); policy/tests/test_handling.py; escalation/tests/test_sensitivity.py.",
	          "Three controls. First, publication approval. We found the workspace's workflow menu and direct API writes both skipped the gates. That is fixed: gates now run on every phase change. Three tests attempt each route, and the proper route still works. Second, sensitive escalations. These are excluded on every read path: lists, counts, search, reports and the API. A link to one reads the same as a link to nothing. Third, confidential documents. On 17 September the confidentiality flags were display-only, so anyone with read access could open and download a confidential document. That is now enforced on every path, attachments and version bodies included, with a view-only in-portal viewer. Thirty-two tests attack it through the API.")
	C = [
		("Publication approval", "P-25", "FIXED", ["**Found:** the workspace's workflow menu and direct writes skipped the gates, so a document could be published with no approval chain.",
		                                          "**Now:** gates run on every phase change, whatever the route. A written exception still works.",
		                                          "**Tested:** menu refused, direct write refused, proper route publishes; plus 7 refusal tests."]),
		("Sensitive escalations", "E-16", "HOLDS", ["**Control:** permission hooks on the matter and its three child records; a dedicated access role.",
		                                           "**Holds on:** lists, counts, search, reports and the API. A link reads like a record that does not exist.",
		                                           "**Tested:** 12 sensitivity tests, including the API list and named people seeing their own matters."]),
		("Confidential documents", "P-1, P-13, P-19", "FIXED", ["**Found (17 Sep):** the view, download, print and share flags were display-only, so attachments were readable by anyone with read access.",
		                                                       "**Now:** read, list, download, print and share refused per flag on every path, attachments and version bodies included; a view-only in-portal viewer.",
		                                                       "**Tested:** 32 handling tests through the API, plus the viewer page."]),
	]
	cw = (CW - 0.6) / 3
	for i, (h, rid, st, items) in enumerate(C):
		x = M + i * (cw + 0.3)
		card(s, x, 1.75, cw, 0.95, NAVY)
		tx(d, s, [{"t": h, "size": 16, "bold": True, "color": WHITE, "gap": 0}, {"t": rid, "size": 11, "color": ICE}], x + 0.2, 1.8, cw - 1.7, 0.85, valign="middle")
		shape(s, "rect", x + cw - 1.45, 2.0, 1.25, 0.45, "2E8B57", line=WHITE)
		tx(d, s, st, x + cw - 1.45, 2.0, 1.25, 0.45, base={"size": 11, "bold": True, "color": WHITE}, align="center", valign="middle")
		card(s, x, 2.7, cw, 3.0)
		tx(d, s, [{"t": t, "gap": 10} for t in items], x + 0.2, 2.88, cw - 0.4, 2.75, base={"size": 12.5})
	card(s, M, 5.9, CW, 0.8, ACCENT_T)
	tx(d, s, "**How we test a control:** by attacking every route to the action, not just the intended one: the workspace menu, a direct API write, the portal action and the file download.",
	   M + 0.2, 5.9, CW - 0.4, 0.8, base={"size": 12.5}, valign="middle")


# 32 — configuration proof
def configuration_proof(d):
	s = frame(d, "We tested the claim that a new approval step is configuration, not code: a Legal Review stage was added with no release", "D",
	          "Source: docs/guides/images/manifest.json and verification screenshots (captured on the demo site, document GDOC-00016); docs/guides/09-administration.md §9.11 and docs/OPERATIONS.md §B (worked example: adding a workflow state).",
	          "This slide is proof of design principle one. An administrator added a Legal Review stage between Review and Approved on the policy lifecycle, entirely through configuration. First, the stage and its transitions were added in the workflow. Second, one flag row says what the stage means; without it the system refuses to move a document into the stage rather than guessing, and the refusal names the missing row. Third, the document moved into Legal Review, and the page's actions updated themselves. No code changed and nothing was deployed.")
	cw = (CW - 0.5) / 3
	for i, (k, cap) in enumerate([("cfg1", "1  The Legal Review stage and its transitions are added to the workflow, as configuration"),
	                              ("cfg2", "2  One flag row says what the stage means: editable, active, requires review"),
	                              ("cfg3", "3  The document moves into Legal Review; the page's actions update themselves")]):
		x = M + i * (cw + 0.25)
		shot(d, s, k, x, 1.8, cw, cw * 900 / 1440)
		tx(d, s, cap, x, 1.9 + cw * 900 / 1440, cw, 0.7, base={"size": 12, "bold": True, "color": NAVY})
	card(s, M, 5.3, CW, 1.35, TINT)
	tx(d, s, [{"t": "**What this proves:** renaming a state or inserting an approval step is an administrator's change, made in minutes and recorded in the audit trail. It needs no release.", "gap": 5},
	          {"t": "**The safety net:** a state with no flag row is refused, not guessed, so a missing configuration shows up at once. Each refusal is written to the Governance Refusal Log."}],
	   M + 0.2, 5.35, CW - 0.4, 1.25, base={"size": 12}, valign="middle")


# 34 — backlog
def backlog(d):
	b = d.facts["backlog"]
	s = frame(d, "Of <<stories_total>> backlog stories, <<stories_done>> are done and none is in progress. Most of what remains is missing tests or work that needs the target environment", "E",
	          "Source: docs/delivery/EPICS.md 'Status at a glance' (final measurement, <<measured>>, against release <<release>>, the demo site and the <<tests_run>>-test run). Done = reachable by a user and covered by a passing test.",
	          "The backlog has been re-measured story by story after the final wave, with a strict definition of done: a user can reach the behaviour, and a passing test covers it. <<stories_done>> of <<stories_total>> are done, and nothing is in progress. Of the original <<orig_total>> stories, <<orig_done>> are done. The <<stories_partial>> partial stories fall into three groups. Deployment-readiness stories need the target environment or a Windows workstation. Some behaviour that exists has no automated test yet: theme, text size, table paging and the report builder. The rest are small product gaps, such as a campaign export or the violation's escalation link on the portal. The stories not started need a Windows workstation.")
	bar_chart(d, s, M, 1.75, 8.3, 4.95, b["labels"], [("Done", b["done"]), ("Partial", b["partial"]), ("Not started", b["notstarted"])],
	          stacked=True, colours=[CLASS_COLOURS["a"], CLASS_COLOURS["c"], CLASS_COLOURS["d"]], label_pos="ctr", label_size=11,
	          label_bold=True, label_colour=WHITE, label_format="0;;;", cat_size=11.5, reverse=True, legend=True, legend_size=11, gap=40, vmin=0)
	x = 9.15
	w = W - M - x
	kpi(d, s, x, 1.7, w, "<<stories_done>> of <<stories_total>>", "stories done: a user can reach it and a passing test covers it", size=30, lh=0.6)
	kpi(d, s, x, 3.05, w, "<<stories_partial>>", "partial: mostly missing tests, or rehearsal that needs the target", size=30, lh=0.6)
	kpi(d, s, x, 4.4, w, "<<orig_done>> of <<orig_total>>", "of the original backlog done; <<stories_added>> stories were added after it", size=30, lh=0.6)
	tx(d, s, "Deployment-readiness stories were rehearsed on a stand-in server. They close only on the target environment (decision 2).", x, 5.8, w, 0.9,
	   base={"size": 11, "italic": True, "color": ACCENT, "bold": True})


# 35 — workstreams
def workstreams(d):
	cov = d.facts["coverage"]

	def status(ids):
		open_d = [i for i in ids if cov.get(i) == "d"]
		open_c = [i for i in ids if cov.get(i) == "c"]
		if not open_d and not open_c:
			return "**Done** · all a or b"
		parts = ([f"{len(open_d)} d"] if open_d else []) + ([f"{len(open_c)} c"] if open_c else [])
		return "**Done** · still open: " + ", ".join(parts)
	WS = [
		("**1 · Handling and viewer**", "Confidential and restricted handling; in-portal document viewer; naming conventions; glossary enforcement", ["P-1", "P-13", "P-19", "P-15", "P-24"], "P-1, P-13, P-19, P-15, P-24 (d)"),
		("**2 · Policy actions**", "Lifecycle buttons, approval steps, version upload and revert, publication, reviews, scans, intake classification", ["P-8", "P-9", "P-16", "P-21", "P-25", "P-26"], "P-8, P-9, P-16, P-21, P-25, P-26 (c)"),
		("**3 · Escalation actions**", "Portal write actions; forum-participant notification; revert for forums and escalations", ["E-5", "E-8", "E-7", "E-12", "G-9"], "E-5, E-8 (c); E-7, E-12, G-9 (d)"),
		("**4 · Queues and imports**", "Task and attestation inbox; campaign administration; import batch review; coverage-gap view", ["G-10", "P-23", "G-19", "P-20", "E-19", "O-3"], "G-10, P-23, G-19, P-20, E-19 (c); O-3 (d)"),
		("**5 · Notifications**", "Email, admin-editable templates, reminders, service-level warnings and time in state, regulatory fan-out", ["G-14", "P-14", "E-17", "O-4", "P-6", "P-7", "P-10", "P-11", "E-9", "E-11", "E-13"], "G-14, P-14, E-17, O-4, P-6, P-7, P-10, P-11, E-9, E-11, E-13 (d)"),
		("**6 · Help assistant**", "Context-aware help, offline by default, optional AI endpoint", ["O-1"], "O-1 (a); usability"),
		("**7 · AI features**", "O-6 and O-7 on the optional, administrator-configured endpoint", ["O-6", "O-7"], "O-6, O-7 (d)"),
	]
	d_mand = ids_in_class(d, "d", MANDATORY)
	title = ("All seven workstreams and the third wave are complete. <<missing_Word>> mandatory requirements still miss one clause each, and none is a design problem"
	         if d_mand else "All seven workstreams and the third wave are complete, and no mandatory requirement is missing a clause")
	s = frame(d, title, "E",
	          "Sources: docs/delivery/REQUIREMENTS-COVERAGE.md §2 (what moved), §4 (remaining gaps), final measurement <<measured>>; docs/delivery/EPICS.md (E27–E33).",
	          "Each row maps the gaps found on 17 September to the workstream that closed them, with what is still open today. All seven workstreams and the third wave are complete, and each was measured on the final build. The box at the bottom lists what is still open. Each item is a single clause with a stated fix in the coverage document. Every notice, the approval-step and disbandment notices included, now goes through an editable template.")
	table(d, s, [["Workstream", "What it closed", "Requirements (class at 17 Sep)", "Status now"]] +
	      [[a, b, c, status(ids)] for a, b, ids, c in WS],
	      M, 1.75, CW, [2.3, 4.55, 3.2, 2.28], font_size=11, row_h=[0.38, 0.52, 0.52, 0.5, 0.5, 0.52, 0.42, 0.42])
	card(s, M, 5.75, CW, 0.95, TINT)
	if d_mand:
		body = [{"t": "STILL OPEN: ONE CLAUSE EACH (CLASS D)", "size": 9.5, "bold": True, "color": MUTED, "gap": 3},
		        {"t": " · ".join(t[:1].upper() + t[1:] if k == 0 else t for k, t in enumerate(topic_list(d, d_mand)))}]
	else:
		c_mand = ids_in_class(d, "c", MANDATORY)
		body = [{"t": "NO MANDATORY REQUIREMENT IS MISSING A CLAUSE", "size": 9.5, "bold": True, "color": MUTED, "gap": 3},
		        {"t": ("Partly reachable (class c): " + topics(d, c_mand)) if c_mand else "Every mandatory requirement is fully reachable."}]
	tx(d, s, body, M + 0.2, 5.78, CW - 0.4, 0.9, base={"size": 10.5})


# 36 — AI
def ai(d):
	s = frame(d, "AI is connected and tested with an OpenAI-compatible provider: a Help assistant on every page answers with citations, and every analysis still works with AI off", "E",
	          "Sources: docs/delivery/REQUIREMENTS-COVERAGE.md O-1, O-6, O-7; docs/delivery/EPICS.md E22, E31-S4, E36-S2; consilium_core/ai/ (client, guard), consilium_core/assistant/; AI Service Request log on the demo site (<<ai_requests>> requests, all succeeded, all at Internal classification); consilium_core/tests/test_ai_features.py (37), test_assistant.py (36), test_integrations.py (31).",
	          "AI is now connected on the demonstration site, through an OpenAI-compatible provider configured in Admin, Integrations, and it works end to end. The Help assistant sits on every page. It answers from the illustrated guides, the glossary and the page's own description, cites where each answer comes from, and respects the asker's access. The analysis pages add AI commentary to rule-based results that stand on their own. The controls are unchanged: guidance-only by default, a classification ceiling, sensitive and restricted records never sent, and every request logged before it leaves. On the demo site that log shows <<ai_requests>> requests, all succeeded, all at Internal classification. For production the organisation chooses its own approved endpoint, or leaves AI off; nothing depends on it.")
	w2, h2 = (CW - 0.3) / 2, 3.3
	shot(d, s, "help_answer", M, 1.75, w2, h2, "The Help assistant answering with its sources")
	shot(d, s, "gaps", M + w2 + 0.3, 1.75, w2, h2, "Gaps and risk: rule-based findings, with labelled AI commentary")
	by = 1.75 + h2 + 0.45
	bh, bw = 6.7 - by, (CW - 0.2) / 3
	for i, (h, t) in enumerate([
		("Works today", "A Help assistant on every page, answering from the guides with citations; commentary on the analysis pages. <<ai_requests>> logged requests on the demo site, all succeeded."),
		("Controls", "Guidance-only by default; a classification ceiling; sensitive and restricted never sent; every call logged first; a person accepts any suggestion."),
		("For production", "An approved endpoint, an outbound path and a data-boundary decision, or AI stays off. Every analysis works without it."),
	]):
		x = M + i * (bw + 0.1)
		card(s, x, by, bw, bh, ACCENT_T if i == 2 else TINT)
		tx(d, s, [{"t": h, "bold": True, "color": NAVY, "size": 12, "gap": 2}, {"t": t, "size": 10.5}], x + 0.12, by + 0.06, bw - 0.24, bh - 0.1)


# 37 — deployment readiness
def readiness(d):
	s = frame(d, "Offline install, migration and upgrade are rehearsed on a stand-in server. The conditions left before go-live need the target environment", "E",
	          "Sources: docs/delivery/DEPLOYMENT-READINESS.md ('Where it stands', §1–9, evidence/linux-rehearsal/); docs/delivery/REQUIREMENTS-COVERAGE.md §5 (re-checked <<measured>>); docs/RUNBOOK.md; HANDOVER.md §4.",
	          "Left: what is proven by running it, on an air-gapped Rocky Linux 9 server standing in for the target. Install, migration of the demonstration site, upgrade from the previous release, backup and restore, the service units, the scheduler and single sign-on against a mock provider all ran, and verify.sh passed <<verify>> of <<verify>>. Right: what is still open. The largest unknown is the target's own PostgreSQL, because the framework calls its PostgreSQL support second-class in this version. The offline bundle must also be rebuilt from the final commit. None of the open items blocks building. All of them block going live. Most need decisions or access from people outside the engineering team.")
	lx, lw = M, 4.3
	card(s, lx, 1.75, lw, 4.95, TINT)
	tx(d, s, [{"t": "Proven by running it", "size": 14, "bold": True, "color": NAVY, "gap": 8}] +
	   [{"t": "✓  " + t, "gap": 9} for t in ["Air-gapped install on Rocky Linux 9 in 2 min 23 s; verify.sh <<verify>>/<<verify>>", "Demo site migrated with identical row counts",
	                                          "Upgrade from the previous release: no table lost a row", "Backup and restore by the kit, verified",
	                                          "systemd units, TLS proxy; one scheduler ran every job once", "OIDC sign-in against a mock provider; existing users matched",
	                                          "CI: platform rules, toolchain tests, app tests, health check"]],
	   lx + 0.2, 1.9, lw - 0.4, 4.7, base={"size": 12.5})
	table(d, s, [
		["Open go-live condition", "Status", "What closes it"],
		["**The target's own PostgreSQL**", {"t": "Stand-in only. Largest unknown.", "color": ACCENT, "bold": True}, "Install and migrate on the target server with representative data"],
		["**Offline bundle**", "Must be rebuilt from the final commit", "Rebuild (Python 3.11, x86_64); install; verify.sh again"],
		["**Load**", "Indicative only (emulated laptop)", "Agreed volume; several web processes; record the times"],
		["**Certificates, IdP, mail route**", "Documented; decisions open", "The organisation's CA, identity provider, and an SMTP relay or a Graph app registration"],
		["**Other platforms**", "RHEL 8, Ubuntu 22.04 not run; Python 3.11 only", "Rehearse; raise the hiredis and psutil pins for 3.12 or ARM"],
		["**Real Windows hardware**", "Never run on a Windows machine", "Bootstrap on a managed laptop; RUNBOOK acceptance script"],
		["**Upgrade rollback**", "Printed, not exercised", "Exercise once before the first production upgrade"],
		["**Write-once storage; backup owner**", "Undecided; unassigned", "Infrastructure decision; a named owner"],
	], lx + lw + 0.3, 1.75, W - M - (lx + lw + 0.3), [2.55, 2.35, 2.83], font_size=11, row_h=[0.38, 0.56, 0.52, 0.52, 0.56, 0.52, 0.52, 0.56, 0.52])


# 38 — assumptions
def assumptions(d):
	s = frame(d, "Five assumptions carry the most rework risk if they prove wrong, and each needs a business or risk judgement, not engineering", "E",
	          "Source: docs/product/07-assumptions-and-gaps.md §7 ('What a reviewer should push back on'), items A-1, C-1, C-3, D-5 and §2 (S-3). Severity: H = rework of a model, schema or delivery mechanism.",
	          "These are the five places where being wrong is expensive, taken from our own assumptions register. Notice that none of them is an engineering question. Whether tamper-evidence is enough where the requirement says write-once is a risk judgement. What restricted handling must prevent is a question for the owner of the confidential-document standard. We would like named people to answer each one in the next few weeks.")
	n = lambda k: {"t": k, "align": "center", "bold": True}  # noqa: E731
	hi = {"t": "H", "align": "center", "bold": True, "color": ACCENT}
	table(d, s, [
		["#", "Assumption", "If it is wrong", "Who settles it", "Severity"],
		[n("1"), "Regulatory citations are chosen from a shared library, not typed as free text (C-1)", "'Notify owners when a regulation changes' cannot be implemented as written", "Owner of the regulatory-change process", hi],
		[n("2"), "'Restricted' means blocking download, print and share, not just viewing (C-3)", "The difference between configuration and a build that must hold on six separate paths", "Owner of the confidential-document standard", hi],
		[n("3"), "Tamper-evident storage is acceptable where the requirement says write-once (A-1)", "An auditor who edits a file directly will succeed; the hash chain will only record that they did", "Risk function, with an infrastructure owner", hi],
		[n("4"), "Retention is built in the platform, not handed to an external records system (S-3)", "If revisited, a substantial part of Core disappears", "Records management", hi],
		[n("5"), "Four forum tags (business unit, risk type, legal entity, jurisdiction) are multi-valued (D-5)", "Correct, but every filter on them becomes a subquery on the most-used screen", "Governance office; confirmed by load test", {"t": "M", "align": "center", "bold": True}],
	], M, 1.75, CW, [0.45, 4.15, 4.1, 2.65, 0.98], font_size=11.5, row_h=[0.4, 0.8, 0.8, 0.8, 0.75, 0.8])


# 40 — roadmap
def roadmap(d):
	v = d.values
	if v["missing"]:
		p1_row = "Remaining class-d clauses and missing tests; re-measure"
		p1_exit = f"Each of the {v['missing']} remaining class-d clauses built or accepted by its owner. Full suite, interface sweep and journeys pass on the final bundle."
		p1_note = f"Phase 1 closes the product: the {v['missing_word']} remaining single-clause gaps and the missing tests, then a final bundle from the final commit."
	else:
		p1_row = "Missing automated tests; final re-measure"
		p1_exit = "No class-d clause remains. Full suite, interface sweep and journeys pass on the final bundle."
		p1_note = "Phase 1 closes the product: the missing automated tests, then a final bundle from the final commit."
	s = frame(d, "A three-phase path to production, with each phase exiting on objective evidence rather than a date", "F",
	          "Durations are planning estimates from the delivery team, expressed as ranges and not taken from repository documents; re-baseline after Phase 2 starts. Exit criteria: HANDOVER.md §6 (Phases 0–3), docs/delivery/DEPLOYMENT-READINESS.md, docs/delivery/REQUIREMENTS-COVERAGE.md §4–5.",
	          "The plan has three phases. " + p1_note + " Phase 2 can start as soon as the environment decision is taken and runs partly in parallel. It rebases onto framework v16, then rehearses migration, load and upgrade on the target, runs on real Windows hardware, and settles sign-on, certificates and service accounts. Phase 3 is pilot and go-live with the business owners. The bars show ranges: the solid part is the lower estimate, the lighter part the upper. The total is roughly 12 to 20 weeks from environment access, to be re-baselined after Phase 2 starts.")
	gx = M + 3.95
	gw = W - M - gx
	weeks = 20
	ww = gw / weeks
	for wk in range(0, weeks + 1, 2):
		tx(d, s, f"W{wk}", gx + wk * ww - 0.25, 1.72, 0.5, 0.25, base={"size": 9, "color": MUTED}, align="center")
		rule(s, gx + wk * ww, 1.98, 0, 3.95, "E3E7ED", 0.75)
	bars = [
		("P1", "Finish the product", None),
		("", "Rebuild the offline bundle from the final commit", (0, 1, 1)),
		("", p1_row, (0, 3, 5)),
		("P2", "Target-environment rehearsal", None),
		("", "Rebase onto framework v16; re-verify", (0, 2, 4)),
		("", "Provision target: certificates, ports, accounts, storage", (0, 2, 4)),
		("", "Migration, load and upgrade rehearsal", (4, 6, 8)),
		("", "Real Windows run; single sign-on; one scheduler", (4, 5, 7)),
		("P3", "Pilot and go-live", None),
		("", "Business rules, taxonomy, data import", (6, 8, 10)),
		("", "User acceptance with the governance and policy offices", (8, 12, 16)),
		("", "Go-live readiness review, then go-live", (12, 13, 20)),
	]
	y, rh = 2.02, 0.325
	for ph, lab, r in bars:
		if not r:
			tx(d, s, [{"t": f"{ph}  {lab}", "bold": True, "color": NAVY}], M, y, 3.9, rh, base={"size": 11.5}, valign="middle")
		else:
			tx(d, s, lab, M + 0.25, y, 3.65, rh, base={"size": 10.5}, valign="middle")
			a, b, c = r
			shape(s, "rect", gx + a * ww, y + 0.06, (b - a) * ww, rh - 0.12, NAVY)
			if c > b:
				shape(s, "rect", gx + b * ww, y + 0.06, (c - b) * ww, rh - 0.12, ICE)
		y += rh
	ew = (CW - 0.4) / 3
	for i, (h, t) in enumerate([("P1 exit", p1_exit),
	                            ("P2 exit", "The same tree runs on the target and on a managed Windows laptop, with 8/8 smoke checks, making no network connections. Migration and load measured. Sign-on and service accounts working."),
	                            ("P3 exit", "Business owners accept UAT. Real rules and taxonomy loaded. Backups scheduled with a named owner. Exactly one scheduler running.")]):
		x = M + i * (ew + 0.2)
		card(s, x, 6.02, ew, 0.72, TINT)
		tx(d, s, f"**{h}:** {t}", x + 0.12, 6.04, ew - 0.24, 0.68, base={"size": 9.5}, valign="middle")


# 41 — RACI
def raci(d):
	s = frame(d, "Clear ownership: engineering builds, the deploying team runs it, the business owns the rules, and leadership owns the risk calls", "F",
	          "Proposed allocation for leadership confirmation. Basis: HANDOVER.md §8 (the network request, the hardware run and the v15/v16 decision need people); docs/product/07-assumptions-and-gaps.md 'Settles it' entries. R = responsible, A = accountable, C = consulted, I = informed.",
	          "This is a proposed ownership model. The pattern is simple. Engineering builds and verifies. The infrastructure or deploying team owns the environment and runs the rehearsals with us. Information security owns sign-on and the AI boundary. The business owners, the risk governance office and the enterprise policy office, own the rules the engines run on and accept the product. Leadership is accountable for the two risk calls: the framework version and the AI position. Please challenge any row you disagree with.")
	roles = ["Executive sponsor", "Delivery engineering", "Infrastructure / deploying team", "Information security", "Business owners (governance, policy, escalation)", "Internal audit"]
	A = [
		("Framework version decision (v15 vs v16)", ["A", "R", "C", "C", "I", "I"]),
		("Rebase onto v16 and full re-verification", ["I", "A/R", "C", "I", "I", "I"]),
		("Target environment, certificates, ports, service accounts", ["I", "C", "A/R", "C", "", "I"]),
		("Migration, load and upgrade rehearsal", ["I", "R", "A", "I", "I", "I"]),
		("Write-once storage and backup ownership", ["C", "C", "R", "C", "A", "C"]),
		("Single sign-on protocol and configuration", ["I", "R", "C", "A", "I", ""]),
		("Classification rules, taxonomy, closure criteria", ["I", "C", "", "", "A/R", "C"]),
		("User acceptance and go-live acceptance", ["A", "C", "C", "C", "R", "C"]),
		("AI position and any AI endpoint", ["A", "C", "C", "R", "C", "I"]),
	]
	def cell(val):
		acc = "A" in val
		return {"t": (f"**{val}**" if acc else val) if val else "–", "align": "center", "fill": "FBE9E4" if acc else None, "color": ACCENT if acc else INK}
	table(d, s, [["Activity"] + roles] + [[a] + [cell(x) for x in r] for a, r in A],
	      M, 1.75, CW, [3.53, 1.3, 1.45, 1.55, 1.4, 1.9, 1.2], font_size=11.5, h_size=10.5, row_h=[0.62] + [0.47] * 9)


# 42 — risks
def risks(d):
	s = frame(d, "The top risk is the framework's second-class PostgreSQL support in v15; rebasing onto v16 before go-live is the main mitigation", "F",
	          "Sources: HANDOVER.md §7 (risk table); docs/product/07-assumptions-and-gaps.md A-1, A-4, B-1, B-4, B-6; docs/product/04-architecture.md §9.3; docs/guides/07-help-and-ai.md; docs/delivery/DEPLOYMENT-READINESS.md §1 (dependency fork verified by content).",
	          "The risk register, ordered by severity. The first two are really one risk: the framework version we use treats PostgreSQL as second-class, and we have already found divergences between database backends. The mitigation is the rebase plus a proper rehearsal on the target. Write-once storage is high severity because it is a risk judgement nobody has made yet. Windows and the scheduler are medium and have simple mitigations. The dependency-substitution risk from the handover has been mitigated by the bundle builder, which verifies content rather than version strings.")
	high = {"t": "High", "bold": True, "color": ACCENT}
	table(d, s, [
		["Risk", "Severity", "Mitigation", "Owner"],
		["Framework v15 treats PostgreSQL as second-class; fixes will target v16 only", high, "Rebase onto v16 before target rehearsal; porting work is version-agnostic", "Sponsor / engineering"],
		["Unknown database divergences appear under load or during migration (3–4 already found and fixed; stand-in rehearsal clean)", high, "Migration and load rehearsal on the target with representative data, not a smoke test", "Infrastructure / engineering"],
		["Write-once storage undecided: the control is tamper-evident, not write-once", high, "Storage decision with a named owner; describe the control accurately until then", "Risk function / infrastructure"],
		["Never run on real Windows hardware; Windows workers have no crash isolation", "Medium", "Front-load the managed-laptop run; run several supervised workers; production is Linux", "Engineering"],
		["SAML mandated: not available in the framework", "Medium", "Confirm the protocol now; if SAML, estimate a separate component", "Information security"],
		["Business rules not supplied (classification, taxonomy, closure criteria)", "Medium", "Engines ship without them; named owners and one working session each", "Business owners"],
		["Platform pins: Python 3.11 on x86_64 only (hiredis blocks 3.12, psutil blocks ARM)", "Medium", "Provision Python 3.11 x86_64; raise the pins before any 3.12 or ARM target", "Engineering / infrastructure"],
		["AI endpoint discloses restricted content", "Low", "Off by default; 'guidance only' sends no record contents; every request logged", "Information security"],
	], M, 1.75, CW, [4.6, 1.0, 4.73, 2.0], font_size=11, row_h=[0.38, 0.55, 0.55, 0.55, 0.55, 0.48, 0.55, 0.55, 0.48])


# 43 — v16 recommendation
def v16(d):
	s = frame(d, "Recommendation: rebase onto framework v16 before go-live. The porting work carries over, and v15 PostgreSQL fixes are not coming", "F",
	          "Sources: HANDOVER.md §7 (quoted framework notice; recommendation to rebase), §8 (an architecture call for people); docs/product/07-assumptions-and-gaps.md A-4; docs/delivery/SESSION-SUMMARY.md; policy/tests/test_regressions.py (TestImplementationGate).",
	          "The framework prints a notice on every new site: PostgreSQL support is limited to v16 and above, and fixes for earlier versions will not be added. We have already found three or four database divergences ourselves, including one among this week's defects. Staying on v15 means every future PostgreSQL issue is ours to fix, without upstream help. Rebasing costs a few weeks of re-verification. Our porting work was written to be version-agnostic, and the rebase should happen before the target rehearsal, so that we rehearse what we will actually ship. The recommendation is to rebase.")
	cw = (CW - 0.3) / 2
	for i, (h, col, pros, cons) in enumerate([
		("Option A — stay on v15", SLATE, ["No rebase effort now"], ["The framework's own notice: PostgreSQL support is limited to v16 and above; fixes for earlier versions will not be added", "3–4 database divergences already found and fixed by us, with no basis to assume that is all", "Every future PostgreSQL defect is ours to find and fix"]),
		("Option B — rebase onto v16 (recommended)", NAVY, ["The framework's supported path for PostgreSQL", "Porting work is version-agnostic: runtime patches, no fork", "Done before rehearsal, so we rehearse what we ship"], ["Rebase effort plus full re-verification: test suite, interface sweep, offline bundle rebuild", "v16 still needs the same real-Windows proof"]),
	]):
		x = M + i * (cw + 0.3)
		card(s, x, 1.75, cw, 0.6, col)
		tx(d, s, h, x + 0.2, 1.75, cw - 0.4, 0.6, base={"size": 15, "bold": True, "color": WHITE}, valign="middle")
		card(s, x, 2.35, cw, 3.2)
		tx(d, s, [{"t": "For", "bold": True, "color": NAVY, "gap": 3}] + [{"t": "+  " + t, "gap": 4} for t in pros] +
		   [{"t": " ", "gap": 2}, {"t": "Against", "bold": True, "color": ACCENT, "gap": 3}] + [{"t": "–  " + t, "gap": 4} for t in cons],
		   x + 0.2, 2.5, cw - 0.4, 3.0, base={"size": 12})
	card(s, M, 5.75, CW, 0.95, NAVY)
	tx(d, s, "**Recommendation:** approve the rebase onto v16 now and schedule it at the start of Phase 2, before any target rehearsal. **Decision owner:** executive sponsor, on the engineering lead's advice.",
	   M + 0.25, 5.75, CW - 0.5, 0.95, base={"size": 13, "color": WHITE}, valign="middle")


# 44 — asks
def asks(d):
	s = frame(d, "Decisions and asks: five approvals today put Consilium on a gated path to production", None,
	          "Sources: slides 3, 37, 40–43. Owners and timing are proposals for confirmation in this meeting.",
	          "Close on the asks. Five decisions, each with an owner and a date by which we need it. If these are taken today, Phase 2 can start as soon as the environment is available. We will report progress against the phase exit criteria, not against dates, and we will re-measure coverage with the same method at each phase exit.")
	y = 1.8
	for i, (dec, owner, when) in enumerate([
		("Rebase onto framework v16 before go-live", "Executive sponsor", "Today"),
		("Provide the target environment and name one infrastructure owner (certificates, ports, service accounts, write-once storage, backups)", "Infrastructure lead", "Start of Phase 2"),
		("Confirm the single sign-on protocol (LDAP or OIDC preferred; SAML is a separate build)", "Information security", "Start of Phase 2"),
		("Name business owners for classification rules, taxonomy values, closure criteria and the regulatory-change file", "Business sponsors", "Within two weeks"),
		("Approve an AI endpoint and its data boundary, or keep AI off for go-live; nothing depends on it", "Executive sponsor, with security", "Today"),
	]):
		card(s, M, y, CW, 0.78)
		badge(d, s, i + 1, M + 0.2, y + 0.2, 0.38)
		tx(d, s, dec, M + 0.8, y, 7.6, 0.78, base={"size": 13, "bold": True, "color": NAVY}, valign="middle")
		tx(d, s, [{"t": "OWNER", "size": 9, "color": MUTED, "bold": True, "gap": 0}, {"t": owner, "size": 12}], M + 8.6, y + 0.08, 2.1, 0.64, valign="middle")
		tx(d, s, [{"t": "NEEDED BY", "size": 9, "color": MUTED, "bold": True, "gap": 0}, {"t": when, "size": 12, "bold": True, "color": ACCENT}], M + 10.8, y + 0.08, 1.45, 0.64, valign="middle")
		y += 0.88
	tx(d, s, "**In return, the delivery team commits to:** re-measuring coverage with the same method at each phase exit; reporting against phase exit criteria; every claim backed by a run.",
	   M, 6.25, CW, 0.5, base={"size": 12, "color": SLATE})


# 45–49 — appendix
def appendix(d):
	from deckkit import footer
	s = d.new_slide(NAVY)
	label(d, s, [("Appendix", {"size": 36, "bold": True, "color": WHITE})], M, 2.3, 8, 0.9)
	tx(d, s, [{"t": "A1  Requirement trace summary", "gap": 4}, {"t": "A2  Glossary", "gap": 4}, {"t": "A3  Test inventory", "gap": 4}, {"t": "A4  Demonstration organisation"}],
	   M, 3.3, 8, 2, base={"size": 16, "color": ICE})
	footer(d, s, None, dark=True)
	notes_(d, s, "Reference material for the pre-read.")
	trace_summary(d)
	glossary(d)
	test_inventory(d)
	demo_org(d)


def trace_summary(d):
	v = d.values
	s = frame(d, "A1 · Requirement trace summary: how each module's requirements are satisfied, changed and covered", "APPENDIX",
	          "Sources: docs/product/01-requirements-baseline.md §3–4 (dominant class, Δ markers — tables authoritative); docs/product/06-traceability.md §7 (64/64 and 7/7 traced); docs/delivery/REQUIREMENTS-COVERAGE.md §2 (classes and tests, final measurement <<measured>>).",
	          "Summary of the trace. Every requirement has an entity and a surface. Fifty-four of the sixty-four need some application code. The traceability summary says 55, because it was written from an earlier pass; the requirement tables are authoritative. Only P-17 is satisfied purely by a stock feature.")
	cls = lambda p: f"{v[p + '_a']} / {v[p + '_b']} / {v[p + '_c']} / {v[p + '_d']}"  # noqa: E731
	rows = [
		["**Governance (G)**", "19", "14", "3", "9", cls("G"), "19 of 19"],
		["**Policy (P)**", "26", "24", "9", "6", cls("P"), "26 of 26"],
		["**Escalation (E)**", "19", "16", "2", "8", cls("E"), "19 of 19"],
		["**Total**", "**64**", "**54**", "**14**", "**23**", f"**{v['mand_a']} / {v['mand_b']} / {v['mand_c']} / {v['mand_d']}**", "**64 of 64**"],
		["Supplementary (O)", "7", "—", "—", "—", cls("O"), "7 of 7"],
	]
	table(d, s, [["Module", "Mandatory", "Needs a build component", "Materially changed (bold Δ)", "Clarified (Δ)", "Coverage a / b / c / d (final)", "≥1 direct passing test"]] +
	      [[r[0]] + [{"t": c, "align": "center"} for c in r[1:]] for r in rows],
	      M, 1.75, CW, [2.2, 1.3, 1.8, 2.0, 1.4, 2.13, 1.5], font_size=12, row_h=[0.62, 0.5, 0.5, 0.5, 0.5, 0.5])
	tx(d, s, [{"t": "**Notes.** 'Needs a build component' counts requirements whose dominant class includes Build (06 states 55; the 01 tables give 54). Only P-17 is purely native. Every mandatory requirement has a direct passing test; for <<partial_n>> the tests cover only part of it (<<partial_list>>).", "gap": 4},
	          {"t": "All 64 mandatory and 7 supplementary requirements trace to at least one entity and one surface (06 §7)."}],
	   M, 5.0, CW, 1.5, base={"size": 11.5, "color": SLATE})


def glossary(d):
	s = frame(d, "A2 · Glossary of terms used in this briefing", "APPENDIX", "Source: docs/product/05-glossary.md §A, §B, §D; docs/guides/11-glossary.md.", "Reference glossary.")
	G = [
		("Governance forum", "Any standing body (committee, council, oversight body, working group) with a mandate, membership and reporting lines."),
		("Governing document", "Framework, Policy, Standard, Procedure or Supporting Document."),
		("Escalation matter / matrix", "An issue raised for decision at a defined authority level; the approved mapping from its attributes to severity and pathway."),
		("Effective challenge", "Structured questioning of a first-line assessment by the second line before a matter proceeds."),
		("Attestation", "Periodic positive confirmation by a named person that stated facts are accurate. Three events, one engine."),
		("Watched field set", "Admin-editable list of fields whose change sends a record back for compliance review."),
		("Semantic flag", "A property such as editable or active that a workflow state sets. Logic reads flags, never state names."),
		("Document version / revert", "Immutable snapshot of a document body; revert writes a new version with the old content."),
		("Archive record", "Immutable, hash-chained retention artefact; tampering becomes detectable."),
		("Import batch / external reference", "The governed file-import pipeline that replaces live connectors; a foreign identifier with its provenance."),
		("Portal / workspace", "Purpose-built screens for daily work / the framework's administrative interface."),
		("WORM · SLA · 1LOD/2LOD/3LOD", "Write once, read many · tracked time target · first, second, third line of defence."),
	]
	cw = (CW - 0.3) / 2
	for c in (0, 1):
		table(d, s, [["Term", "Meaning"]] + [[f"**{a}**", b] for a, b in G[c * 6:c * 6 + 6]],
		      M + c * (cw + 0.3), 1.75, cw, [1.9, cw - 1.9], font_size=11, row_h=[0.38] + [0.74] * 6)


def test_inventory(d):
	s = frame(d, "A3 · Test inventory: the suites behind the evidence, by area", "APPENDIX",
	          "Source: test files under apps/consilium/consilium/*/tests/ (methods counted from source); docs/delivery/REQUIREMENTS-COVERAGE.md §1 (final run: <<tests_run>> tests, OK); HANDOVER.md §4. Largest suites per module; not an exhaustive list.",
	          "The largest test files in each module. The coverage matrix maps every test class to the requirements it proves. The final full run was <<tests_run>> tests on a clean site, all passing.")
	T = [
		("Core (476)", [("AI features (rule-based)", "37"), ("Help assistant", "36"), ("Integrations", "31"), ("Service levels and time in state", "22"), ("Notification templates", "22"), ("Inbox and campaigns", "22"), ("Microsoft Graph mail", "20"), ("Navigation and search", "20")]),
		("Governance (242)", [("Formation portal", "35"), ("Wave-3 screens (charter, disband, map)", "33"), ("Formation engine", "27"), ("Membership", "25"), ("Lifecycle and reviews", "22"), ("Voting screen, queues, bypass", "20"), ("Governance entities", "19"), ("Voting", "18")]),
		("Policy (328)", [("Portal actions", "68"), ("Search, reports, notices", "34"), ("Lifecycle and routing", "33"), ("Confidential handling", "32"), ("Repository", "27"), ("Monitoring and glossary", "24"), ("Horizon scanning", "19"), ("Intake classification", "19")]),
		("Escalation (149)", [("Portal actions", "43"), ("Queues, systemic route, timing", "22"), ("Resolution and closure", "19"), ("Escalation entities", "14"), ("Routing matrix", "12"), ("Sensitive matters", "12"), ("Templates", "8"), ("Pathway participants", "5")]),
	]
	cw = (CW - 0.45) / 4
	for i, (h, rows) in enumerate(T):
		table(d, s, [[h, "Tests"]] + [[a, {"t": b, "align": "right"}] for a, b in rows], M + i * (cw + 0.15), 1.75, cw, [cw - 0.65, 0.65], font_size=11, row_h=[0.38] + [0.4] * 8)
	card(s, M, 5.6, CW, 1.05, TINT)
	tx(d, s, "**Beyond the module suites:** <<tests_passed>> / <<tests_run>> full application suite (258 more in record-type test files) · <<ui_sweep>>/<<ui_sweep>> interface sweep · <<journeys>>/<<journeys>> browser journeys · <<pytest>> toolchain tests (<<compat_windows>> simulate Windows) · verify.sh <<verify>>/<<verify>> and health <<health>>/<<health>> on the rehearsal server · <<platform_rules>>/<<platform_rules>> platform rules · about 190 of the framework's own tests on PostgreSQL (3 failures, none ours).",
	   M + 0.2, 5.6, CW - 0.4, 1.05, base={"size": 11.5}, valign="middle")


def demo_org(d):
	s = frame(d, "A4 · The demonstration organisation: realistic enough to find defects, fictitious by design", "APPENDIX",
	          "Sources: demonstration site rebuilt from scratch (deploy/demo_data.py, about 27 s, idempotent); docs/delivery/REQUIREMENTS-COVERAGE.md §3 (records queried <<measured>>); docs/delivery/DEMO-LOGINS.md. All personas use a reserved demo domain.",
	          "The demonstration organisation is fictitious and must never be loaded into production. It is realistic enough to exercise every state of every lifecycle, and that is what found the nine defects. It rebuilds from scratch in about 27 seconds. Personas are created with no password. A demonstrator issues random per-run passwords with deploy/demo_logins.py into a file outside the repository, so no password is ever committed.")
	kw = (CW - 1.0) / 6
	for i, (val, cap) in enumerate([("<<demo_personas>>", "role-based personas"), ("<<demo_forums>>", "forums, board to working group"),
	                                 ("<<demo_documents>>", "governing documents; <<demo_versions>> versions"), ("<<demo_escalations>>", "escalations, every state"),
	                                 ("<<demo_meetings>>", "meetings; <<demo_motions>> motions, <<demo_votes>> votes"), ("<<demo_attestation_tasks>>", "attestation tasks")]):
		x = M + i * (kw + 0.2)
		card(s, x, 1.75, kw, 1.45)
		kpi(d, s, x + 0.15, 1.75, kw - 0.3, val, cap, size=30, lh=0.6)
	table(d, s, [
		["Area", "What is loaded (examples)"],
		["**Formation**", "Requests at every stage, from draft to approved; an approved request created a forum through a recorded bypass exception"],
		["**Attestation**", "2026 forum inventory campaign: 22 attested, 11 pending, 3 declined, 3 with exceptions; policy campaign: 5 attested, 4 pending; 2025 campaign closed"],
		["**Policy**", "Lineage from framework to procedures; an authorised exemption; a retired standard superseded, raising a remediation task on its child; 13 glossary terms"],
		["**Escalation**", "Matrix-routed and manually overridden matters; action plans; risk acceptances pending, approved and expired; sensitive matters; an external closure"],
		["**Configuration**", "Escalation matrix, time limits, approval routes, 5 document templates, 5 retention classes, 6 guide articles"],
	], M, 3.4, CW, [2.0, CW - 2.0], font_size=11.5, row_h=[0.38, 0.52, 0.52, 0.52, 0.52, 0.52])
