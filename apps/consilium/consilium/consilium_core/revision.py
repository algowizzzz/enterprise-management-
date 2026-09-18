"""Revision snapshots, and revert, for records that must be revertible (G-9, E-12).

A forum record and an escalation matter are edited in place. The framework's own
change log (`Version`, from ``track_changes``) is a forward diff trail: it says
what changed, but it cannot put a record back. So these two entities keep a
chain in Core's ``Document Version`` as well — the same append-only chain charters,
minutes and documents use — and revert works on that chain.

**When a version is written.** On every save that changes *content*: a field a
person can edit, or the record's state. A save that only moves a system counter
(an SLA clock reference, a breach counter, a denormalised officer field) writes
nothing, because a history that fills with those hides the changes people made.
A record that existed before this module was switched on has no chain; its first
change therefore writes two versions — the state before the change, as a
baseline, and the state after it — so the very first edit is already revertible.

**What a revert restores, and what it never touches.** A revert puts back the
fields a person could have typed, and nothing else:

* never the **state**. A state moves through its own transitions (a compliance
  review, a status action), each with an author and a reason. A revert that
  rewrote it would be a way round every one of them;
* never a **read-only** field. Those are maintained by the platform (flags,
  officer fields derived from membership, SLA references, breach counters);
* never the **handling classification** (``sensitive``, ``confidential``).
  Declassifying a record is a decision in its own right, not a side effect of
  undoing an edit;
* never the review rounds on a matter. They are the record of challenge.

**When a revert is refused** — each refusal audited, because a refused
modification has to leave a record:

* without a reason;
* by someone who does not hold a revert role, or cannot write the record;
* while the record's state says it is not editable (a closed matter, a forum
  locked for compliance review, a disbanded forum);
* when the target version was taken on the other side of a boundary the record
  may not cross back over — for a matter, open versus at rest; for a forum,
  active versus disbanded. Read from the flags configured for the *state the
  version recorded*, never from a label.

**The Governance Forum's own rules still apply.** The revert is an ordinary save
of the forum, so the controller's guards run, and a watched field put back by a
revert sends the forum back for compliance review exactly as a hand edit would.

The resulting version records what the record *actually* holds after the
revert, not a copy of the target's snapshot: the state, the classification and
the system fields were deliberately left alone, and a head that claimed
otherwise would make the next comparison report changes nobody made. That is why
this module composes Core's ``create_version`` and writes the ``Version Revert
Log`` itself, rather than calling ``versioning.revert_to_version``, which stamps
the target's snapshot as the new head.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.model import display_fieldtypes, table_fields
from frappe.utils import now

from consilium.consilium_core import audit, state_flags, versioning


@dataclass(frozen=True)
class RevisionPolicy:
    """How one entity is versioned and reverted. Configuration, read by key."""

    #: The field the record's state lives in. Never restored.
    state_field: str
    #: Flags whose value a revert may not change: the boundary it may not cross.
    boundary_flags: tuple[str, ...]
    #: Editable fields a revert leaves as they are.
    kept_fields: tuple[str, ...]
    #: Roles that may revert, beyond the superuser.
    revert_roles: tuple[str, ...]


POLICIES: dict[str, RevisionPolicy] = {
    "Escalation Matter": RevisionPolicy(
        state_field="status",
        boundary_flags=("is_open",),
        kept_fields=("sensitive", "reviews"),
        revert_roles=("Escalation Owner", "Consilium Administrator"),
    ),
    "Governance Forum": RevisionPolicy(
        state_field="compliance_status",
        boundary_flags=("is_active",),
        kept_fields=("confidential",),
        revert_roles=("Risk Governance Office",),
    ),
}

SUPERUSER_ROLES = ("System Manager",)

#: Set on a document to save it without writing a version: the revert writes
#: its own, with the ``Reverted`` origin.
SKIP_FLAG = "consilium_revision_skip"

#: Child-row keys that identify a row rather than describe it.
_ROW_IDENTITY = frozenset({
    "name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
    "parent", "parentfield", "parenttype", "doctype", "__islocal", "__unsaved",
})


# ------------------------------------------------------------------- fields


def _policy(doctype: str) -> RevisionPolicy:
    policy = POLICIES.get(doctype)
    if not policy:
        frappe.throw(
            _("{0} records do not keep a revision chain here.").format(doctype),
            title=_("Not Revertible"),
        )
    return policy


def restorable_fields(doctype: str) -> list:
    """The fields a revert puts back: editable, value-bearing, not kept, not the state."""
    policy = _policy(doctype)
    fields = []
    for df in frappe.get_meta(doctype).fields:
        if df.fieldtype in display_fieldtypes or df.read_only:
            continue
        if df.fieldname in policy.kept_fields or df.fieldname == policy.state_field:
            continue
        fields.append(df)
    return fields


def _editable_child_fields(child_doctype: str) -> set[str]:
    return {
        df.fieldname
        for df in frappe.get_meta(child_doctype).fields
        if df.fieldtype not in display_fieldtypes and not df.read_only
    }


def _normal(value):
    """Empty is empty: a check of 0, a blank string and a null are one value."""
    if value in (None, "", 0, 0.0, "0"):
        return None
    return str(value)


def _content(doctype: str, snapshot: dict) -> dict:
    """What a version *says*, reduced to what a person can change, plus the state.

    Child rows lose their identity (a re-saved row gets a new name) and their
    platform-maintained columns, and are compared as a set.
    """
    policy = _policy(doctype)
    content = {policy.state_field: _normal(snapshot.get(policy.state_field))}
    for df in restorable_fields(doctype):
        value = snapshot.get(df.fieldname)
        if df.fieldtype in table_fields:
            editable = _editable_child_fields(df.options)
            rows = [
                tuple(sorted((k, _normal(v)) for k, v in (row or {}).items() if k in editable and _normal(v)))
                for row in (value or [])
            ]
            content[df.fieldname] = tuple(sorted(rows))
        else:
            content[df.fieldname] = _normal(value)
    return content


def _snapshot(doc) -> dict:
    """The full snapshot, through the same JSON round trip a stored one has had."""
    return json.loads(json.dumps(versioning.snapshot_of(doc), default=str))


def _labels(doctype: str) -> dict[str, str]:
    meta = frappe.get_meta(doctype)
    return {df.fieldname: df.label or df.fieldname for df in meta.fields}


def _changed_fields(doctype: str, before: dict, after: dict) -> list[str]:
    old, new = _content(doctype, before), _content(doctype, after)
    return [field for field in new if old.get(field) != new.get(field)]


def _summary(doctype: str, changed: list[str]) -> str:
    labels = _labels(doctype)
    names = [labels.get(field, field) for field in changed]
    if len(names) > 8:
        names = names[:8] + [_("and {0} more").format(len(changed) - 8)]
    return _("Changed: {0}.").format(", ".join(names))


# ----------------------------------------------------------------- snapshot


def snapshot(doc, method=None) -> None:
    """``on_update``: add a version when the save changed content. Registered in hooks.py."""
    if doc.doctype not in POLICIES or doc.flags.get(SKIP_FLAG) or frappe.flags.in_install:
        return

    after = _snapshot(doc)
    head = versioning.current_version(doc.doctype, doc.name)

    if head is None:
        if doc.flags.in_insert:
            versioning.create_version(doc, change_summary=_("Created."), metadata_snapshot=after)
            return
        before_doc = doc.get_doc_before_save()
        if before_doc is None:
            versioning.create_version(
                doc, change_summary=_("First recorded version."), metadata_snapshot=after
            )
            return
        # A record from before revision tracking: keep what it said before this
        # save, so that this first change can itself be undone.
        before = _snapshot(before_doc)
        versioning.create_version(
            doc,
            change_summary=_("The record as it stood when revision tracking began."),
            origin="Migrated",
            metadata_snapshot=before,
        )
    else:
        before = versioning.as_dict(head.metadata_snapshot)

    changed = _changed_fields(doc.doctype, before, after)
    if not changed:
        return
    versioning.create_version(doc, change_summary=_summary(doc.doctype, changed), metadata_snapshot=after)


# ------------------------------------------------------------------ revert


def _holds(roles, user: str | None = None) -> bool:
    held = set(frappe.get_roles(user or frappe.session.user))
    return bool(held & (set(roles) | set(SUPERUSER_ROLES)))


def _load(doctype: str, name: str, ptype: str):
    """The record, if the caller may ``ptype`` it.

    A record that does not exist and one the caller may not see get the same
    answer, so that probing a reference cannot reveal a sensitive matter.
    """
    _policy(doctype)
    if not name or not frappe.db.exists(doctype, name):
        frappe.throw(_("{0} {1} is not available to you.").format(doctype, name), frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    if not frappe.has_permission(doctype, "read", doc=doc):
        frappe.throw(_("{0} {1} is not available to you.").format(doctype, name), frappe.PermissionError)
    if ptype != "read":
        doc.check_permission(ptype)
    return doc


def _state_flags_of(doctype: str, snapshot: dict) -> dict:
    """The flags of the state a snapshot recorded, from the configuration.

    The configured flags of that state are the authority; the flag columns
    stored in the snapshot are used only if the state is no longer configured.
    """
    policy = _policy(doctype)
    flags = state_flags.flags_for(doctype, policy.state_field, snapshot.get(policy.state_field))
    if flags is not None:
        return flags
    return {flag: int(snapshot.get(flag) or 0) for flag in state_flags.FLAG_FIELDS}


def revert_blocker(doc, target_snapshot: dict | None = None) -> str | None:
    """Why this record cannot be reverted now (to this snapshot), or None."""
    policy = _policy(doc.doctype)
    if not doc.get("is_editable"):
        return _(
            "{0} {1} is not editable in its present state ({2}), so it cannot be reverted. "
            "It must first return to an editable state through its own process."
        ).format(doc.doctype, doc.name, doc.get(policy.state_field))
    if target_snapshot is None:
        return None
    target_flags = _state_flags_of(doc.doctype, target_snapshot)
    for flag in policy.boundary_flags:
        if int(target_flags.get(flag) or 0) != int(doc.get(flag) or 0):
            return _(
                "That version was recorded while {0} {1} was {2}. Reverting to it would carry the "
                "record back across a state it may not re-enter; restore the fields by hand instead."
            ).format(doc.doctype, doc.name, target_snapshot.get(policy.state_field) or _("in another state"))
    return None


def may_revert(doc, user: str | None = None) -> bool:
    """Standing to revert: a revert role and write access. Says nothing about state."""
    user = user or frappe.session.user
    return _holds(_policy(doc.doctype).revert_roles, user) and bool(
        frappe.has_permission(doc.doctype, "write", doc=doc, user=user)
    )


def _restore(doc, snapshot: dict) -> list[str]:
    """Put the restorable fields back from a snapshot. Returns what differed."""
    restored = []
    current = _content(doc.doctype, _snapshot(doc))
    target = _content(doc.doctype, snapshot)
    for df in restorable_fields(doc.doctype):
        if current.get(df.fieldname) == target.get(df.fieldname):
            continue
        value = snapshot.get(df.fieldname)
        if df.fieldtype in table_fields:
            # Rows go back as new rows. A row's old name may belong to a row that
            # has since been deleted, and updating a row that no longer exists
            # silently writes nothing.
            editable = _editable_child_fields(df.options)
            doc.set(df.fieldname, [])
            for row in value or []:
                doc.append(df.fieldname, {
                    k: v for k, v in (row or {}).items() if k not in _ROW_IDENTITY and k in editable
                })
        else:
            doc.set(df.fieldname, value)
        restored.append(df.fieldname)
    return restored


def revert_record(doctype: str, name: str, version: str, reason: str):
    """Revert one record to a version of its chain. Returns the ``Version Revert Log``."""
    doc = _load(doctype, name, "write")
    policy = _policy(doctype)

    if not may_revert(doc):
        audit.refuse(
            _("{0} may not revert {1} {2}. Reverting belongs to: {3}.").format(
                frappe.session.user, doctype, name, ", ".join(policy.revert_roles)
            ),
            subject_doctype=doctype,
            subject_name=name,
            attempted_action="Revert",
            control="revert role",
        )
    if not (reason or "").strip():
        audit.refuse(
            _("Revert of {0} {1} is refused: a revert carries a mandatory reason, because the revert "
              "is itself an auditable act.").format(doctype, name),
            subject_doctype=doctype,
            subject_name=name,
            attempted_action="Revert",
            control="revert justification",
            exc=frappe.ValidationError,
        )

    target = frappe.get_doc("Document Version", version) if frappe.db.exists("Document Version", version) else None
    if not target or (target.subject_doctype, target.subject_name) != (doctype, name):
        frappe.throw(_("Version {0} does not belong to {1} {2}.").format(version, doctype, name),
                     title=_("Wrong Version"))
    head = versioning.current_version(doctype, name)
    if head and head.name == target.name:
        frappe.throw(_("Version {0} is already current; there is nothing to revert to.").format(
            target.version_number), title=_("Nothing To Revert"))

    snapshot_data = versioning.as_dict(target.metadata_snapshot)
    blocker = revert_blocker(doc, snapshot_data)
    if blocker:
        audit.refuse(
            blocker,
            subject_doctype=doctype,
            subject_name=name,
            attempted_action="Revert",
            control="revert state boundary",
            exc=frappe.ValidationError,
        )

    restored = _restore(doc, snapshot_data)
    if not restored:
        frappe.throw(
            _("{0} {1} already holds what version {2} holds; there is nothing to revert.").format(
                doctype, name, target.version_number),
            title=_("Nothing To Revert"),
        )

    doc.flags[SKIP_FLAG] = True
    doc.save(ignore_permissions=True)
    doc.reload()

    labels = _labels(doctype)
    summary = _("Reverted to version {0}, restoring {1}. Reason: {2}").format(
        target.version_number, ", ".join(labels.get(f, f) for f in restored), reason.strip()
    )
    resulting = versioning.create_version(
        doc, change_summary=summary, origin="Reverted", metadata_snapshot=_snapshot(doc)
    )
    return frappe.get_doc(
        {
            "doctype": "Version Revert Log",
            "subject_doctype": doctype,
            "subject_name": name,
            "from_version": head.name if head else target.name,
            "target_version": target.name,
            "resulting_version": resulting.name,
            "reverted_by": frappe.session.user,
            "reverted_on": now(),
            "justification": reason.strip(),
        }
    ).insert(ignore_permissions=True)


# ----------------------------------------------------------------- history


def history_of(doc) -> dict:
    """The chain, newest first, and which of its versions this viewer may revert to now.

    Version rows are Core records readable only by administrators and audit;
    here they are shown to whoever may read the *subject*, which is the check
    the caller has already made — the same way a child row follows its parent.
    """
    policy = _policy(doc.doctype)
    can_revert = may_revert(doc)
    standing_blocker = revert_blocker(doc)
    rows = frappe.get_all(
        "Document Version",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name},
        fields=["name", "version_number", "origin", "is_current", "change_summary", "owner",
                "creation", "metadata_snapshot"],
        order_by="version_number desc",
    )
    current_content = _content(doc.doctype, _snapshot(doc))
    versions = []
    for row in rows:
        snap = versioning.as_dict(row.pop("metadata_snapshot"))
        blocker = None
        if not row.is_current:
            blocker = revert_blocker(doc, snap)
            if not blocker and _content(doc.doctype, snap) == current_content:
                blocker = _("The record already holds what this version holds.")
            elif not blocker:
                same_but_state = {k: v for k, v in _content(doc.doctype, snap).items() if k != policy.state_field}
                now_but_state = {k: v for k, v in current_content.items() if k != policy.state_field}
                if same_but_state == now_but_state:
                    blocker = _("This version differs only in its state, which a revert never changes.")
        versions.append({
            **row,
            "state": snap.get(policy.state_field),
            "can_revert": bool(can_revert and not row.is_current and not blocker),
            "blocker": blocker,
        })
    reverts = frappe.get_all(
        "Version Revert Log",
        filters={"subject_doctype": doc.doctype, "subject_name": doc.name},
        fields=["name", "from_version", "target_version", "resulting_version", "reverted_by",
                "reverted_on", "justification"],
        order_by="reverted_on desc",
    )
    return {
        "subject_doctype": doc.doctype,
        "subject_name": doc.name,
        "versions": versions,
        "reverts": reverts,
        "can_revert": can_revert,
        "blocker": standing_blocker,
        "revert_roles": list(policy.revert_roles),
    }


@frappe.whitelist(methods=["GET"])
def history(doctype: str, name: str) -> dict:
    """The revision chain of a record the caller may read."""
    return history_of(_load(doctype, name, "read"))


@frappe.whitelist(methods=["POST"])
def revert(doctype: str, name: str, version: str, reason: str | None = None) -> dict:
    """Revert a forum or an escalation matter to an earlier version, with a reason.

    Requires write access to the record and a revert role (``POLICIES``); refused,
    with an audit record, without a reason, in a state that is not editable, or
    across a state boundary the record may not re-cross.
    """
    log = revert_record(doctype, name, version, reason or "")
    result = history_of(frappe.get_doc(doctype, name))
    result["revert_log"] = log.name
    result["resulting_version"] = log.resulting_version
    return result
