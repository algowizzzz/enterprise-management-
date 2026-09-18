"""Regulatory Requirement — controller.

A shared library of laws, rules, regulations and standards that both forums and governing documents cite (T-17). [Inferred — 02-data-model.md §11 I-1. Neither source says the citations are shared; modelling them shared is what makes 'notify impacted owners on regulatory change' a one-hop query rather than a text search.]

That one-hop query is made here (P-6, O-7). When the substance of a requirement
changes — by hand on desk or through an import, both of which save the record —
the owner of every governing document and every forum that cites it is told,
with what changed. The fan-out is on the save, not a nightly comparison, because
the save is the only moment the old values are still to hand.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, nowdate

#: Fields whose change is a change to what the requirement demands. Sort order
#: and the like are housekeeping and tell nobody anything.
SUBSTANTIVE_FIELDS = (
    "regulatory_requirement_name", "description", "citation", "jurisdiction", "regulator",
    "effective_date", "summary", "external_code", "is_active",
)

EVENT = "regulatory.requirement.changed"


class RegulatoryRequirement(Document):
    def validate(self):
        # A substantive change is dated even when the editor forgot to: the
        # date is what tells a reader of a citing document that it may be stale.
        if self.changed_fields() and not self._value_changed("last_change_on"):
            self.last_change_on = nowdate()

    def on_update(self):
        changes = self.changed_fields()
        if not changes:
            return
        try:
            notify_citing_owners(self, changes)
        except Exception:
            # The requirement is saved either way; a notification that could
            # not be sent is logged, not allowed to undo the edit.
            frappe.log_error(title=_("Regulatory change fan-out for {0} failed").format(self.name),
                             message=frappe.get_traceback())

    def _value_changed(self, fieldname) -> bool:
        before = self.get_doc_before_save()
        return bool(before) and cstr(before.get(fieldname)) != cstr(self.get(fieldname))

    def changed_fields(self) -> list[dict]:
        """``[{field, label, old, new}]`` for substantive fields; empty for a new record."""
        before = self.get_doc_before_save()
        if not before:
            return []
        out = []
        for field in SUBSTANTIVE_FIELDS:
            old, new = cstr(before.get(field)), cstr(self.get(field))
            if old != new:
                out.append({"field": field, "label": _(self.meta.get_label(field)), "old": old, "new": new})
        return out


def citing_records(requirement: str) -> list[dict]:
    """Governing documents and forums that cite a requirement, with their owners.

    Retired documents and disbanded forums are left out: an owner of a record
    that no longer governs anything has nothing to update. A document is
    recognised as retired by its retirement date (the document's flags cannot
    tell a retired document from an approved one awaiting publication), and
    that date is tested here rather than in the query because an "is set"
    filter on a date column is rejected by PostgreSQL.
    """
    out = []
    if frappe.db.table_exists("Document Regulatory Reference"):
        documents = set(frappe.get_all(
            "Document Regulatory Reference",
            filters={"regulatory_requirement": requirement, "parenttype": "Governing Document"},
            pluck="parent",
        ))
        for row in frappe.get_all(
            "Governing Document",
            filters={"name": ["in", list(documents) or [""]]},
            fields=["name", "document_name", "document_owner", "retired_on"],
        ):
            if row.retired_on:
                continue
            out.append({"doctype": "Governing Document", "name": row.name,
                        "label": f"{row.document_name} ({row.name})", "owners": [row.document_owner]})
    if frappe.db.table_exists("Forum Regulatory Requirement"):
        forums = set(frappe.get_all(
            "Forum Regulatory Requirement",
            filters={"regulatory_requirement": requirement, "parenttype": "Governance Forum"},
            pluck="parent",
        ))
        for row in frappe.get_all(
            "Governance Forum",
            filters={"name": ["in", list(forums) or [""]], "is_active": 1},
            fields=["name", "forum_name", "forum_owner"],
        ):
            out.append({"doctype": "Governance Forum", "name": row.name,
                        "label": f"{row.forum_name} ({row.name})", "owners": [row.forum_owner]})
    return out


def notify_citing_owners(requirement, changes: list[dict]) -> list[str]:
    """Tell the owner of each citing record. One notice per record, so each
    dispatch sits on the record the owner has to look at.

    Public so a regulatory-change import can call it for a change it applies
    without saving the requirement through its controller.
    """
    from consilium.consilium_core import notification

    if isinstance(requirement, str):
        requirement = frappe.get_doc("Regulatory Requirement", requirement)
    summary = {
        "code": requirement.regulatory_requirement_code,
        "name": requirement.regulatory_requirement_name,
        "citation": requirement.citation,
        "regulator": requirement.regulator,
        "summary": requirement.summary,
        "requirement": requirement.name,
    }
    sent = []
    for record in citing_records(requirement.name):
        sent.extend(
            notification.notify(
                EVENT,
                [o for o in record["owners"] if o],
                {
                    "requirement": summary,
                    "changes": changes,
                    "changed_fields": ", ".join(c["label"] for c in changes),
                    "citing_label": record["label"],
                },
                record["doctype"],
                record["name"],
            )
        )
    return sent
