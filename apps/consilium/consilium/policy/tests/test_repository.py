"""E11 — the repository record: metadata, search, lineage, applicability, notice."""

from __future__ import annotations

import frappe

from consilium.policy import applicability, lineage, repository
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_document_type,
    make_org_unit,
    make_risk_category,
    make_user,
    make_user_group,
    unique,
)

DOCTYPE = "Governing Document"


class TestGoverningDocument(PolicyTestCase):
    # ----------------------------------------------------------- create / read

    def test_creates_with_required_metadata(self):
        doc = make_document(document_abstract="A policy about something.")
        self.assertTrue(doc.name.startswith("GDOC-"))
        fetched = frappe.get_doc(DOCTYPE, doc.name)
        self.assertEqual(fetched.document_abstract, "A policy about something.")
        self.assertEditable(fetched, True)
        self.assertNotInForce(fetched)

    def test_refuses_creation_without_required_metadata(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": DOCTYPE, "document_name": unique("Nameless")}).insert(
                ignore_permissions=True
            )

    def test_document_type_is_drawn_from_the_taxonomy(self):
        with self.assertRaises(frappe.LinkValidationError):
            make_document(document_type="Not A Real Type")

    def test_update_is_tracked(self):
        doc = make_document()
        doc.document_abstract = "Revised."
        doc.save(ignore_permissions=True)
        doc.reload()
        self.assertEqual(doc.document_abstract, "Revised.")
        # The framework writes the change history only outside tests, so what is
        # asserted here is that change tracking is switched on for the DocType —
        # the setting that produces it in a real deployment.
        self.assertTrue(frappe.get_meta(DOCTYPE).track_changes)

    # ------------------------------------------------------------- validation

    def test_material_entity_flag_requires_an_entity(self):
        with self.assertRaises(frappe.ValidationError):
            make_document(material_entity_impact=1)

    def test_regulatory_flag_requires_a_reference(self):
        with self.assertRaises(frappe.ValidationError):
            make_document(regulatory_required=1)

    def test_confidential_closes_the_three_actions_by_default(self):
        doc = make_document(confidential=1)
        self.assertEqual(doc.handling_classification, "Confidential")
        self.assertFalse(int(doc.allow_download))
        self.assertFalse(int(doc.allow_print))
        self.assertFalse(int(doc.allow_share))

    def test_review_date_derives_from_cadence(self):
        doc = make_document(review_frequency_months=12, effective_on="2025-01-01")
        self.assertEqual(str(doc.next_review_on), "2026-01-01")

    def test_a_document_cannot_supersede_itself(self):
        doc = make_document()
        doc.superseded_by = doc.name
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    # ------------------------------------------------------------- permissions

    def test_a_reviewer_cannot_create_a_document(self):
        reviewer = make_user("Policy Reviewer")
        unit = make_org_unit()
        category = make_risk_category()
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            frappe.get_doc(
                {
                    "doctype": DOCTYPE,
                    "document_name": unique("Sneaky"),
                    "document_type": make_document_type(),
                    "document_owner": reviewer,
                    "document_approver": reviewer,
                    "owning_operating_group": unit,
                    "primary_risk_category": category,
                }
            ).insert()

    def test_a_policy_owner_cannot_delete_a_document(self):
        doc = make_document()
        owner = make_user("Policy Owner")
        with as_user(owner), self.assertRaises(frappe.PermissionError):
            frappe.delete_doc(DOCTYPE, doc.name)

    def test_the_policy_office_may_delete_a_document(self):
        doc = make_document()
        office = make_user("Enterprise Policy Office")
        with as_user(office):
            frappe.delete_doc(DOCTYPE, doc.name)
        self.assertFalse(frappe.db.exists(DOCTYPE, doc.name))

    def test_an_auditor_may_read_but_not_write(self):
        doc = make_document()
        auditor = make_user("Consilium Audit")
        with as_user(auditor):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            self.assertEqual(fetched.name, doc.name)
            fetched.document_abstract = "Audit edit."
            with self.assertRaises(frappe.PermissionError):
                fetched.save()

    # ----------------------------------------------------------------- search

    def test_search_filters_and_matches_title_and_content(self):
        marker = frappe.generate_hash(length=10)
        doc = make_document(document_name=f"Cyber {marker}", document_abstract="about resilience")
        frappe.db.set_value(DOCTYPE, doc.name, "body_text", f"body mentions {marker}")

        by_title = repository.search(text=marker)
        self.assertIn(doc.name, [row["name"] for row in by_title])

        by_type = repository.search(document_type=doc.document_type)
        self.assertIn(doc.name, [row["name"] for row in by_type])

        by_owner = repository.search(document_owner=doc.document_owner)
        self.assertIn(doc.name, [row["name"] for row in by_owner])

        in_force_only = repository.search(text=marker, in_force=1)
        self.assertNotIn(doc.name, [row["name"] for row in in_force_only])

    def test_search_respects_permissions(self):
        marker = frappe.generate_hash(length=10)
        doc = make_document(document_name=f"Hidden {marker}")
        outsider = make_user("Blogger")
        with as_user(outsider), self.assertRaises(frappe.PermissionError):
            repository.search(text=marker)
        self.assertIn(doc.name, [row["name"] for row in repository.search(text=marker)])


class TestLineage(PolicyTestCase):
    def test_lineage_is_navigable_in_both_directions(self):
        parent = make_document()
        child = make_document(parent_document=parent.name)
        addendum = make_document()

        parent.append(
            "relationships",
            {"related_document": addendum.name, "relationship_type": "Addendum"},
        )
        parent.save(ignore_permissions=True)

        self.assertIn(parent.name, lineage.parents(child.name))
        self.assertIn(child.name, [row["document"] for row in lineage.children(parent.name)])
        self.assertIn(addendum.name, [row["document"] for row in lineage.children(parent.name)])
        self.assertIn(parent.name, lineage.parents(addendum.name))

    def test_a_document_cannot_be_its_own_parent(self):
        doc = make_document()
        doc.parent_document = doc.name
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_a_circular_chain_is_refused_and_audited(self):
        first = make_document()
        second = make_document(parent_document=first.name)
        third = make_document(parent_document=second.name)

        first.parent_document = third.name
        self.purge_on_teardown(DOCTYPE, first.name)
        with self.assertRaises(frappe.ValidationError):
            first.save(ignore_permissions=True)

        frappe.db.rollback()
        refusals = [row for row in refusals_of(DOCTYPE, first.name)]
        self.assertTrue(refusals, "the refused cycle should be in the refusal log")
        self.assertEqual(refusals[-1]["control"], "lineage cycle")

    def test_a_cycle_through_a_relationship_row_is_refused(self):
        parent = make_document()
        child = make_document(parent_document=parent.name)
        child.append("relationships", {"related_document": parent.name, "relationship_type": "Child"})
        self.purge_on_teardown(DOCTYPE, child.name)
        with self.assertRaises(frappe.ValidationError):
            child.save(ignore_permissions=True)


def refusals_of(doctype, name):
    from consilium.policy.tests.utils import refusals_for

    return refusals_for(doctype, name)


class TestApplicability(PolicyTestCase):
    def _document_with_scope(self, group_members):
        group = make_user_group(group_members)
        doc = make_document()
        doc.append(
            "applicability",
            {"scope_type": "Organization Unit", "scope_value": doc.owning_operating_group,
             "notification_group": group},
        )
        doc.save(ignore_permissions=True)
        return doc, group

    def test_applicability_covers_units_entities_jurisdictions_and_roles(self):
        doc = make_document()
        jurisdiction = frappe.get_doc(
            {"doctype": "Jurisdiction", "jurisdiction_code": unique("JU"),
             "jurisdiction_name": "Somewhere", "jurisdiction_level": "Federal"}
        ).insert(ignore_permissions=True)
        legal_entity = frappe.get_doc(
            {"doctype": "Legal Entity", "legal_entity_code": unique("LE"), "legal_entity_name": "Entity"}
        ).insert(ignore_permissions=True)

        doc.append("applicability", {"scope_type": "Organization Unit",
                                     "scope_value": doc.owning_operating_group})
        doc.append("applicability", {"scope_type": "Legal Entity", "scope_value": legal_entity.name})
        doc.append("applicability", {"scope_type": "Jurisdiction", "scope_value": jurisdiction.name})
        doc.append("applicability", {"scope_type": "Role", "scope_value": "Policy Owner"})
        doc.append("applicability", {"scope_type": "Function", "scope_label": "Treasury"})
        doc.save(ignore_permissions=True)

        scopes = applicability.applicable_scopes(doc.name)
        self.assertEqual(len(scopes), 5)
        self.assertEqual(
            {row["scope_type"] for row in scopes},
            {"Organization Unit", "Legal Entity", "Jurisdiction", "Role", "Function"},
        )

    def test_a_scope_naming_a_record_must_name_one(self):
        doc = make_document()
        doc.append("applicability", {"scope_type": "Legal Entity"})
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_affected_parties_derive_from_applicability(self):
        member = make_user()
        doc, _group = self._document_with_scope([member])
        self.assertIn(member, applicability.affected_parties(doc.name))

    def test_a_role_scope_reaches_the_holders_of_that_role(self):
        holder = make_user("Policy Reviewer")
        doc = make_document()
        doc.append("applicability", {"scope_type": "Role", "scope_value": "Policy Reviewer"})
        doc.save(ignore_permissions=True)
        self.assertIn(holder, applicability.affected_parties(doc.name))

    def test_an_authorised_exemption_removes_a_scope_from_notification(self):
        member = make_user()
        doc, _group = self._document_with_scope([member])
        self.assertIn(member, applicability.affected_parties(doc.name))

        exemption = frappe.get_doc(
            {
                "doctype": "Applicability Exemption",
                "document": doc.name,
                "exemption_type": "Exemption",
                "scope_type": "Organization Unit",
                "scope_value": doc.owning_operating_group,
                "justification": "Covered by a local standard.",
                "requested_by": doc.document_owner,
            }
        ).insert(ignore_permissions=True)
        self.assertIn(member, applicability.affected_parties(doc.name))

        exemption.authorise(approved_by=doc.document_approver)
        self.assertNotIn(member, applicability.affected_parties(doc.name))

    def test_an_exemption_in_force_must_name_its_authoriser(self):
        doc = make_document()
        exemption = frappe.get_doc(
            {
                "doctype": "Applicability Exemption",
                "document": doc.name,
                "exemption_type": "Deviation",
                "scope_type": "Function",
                "scope_label": "Treasury",
                "justification": "Temporary.",
                "requested_by": doc.document_owner,
                "exemption_status": "Authorised",
            }
        )
        with self.assertRaises(frappe.ValidationError):
            exemption.insert(ignore_permissions=True)

    def test_notification_records_a_dispatch_per_affected_party(self):
        member = make_user()
        doc, _group = self._document_with_scope([member])
        dispatched = applicability.notify_affected(doc.name, "published")
        self.assertEqual(len(dispatched), 1)
        row = frappe.get_doc("Notification Dispatch", dispatched[0])
        self.assertEqual(row.recipient, member)
        self.assertEqual(row.subject_name, doc.name)

    def test_a_scope_that_reaches_nobody_is_reported_not_hidden(self):
        doc = make_document()
        doc.append("applicability", {"scope_type": "Organization Unit",
                                     "scope_value": doc.owning_operating_group})
        doc.save(ignore_permissions=True)
        self.assertEqual(applicability.affected_parties(doc.name), [])
        self.assertEqual(len(applicability.scopes_without_recipients(doc.name)), 1)
