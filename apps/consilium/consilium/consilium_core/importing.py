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

    for existing in frappe.get_all("Import Row", filters={"import_batch": batch.name}, pluck="name"):
        frappe.delete_doc("Import Row", existing, ignore_permissions=True, force=True)

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
