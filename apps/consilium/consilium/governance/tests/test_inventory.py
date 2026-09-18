"""Reading the inventory: search, filter, hierarchy, interconnectivity, attestation."""

import frappe

from consilium.governance.tests import task_for
from frappe.utils import add_days, nowdate

from consilium.consilium_core import attestation
from consilium.governance import inventory, lifecycle, reviews
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_jurisdiction, make_org_unit, make_risk_category,
    make_seat, make_user, seat_role, unique,
)


class TestSearchAndFilter(GovernanceTestCase):
    def test_free_text_search_covers_identifier_name_and_mandate(self):
        forum = make_forum(forum_name="Model Risk Oversight Council",
                           description="Oversight of model validation.")
        make_forum(forum_name="Unrelated Forum", description="Something else.")

        self.assertIn(forum.name, [row["name"] for row in inventory.search("Model Risk")])
        self.assertIn(forum.name, [row["name"] for row in inventory.search("model validation")])
        self.assertIn(forum.name, [row["name"] for row in inventory.search(forum.name)])
        self.assertEqual(inventory.search("no forum says this"), [])

    def test_filtering_by_status_and_by_a_tagged_dimension(self):
        jurisdiction = make_jurisdiction()
        tagged = make_forum()
        tagged.append("jurisdictions", {"jurisdiction": jurisdiction})
        tagged.save(ignore_permissions=True)
        untagged = make_forum()

        names = [row["name"] for row in inventory.search(tagged={"jurisdiction": jurisdiction})]
        self.assertEqual(names, [tagged.name])

        lifecycle.set_forum_state(tagged, "Compliant")
        compliant = [row["name"] for row in
                     inventory.search(filters={"compliance_status": "Compliant"})]
        self.assertIn(tagged.name, compliant)
        self.assertNotIn(untagged.name, compliant)

    def test_results_paginate_and_sort(self):
        for index in range(3):
            make_forum(forum_name=f"Paged Forum {index}")
        page_one = inventory.search("Paged Forum", limit=2, order_by="forum_name asc")
        page_two = inventory.search("Paged Forum", limit=2, start=2, order_by="forum_name asc")
        self.assertEqual(len(page_one), 2)
        self.assertEqual(len(page_two), 1)
        self.assertEqual([row["forum_name"] for row in page_one],
                         sorted(row["forum_name"] for row in page_one))

    def test_search_respects_permissions(self):
        forum = make_forum()
        viewer = make_user("Governance Viewer")
        nobody = make_user()

        self.assertIn(forum.name, [row["name"] for row in inventory.search(user=viewer)])

        frappe.set_user(nobody)
        try:
            with self.assertRaises(frappe.PermissionError):
                inventory.search()
        finally:
            frappe.set_user("Administrator")


class TestRelationships(GovernanceTestCase):
    def test_the_hierarchy_reads_from_the_parent_link(self):
        parent = make_forum()
        child = make_forum(parent_forum=parent.name)
        self.assertIn(child.name, [row["name"] for row in inventory.hierarchy(parent.name)])

        roots = [row["name"] for row in inventory.hierarchy()]
        self.assertIn(parent.name, roots)
        self.assertNotIn(child.name, roots)

    def test_the_inverse_relationship_is_visible_from_the_other_side(self):
        forum = make_forum()
        upstream = make_forum()
        forum.append("upstream_links", {"linked_forum": upstream.name,
                                        "relationship_type": "Escalates To"})
        forum.save(ignore_permissions=True)

        near = inventory.interconnectivity(forum.name)
        self.assertEqual(near["outbound"][0]["linked_forum"], upstream.name)

        far = inventory.interconnectivity(upstream.name)
        self.assertEqual(far["inbound"][0]["parent"], forum.name)
        self.assertEqual(far["inbound"][0]["relationship_type"], "Escalates To")


class TestAttestationStamp(GovernanceTestCase):
    def test_a_completed_attestation_stamps_the_forum(self):
        forum = make_forum()
        chair = make_user()
        make_seat(forum.name, seat_role(is_chair_role=1, max_holders=1, can_attest=1), chair)

        campaign = reviews.open_inventory_attestation(unique("period"),
                                                      due_on=reviews.next_first_quarter_due())
        task_name = task_for(reviews.generate(campaign), forum.name)

        self.assertIsNone(inventory.stamp_attestation(task_name))
        self.assertIn(forum.name, [row["name"] for row in inventory.unattested()])

        attestation.respond(task_name, "Attested")
        self.assertEqual(inventory.stamp_attestation(task_name), forum.name)
        forum.reload()
        self.assertEqual(str(forum.last_attested_on), nowdate())

    def test_the_sweep_stamps_every_completed_task(self):
        forum = make_forum()
        make_seat(forum.name, seat_role(is_owner_role=1, max_holders=1, can_attest=1), make_user())
        campaign = reviews.open_inventory_attestation(unique("period"),
                                                      due_on=reviews.next_first_quarter_due())
        for task in reviews.generate(campaign)["created"]:
            attestation.respond(task, "Attested")
        self.assertIn(forum.name, inventory.refresh_last_attested(campaign.name))

    def test_a_declined_attestation_still_stamps_but_flags_review(self):
        forum = make_forum()
        make_seat(forum.name, seat_role(is_owner_role=1, max_holders=1, can_attest=1), make_user())
        campaign = reviews.open_inventory_attestation(unique("period"),
                                                      due_on=reviews.next_first_quarter_due())
        task_name = task_for(reviews.generate(campaign), forum.name)
        attestation.respond(task_name, "Declined", statement="The record is out of date.")

        task = frappe.get_doc("Attestation Task", task_name)
        self.assertTrue(task.requires_review)
        self.assertEqual(inventory.stamp_attestation(task), forum.name)
