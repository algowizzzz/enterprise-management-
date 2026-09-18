"""Required metadata: finding what is missing, and correcting it in place.

E15-S5 asks for a maintenance view that lists incomplete records by field and
supports correcting them there. P-23 asks for something adjacent: when a
lifecycle event on one record invalidates a required field on **another**, the
other record's owner is given a task.

Both read the same definition of "required", which comes from two places and
neither of them is a constant in this file:

* the DocType's own ``reqd`` fields, which the framework already enforces on
  save but which historical and imported rows can predate;
* the ``required_fields`` list on the ``Document Template`` configured for the
  record's document type and action, which is P-15's per-type requirement and is
  editable without a deployment.

Correction is a normal write through the framework, so the permission engine and
the retention guards apply exactly as they would anywhere else.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

DOCTYPE = "Governing Document"

#: Fields the framework marks required but which are set by machinery rather
#: than by a person, so listing them as "missing metadata" would be noise.
_MACHINE_SET = {"workflow_state", "lifecycle_phase"}


def _loads(value):
    if not value:
        return []
    if isinstance(value, list | dict):
        return value
    return json.loads(value)


def template_required_fields(doctype: str, document_type: str | None, action: str = "New") -> list[str]:
    if doctype != DOCTYPE or not document_type:
        return []
    raw = frappe.db.get_value(
        "Document Template",
        {"document_type": document_type, "action": action, "is_active": 1},
        "required_fields",
    )
    fields = _loads(raw)
    if isinstance(fields, dict):
        fields = fields.get("fields", [])
    return [f for f in fields if isinstance(f, str)]


def required_fields_for(doc) -> list[str]:
    meta = frappe.get_meta(doc.doctype)
    required = {
        df.fieldname
        for df in meta.fields
        if df.reqd and df.fieldname not in _MACHINE_SET
    }
    required |= set(template_required_fields(doc.doctype, doc.get("document_type")))
    return sorted(f for f in required if meta.has_field(f))


def missing_fields(doc) -> list[str]:
    """Required fields this record does not carry a value for."""
    missing = []
    for fieldname in required_fields_for(doc):
        value = doc.get(fieldname)
        if isinstance(value, list):
            if not value:
                missing.append(fieldname)
        elif value in (None, "", 0) and not _is_meaningful_zero(doc, fieldname):
            missing.append(fieldname)
    return missing


def _is_meaningful_zero(doc, fieldname: str) -> bool:
    df = frappe.get_meta(doc.doctype).get_field(fieldname)
    return bool(df and df.fieldtype in ("Check", "Int", "Float", "Currency", "Percent"))


@frappe.whitelist()
def incomplete_records(doctype: str = DOCTYPE, limit: int = 200) -> list[dict]:
    """The maintenance view: records with required metadata missing (E15-S5)."""
    frappe.has_permission(doctype, "read", throw=True)
    out = []
    # get_list, not get_all: record-level restrictions apply here as on every
    # other read, and `limit` bounds what is returned, not what is examined.
    limit = int(limit or 200)
    for name in frappe.get_list(doctype, filters={"docstatus": ["<", 2]}, pluck="name", limit_page_length=0):
        doc = frappe.get_doc(doctype, name)
        missing = missing_fields(doc)
        if missing:
            out.append({"doctype": doctype, "name": name, "missing": missing})
            if len(out) >= limit:
                break
    return out


#: Fields a correction may not touch, whatever the DocType allows. The lifecycle
#: and its flags move only through transitions; the body and its version belong
#: to the version chain, and changing them is a new version, not a correction;
#: the implementation sign-offs are acts with their own entry points.
NOT_METADATA = {
    "lifecycle_phase", "workflow_state", "is_editable", "is_active", "requires_review",
    "current_version", "version_label", "body_text", "retired_on",
    "implementation_confirmed_by", "implementation_confirmed_on",
    "implementation_verified_by", "implementation_verified_on",
}

#: Field types a single-value correction can carry. Child tables are edited
#: where they are shown, not here.
_CORRECTABLE_TYPES = {
    "Data", "Small Text", "Text", "Long Text", "Select", "Link", "Dynamic Link", "Date", "Datetime",
    "Int", "Float", "Check",
}


def correctable_fields(doctype: str = DOCTYPE) -> list:
    """The fields a metadata correction may set, as DocField rows."""
    return [
        df for df in frappe.get_meta(doctype).fields
        if df.fieldtype in _CORRECTABLE_TYPES and df.fieldname not in NOT_METADATA
        and df.fieldname not in _MACHINE_SET and not df.read_only and not df.hidden
    ]


def _shown(value) -> str:
    return "" if value in (None, "") else str(value)


@frappe.whitelist(methods=["POST"])
def correct(doctype: str, name: str, values: dict | str, reason: str | None = None) -> dict:
    """Correct a record in place from the maintenance view.

    Deliberately a normal ``save``: the permission engine, the retention guards
    and the workflow's edit rules all apply. A maintenance screen that wrote
    around them would be a second, unaudited write path.

    A correction changes metadata only, and makes **no new version**: the body
    and the version chain are not touched, and neither is the lifecycle
    (``NOT_METADATA``). That is what lets a published document's owner fix a
    wrong review date without sending the document back through approval.
    The audit trail is the framework's change log (the DocType tracks changes)
    plus a comment on the record naming who corrected what, from what to what,
    and why.
    """
    if isinstance(values, str):
        values = json.loads(values)
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("write")
    meta = frappe.get_meta(doctype)
    allowed = {df.fieldname for df in correctable_fields(doctype)}
    for fieldname in values:
        if not meta.has_field(fieldname):
            frappe.throw(_("{0} has no field {1}.").format(doctype, fieldname))
        if fieldname not in allowed:
            frappe.throw(
                _("{0} is not metadata that can be corrected in place. The lifecycle moves by its actions, and "
                  "the body changes by a new version.").format(meta.get_label(fieldname)),
                title=_("Not Correctable"),
            )
    before = {fieldname: doc.get(fieldname) for fieldname in values}
    for fieldname, value in values.items():
        doc.set(fieldname, value)
    doc.save()
    changes = [
        {"field": fieldname, "label": meta.get_label(fieldname), "old": _shown(before[fieldname]),
         "new": _shown(doc.get(fieldname))}
        for fieldname in values
        if _shown(before[fieldname]) != _shown(doc.get(fieldname))
    ]
    if changes:
        # The comment is shown as HTML in the workspace timeline, so every value
        # in it — typed by a person — is escaped before it is stored.
        esc = frappe.utils.escape_html
        doc.add_comment(
            "Comment",
            _("Metadata corrected by {0}. {1}. Reason: {2}").format(
                esc(frappe.session.user),
                "; ".join(_("{0}: “{1}” to “{2}”").format(esc(c["label"]), esc(c["old"]), esc(c["new"]))
                          for c in changes),
                esc((reason or "").strip()) or _("none given"),
            ),
        )
    resolved = resolve_tasks_for(doctype, name, list(values))
    return {"doctype": doctype, "name": name, "missing": missing_fields(doc), "tasks_resolved": resolved,
            "changes": changes}


def _choices(df, current) -> list[dict] | None:
    """The values a Select or taxonomy Link may take for a correction.

    A taxonomy offers only its active values for a new choice (a retired value
    must not be newly applied), but the value the record already carries is
    always listed, retired or not, so the form shows the record as it stands.
    """
    if df.fieldtype == "Select":
        return [{"value": option, "label": option} for option in (df.options or "").split("\n") if option]
    if df.fieldtype != "Link" or not df.options or df.options in ("User", DOCTYPE):
        return None
    target = frappe.get_meta(df.options)
    if not target.has_field("is_active") or not frappe.has_permission(df.options, "read"):
        # No list to offer: the value is typed, and the framework validates the
        # reference when the record is saved.
        return None
    title = target.get_title_field() or "name"
    fields = ["name"] + ([title] if title != "name" else [])
    rows = frappe.get_list(df.options, filters={"is_active": 1}, fields=fields, order_by=f"{title} asc",
                           limit_page_length=500)
    out = [{"value": row["name"], "label": row.get(title) or row["name"]} for row in rows]
    if current and current not in {row["value"] for row in out}:
        label = frappe.db.get_value(df.options, current, title) if title != "name" else current
        out.insert(0, {"value": current, "label": _("{0} (retired)").format(label or current)})
    return out


def correction_context(doc) -> dict:
    from consilium.policy import lifecycle

    missing = set(missing_fields(doc))
    can_correct = bool(
        lifecycle.may_take(doc, "correct_metadata") and frappe.has_permission(DOCTYPE, "write", doc=doc)
    )
    fields = []
    if can_correct:
        required = set(required_fields_for(doc))
        for df in correctable_fields(doc.doctype):
            value = doc.get(df.fieldname)
            fields.append({
                "fieldname": df.fieldname,
                "label": df.label or df.fieldname,
                "fieldtype": df.fieldtype,
                "link_doctype": df.options if df.fieldtype == "Link" else None,
                "value": _shown(value),
                "required": 1 if df.fieldname in required else 0,
                "missing": 1 if df.fieldname in missing else 0,
                "choices": _choices(df, value),
            })
        fields.sort(key=lambda row: (not row["missing"], row["label"].lower()))
    history = frappe.get_all(
        "Comment",
        filters={"reference_doctype": doc.doctype, "reference_name": doc.name, "comment_type": "Comment",
                 "content": ["like", "Metadata corrected by%"]},
        fields=["content", "creation", "owner"],
        order_by="creation desc",
        limit=20,
    )
    return {
        "document": doc.name,
        "can_correct": can_correct,
        "missing": sorted(missing),
        "fields": fields,
        "history": history,
    }


@frappe.whitelist(methods=["GET"])
def correction_form(document: str) -> dict:
    """The document page's metadata correction panel (E15-S5)."""
    from consilium.policy import lifecycle

    doc = lifecycle.load_for_portal(document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    return correction_context(doc)


@frappe.whitelist(methods=["POST"])
def correct_metadata(document: str, fieldname: str, value=None, reason: str | None = None) -> dict:
    """Correct one field of a document in place, with the reason, from the portal.

    Open at every stage — a published document is the case this is for — to
    the roles that hold write on the record (``lifecycle.ACTION_ROLES``). The
    reason is required: it is the only account of the change anyone will have.
    """
    from consilium.policy import lifecycle

    doc = lifecycle.load_for_portal(document)
    frappe.has_permission(DOCTYPE, "read", doc=doc, throw=True)
    lifecycle.authorise(doc, "correct_metadata")
    if not (reason or "").strip():
        frappe.throw(_("A correction is recorded with its reason. Say why the value was wrong."),
                     title=_("Reason Required"))
    correct(DOCTYPE, doc.name, {fieldname: value if value not in ("",) else None}, reason=reason)
    return correction_context(frappe.get_doc(DOCTYPE, doc.name))


def raise_task(
    *,
    subject_doctype: str,
    subject_name: str,
    invalid_fieldname: str,
    trigger_event: str,
    trigger_doctype: str | None = None,
    trigger_name: str | None = None,
    assigned_to: str | None = None,
    due_in_days: int = 30,
) -> str | None:
    """Raise one remediation task, unless an open one already covers the field."""
    duplicate = frappe.db.exists(
        "Metadata Remediation Task",
        {
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": invalid_fieldname,
            "is_open": 1,
            "docstatus": ["<", 2],
        },
    )
    if duplicate:
        return None
    return frappe.get_doc(
        {
            "doctype": "Metadata Remediation Task",
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": invalid_fieldname,
            "trigger_event": trigger_event,
            "trigger_doctype": trigger_doctype,
            "trigger_name": trigger_name,
            "assigned_to": assigned_to,
            "due_on": add_days(nowdate(), due_in_days),
            "task_status": "Raised",
        }
    ).insert(ignore_permissions=True).name


def resolve_tasks_for(subject_doctype: str, subject_name: str, fieldnames: list[str]) -> list[str]:
    """Close the open tasks a correction has just satisfied."""
    resolved = []
    for name in frappe.get_all(
        "Metadata Remediation Task",
        filters={
            "subject_doctype": subject_doctype,
            "subject_name": subject_name,
            "invalid_fieldname": ["in", fieldnames],
            "is_open": 1,
            "docstatus": ["<", 2],
        },
        pluck="name",
    ):
        task = frappe.get_doc("Metadata Remediation Task", name)
        task.task_status = "Resolved"
        task.resolved_on = nowdate()
        task.resolution_note = _("Corrected in place from the metadata maintenance view.")
        task.save(ignore_permissions=True)
        resolved.append(name)
    return resolved


def raise_tasks_for_deactivated_parent(document) -> list[str]:
    """P-23. A document that stops being in force invalidates its children's parent link."""
    from consilium.policy import lineage

    raised = []
    for row in lineage.children(document.name):
        child = row["document"]
        owner = frappe.db.get_value(DOCTYPE, child, "document_owner")
        name = raise_task(
            subject_doctype=DOCTYPE,
            subject_name=child,
            invalid_fieldname="parent_document",
            trigger_event="Parent Retired",
            trigger_doctype=DOCTYPE,
            trigger_name=document.name,
            assigned_to=owner,
        )
        if name:
            raised.append(name)
    return raised


@frappe.whitelist()
def sweep(doctype: str = DOCTYPE, limit: int = 200) -> list[str]:
    """Raise a remediation task for every record the maintenance view lists."""
    raised = []
    for row in incomplete_records(doctype, limit=limit):
        owner = frappe.db.get_value(doctype, row["name"], "document_owner")
        for fieldname in row["missing"]:
            name = raise_task(
                subject_doctype=doctype,
                subject_name=row["name"],
                invalid_fieldname=fieldname,
                trigger_event="Missing Required Metadata",
                assigned_to=owner,
            )
            if name:
                raised.append(name)
    return raised
