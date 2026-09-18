"""DEMONSTRATION data for the platform gaps closed on 18 September: O-3 (a saved
dashboard layout), G-16 / P-18 / E-18 (retention in force and disposals due),
G-19 / P-20 / E-19 (governed export profiles and a logged export), G-12 (forum
time targets), G-13 (a chair's delegate) and P-5 (a document's links to
risk-programme records held elsewhere).

    from deploy.demo_additions import gaps_platform
    gaps_platform.run(frappe)     # inside a connected site; the caller commits

Builds on the records ``deploy/demo_data.py`` has already made, found by name.
Idempotent: every step looks for what it would create and skips it when it is
there. Steps are taken **as the persona who would take them**, through the same
entry points the portal calls.

* **Retention in force (G-16, P-18, E-18).** The retention classes the
  organisation already has are assigned: forums (ten years after disbandment),
  governing documents (seven years after retirement), escalation matters (seven
  years after closure) — and minutes, which are write-once: a meeting with
  recorded minutes can no longer be changed, and an attempt is refused and
  logged. The nightly job archives each record as its trigger passes.
* **Disposals due.** Three closed escalation matters fall under a short
  demonstration class (one month after closure, then review), so they are
  archived and due now. On ``/records`` the records manager sees one waiting
  for a decision, one they have proposed to dispose of that waits for a second
  person's approval, and one held by a legal hold that General Counsel placed.
* **Exports (G-19, P-20, E-19).** Three profiles: the forum inventory for the
  enterprise risk register, policy metadata for the GRC platform, and escalation
  status for the GRC platform. The risk governance lead has run the first, so
  ``/exports`` shows a logged batch with its fingerprint.
* **Forum time targets (G-12).** Formation requests are timed in evaluation
  and awaiting approval, and forums while a compliance decision is pending.
* **A saved layout (O-3).** The Chief Risk Officer has arranged Management
  reporting with escalations first and the document families hidden.
* **A chair's delegate (G-13).** The Head of Operational Risk, chair of the
  Operational Risk Committee, has nominated the Risk Governance Analyst for the
  committee's administrative tasks for the next four weeks.
* **External links (P-5).** The Operational Risk Management Policy links to a
  risk in the risk register, a control on the GRC platform and a training
  course; ``/imports`` offers profiles for bringing such links in from a file,
  for documents and for forums (G-19).

Everything is fictitious. Addresses use the reserved ``example.com`` domain.
"""

from __future__ import annotations

import json

ADMIN = "risk.governance.lead@demo.example"
RECORDS = "records.manager@demo.example"
COUNSEL = "general.counsel@demo.example"
CRO = "chief.risk.officer@demo.example"

DEMO_CLASS = ("ESC-DEMO-ELAPSED", "Escalation matters: short retention (demonstration)")
#: Closed matters put up for disposal: (title, what happens on /records).
DISPOSAL_MATTERS = (
    ("Critical payments processor outage breached its recovery time objective", "due"),
    ("Quarterly regulatory capital return submitted two business days late", "proposed"),
    ("Targeted phishing campaign against finance staff", "held"),
)
HOLD_REFERENCE = "LH-2026-014"

ASSIGNMENTS = (
    # title, target, filter, class, priority
    ("Governance forums, from disbandment", "Governance Forum", {}, "GOV-FORUM", 100),
    ("Governing documents, from retirement", "Governing Document", {}, "POL-DOCUMENT", 100),
    ("Escalation matters, from closure", "Escalation Matter", {}, "ESC-MATTER", 100),
    ("Minutes of forum meetings, write-once", "Forum Meeting", {"minutes_version": ["is", "set"]}, "GOV-MINUTES", 100),
)

DELEGATING_FORUM = "Operational Risk Committee"
DELEGATE = "risk.governance.analyst@demo.example"

LINKED_DOCUMENT = "Operational Risk Management Policy"
LINKS = (
    ("RISK_REGISTER", "Risk", "RSK-OPS-014", "Process execution failure in payments operations",
     "https://risk-register.example.com/risks/RSK-OPS-014"),
    ("GRC_PLATFORM", "Control", "CTL-0457", "Daily reconciliation sign-off",
     "https://grc.example.com/controls/CTL-0457"),
    (None, "Training", "", "Operational risk essentials (annual course)",
     "https://learning.example.com/courses/ORM-101"),
)


def _as(frappe, user: str):
	frappe.set_user(user if frappe.db.exists("User", user) else "Administrator")


# ------------------------------------------------------------------ retention


def retention_in_force(frappe, notes: list[str]) -> None:
	from consilium.consilium_core import retention

	made = []
	for title, target, record_filter, retention_class, priority in ASSIGNMENTS:
		if not frappe.db.exists("Retention Class", retention_class) or not frappe.db.exists("DocType", target):
			continue
		if frappe.db.exists("Retention Assignment", {"assignment_title": title}):
			continue
		frappe.get_doc({
			"doctype": "Retention Assignment", "assignment_title": title, "target_doctype": target,
			"record_filter": json.dumps(record_filter), "retention_class": retention_class,
			"priority": priority, "is_active": 1,
		}).insert(ignore_permissions=True)
		made.append(title)
	retention.clear_cache()
	notes.append(f"retention assignments: {len(made)} made" + (f" ({'; '.join(made)})" if made else ""))


def disposals_due(frappe, notes: list[str]) -> None:
	from consilium.consilium_core import records, retention

	code, title = DEMO_CLASS
	if not frappe.db.exists("Retention Class", code):
		frappe.get_doc({
			"doctype": "Retention Class", "class_code": code, "title": title,
			"description": "A demonstration class, so the disposal screen has records due today.",
			"retention_period_months": 1, "trigger_event": "Closure", "disposition_action": "Review",
			"requires_worm": 0, "legal_basis": "Demonstration only.", "is_active": 1,
		}).insert(ignore_permissions=True)
	matters = {}
	for matter_title, role in DISPOSAL_MATTERS:
		name = frappe.db.get_value("Escalation Matter", {"escalation_title": matter_title}, "name")
		if name:
			matters[role] = name
	if not matters:
		notes.append("disposals: skipped, the closed demonstration matters are missing")
		return
	assignment_title = "Demonstration: closed matters due for disposal"
	if not frappe.db.exists("Retention Assignment", {"assignment_title": assignment_title}):
		frappe.get_doc({
			"doctype": "Retention Assignment", "assignment_title": assignment_title,
			"target_doctype": "Escalation Matter",
			"record_filter": json.dumps({"name": ["in", sorted(matters.values())]}),
			"retention_class": code, "priority": 500, "is_active": 1,
		}).insert(ignore_permissions=True)
	retention.clear_cache()

	held = matters.get("held")
	if held and not frappe.db.exists("Legal Hold", HOLD_REFERENCE):
		_as(frappe, COUNSEL)
		try:
			frappe.get_doc({
				"doctype": "Legal Hold", "hold_reference": HOLD_REFERENCE,
				"description": "Preserve the phishing investigation file: a related claim is in correspondence.",
				"requested_by": COUNSEL, "approved_by": COUNSEL, "placed_on": frappe.utils.add_days(frappe.utils.nowdate(), -20),
				"scope_doctype": "Escalation Matter", "scope_filter": json.dumps({"name": held}),
			}).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
		retention.clear_cache()

	archived = [records.archive("Escalation Matter", name) for name in matters.values()]
	retention.flag_due_for_disposal()
	proposed = matters.get("proposed")
	archive = proposed and records.archived("Escalation Matter", proposed)
	event = archive and frappe.db.get_value("Disposition Event", {"archive_record": archive, "is_open": 1}, "name")
	if event and not frappe.db.get_value("Disposition Event", event, "decision"):
		_as(frappe, RECORDS)
		try:
			records.propose_disposition(event, "Dispose",
				"Closed and tracked on the GRC platform since March; nothing open refers to it, and the "
				"external platform keeps the regulator correspondence.")
		finally:
			frappe.set_user("Administrator")
	due = frappe.db.count("Disposition Event", {"is_open": 1})
	notes.append(f"disposals: {len(archived)} matters archived under {code}; {due} disposition(s) open "
		f"(one proposed by the records manager, one held by {HOLD_REFERENCE})")


# --------------------------------------------------------------------- exports


def export_profiles(frappe, notes: list[str]) -> None:
	from consilium.consilium_core import exporting

	profiles = (
		("Forum inventory for the enterprise risk register", "RISK_REGISTER", "Governance Forum", "CSV",
		 {"is_active": 1}, "Risk Governance Office\nHead of Risk Governance\nConsilium Audit",
		 "Active forums, their chairs, owning groups and primary risk categories, so the risk register can name "
		 "the forum that oversees each risk."),
		("Policy metadata for the GRC platform", "GRC_PLATFORM", "Governing Document", "CSV", {},
		 "Enterprise Policy Office\nRisk Governance Office",
		 "Governing documents with their owners, approving forums and review dates."),
		("Escalation status for the GRC platform", "GRC_PLATFORM", "Escalation Matter", "JSON", {},
		 "Risk Governance Office\nHead of Risk Governance",
		 "Status, severity and pathway of every escalation, for issue tracking downstream."),
	)
	made = []
	for title, system, source, fmt, record_filter, roles, description in profiles:
		if not frappe.db.exists("External System", system):
			continue
		if frappe.db.exists("Export Profile", {"profile_title": title}):
			continue
		frappe.get_doc({
			"doctype": "Export Profile", "profile_title": title, "description": description,
			"source_doctype": source, "target_system": system, "file_format": fmt,
			"record_filter": json.dumps(record_filter), "allowed_roles": roles, "max_rows": 5000,
			"schedule": "Manual Only", "is_active": 1,
		}).insert(ignore_permissions=True)
		made.append(title)
	first = frappe.db.get_value("Export Profile", {"profile_title": profiles[0][0]}, "name")
	ran = None
	if first and not frappe.db.exists("Export Batch", {"export_profile": first}):
		_as(frappe, ADMIN)
		try:
			ran = exporting.export_now(first)["batch"]
		finally:
			frappe.set_user("Administrator")
	notes.append(f"export profiles: {len(made)} made" + (f"; {ran} exported by the risk governance lead" if ran else ""))


# ------------------------------------------------------------------ time limits


def forum_time_targets(frappe, notes: list[str]) -> None:
	from consilium.consilium_core import sla

	calendar = frappe.db.get_value("SLA Definition", "ESC-HIGH", "business_calendar")
	definitions = (
		("GOV-FORMATION-EVAL", "Formation request: evaluation within two working weeks",
		 "Committee Formation Request", "workflow_state", "Under Evaluation", 80.0),
		("GOV-FORMATION-APPROVAL", "Formation request: approval within three working weeks",
		 "Committee Formation Request", "workflow_state", "Pending Approval", 120.0),
		("GOV-FORUM-COMPLIANCE", "Forum: compliance decision within two working weeks",
		 "Governance Forum", "compliance_status", "Pending", 80.0),
	)
	made = []
	for code, title, doctype, field, value, hours in definitions:
		options = (frappe.get_meta(doctype).get_field(field).options or "").split("\n")
		if value not in options or frappe.db.exists("SLA Definition", code):
			continue
		frappe.get_doc({
			"doctype": "SLA Definition", "sla_code": code, "title": title, "target_doctype": doctype,
			"measure": sla.MEASURE_TIME_IN_STATE, "state_field": field, "state_value": value,
			"target_hours": hours, "warning_threshold_pct": 75,
			"calendar": "Business Hours" if calendar else "24x7", "business_calendar": calendar,
			"is_active": 1,
		}).insert(ignore_permissions=True)
		made.append(code)
	clocks = []
	for doctype in ("Committee Formation Request", "Governance Forum"):
		clocks += sla.sync_state_clocks(doctype) or []
	notes.append(f"forum time targets: {len(made)} made; {len(clocks)} clock change(s)")


# ---------------------------------------------------------------------- layout


def saved_layout(frappe, notes: list[str]) -> None:
	from consilium.consilium_core import dashboard_layout

	if not frappe.db.exists("User", CRO):
		return
	if frappe.db.exists("Dashboard Layout", {"user": CRO, "page": "reports", "is_customised": 1}):
		notes.append("saved layout: already there for the Chief Risk Officer")
		return
	_as(frappe, CRO)
	try:
		layout = dashboard_layout.get_layout("reports")["layout"]
		order = ["escalations-heading", "forum-service-heading", "headline-heading"]
		layout.sort(key=lambda entry: order.index(entry["key"]) if entry["key"] in order else len(order))
		for entry in layout:
			for dim in entry["dimensions"]:
				if dim["key"] in ("families-heading", "missing-heading"):
					dim["shown"] = False
		dashboard_layout.save_layout("reports", json.dumps(layout))
	finally:
		frappe.set_user("Administrator")
	notes.append("saved layout: the Chief Risk Officer's reporting page, escalations first")


# ------------------------------------------------------------------- delegates


def chairs_delegate(frappe, notes: list[str]) -> None:
	from consilium.governance import delegates

	forum = frappe.db.get_value("Governance Forum", {"forum_name": DELEGATING_FORUM},
		["name", "committee_chair"], as_dict=True)
	if not forum or not forum.committee_chair or not frappe.db.exists("User", DELEGATE):
		notes.append("chair's delegate: skipped, the forum or its chair is missing")
		return
	if frappe.db.exists("Authority Delegation", {"delegator": forum.committee_chair, "scope_record": forum.name}):
		notes.append("chair's delegate: already nominated")
		return
	today = frappe.utils.nowdate()
	_as(frappe, forum.committee_chair)
	try:
		out = delegates.nominate_delegate(
			forum.name, DELEGATE, json.dumps(["SUBMIT", "EDIT", "ACKNOWLEDGE"]), today,
			frappe.utils.add_days(today, 28),
			"Covering the committee's papers and minutes while I lead the resilience testing programme.")
	finally:
		frappe.set_user("Administrator")
	notes.append(f"chair's delegate: {out['delegations'][0]['name']} on {forum.name}")


# ------------------------------------------------------------------------ links


def external_links(frappe, notes: list[str]) -> None:
	from consilium.policy import external_links as links

	document = frappe.db.get_value("Governing Document", {"document_name": LINKED_DOCUMENT},
		["name", "document_owner"], as_dict=True)
	if not document:
		notes.append("external links: skipped, the document is missing")
		return
	made = 0
	# Added by the document's owner where they may edit it (the usual case),
	# otherwise by the administrator, so the step never depends on a persona's
	# access being exactly what it is today.
	owner = document.document_owner
	editor = owner if owner and frappe.has_permission("Governing Document", "write", doc=document.name,
		user=owner) else "Administrator"
	_as(frappe, editor)
	try:
		for system, kind, key, label, url in LINKS:
			if frappe.db.exists("External Reference", {"subject_doctype": "Governing Document",
					"subject_name": document.name, "url": url, "is_active": 1}):
				continue
			if system and not frappe.db.exists("External System", system):
				system = None
			links.add_document_link(document.name, url, label, kind, system, key or None)
			made += 1
	finally:
		frappe.set_user("Administrator")
	notes.append(f"external links: {made} added to {document.name}")


def reference_import_profiles(frappe, notes: list[str]) -> None:
	"""P-5 and G-19: profiles for bringing such links in from a file on /imports."""
	from consilium.consilium_core import importing

	made = [
		importing.ensure_reference_profile("Governing Document",
			"Governing document links to risk-programme records (file)"),
		importing.ensure_reference_profile("Governance Forum", "Forum links to the risk register (file)"),
	]
	notes.append(f"reference import profiles: {', '.join(made)}")


def run(frappe) -> list[str]:
	"""Apply the additions. Returns what was done; the caller commits."""
	notes: list[str] = []
	if not frappe.db.exists("Governance Forum", {"forum_name": DELEGATING_FORUM}):
		return ["skipped: the demonstration forums are missing; run deploy/demo_data.py first"]
	for label, step in (("retention", retention_in_force), ("disposals", disposals_due),
			("exports", export_profiles), ("time targets", forum_time_targets), ("layout", saved_layout),
			("delegate", chairs_delegate), ("links", external_links),
			("reference import profiles", reference_import_profiles)):
		frappe.db.savepoint("gaps_platform")
		try:
			step(frappe, notes)
		except Exception as exc:  # one step failing must not undo the others
			frappe.db.rollback(save_point="gaps_platform")
			frappe.set_user("Administrator")
			notes.append(f"failed: {label}: {exc}")
	return notes
