"""Governance Forum — controller.

The inventory record every other module links to. Its rules:

* The officer fields are derived from membership and are not editable here.
* Its compliance state is moved by a compliance review, a watched-field trigger
  or a disbandment — never by editing the field.
* While the state's ``is_editable`` flag is false, the record is locked.
* A forum is disbanded, never deleted.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from consilium.consilium_core import audit
from consilium.governance import lifecycle, membership, setup

#: Fields the lifecycle owns. A direct edit to any of them is refused.
LIFECYCLE_FIELDS = ("compliance_status", "disbanded_on", "disbandment_plan")

#: Fields derived from the membership record, which is authoritative.
DERIVED_OFFICER_FIELDS = tuple(fieldname for _flag, fieldname in membership.OFFICER_FIELDS)

ORG_GROUP_LEVELS = ("Operating Group", "Corporate Support")


class GovernanceForum(Document):
    def validate(self):
        setup.apply_governance_flags(self)
        self._guard_derived_officers()
        self._guard_lifecycle_fields()
        self._guard_editability()
        self._validate_hierarchy()
        self._validate_owning_organisation()
        self._validate_regulatory()
        self._validate_quorum()
        self._stamp_link_direction()

    def on_update(self):
        lifecycle.on_watched_change(self)

    def on_trash(self):
        lifecycle.refuse_deletion(self)

    # ------------------------------------------------------------- guards

    def _changed(self, fieldnames):
        before = self.get_doc_before_save()
        if not before:
            return []
        return [f for f in fieldnames if (before.get(f) or None) != (self.get(f) or None)]

    def _guard_derived_officers(self):
        if self.flags.consilium_officer_sync or self.is_new():
            return
        changed = self._changed(DERIVED_OFFICER_FIELDS)
        if changed:
            frappe.throw(
                _(
                    "{0} is derived from forum membership and cannot be edited here. "
                    "Change the seat instead; the forum follows it."
                ).format(", ".join(changed)),
                title=_("Derived Field"),
            )

    def _guard_lifecycle_fields(self):
        if self.flags.consilium_lifecycle or self.is_new():
            return
        changed = self._changed(LIFECYCLE_FIELDS)
        if changed:
            audit.refuse(
                _(
                    "{0} cannot be edited directly on forum {1}. A forum's compliance standing moves "
                    "through a Forum Compliance Review, a watched-field trigger or a disbandment, so "
                    "that every transition has an author and a reason."
                ).format(", ".join(changed), self.name),
                subject_doctype=self.doctype,
                subject_name=self.name,
                attempted_action="Modify",
                control="forum lifecycle transition",
                context={"fields": changed},
            )

    def _guard_editability(self):
        if self.flags.consilium_lifecycle or self.is_new():
            return
        before = self.get_doc_before_save()
        if not before or before.get("is_editable"):
            return
        frappe.throw(
            _("Forum {0} is not editable while it is under compliance review.").format(self.name),
            title=_("Locked For Review"),
        )

    # --------------------------------------------------------- validation

    def _validate_hierarchy(self):
        if not self.parent_forum:
            return
        if self.parent_forum == self.name:
            frappe.throw(_("A forum cannot be its own parent."), title=_("Invalid Hierarchy"))
        seen, cursor = {self.name}, self.parent_forum
        while cursor:
            if cursor in seen:
                frappe.throw(
                    _("Forum {0} would become its own ancestor.").format(self.name),
                    title=_("Invalid Hierarchy"),
                )
            seen.add(cursor)
            cursor = frappe.db.get_value("Governance Forum", cursor, "parent_forum")

    def _validate_owning_organisation(self):
        if self.owning_operating_group:
            level = frappe.db.get_value("Organization Unit", self.owning_operating_group, "unit_level")
            if level not in ORG_GROUP_LEVELS:
                frappe.throw(
                    _("{0} is not an operating group; organisational ownership is one accountable line.").format(
                        self.owning_operating_group
                    ),
                    title=_("Invalid Owning Organisation"),
                )
        if self.owning_line_of_business and self.owning_operating_group:
            parent = frappe.db.get_value(
                "Organization Unit", self.owning_line_of_business, "parent_org_unit"
            )
            if parent and parent != self.owning_operating_group:
                frappe.throw(
                    _("Line of business {0} does not sit under {1}.").format(
                        self.owning_line_of_business, self.owning_operating_group
                    ),
                    title=_("Invalid Owning Organisation"),
                )

    def _validate_regulatory(self):
        if self.regulatory_required and not self.regulatory_requirements:
            frappe.throw(
                _("A regulatory-required forum must cite the requirement that mandates it (G-4)."),
                title=_("Regulatory Detail Required"),
            )

    def _validate_quorum(self):
        needs_value = self.quorum_rule_type in ("Count", "Percentage", "Chair Plus Count")
        if needs_value and not self.quorum_value:
            frappe.throw(
                _("The {0} quorum rule needs a value.").format(self.quorum_rule_type),
                title=_("Quorum Value Required"),
            )
        if self.quorum_rule_type == "Percentage" and not 0 < float(self.quorum_value or 0) <= 100:
            frappe.throw(_("A percentage quorum sits between 1 and 100."), title=_("Quorum Value Required"))

    def _stamp_link_direction(self):
        """A row's direction is the field it sits in, not a thing to get wrong."""
        for row in self.get("upstream_links") or []:
            row.direction = "Upstream"
        for row in self.get("downstream_links") or []:
            row.direction = "Downstream"
        for row in (self.get("upstream_links") or []) + (self.get("downstream_links") or []):
            if row.linked_forum == self.name:
                frappe.throw(_("A forum cannot link to itself."), title=_("Invalid Link"))
