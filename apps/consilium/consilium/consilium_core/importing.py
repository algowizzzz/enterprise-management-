"""The governed file import pipeline — the connector replacement.

    file → Import Batch (staged) → Import Row (per record, validated)
         → handling rules applied → commit → target records + External Reference

Nothing here calls anything. A batch keeps the file exactly as received with its
hash, every row keeps both its raw and its mapped payload, and the foreign
identifier survives as an ``External Reference`` with a known provenance batch.
When a connector is eventually built it populates the same rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json

import frappe
from frappe import _
from frappe.utils import getdate, now

TRANSFORMS = {
    "None": lambda value, mapping: value,
    "Trim": lambda value, mapping: (value or "").strip(),
    "Upper": lambda value, mapping: (value or "").upper(),
    "Date Parse": lambda value, mapping: str(getdate(value)) if value else None,
}


def _loads(value, default=None):
    if not value:
        return default if default is not None else {}
    if isinstance(value, dict | list):
        return value
    return json.loads(value)


def read_rows_from_file(file_url: str) -> list[dict]:
    """Read a delimited file already attached to the site. No network access."""
    content = frappe.get_doc("File", {"file_url": file_url}).get_content()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


def sha256_of(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _lookup(value, mapping, profile, messages: list[str]):
    """Resolve a taxonomy value, applying the profile's unknown-value handling."""
    if value in (None, ""):
        return None, True
    existing = frappe.db.get_value(mapping.lookup_doctype, {mapping.lookup_field: value}, "name")
    if existing:
        return existing, True

    handling = profile.on_unknown_taxonomy
    if handling == "Create Inactive":
        doc = frappe.get_doc({"doctype": mapping.lookup_doctype, mapping.lookup_field: value, "is_active": 0})
        title_field = frappe.get_meta(mapping.lookup_doctype).get_title_field()
        if title_field and not doc.get(title_field):
            doc.set(title_field, value)
        doc.insert(ignore_permissions=True)
        messages.append(f"{mapping.target_fieldname}: created inactive taxonomy value {value!r}")
        return doc.name, True
    if handling == "Map To Default":
        messages.append(f"{mapping.target_fieldname}: unknown value {value!r} mapped to the default")
        return mapping.default_value, True
    if handling == "Warn And Continue":
        messages.append(f"{mapping.target_fieldname}: unknown value {value!r} left empty")
        return None, True
    messages.append(f"{mapping.target_fieldname}: unknown value {value!r}")
    return None, False


def map_row(raw: dict, profile, messages: list[str]) -> tuple[dict, bool]:
    mapped, ok = {}, True
    for mapping in profile.mappings:
        value = raw.get(mapping.source_column)
        if mapping.transform == "Lookup":
            value, resolved = _lookup(value, mapping, profile, messages)
            ok = ok and resolved
        else:
            value = TRANSFORMS[mapping.transform](value, mapping)

        if value in (None, "") and mapping.default_value:
            value = mapping.default_value
        if value in (None, "") and mapping.is_required:
            handling = profile.on_missing_required
            messages.append(f"{mapping.target_fieldname}: required value missing")
            if handling == "Reject Batch":
                raise BatchRejected(f"Required value missing for {mapping.target_fieldname}")
            if handling in ("Reject Row", "Default"):
                ok = False
        mapped[mapping.target_fieldname] = value
    return mapped, ok


class BatchRejected(frappe.ValidationError):
    pass


def validate_batch(batch, rows: list[dict] | None = None) -> dict:
    """Stage and validate every row. Writes no target record."""
    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)
    profile = frappe.get_doc("Import Profile", batch.import_profile)
    if rows is None:
        if not batch.source_file:
            frappe.throw(_("Batch {0} has no source file and no rows were supplied.").format(batch.name))
        rows = read_rows_from_file(batch.source_file)

    # Staged rows from an earlier validation are cleared without the framework's
    # Deleted Document archive: on PostgreSQL a row's JSON ``messages`` comes back
    # as a list, the archive's serialiser refuses a list ("Messages cannot be a
    # list"), and so validating a batch a second time failed on any row that had
    # a message. See ``_clear_staged_rows``, which this shares.
    _clear_staged_rows(batch)

    counts = {"Valid": 0, "Warning": 0, "Error": 0}
    try:
        for index, raw in enumerate(rows, start=1):
            messages: list[str] = []
            mapped, ok = map_row(raw, profile, messages)
            status = "Valid" if ok else "Error"
            if ok and messages:
                status = "Warning"
            external_key = raw.get(profile.external_key_column) if profile.external_key_column else None
            frappe.get_doc(
                {
                    "doctype": "Import Row",
                    "import_batch": batch.name,
                    "row_number": index,
                    "raw_payload": json.dumps(raw),
                    "mapped_payload": json.dumps(mapped, default=str),
                    "status": status,
                    "messages": json.dumps(messages),
                    "external_key": external_key,
                }
            ).insert(ignore_permissions=True)
            counts[status] += 1
    except BatchRejected as exc:
        batch.status = "Rejected"
        batch.validation_report = json.dumps({"rejected": str(exc)})
        batch.save(ignore_permissions=True)
        raise

    valid, warnings, errors = counts["Valid"], counts["Warning"], counts["Error"]
    batch.target_doctype = profile.target_doctype
    batch.row_count = len(rows)
    batch.valid_count = valid
    batch.warning_count = warnings
    batch.error_count = errors
    batch.status = "Rejected" if errors and not (valid + warnings) else "Validated"
    batch.validation_report = json.dumps(
        {"rows": len(rows), "valid": valid, "warnings": warnings, "errors": errors}
    )
    batch.save(ignore_permissions=True)
    return {"valid": valid, "warnings": warnings, "errors": errors}


def _existing_target(profile, mapped: dict, external_key: str | None) -> str | None:
    if profile.key_strategy == "Always Insert":
        return None
    if profile.key_strategy == "External Key" and external_key:
        return frappe.db.get_value(
            "External Reference",
            {
                "external_system": profile.source_system,
                "external_key": external_key,
                "subject_doctype": profile.target_doctype,
            },
            "subject_name",
        )
    if profile.key_strategy == "Natural Key" and profile.natural_key_fieldname:
        value = mapped.get(profile.natural_key_fieldname)
        if value:
            return frappe.db.get_value(profile.target_doctype, {profile.natural_key_fieldname: value}, "name")
    return None


def commit_batch(batch) -> dict:
    """Write the staged rows the flags say may be committed."""
    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)
    if not batch.is_editable:
        frappe.throw(_("Batch {0} has already been committed.").format(batch.name))
    profile = frappe.get_doc("Import Profile", batch.import_profile)

    committed, skipped, failed = [], [], []
    for name in frappe.get_all(
        "Import Row", filters={"import_batch": batch.name}, pluck="name", order_by="row_number asc"
    ):
        row = frappe.get_doc("Import Row", name)
        if not row.is_committable:
            skipped.append(row.name)
            continue

        mapped = _loads(row.mapped_payload)
        existing = _existing_target(profile, mapped, row.external_key)
        try:
            if existing:
                if profile.on_duplicate_key == "Skip":
                    row.status = "Skipped"
                    row.save(ignore_permissions=True)
                    skipped.append(row.name)
                    continue
                if profile.on_duplicate_key == "Reject":
                    row.status = "Error"
                    row.messages = json.dumps(_loads(row.messages, []) + ["duplicate key rejected"])
                    row.save(ignore_permissions=True)
                    failed.append(row.name)
                    continue
                target = frappe.get_doc(profile.target_doctype, existing)
                for field, value in mapped.items():
                    target.set(field, value)
                target.save(ignore_permissions=True)
            else:
                target = frappe.get_doc({"doctype": profile.target_doctype, **mapped}).insert(
                    ignore_permissions=True
                )
        except Exception as exc:
            row.status = "Error"
            row.messages = json.dumps(_loads(row.messages, []) + [f"{type(exc).__name__}: {exc}"])
            row.save(ignore_permissions=True)
            failed.append(row.name)
            continue

        if row.external_key:
            record_external_reference(
                subject_doctype=profile.target_doctype,
                subject_name=target.name,
                external_system=profile.source_system,
                external_key=row.external_key,
                source_import_batch=batch.name,
            )

        row.status = "Committed"
        row.target_name = target.name
        row.save(ignore_permissions=True)
        committed.append(row.name)

    batch.status = "Committed" if not (skipped or failed) else "Partially Committed"
    batch.committed_on = now()
    batch.save(ignore_permissions=True)
    return {"committed": committed, "skipped": skipped, "failed": failed}


def record_external_reference(
    *,
    subject_doctype: str,
    subject_name: str,
    external_system: str,
    external_key: str,
    external_type: str | None = None,
    label: str | None = None,
    source_import_batch: str | None = None,
):
    """Upsert the foreign identifier that stands where a connector would be."""
    existing = frappe.db.get_value(
        "External Reference",
        {
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "external_system": external_system,
            "external_key": external_key,
        },
        "name",
    )
    values = {
        "external_type": external_type,
        "label": label,
        "last_seen_on": frappe.utils.nowdate(),
        "source_import_batch": source_import_batch,
    }
    if existing:
        doc = frappe.get_doc("External Reference", existing)
        doc.update({k: v for k, v in values.items() if v is not None})
        doc.save(ignore_permissions=True)
        return doc
    return frappe.get_doc(
        {
            "doctype": "External Reference",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "external_system": external_system,
            "external_key": external_key,
            **values,
        }
    ).insert(ignore_permissions=True)


def export_records(
    *,
    export_profile: str,
    target_system: str,
    source_doctype: str,
    fields: list[str],
    filters: dict | None = None,
):
    """Generate an outbound file and record the batch that produced it."""
    rows = frappe.get_all(source_doctype, filters=filters or {}, fields=fields, order_by="name asc")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    content = buffer.getvalue()

    return frappe.get_doc(
        {
            "doctype": "Export Batch",
            "export_profile": export_profile,
            "target_system": target_system,
            "source_doctype": source_doctype,
            "generated_on": now(),
            "generated_by": frappe.session.user,
            "record_count": len(rows),
            "output_sha256": sha256_of(content),
            "export_filter": json.dumps(filters or {}),
            "status": "Generated",
        }
    ).insert(ignore_permissions=True), content


# ---------------------------------------------------------------------------
# Batch review from the portal (CS-11).
#
# Validation and commit had no caller outside the tests, so a file could only
# be brought in from a Python shell. These endpoints are the review screen's
# way in. They add no second pipeline: every one of them hands the batch to
# `validate_batch` or `commit_batch` above. What they add is the gate —
# who may look, who may act — and the two decisions a reviewer makes that the
# pipeline had no word for: leaving a row out, and discarding a whole batch.
#
# Permission is the Import Batch DocType's own: read to look, write to act,
# create to upload. Committing also needs the right to create the records the
# batch would write, because the pipeline writes them on the reviewer's
# behalf and must not become a way round the target's permissions.
# ---------------------------------------------------------------------------

#: The status a discarded batch is written with. A value handed to the flag map,
#: never compared: what it *means* (no longer editable, no longer open) is read
#: from `is_editable` and `is_open` like every other state.
DISCARDED_BATCH_STATUS = "Rejected"

#: The status a row the reviewer leaves out is written with. Its flags clear
#: `is_committable`, which is the only thing `commit_batch` reads.
EXCLUDED_ROW_STATUS = "Skipped"

#: The largest file the portal accepts. A governed import is a register or a
#: feed extract, not a data warehouse; anything bigger belongs in several batches.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: Row payloads returned to the screen. The review page pages them in memory.
MAX_REVIEW_ROWS = 5000


def _batch_for(batch: str, ptype: str):
    doc = frappe.get_doc("Import Batch", batch)
    doc.check_permission(ptype)
    return doc


def _preparers(target_doctype: str) -> list:
    """Module hooks that finish a row's payload before Core commits it.

    A flat file cannot express a child table, so a module that needs one (the
    escalation module's impacted entities) registers a preparer under the
    ``consilium_import_preparers`` hook, keyed by the target DocType. Core
    stays ignorant of the modules; the module stays out of Core's commit.
    """
    hooks = frappe.get_hooks("consilium_import_preparers") or {}
    paths = hooks.get(target_doctype) or []
    if isinstance(paths, str):
        paths = [paths]
    return [frappe.get_attr(path) for path in paths]


def review_context(batch) -> dict:
    """The review screen's payload: the batch, its profile, and every staged row."""
    if isinstance(batch, str):
        batch = frappe.get_doc("Import Batch", batch)
    profile = frappe.get_doc("Import Profile", batch.import_profile)
    rows = []
    for row in frappe.get_all(
        "Import Row",
        filters={"import_batch": batch.name},
        fields=["name", "row_number", "status", "is_committable", "messages", "raw_payload",
                "mapped_payload", "external_key", "target_name"],
        order_by="row_number asc",
        limit_page_length=MAX_REVIEW_ROWS,
    ):
        row["messages"] = _loads(row["messages"], [])
        row["raw_payload"] = _loads(row["raw_payload"])
        row["mapped_payload"] = _loads(row["mapped_payload"])
        rows.append(row)

    editable = bool(batch.is_editable)
    committable = sum(1 for row in rows if row["is_committable"])
    may_write = bool(frappe.has_permission("Import Batch", "write", doc=batch))
    may_create_target = bool(frappe.has_permission(profile.target_doctype, "create"))
    return {
        "batch": {
            field: (str(batch.get(field)) if batch.get(field) is not None else None)
            for field in ("name", "batch_reference", "source_system", "import_profile", "target_doctype",
                          "source_file", "source_file_sha256", "received_on", "imported_by", "status",
                          "committed_on")
        }
        | {
            "is_editable": int(batch.is_editable or 0),
            "is_open": int(batch.is_open or 0),
            "row_count": batch.row_count or 0,
            "valid_count": batch.valid_count or 0,
            "warning_count": batch.warning_count or 0,
            "error_count": batch.error_count or 0,
            "validation_report": _loads(batch.validation_report),
        },
        "profile": {
            "name": profile.name,
            "profile_title": profile.profile_title,
            "target_doctype": profile.target_doctype,
            "key_strategy": profile.key_strategy,
            "on_duplicate_key": profile.on_duplicate_key,
        },
        "rows": rows,
        "committable": committable,
        "actions": {
            "commit": editable and may_write and may_create_target and committable > 0,
            "discard": editable and may_write,
            "revalidate": editable and may_write and bool(batch.source_file),
            "exclude_row": editable and may_write,
        },
        "may_create_target": may_create_target,
    }


def _require_editable(batch) -> None:
    if not batch.is_editable:
        frappe.throw(
            _("Batch {0} is closed — committed or discarded — and cannot be changed.").format(batch.name),
            title=_("Batch Closed"),
        )


@frappe.whitelist(methods=["GET"])
def get_batch_review(batch: str) -> dict:
    return review_context(_batch_for(batch, "read"))


@frappe.whitelist(methods=["GET"])
def import_profiles() -> list[dict]:
    """The active profiles a file can be uploaded against, with the columns each expects."""
    if not frappe.has_permission("Import Batch", "create"):
        frappe.throw(_("You may not upload an import file."), frappe.PermissionError)
    out = []
    for name in frappe.get_all("Import Profile", filters={"is_active": 1}, pluck="name", order_by="profile_title asc"):
        profile = frappe.get_doc("Import Profile", name)
        columns = [
            {"column": m.source_column, "field": m.target_fieldname, "required": int(m.is_required or 0),
             "transform": m.transform}
            for m in profile.mappings
        ]
        if profile.external_key_column:
            columns.insert(0, {"column": profile.external_key_column, "field": None, "required": 0,
                               "transform": "External Key"})
        out.append({
            "name": profile.name,
            "profile_title": profile.profile_title,
            "source_system": profile.source_system,
            "target_doctype": profile.target_doctype,
            "may_create_target": bool(frappe.has_permission(profile.target_doctype, "create")),
            "columns": columns,
        })
    return out


@frappe.whitelist(methods=["POST"])
def upload_batch(import_profile: str, file_name: str, content: str, batch_reference: str | None = None) -> dict:
    """Stage an uploaded delimited file against a profile, and validate it.

    The file is kept exactly as received, privately attached to the batch with
    its hash, which is the pipeline's provenance promise. Nothing is written to
    a target record: that waits for a reviewer's commit.
    """
    if not frappe.has_permission("Import Batch", "create"):
        frappe.throw(_("You may not upload an import file."), frappe.PermissionError)
    profile = frappe.get_doc("Import Profile", import_profile)
    if not profile.is_active:
        frappe.throw(_("Import profile {0} is not active.").format(profile.name), title=_("Profile Inactive"))
    raw = (content or "").encode("utf-8")
    if not raw.strip():
        frappe.throw(_("The file is empty."), title=_("Empty File"))
    if len(raw) > MAX_UPLOAD_BYTES:
        frappe.throw(_("The file is larger than {0} MB. Split it into several batches.").format(
            MAX_UPLOAD_BYTES // (1024 * 1024)), title=_("File Too Large"))
    file_name = frappe.utils.cstr(file_name or "import.csv").split("/")[-1].split("\\")[-1] or "import.csv"
    if not file_name.lower().endswith((".csv", ".txt")):
        frappe.throw(_("Upload a comma-separated file (.csv)."), title=_("Unsupported File"))

    batch = frappe.get_doc(
        {
            "doctype": "Import Batch",
            "batch_reference": (batch_reference or "").strip() or f"{profile.source_system}-{now()[:19]}",
            "source_system": profile.source_system,
            "import_profile": profile.name,
            "target_doctype": profile.target_doctype,
            "source_file_sha256": sha256_of(raw),
            "received_on": now(),
            "imported_by": frappe.session.user,
            "status": "Uploaded",
        }
    ).insert()
    stored = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "is_private": 1,
            "content": raw,
            "attached_to_doctype": "Import Batch",
            "attached_to_name": batch.name,
        }
    ).insert(ignore_permissions=True)
    batch.db_set("source_file", stored.file_url)
    _validate_keeping_the_batch(batch)
    return review_context(batch.name)


def _validate_keeping_the_batch(batch) -> None:
    """Validate; on a batch-level rejection keep the batch and its reason.

    `validate_batch` records the rejection and then raises, and a raise rolls
    the request back — taking the uploaded file and the recorded reason with it,
    so the reviewer would see an error and no batch. The rejection is the
    outcome here, not a failure, so it is kept.
    """
    try:
        validate_batch(batch.name)
    except BatchRejected:
        pass


@frappe.whitelist(methods=["POST"])
def revalidate_batch(batch: str) -> dict:
    """Validate the kept file again — after a taxonomy value it named has been added, say."""
    doc = _batch_for(batch, "write")
    _require_editable(doc)
    if not doc.source_file:
        frappe.throw(_("Batch {0} kept no file, so there is nothing to validate again.").format(doc.name),
                     title=_("No File"))
    _clear_staged_rows(doc)
    _validate_keeping_the_batch(doc)
    return review_context(doc.name)


def _clear_staged_rows(batch) -> None:
    """Remove a batch's staged rows before it is validated again.

    `validate_batch` deletes them itself, through the framework's delete, which
    first archives each row as a Deleted Document. On PostgreSQL a JSON column
    is read back as a list, and the archive's serialiser refuses a list — so any
    row carrying a message (every refused row does) made validating again fail.
    The rows are derived data, rebuilt from the kept file and its hash on the
    very next line, so they are deleted without the archive copy; retention's
    deletion guard still runs, because this is still the framework's delete.
    """
    for name in frappe.get_all("Import Row", filters={"import_batch": batch.name}, pluck="name"):
        frappe.delete_doc("Import Row", name, ignore_permissions=True, force=True, delete_permanently=True)


@frappe.whitelist(methods=["POST"])
def exclude_row(row: str, reason: str | None = None) -> dict:
    """Leave one staged row out of the commit. Validating the file again restores it."""
    doc = frappe.get_doc("Import Row", row)
    batch = _batch_for(doc.import_batch, "write")
    # An open batch has written nothing yet, so every one of its rows may still
    # be left out; the row carries no editable flag of its own to ask.
    _require_editable(batch)
    note = (reason or "").strip()
    doc.status = EXCLUDED_ROW_STATUS
    doc.messages = json.dumps(
        _loads(doc.messages, []) + [f"left out by {frappe.session.user}" + (f": {note}" if note else "")]
    )
    doc.save(ignore_permissions=True)
    return review_context(batch.name)


@frappe.whitelist(methods=["POST"])
def commit_reviewed_batch(batch: str) -> dict:
    """Commit the rows the flags mark committable, through Core's commit."""
    doc = _batch_for(batch, "write")
    _require_editable(doc)
    profile = frappe.get_doc("Import Profile", doc.import_profile)
    if not frappe.has_permission(profile.target_doctype, "create"):
        frappe.throw(
            _("You may not create {0} records, so you may not commit a batch that writes them.").format(
                _(profile.target_doctype)),
            frappe.PermissionError,
        )
    if not frappe.db.exists("Import Row", {"import_batch": doc.name, "is_committable": 1}):
        frappe.throw(_("Batch {0} has no row that may be committed.").format(doc.name), title=_("Nothing To Commit"))
    for prepare in _preparers(profile.target_doctype):
        prepare(doc)
    doc.reload()
    outcome = commit_batch(doc)
    context = review_context(doc.name)
    context["outcome"] = {key: len(value) for key, value in outcome.items()}
    return context


@frappe.whitelist(methods=["POST"])
def discard_batch(batch: str, reason: str) -> dict:
    """Close a batch without writing anything. The file, rows and reason are kept."""
    doc = _batch_for(batch, "write")
    _require_editable(doc)
    reason = (reason or "").strip()
    if not reason:
        frappe.throw(_("Say why the batch is being discarded."), title=_("Reason Required"))
    report = _loads(doc.validation_report)
    report["discarded"] = {"by": frappe.session.user, "on": now(), "reason": reason}
    doc.validation_report = json.dumps(report)
    doc.status = DISCARDED_BATCH_STATUS
    doc.save()
    return review_context(doc.name)
