"""The governed outbound export (G-19, P-20, E-19).

Connectors are out of scope (S-2), so the outbound half of every integration
requirement is a file: forum data for the risk appetite system and the risk
register, policy metadata for the GRC platform, escalation status for issue
management. ``importing.export_records`` recorded such a file as an
``Export Batch`` but nothing called it, so no file could be produced. This
module is the caller, and the rules that make an export governed:

* **What goes in is configuration.** An ``Export Profile`` names the record
  type, the fields and their column headings, the filter, the format (CSV or
  JSON) and the roles that may run it. The record's identifier is always the
  first column: it is the linkage the receiving system quotes back.
* **Permissions apply as they do on screen.** Rows are read through
  ``frappe.get_list`` as the person running the export, so the sensitive
  escalation restriction and document handling hold exactly as on the
  registers. On top of that, **restricted records are left out by default**:
  a sensitive escalation, a confidential forum, a confidential or restricted
  document stays out of the file even for someone who may read it, unless the
  profile says otherwise — a file travels further than a screen. A scheduled
  drop never includes them.
* **Every run is logged.** Each file is an ``Export Batch``: who, when, which
  profile and target system, the filter and fields, the SHA-256 of the file,
  the identifier of every record in it (the linkage register), how many were
  left out as restricted, and whether the row limit was reached. The file
  itself is kept on the batch as a private attachment.
* **Capped and formula-safe.** At most 5,000 rows, the same limit as the list
  pages' CSV export. A CSV cell that a spreadsheet would run as a formula (a
  leading ``= + - @``) is written as text, as ``policy.reporting`` and the list
  pages already do.
* **Nothing leaves the network unless configured.** A manual run hands the
  file to the person who asked, in their browser. A scheduled run writes to a
  folder **under the drop root the server administrator put in the site
  configuration** (``consilium_export_drop_root``); a profile names only a
  sub-folder. With no root configured, a scheduled run writes nothing and says
  so on the profile. The platform opens no connection to anyone.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, getdate, now, now_datetime

from consilium.consilium_core import audit, importing

PROFILE = "Export Profile"
BATCH = "Export Batch"

#: The most rows one file may carry, whatever a profile asks for.
HARD_CAP = 5000

#: Roles that may run any profile, and see every export batch.
ADMIN_ROLES = ("System Manager", "Consilium Administrator")

#: The site-configuration key naming the only place a scheduled drop may write.
DROP_ROOT_KEY = "consilium_export_drop_root"

#: Option values of the profile's schedule field (configuration, not states).
SCHEDULE_MANUAL = "Manual Only"
SCHEDULE_DAILY = "Daily"
SCHEDULE_WEEKLY = "Weekly"

FORMAT_CSV = "CSV"
FORMAT_JSON = "JSON"

#: Columns computed from related records rather than read from a field.
PSEUDO_FIELDS = {
	"external_references": "External references",
	"pathway_forums": "Governance forums on the pathway",
}

#: Per record type: the standard columns, and the filter that leaves
#: restricted records out. Fieldnames a site does not have are skipped.
SOURCES: dict[str, dict] = {
	"Governance Forum": {
		"fields": [
			("forum_name", "Forum"), ("forum_type", "Forum type"), ("compliance_status", "Compliance status"),
			("is_active", "Active"), ("committee_chair", "Chair"), ("sponsor", "Sponsor"),
			("secretary", "Secretary"), ("forum_owner", "Forum owner"),
			("primary_risk_category", "Primary risk category"),
			("owning_operating_group", "Owning operating group"),
			("owning_line_of_business", "Owning line of business"), ("parent_forum", "Parent forum"),
			("regulatory_required", "Regulatory required"), ("established_on", "Established on"),
			("next_review_on", "Next review on"), ("last_attested_on", "Last attested on"),
			("disbanded_on", "Disbanded on"), ("external_references", "External references"),
		],
		"unrestricted": [["confidential", "=", 0]],
	},
	"Governing Document": {
		"fields": [
			("document_name", "Document"), ("document_type", "Document type"),
			("lifecycle_phase", "Lifecycle phase"), ("version_label", "Version"),
			("document_owner", "Owner"), ("document_approver", "Approver"),
			("approving_forum", "Approving forum"), ("parent_document", "Parent document"),
			("primary_risk_category", "Primary risk category"),
			("owning_operating_group", "Owning operating group"),
			("owning_line_of_business", "Owning line of business"),
			("material_entity_impact", "Material entity impact"),
			("regulatory_required", "Regulatory required"),
			("handling_classification", "Handling"), ("effective_on", "Effective on"),
			("next_review_on", "Next review on"), ("retired_on", "Retired on"),
			("external_references", "External references"),
		],
		"unrestricted": [["confidential", "=", 0],
			["handling_classification", "not in", ["Confidential", "Restricted"]]],
	},
	"Escalation Matter": {
		"fields": [
			("escalation_title", "Title"), ("escalation_type", "Escalation type"), ("severity", "Severity"),
			("status", "Status"), ("tier_1_risk_type", "Risk type"),
			("organizational_level", "Organisational level"), ("response_owner", "Response owner"),
			("accountable_executive", "Accountable executive"),
			("risk_appetite_breach", "Risk appetite breached"),
			("risk_appetite_reference", "Risk appetite reference"),
			("related_risk_reference", "Related risk reference"),
			("external_reference", "Tracked externally as"), ("pathway_forums", "Governance forums on the pathway"),
			("opened_on", "Opened on"), ("closed_on", "Closed on"),
			("external_references", "External references"),
		],
		"unrestricted": [["sensitive", "=", 0]],
	},
}


# ------------------------------------------------------------ configuration


def _lines(value) -> list[str]:
	return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _loads(value):
	if not value:
		return {}
	if isinstance(value, (dict, list)):
		return value
	return json.loads(value)


def columns_for(profile) -> list[tuple[str, str]]:
	"""``[(fieldname, heading)]`` in file order, identifier first."""
	source = SOURCES[profile.source_doctype]
	meta = frappe.get_meta(profile.source_doctype)
	chosen = []
	for line in _lines(profile.export_fields):
		field, _sep, heading = line.partition("=")
		field, heading = field.strip(), heading.strip()
		if not heading:
			heading = PSEUDO_FIELDS.get(field) or (meta.get_label(field) if meta.has_field(field) else field)
		chosen.append((field, heading))
	if not chosen:
		chosen = [(f, h) for f, h in source["fields"] if f in PSEUDO_FIELDS or meta.has_field(f)]
	return [("name", "Identifier")] + [(f, h) for f, h in chosen if f != "name"]


def validate_profile(profile) -> None:
	"""The Export Profile controller's checks: every name is real, nothing escapes the drop root."""
	if profile.source_doctype not in SOURCES:
		frappe.throw(_("{0} records cannot be exported.").format(profile.source_doctype))
	meta = frappe.get_meta(profile.source_doctype)
	for line in _lines(profile.export_fields):
		field = line.partition("=")[0].strip()
		if field == "name" or field in PSEUDO_FIELDS:
			continue
		if not meta.has_field(field):
			frappe.throw(_("{0} has no field {1}.").format(profile.source_doctype, field), title=_("Unknown Field"))
		if meta.get_field(field).fieldtype in frappe.model.table_fields:
			frappe.throw(_("{0} is a table and cannot be a column.").format(field), title=_("Unknown Field"))
	try:
		filters = _loads(profile.record_filter)
	except ValueError:
		frappe.throw(_("The filter is not valid JSON."), title=_("Invalid Filter"))
	if not isinstance(filters, dict):
		frappe.throw(_("The filter must be field and value pairs, such as {\"is_active\": 1}."),
			title=_("Invalid Filter"))
	for field in filters:
		if field != "name" and not meta.has_field(field):
			frappe.throw(_("The filter names {0}, which {1} does not have.").format(field, profile.source_doctype),
				title=_("Invalid Filter"))
	for role in _lines(profile.allowed_roles):
		if not frappe.db.exists("Role", role):
			frappe.throw(_("There is no role called {0}.").format(role), title=_("Unknown Role"))
	if profile.max_rows is not None and int(profile.max_rows or 0) <= 0:
		profile.max_rows = HARD_CAP
	profile.max_rows = min(int(profile.max_rows or HARD_CAP), HARD_CAP)
	folder = (profile.drop_folder or "").strip()
	if folder and (folder.startswith((".", "/", "\\")) or ".." in folder or ":" in folder
			or not re.fullmatch(r"[A-Za-z0-9 _\-/]+", folder)):
		frappe.throw(_("The drop folder is a folder name under the server's drop root, such as risk-register. "
			"It cannot be a full path or climb out of the root."), title=_("Invalid Drop Folder"))
	profile.drop_folder = folder or None
	if profile.schedule and profile.schedule != SCHEDULE_MANUAL:
		if not profile.drop_folder:
			frappe.throw(_("A scheduled drop needs a drop folder."), title=_("Drop Folder Required"))
		if not profile.run_as:
			frappe.throw(_("A scheduled drop needs the person whose read access it uses."),
				title=_("Run As Required"))


# ---------------------------------------------------------------- who may run


def _roles(user: str) -> set[str]:
	return set(frappe.get_roles(user))


def may_run(profile, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Guest" or not int(profile.is_active or 0):
		return False
	roles = _roles(user)
	allowed = roles.intersection(ADMIN_ROLES) or roles.intersection(_lines(profile.allowed_roles))
	return bool(allowed) and bool(frappe.has_permission(profile.source_doctype, "read", user=user))


def _refuse(profile, reason: str):
	audit.refuse(
		reason,
		subject_doctype=PROFILE,
		subject_name=profile.name,
		attempted_action="Export",
		control="export profile",
		context={"source_doctype": profile.source_doctype},
	)


# ------------------------------------------------------------------ the rows


def csv_cell(value) -> str:
	"""A cell a spreadsheet will not execute: a leading = + - @ is quoted as text."""
	text = "" if value is None else str(value)
	return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def _pseudo_values(doctype: str, names: list[str], field: str) -> dict[str, str]:
	if not names:
		return {}
	out: dict[str, list[str]] = {}
	if field == "external_references":
		for row in frappe.get_all(
			"External Reference",
			filters={"subject_doctype": doctype, "subject_name": ["in", names], "is_active": 1},
			fields=["subject_name", "external_system", "external_key"],
			order_by="external_system asc, external_key asc",
		):
			out.setdefault(row.subject_name, []).append(f"{row.external_system}:{row.external_key}")
	elif field == "pathway_forums" and doctype == "Escalation Matter":
		for row in frappe.get_all(
			"Escalation Forum Link",
			filters={"parenttype": doctype, "parent": ["in", names]},
			fields=["parent", "governance_forum"],
			order_by="idx asc",
		):
			out.setdefault(row.parent, []).append(row.governance_forum)
	return {name: "; ".join(values) for name, values in out.items()}


def collect(profile, user: str, include_restricted: bool) -> dict:
	"""The rows a run would write, as ``user`` may read them."""
	columns = columns_for(profile)
	real = [f for f, _h in columns if f not in PSEUDO_FIELDS]
	cap = min(int(profile.max_rows or HARD_CAP), HARD_CAP)
	filters = [[k, "=", v] if not isinstance(v, (list, tuple)) else [k, *v]
		for k, v in _loads(profile.record_filter).items()]
	restricted_out = [] if include_restricted else SOURCES[profile.source_doctype]["unrestricted"]
	meta = frappe.get_meta(profile.source_doctype)
	restricted_out = [f for f in restricted_out if meta.has_field(f[0])]

	rows = frappe.get_list(
		profile.source_doctype, filters=filters + restricted_out, fields=real, order_by="name asc",
		limit_page_length=cap + 1, user=user,
	)
	capped = len(rows) > cap
	rows = rows[:cap]
	excluded = 0
	if restricted_out:
		readable = frappe.get_list(profile.source_doctype, filters=filters, pluck="name", limit_page_length=0,
			user=user)
		excluded = max(0, len(readable) - len(frappe.get_list(
			profile.source_doctype, filters=filters + restricted_out, pluck="name", limit_page_length=0, user=user)))
	names = [row.name for row in rows]
	for field, _heading in columns:
		if field in PSEUDO_FIELDS:
			values = _pseudo_values(profile.source_doctype, names, field)
			for row in rows:
				row[field] = values.get(row.name, "")
	return {"columns": columns, "rows": rows, "capped": capped, "excluded": excluded}


def render(profile, collected: dict, stamp: str) -> str:
	columns = collected["columns"]
	if profile.file_format == FORMAT_JSON:
		return json.dumps({
			"profile": profile.name,
			"profile_title": profile.profile_title,
			"source": profile.source_doctype,
			"target_system": profile.target_system,
			"generated_on": stamp,
			"columns": [{"field": f, "heading": h} for f, h in columns],
			"records": [{f: row.get(f) for f, _h in columns} for row in collected["rows"]],
		}, indent=1, default=str)
	buffer = io.StringIO()
	writer = csv.writer(buffer)
	writer.writerow([h for _f, h in columns])
	for row in collected["rows"]:
		writer.writerow([csv_cell(row.get(f)) for f, _h in columns])
	return buffer.getvalue()


def _file_name(profile, batch: str, stamp) -> str:
	slug = re.sub(r"[^a-z0-9]+", "-", (profile.profile_title or profile.name).lower()).strip("-") or "export"
	ext = "json" if profile.file_format == FORMAT_JSON else "csv"
	return f"{slug}-{batch}-{get_datetime(stamp).strftime('%Y%m%d-%H%M')}.{ext}"


def generate(profile, *, user: str, include_restricted: bool, delivered_to: str) -> dict:
	"""Collect, render and record one file. Returns the batch, its name and content."""
	stamp = now()
	collected = collect(profile, user, include_restricted)
	content = render(profile, collected, stamp)
	names = [row.name for row in collected["rows"]]
	batch, _content = importing.export_records(
		export_profile=profile.name,
		target_system=profile.target_system,
		source_doctype=profile.source_doctype,
		fields=[f for f, _h in collected["columns"]],
		filters=_loads(profile.record_filter),
		rows=collected["rows"],
		content=content,
		extra={
			"generated_by": user,
			"generated_on": stamp,
			"file_format": profile.file_format or FORMAT_CSV,
			"record_names": json.dumps(names),
			"excluded_count": collected["excluded"],
			"capped": 1 if collected["capped"] else 0,
			"delivered_to": delivered_to,
			"export_filter": json.dumps({
				"filter": _loads(profile.record_filter),
				"fields": [f for f, _h in collected["columns"]],
				"include_restricted": bool(include_restricted),
				"row_limit": min(int(profile.max_rows or HARD_CAP), HARD_CAP),
			}),
		},
	)
	file_name = _file_name(profile, batch.name, stamp)
	saved = frappe.get_doc({
		"doctype": "File",
		"file_name": file_name,
		"attached_to_doctype": BATCH,
		"attached_to_name": batch.name,
		"is_private": 1,
		"content": content,
	}).insert(ignore_permissions=True)
	batch.db_set("output_file", saved.file_url, update_modified=False)
	frappe.db.set_value(PROFILE, profile.name, {
		"last_run_on": stamp, "last_export_batch": batch.name,
		"last_run_note": _("{0} records written by {1}.").format(len(names), user),
	}, update_modified=False)
	return {"batch": batch, "file_name": file_name, "content": content, "collected": collected}


# ------------------------------------------------------------- the endpoints


def _load_profile(name: str):
	if not name or not frappe.db.exists(PROFILE, name):
		frappe.throw(_("There is no export profile {0}.").format(name), frappe.DoesNotExistError)
	return frappe.get_doc(PROFILE, name)


def _summary(profile) -> dict:
	filters = _loads(profile.record_filter)
	return {
		"name": profile.name,
		"profile_title": profile.profile_title,
		"description": profile.description,
		"source_doctype": profile.source_doctype,
		"target_system": profile.target_system,
		"target_title": frappe.db.get_value("External System", profile.target_system, "title"),
		"file_format": profile.file_format,
		"columns": [h for _f, h in columns_for(profile)],
		"filter": filters,
		"include_restricted": int(profile.include_restricted or 0),
		"row_limit": min(int(profile.max_rows or HARD_CAP), HARD_CAP),
		"schedule": profile.schedule,
		"last_run_on": str(profile.last_run_on) if profile.last_run_on else None,
		"last_run_note": profile.last_run_note,
	}


@frappe.whitelist(methods=["GET"])
def my_profiles() -> dict:
	"""The profiles the caller may run, and the exports they may look back on."""
	user = frappe.session.user
	if user == "Guest":
		raise frappe.PermissionError(_("Sign in to export records."))
	profiles = [
		_summary(profile)
		for profile in (frappe.get_doc(PROFILE, name) for name in
			frappe.get_all(PROFILE, filters={"is_active": 1}, pluck="name", order_by="profile_title asc"))
		if may_run(profile, user)
	]
	sees_all = bool(_roles(user).intersection(ADMIN_ROLES)) or bool(frappe.has_permission(BATCH, "read"))
	filters = {} if sees_all else {"generated_by": user}
	batches = frappe.get_all(
		BATCH, filters=filters,
		fields=["name", "export_profile", "source_doctype", "target_system", "generated_on", "generated_by",
			"record_count", "excluded_count", "capped", "file_format", "status", "delivered_to", "output_sha256"],
		order_by="generated_on desc", limit_page_length=50,
	)
	titles = dict(frappe.get_all(PROFILE, fields=["name", "profile_title"], as_list=True))
	for row in batches:
		row["profile_title"] = titles.get(row.export_profile, row.export_profile)
	return {
		"profiles": profiles,
		"batches": batches,
		"sees_all": sees_all,
		"may_configure": bool(frappe.has_permission(PROFILE, "create")),
		"drop_root_configured": bool(frappe.conf.get(DROP_ROOT_KEY)),
	}


@frappe.whitelist(methods=["POST"])
def export_now(profile: str) -> dict:
	"""Run a profile for the caller and hand them the file. Logged as an Export Batch."""
	doc = _load_profile(profile)
	user = frappe.session.user
	if not may_run(doc, user):
		_refuse(doc, _("{0} may not run the export {1}: it needs one of the profile's roles and read access "
			"to {2} records.").format(user, doc.profile_title, doc.source_doctype))
	out = generate(doc, user=user, include_restricted=bool(int(doc.include_restricted or 0)),
		delivered_to=_("Downloaded by {0}").format(user))
	batch = out["batch"]
	return {
		"batch": batch.name,
		"file_name": out["file_name"],
		"content": out["content"],
		"mime": "application/json" if doc.file_format == FORMAT_JSON else "text/csv",
		"record_count": batch.record_count,
		"excluded": out["collected"]["excluded"],
		"capped": out["collected"]["capped"],
		"sha256": batch.output_sha256,
	}


# --------------------------------------------------------------- scheduled


def _due(profile, today) -> bool:
	if not profile.last_run_on:
		return True
	last = getdate(profile.last_run_on)
	if profile.schedule == SCHEDULE_WEEKLY:
		return last <= add_days(today, -7)
	return last < today


def drop_path(profile) -> str | None:
	"""The folder a scheduled run writes to, or None when no root is configured."""
	root = frappe.conf.get(DROP_ROOT_KEY)
	if not root or not profile.drop_folder:
		return None
	root = os.path.realpath(root)
	target = os.path.realpath(os.path.join(root, profile.drop_folder))
	if os.path.commonpath([root, target]) != root:
		return None
	return target


def run_scheduled(as_of=None) -> list[str]:
	"""Daily: write the due scheduled drops. Returns the batches written.

	Each profile in its own savepoint, so one failing drop does not stop the
	rest. A profile with no configured root is skipped with a note, never
	written somewhere else.
	"""
	today = getdate(as_of or now_datetime())
	written = []
	for name in frappe.get_all(PROFILE, filters={"is_active": 1, "schedule": ["!=", SCHEDULE_MANUAL]}, pluck="name"):
		profile = frappe.get_doc(PROFILE, name)
		if not _due(profile, today):
			continue
		folder = drop_path(profile)
		if not folder:
			frappe.db.set_value(PROFILE, name, "last_run_note",
				_("Not written: no export drop root is configured on this server ({0}).").format(DROP_ROOT_KEY),
				update_modified=False)
			continue
		frappe.db.savepoint("export_drop")
		try:
			out = generate(profile, user=profile.run_as, include_restricted=False, delivered_to=folder)
			os.makedirs(folder, exist_ok=True)
			with open(os.path.join(folder, out["file_name"]), "w", encoding="utf-8", newline="") as handle:
				handle.write(out["content"])
			out["batch"].db_set({"status": "Delivered", "delivered_to": os.path.join(folder, out["file_name"])},
				update_modified=False)
			written.append(out["batch"].name)
		except Exception:
			frappe.db.rollback(save_point="export_drop")
			frappe.log_error(title=f"Consilium: scheduled export {name} failed", message=frappe.get_traceback())
	return written
