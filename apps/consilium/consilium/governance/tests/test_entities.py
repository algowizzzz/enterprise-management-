"""Every Governance entity: create, read, update, validate, and who may do it."""

import frappe
from frappe.utils import add_days, nowdate

from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_forum_type, make_jurisdiction, make_org_unit,
    make_risk_category, make_seat, make_user, seat_role, unique,
)

GOVERNANCE_DOCTYPES = (
    "Governance Forum", "Forum Membership", "Committee Formation Request", "Committee Charter",
    "Forum Compliance Review", "Forum Meeting", "Forum Motion", "Forum Vote", "Disbandment Plan",
    "Formation Approval Route",
)


class TestGovernanceEntities(GovernanceTestCase):
    def test_every_entity_exists_with_a_table(self):
        for doctype in GOVERNANCE_DOCTYPES:
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.db.exists("DocType", doctype))
                self.assertTrue(frappe.db.table_exists(doctype))

    # ------------------------------------------------------- forum: CRUD

    def test_a_forum_is_created_read_and_updated(self):
        forum = make_forum(forum_name="Enterprise Risk Committee")
        self.assertTrue(forum.name.startswith("FRM-"))

        fetched = frappe.get_doc("Governance Forum", forum.name)
        self.assertEqual(fetched.forum_name, "Enterprise Risk Committee")
        self.assertEqual(fetched.compliance_status, "Draft")

        fetched.description = "A revised mandate."
        fetched.save(ignore_permissions=True)
        self.assertEqual(
            frappe.db.get_value("Governance Forum", forum.name, "description"), "A revised mandate."
        )

    def test_required_fields_are_enforced(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Governance Forum", "forum_name": unique("Forum")}
            ).insert(ignore_permissions=True)

    def test_the_forum_carries_its_semantic_flags(self):
        forum = make_forum()
        self.assertTrue(forum.is_editable)
        self.assertTrue(forum.is_active)
        self.assertTrue(forum.requires_review)

    # --------------------------------------------------------- taxonomies

    def test_four_dimensions_are_multi_valued_and_two_are_not(self):
        forum = make_forum()
        for _ in range(2):
            forum.append("business_units", {"business_unit": make_org_unit("Business Unit")})
            forum.append("risk_types", {"risk_type": frappe.get_doc(
                {"doctype": "Risk Type", "risk_type_code": unique("RT").upper(),
                 "risk_type_name": "Test", "tier": 1}).insert(ignore_permissions=True).name})
            forum.append("legal_entities", {"legal_entity": frappe.get_doc(
                {"doctype": "Legal Entity", "legal_entity_code": unique("LE").upper(),
                 "legal_entity_name": "Test"}).insert(ignore_permissions=True).name})
            forum.append("jurisdictions", {"jurisdiction": make_jurisdiction()})
        forum.save(ignore_permissions=True)
        forum.reload()

        self.assertEqual(len(forum.business_units), 2)
        self.assertEqual(len(forum.risk_types), 2)
        self.assertEqual(len(forum.legal_entities), 2)
        self.assertEqual(len(forum.jurisdictions), 2)

        # The two carve-outs are single Link columns, not tables.
        meta = frappe.get_meta("Governance Forum")
        self.assertEqual(meta.get_field("primary_risk_category").fieldtype, "Link")
        self.assertEqual(meta.get_field("owning_operating_group").fieldtype, "Link")

    def test_regulatory_detail_becomes_required_when_the_flag_is_set(self):
        forum = make_forum()
        forum.regulatory_required = 1
        with self.assertRaises(frappe.ValidationError):
            forum.save(ignore_permissions=True)

        forum.reload()
        forum.regulatory_required = 1
        requirement = frappe.get_doc(
            {"doctype": "Regulatory Requirement", "regulatory_requirement_code": unique("REG").upper(),
             "regulatory_requirement_name": "A rule"}
        ).insert(ignore_permissions=True)
        forum.append("regulatory_requirements", {"regulatory_requirement": requirement.name})
        forum.save(ignore_permissions=True)
        self.assertEqual(len(forum.regulatory_requirements), 1)

    # ------------------------------------------------------- relationships

    def test_a_forum_cannot_be_its_own_ancestor(self):
        parent = make_forum()
        child = make_forum(parent_forum=parent.name)
        parent.reload()
        parent.parent_forum = child.name
        with self.assertRaises(frappe.ValidationError):
            parent.save(ignore_permissions=True)

    def test_a_link_takes_its_direction_from_the_field_it_sits_in(self):
        upstream = make_forum()
        downstream = make_forum()
        forum = make_forum()
        forum.append("upstream_links", {"linked_forum": upstream.name, "direction": "Downstream",
                                        "relationship_type": "Reports To"})
        forum.append("downstream_links", {"linked_forum": downstream.name, "direction": "Upstream",
                                          "relationship_type": "Informs"})
        forum.save(ignore_permissions=True)
        forum.reload()
        self.assertEqual(forum.upstream_links[0].direction, "Upstream")
        self.assertEqual(forum.downstream_links[0].direction, "Downstream")

        # And the reverse traversal works from the other side.
        rows = frappe.get_all(
            "Forum Link", filters={"linked_forum": upstream.name}, fields=["parent", "parentfield"]
        )
        self.assertEqual(rows[0]["parent"], forum.name)

    def test_a_forum_cannot_link_to_itself(self):
        forum = make_forum()
        forum.append("upstream_links", {"linked_forum": forum.name, "relationship_type": "Reports To"})
        with self.assertRaises(frappe.ValidationError):
            forum.save(ignore_permissions=True)

    def test_the_owning_organisation_must_be_an_operating_group(self):
        with self.assertRaises(frappe.ValidationError):
            make_forum(owning_operating_group=make_org_unit("Business Unit"))

    def test_a_line_of_business_must_sit_under_its_operating_group(self):
        group = make_org_unit("Operating Group")
        other = make_org_unit("Operating Group")
        lob = make_org_unit("Line of Business", parent=other)
        with self.assertRaises(frappe.ValidationError):
            make_forum(owning_operating_group=group, owning_line_of_business=lob)

    def test_quorum_configuration_is_validated(self):
        with self.assertRaises(frappe.ValidationError):
            make_forum(quorum_rule_type="Percentage", quorum_value=0)
        with self.assertRaises(frappe.ValidationError):
            make_forum(quorum_rule_type="Percentage", quorum_value=180)
        forum = make_forum(quorum_rule_type="All Voting Members", quorum_value=0)
        self.assertEqual(forum.quorum_rule_type, "All Voting Members")

    # ------------------------------------------------- the other entities

    def test_a_charter_belongs_to_a_forum_or_to_a_request(self):
        forum = make_forum()
        charter = frappe.get_doc(
            {"doctype": "Committee Charter", "charter_title": "Charter", "forum": forum.name}
        ).insert(ignore_permissions=True)
        self.assertEqual(charter.rgo_challenge_status, "Not Reviewed")
        self.assertTrue(charter.requires_review)

        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Committee Charter", "charter_title": "Orphan"}
            ).insert(ignore_permissions=True)

    def test_a_meeting_records_attendance_against_seats_of_its_own_forum(self):
        forum = make_forum()
        other = make_forum()
        seat = make_seat(other.name, seat_role())
        meeting = frappe.get_doc(
            {"doctype": "Forum Meeting", "forum": forum.name, "meeting_reference": "M-1",
             "scheduled_on": nowdate()}
        )
        meeting.append("attendance", {"membership": seat.name, "attendee": seat.member, "present": 1})
        with self.assertRaises(frappe.ValidationError):
            meeting.insert(ignore_permissions=True)

    def test_a_disbandment_plan_needs_the_approvals_it_requires(self):
        forum = make_forum()
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {"doctype": "Disbandment Plan", "forum": forum.name,
                 "trigger_scenario": "Mandate Complete",
                 "records_disposition_note": "Archive."}
            ).insert(ignore_permissions=True)

    # ------------------------------------------------------- permissions

    def test_permissions_are_enforced_server_side(self):
        viewer = make_user("Governance Viewer")
        secretary = make_user("Committee Secretary")

        self.assertTrue(frappe.has_permission("Governance Forum", "read", user=viewer))
        self.assertFalse(frappe.has_permission("Governance Forum", "write", user=viewer))
        self.assertFalse(frappe.has_permission("Governance Forum", "create", user=viewer))
        self.assertFalse(frappe.has_permission("Forum Membership", "write", user=viewer))

        # A secretary administers a forum but does not decide its compliance.
        self.assertTrue(frappe.has_permission("Forum Membership", "create", user=secretary))
        self.assertFalse(frappe.has_permission("Forum Compliance Review", "create", user=secretary))
        self.assertFalse(frappe.has_permission("Forum Compliance Review", "write", user=secretary))

    def test_a_viewer_cannot_create_a_forum(self):
        viewer = make_user("Governance Viewer")
        payload = {
            "doctype": "Governance Forum",
            "forum_name": unique("Forum"),
            "forum_type": make_forum_type(),
            "description": "A mandate.",
            "cadence": "Quarterly",
            "primary_risk_category": make_risk_category(),
            "owning_operating_group": make_org_unit(),
            "quorum_rule_type": "Count",
            "quorum_value": 1,
        }
        frappe.set_user(viewer)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(dict(payload)).insert()
        finally:
            frappe.set_user("Administrator")
        # The same payload is accepted from a role that does have the permission,
        # so the refusal above is about permission and not about the data.
        frappe.get_doc(dict(payload)).insert(ignore_permissions=True)

    def test_a_secretary_may_not_record_a_compliance_decision(self):
        forum = make_forum()
        secretary = make_user("Committee Secretary")
        frappe.set_user(secretary)
        try:
            with self.assertRaises(frappe.PermissionError):
                frappe.get_doc(
                    {"doctype": "Forum Compliance Review", "forum": forum.name,
                     "review_type": "Initial", "decision": "Compliant"}
                ).insert()
        finally:
            frappe.set_user("Administrator")

    def test_an_auditor_reads_everything_and_writes_nothing(self):
        auditor = make_user("Consilium Audit")
        for doctype in GOVERNANCE_DOCTYPES:
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.has_permission(doctype, "read", user=auditor))
                self.assertFalse(frappe.has_permission(doctype, "write", user=auditor))
                self.assertFalse(frappe.has_permission(doctype, "delete", user=auditor))
