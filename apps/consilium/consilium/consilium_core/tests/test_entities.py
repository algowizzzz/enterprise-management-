"""Every Core entity: create, read, update, permissions, validation.

The taxonomies share one shape, so they are covered by one parameterised pass
rather than seventeen near-identical tests.
"""

import frappe

from consilium.consilium_core.tests.utils import CoreTestCase, make_user, unique

#: entity -> (code fieldname, title fieldname, extra required values)
TAXONOMIES = {
    "Risk Category": ("risk_category_code", "risk_category_name", {}),
    "Risk Type": ("risk_type_code", "risk_type_name", {"tier": 1}),
    "Legal Entity": ("legal_entity_code", "legal_entity_name", {}),
    "Organization Unit": ("org_unit_code", "org_unit_name", {"unit_level": "Business Unit"}),
    "Jurisdiction": ("jurisdiction_code", "jurisdiction_name", {}),
    "Material Entity": ("material_entity_code", "material_entity_name", {}),
    "Line Of Defence": ("line_of_defence_code", "line_of_defence_name", {"line_number": 2}),
    "Organizational Level": ("organizational_level_code", "organizational_level_name", {"level_rank": 3}),
    "Governing Document Type": ("document_type_code", "document_type_name", {}),
    "Governance Forum Type": ("forum_type_code", "forum_type_name", {}),
    "Governance Forum Role": ("governance_forum_role_code", "governance_forum_role_name", {}),
    "Governance Responsibility": ("governance_responsibility_code", "governance_responsibility_name", {}),
    "Escalation Type": ("escalation_type_code", "escalation_type_name", {}),
    "Horizon Scanning Coverage Area": ("coverage_area_code", "coverage_area_name", {}),
    "Regulatory Requirement": ("regulatory_requirement_code", "regulatory_requirement_name", {}),
    "Delegable Action": ("delegable_action_code", "delegable_action_name", {}),
    "Document Role": ("document_role_code", "document_role_name", {}),
}

#: Every standalone entity Core owns, for the structural assertions.
CORE_DOCTYPES = sorted(
    frappe.get_all(
        "DocType", filters={"module": "Consilium Core", "istable": 0}, pluck="name"
    )
) if frappe.db else []


class TestTaxonomies(CoreTestCase):
    def _values(self, entity):
        code_field, title_field, extra = TAXONOMIES[entity]
        return {
            "doctype": entity,
            code_field: unique("C").upper(),
            title_field: "Reference value",
            "description": "Created by a test.",
            **extra,
        }

    def test_create_read_update_and_deactivate(self):
        for entity, (code_field, title_field, _extra) in TAXONOMIES.items():
            with self.subTest(entity=entity):
                doc = frappe.get_doc(self._values(entity)).insert(ignore_permissions=True)
                self.assertEqual(doc.name, doc.get(code_field))
                self.assertTrue(doc.is_active, msg="values are active by default")

                read_back = frappe.get_doc(entity, doc.name)
                self.assertEqual(read_back.get(title_field), "Reference value")

                read_back.set(title_field, "Renamed value")
                read_back.save(ignore_permissions=True)
                self.assertEqual(frappe.db.get_value(entity, doc.name, title_field), "Renamed value")

                # Deactivation, never deletion: a historical row must keep resolving.
                read_back.is_active = 0
                read_back.save(ignore_permissions=True)
                self.assertEqual(frappe.db.get_value(entity, doc.name, "is_active"), 0)

    def test_a_code_cannot_be_reused(self):
        for entity in TAXONOMIES:
            with self.subTest(entity=entity):
                values = self._values(entity)
                frappe.get_doc(dict(values)).insert(ignore_permissions=True)
                with self.assertRaises(Exception):
                    frappe.get_doc(dict(values)).insert(ignore_permissions=True)
                frappe.db.rollback()

    def test_every_taxonomy_carries_the_reconciliation_seam(self):
        for entity in TAXONOMIES:
            with self.subTest(entity=entity):
                meta = frappe.get_meta(entity)
                self.assertTrue(meta.has_field("external_code"))
                self.assertTrue(meta.has_field("sort_order"))
                self.assertTrue(meta.has_field("is_active"))

    def test_the_hierarchical_taxonomies_are_trees(self):
        for entity, parent_field in (
            ("Risk Category", "parent_risk_category"),
            ("Risk Type", "parent_risk_type"),
            ("Organization Unit", "parent_org_unit"),
            ("Jurisdiction", "parent_jurisdiction"),
            ("Organizational Level", "parent_organizational_level"),
            ("Legal Entity", "parent_legal_entity"),
        ):
            with self.subTest(entity=entity):
                meta = frappe.get_meta(entity)
                self.assertTrue(meta.is_tree, msg=f"{entity} should be a tree")
                self.assertTrue(meta.has_field(parent_field))

    def test_a_child_resolves_to_its_parent(self):
        parent = frappe.get_doc(self._values("Risk Type") | {"tier": 1, "is_group": 1}).insert(
            ignore_permissions=True
        )
        child = frappe.get_doc(
            self._values("Risk Type") | {"tier": 2, "parent_risk_type": parent.name}
        ).insert(ignore_permissions=True)
        self.assertEqual(child.parent_risk_type, parent.name)

    def test_the_risk_tiers_are_enforced(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(self._values("Risk Type") | {"tier": 3}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(self._values("Risk Type") | {"tier": 2}).insert(ignore_permissions=True)

    def test_the_three_lines_are_enforced(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(self._values("Line Of Defence") | {"line_number": 4}).insert(
                ignore_permissions=True
            )

    def test_the_seeded_seat_roles_carry_their_behaviour(self):
        chair = frappe.get_doc("Governance Forum Role", "CHAIR")
        self.assertTrue(chair.is_chair_role)
        self.assertTrue(chair.can_attest)
        self.assertTrue(chair.counts_toward_quorum)

        observer = frappe.get_doc("Governance Forum Role", "OBSERVER")
        self.assertFalse(observer.votes_by_default)
        self.assertFalse(observer.counts_toward_quorum)
        self.assertFalse(observer.can_attest)

    def test_a_change_is_recorded_in_the_audit_trail(self):
        doc = frappe.get_doc(self._values("Escalation Type")).insert(ignore_permissions=True)
        doc.escalation_type_name = "Changed"
        # The framework suppresses version rows under test unless asked for them.
        doc.save(ignore_permissions=True, ignore_version=False)
        versions = frappe.get_all(
            "Version", filters={"ref_doctype": "Escalation Type", "docname": doc.name}, pluck="name"
        )
        self.assertTrue(versions, msg="track_changes is what gives us the audit trail")


class TestEntityStructure(CoreTestCase):
    def test_every_core_entity_has_permission_rows(self):
        for doctype in CORE_DOCTYPES:
            with self.subTest(doctype=doctype):
                meta = frappe.get_meta(doctype)
                self.assertTrue(meta.permissions, msg=f"{doctype} has no permission rows")
                self.assertTrue(
                    any(perm.read for perm in meta.permissions),
                    msg=f"nobody can read {doctype}",
                )

    def test_governed_entities_keep_their_change_history(self):
        high_volume = {"Import Row", "Notification Dispatch"}
        for doctype in CORE_DOCTYPES:
            if doctype in high_volume:
                continue
            with self.subTest(doctype=doctype):
                self.assertTrue(
                    frappe.get_meta(doctype).track_changes,
                    msg=f"{doctype} would have no audit trail",
                )

    def test_append_only_entities_grant_nobody_delete(self):
        for doctype in (
            "Document Version",
            "Version Revert Log",
            "Archive Record",
            "Classification Assessment",
            "AI Service Request",
            "AI Suggestion Acceptance",
            "Governance Refusal Log",
        ):
            with self.subTest(doctype=doctype):
                for perm in frappe.get_meta(doctype).permissions:
                    self.assertFalse(perm.delete, msg=f"{perm.role} may delete {doctype}")
                    self.assertFalse(perm.cancel, msg=f"{perm.role} may cancel {doctype}")
                    self.assertFalse(perm.amend, msg=f"{perm.role} may amend {doctype}")


class TestPermissions(CoreTestCase):
    def setUp(self):
        self.taxonomy_admin = make_user("Taxonomy Administrator")
        self.auditor = make_user("Consilium Audit")
        self.records_manager = make_user("Records Manager")
        self.nobody = make_user()

    def test_a_taxonomy_administrator_may_maintain_taxonomies_but_not_delete_them(self):
        self.assertTrue(frappe.has_permission("Risk Category", "write", user=self.taxonomy_admin))
        self.assertTrue(frappe.has_permission("Risk Category", "create", user=self.taxonomy_admin))
        self.assertFalse(frappe.has_permission("Risk Category", "delete", user=self.taxonomy_admin))

    def test_an_auditor_reads_everything_and_writes_nothing(self):
        for doctype in ("Risk Category", "Archive Record", "Attestation Task", "Governance Refusal Log"):
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.has_permission(doctype, "read", user=self.auditor))
                self.assertFalse(frappe.has_permission(doctype, "write", user=self.auditor))
                self.assertFalse(frappe.has_permission(doctype, "delete", user=self.auditor))

    def test_retention_is_the_records_manager_s_to_run(self):
        self.assertTrue(frappe.has_permission("Retention Class", "write", user=self.records_manager))
        self.assertTrue(frappe.has_permission("Legal Hold", "create", user=self.records_manager))
        self.assertFalse(frappe.has_permission("Retention Class", "write", user=self.nobody))
        self.assertFalse(frappe.has_permission("Legal Hold", "read", user=self.nobody))

    def test_nobody_may_write_an_append_only_artefact(self):
        for user in (self.records_manager, self.auditor, self.nobody):
            with self.subTest(user=user):
                self.assertFalse(frappe.has_permission("Document Version", "write", user=user))
                self.assertFalse(frappe.has_permission("Archive Record", "delete", user=user))

    def test_a_server_side_write_without_permission_is_refused(self):
        frappe.set_user(self.nobody)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(
                    {
                        "doctype": "Retention Class",
                        "class_code": unique("RC"),
                        "title": "Unauthorised",
                        "retention_period_months": 12,
                        "trigger_event": "Creation",
                        "disposition_action": "Review",
                    }
                ).insert()
        finally:
            frappe.set_user("Administrator")
