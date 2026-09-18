"""E12 — the lifecycle, the routing, and the refusals that matter.

No test in this file asserts on a state name. Records are moved by performing
configured actions, and the outcome is read from the semantic flags — which is
what the business logic does, so a state rename breaks neither.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import approvals, versioning
from consilium.policy import lifecycle, publication, routing
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_user,
    make_user_group,
    refusals_for,
)

DOCTYPE = "Governing Document"


def _with_applicability(doc, members=None):
    group = make_user_group(members or [make_user()])
    doc.append(
        "applicability",
        {"scope_type": "Organization Unit", "scope_value": doc.owning_operating_group,
         "notification_group": group},
    )
    doc.save(ignore_permissions=True)
    return doc


def _version(doc, summary="First upload."):
    return versioning.create_version(doc, change_summary=summary, origin="Uploaded", version_label="1.0")


def _approve_all(doc):
    """Decide every routed step affirmatively, as the assigned approver."""
    routing.instantiate(doc)
    for name in frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": DOCTYPE, "subject_name": doc.name, "is_open": 1},
        pluck="name",
        # In route order: a sequential step waits for the steps ahead (E7-S4).
        order_by="step_sequence asc, creation asc",
    ):
        row = frappe.get_doc("Approval Decision", name)
        approvals.record_decision(row, "Approved", comments="Content reviewed.", acting_user=row.assigned_to)


def approval_gate_off():
    """Switch off the approval-chain gate on Approved, for this test only.

    Recording the approval is refused while the routed chain is incomplete (a
    "Complete Approval Chain" gate on Approved). A test whose subject is the
    *publication* gate — which refuses the same incomplete chain again, and
    must hold on its own if an administrator removes the earlier row — turns
    the earlier one off so it can reach publication with the chain still
    incomplete. The change is rolled back with the test.
    """
    frappe.db.set_value(
        "Document Lifecycle Gate",
        {"target_doctype": DOCTYPE, "state_value": "Approved", "gate": "Complete Approval Chain"},
        "is_active", 0,
    )


class TestLifecycleConfiguration(PolicyTestCase):
    def test_the_lifecycle_is_configuration(self):
        workflow = frappe.get_doc("Workflow", "Governing Document Lifecycle")
        self.assertEqual(workflow.document_type, DOCTYPE)
        self.assertTrue(workflow.is_active)
        self.assertGreaterEqual(len(workflow.states), 6)
        self.assertGreaterEqual(len(workflow.transitions), 11)

    def test_available_actions_come_from_configuration(self):
        doc = make_document()
        actions = {entry["action"] for entry in lifecycle.available_actions(doc)}
        self.assertIn("Submit for Review", actions)

    def test_an_unconfigured_action_is_refused(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Teleport")

    def test_a_gate_must_name_an_implemented_check(self):
        """A gate binds a state to a check. A gate naming no check is a dead rule."""
        gate = frappe.get_doc(
            {
                "doctype": "Document Lifecycle Gate",
                "target_doctype": DOCTYPE,
                "state_field": "lifecycle_phase",
                "state_value": "Published",
                "gate": "Complete Approval Chain",
            }
        )
        gate.gate = "Whatever I Like"
        with self.assertRaises(frappe.ValidationError):
            gate.insert(ignore_permissions=True)

    def test_the_publication_gates_are_configured(self):
        gates = {
            row["gate"]
            for row in lifecycle.gates_for(DOCTYPE, "lifecycle_phase", "Published")
        }
        self.assertIn("Complete Approval Chain", gates)


class TestLifecycleTransitions(PolicyTestCase):
    def test_a_document_moves_through_drafting_review_and_approval(self):
        doc = _with_applicability(make_document())
        _version(doc)
        _approve_all(doc)
        self.assertEditable(doc, True)
        self.assertNotInForce(doc)

        lifecycle.perform(doc, "Submit for Review")
        doc.reload()
        self.assertTrue(int(doc.requires_review or 0))

        lifecycle.perform(doc, "Record Approval")
        self.assertEditable(doc, False)
        self.assertNotInForce(doc)

    def test_publication_puts_the_document_in_force(self):
        doc = _with_applicability(make_document())
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        lifecycle.perform(doc, "Publish")
        self.assertInForce(doc)
        self.assertEditable(doc, False)

    def test_retirement_takes_it_out_of_force_and_stamps_the_date(self):
        doc = _with_applicability(make_document())
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        lifecycle.perform(doc, "Publish")
        lifecycle.perform(doc, "Retire")
        self.assertNotInForce(doc)
        doc.reload()
        self.assertTrue(doc.retired_on)

    def test_reopening_makes_it_editable_again(self):
        doc = _with_applicability(make_document())
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        lifecycle.perform(doc, "Publish")
        lifecycle.perform(doc, "Reopen for Change")
        self.assertEditable(doc, True)


class TestPublicationRefusal(PolicyTestCase):
    """The publication gate, on its own (see `approval_gate_off`)."""

    def setUp(self):
        super().setUp()
        approval_gate_off()

    def test_publication_without_a_complete_approval_chain_is_refused(self):
        doc = _with_applicability(make_document())
        _version(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")

        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")

        doc.reload()
        self.assertNotInForce(doc)

        frappe.db.rollback()
        refusals = refusals_for(DOCTYPE, doc.name)
        self.assertTrue(refusals)
        self.assertEqual(refusals[-1]["control"], "lifecycle gate")
        self.assertIn("Complete Approval Chain", refusals[-1]["refusal_reason"])

    def test_publication_with_an_outstanding_step_is_refused(self):
        doc = _with_applicability(make_document())
        _version(doc)
        routing.instantiate(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")

        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")
        self.assertFalse(routing.chain_status(doc)["complete"])

    def test_a_rejected_step_blocks_publication(self):
        doc = _with_applicability(make_document())
        _version(doc)
        routing.instantiate(doc)
        rows = frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": DOCTYPE, "subject_name": doc.name},
            pluck="name",
            order_by="step_sequence asc, creation asc",
        )
        for index, name in enumerate(rows):
            row = frappe.get_doc("Approval Decision", name)
            outcome = "Rejected" if index == 0 else "Approved"
            approvals.record_decision(row, outcome, acting_user=row.assigned_to)

        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")

    def test_publication_without_a_version_is_refused(self):
        doc = _with_applicability(make_document())
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")

    def test_publication_without_applicability_is_refused(self):
        doc = make_document()
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")

    def test_a_bypass_needs_a_recorded_exception_authorisation(self):
        doc = _with_applicability(make_document())
        _version(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")

        authorisation = frappe.get_doc(
            {
                "doctype": "Exception Authorisation",
                "subject_doctype": DOCTYPE,
                "subject_name": doc.name,
                "exception_type": "Approval Bypass",
                "justification": "Regulator deadline; approvals gathered out of band.",
                "requested_by": doc.document_owner,
            }
        ).insert(ignore_permissions=True)

        self.purge_on_teardown(DOCTYPE, doc.name)
        # Unapproved: the bypass is still refused.
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish", exception_authorisation=authorisation.name)

        # Approved by the document's approver, who holds no standing to excuse a
        # gate: still refused (lifecycle.approval_unfit).
        frappe.db.set_value(
            "Exception Authorisation", authorisation.name, "approved_by", doc.document_approver
        )
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish", exception_authorisation=authorisation.name)

        frappe.db.set_value(
            "Exception Authorisation", authorisation.name, "approved_by", make_user("Enterprise Policy Office")
        )
        lifecycle.perform(doc, "Publish", exception_authorisation=authorisation.name)
        self.assertInForce(doc)

    def test_readiness_explains_the_refusal_before_it_happens(self):
        doc = _with_applicability(make_document())
        _version(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        readiness = lifecycle.readiness(doc.name)
        publish = [row for row in readiness["actions"] if row["action"] == "Publish"][0]
        self.assertTrue(publish["blocked_by"])
        self.assertFalse(readiness["approval_chain"]["complete"])


class TestApprovalRouting(PolicyTestCase):
    def _classified_document(self, outcome: str):
        doc = make_document()
        request = frappe.get_doc(
            {
                "doctype": "Document Intake Request",
                "request_type": "Change",
                "subject_document": doc.name,
                "requester": doc.document_owner,
                "business_justification": "A change is needed.",
                "created_document": doc.name,
                "change_classification": outcome,
            }
        ).insert(ignore_permissions=True)
        return doc, request

    def test_a_major_change_routes_through_three_approvals(self):
        doc, _request = self._classified_document("Major")
        preview = routing.preview(doc.name)
        self.assertEqual(preview["route"], "Major Change Route")
        self.assertEqual(len(preview["steps"]), 3)

    def test_a_minor_change_routes_through_one(self):
        doc, _request = self._classified_document("Minor")
        preview = routing.preview(doc.name)
        self.assertEqual(preview["route"], "Minor Change Route")
        self.assertEqual(len(preview["steps"]), 1)

    def test_an_unclassified_document_takes_the_conservative_default(self):
        doc = make_document()
        preview = routing.preview(doc.name)
        self.assertEqual(preview["route"], "Default Route")
        self.assertEqual(len(preview["steps"]), 2)

    def test_the_path_is_visible_before_submission(self):
        doc = make_document()
        preview = routing.preview(doc.name)
        self.assertEqual(preview["document"], doc.name)
        self.assertTrue(all(step["assigned_to"] for step in preview["steps"]))
        self.assertFalse(
            frappe.get_all("Approval Decision", filters={"subject_name": doc.name}),
            "a preview must not write anything",
        )

    def test_routing_is_configuration(self):
        doc = make_document()
        frappe.db.set_value("Approval Route", "Default Route", "is_active", 0)
        route = frappe.get_doc(
            {
                "doctype": "Approval Route",
                "route_title": "Type Specific Route",
                "target_doctype": DOCTYPE,
                "document_type": doc.document_type,
                "priority": 5,
                "is_active": 1,
                "steps": [
                    {
                        "step_sequence": 1,
                        "approval_step": "Single Approval",
                        "assignee_source": "Document Approver",
                        "is_mandatory": 1,
                    }
                ],
            }
        ).insert(ignore_permissions=True)
        preview = routing.preview(doc.name)
        self.assertEqual(preview["route"], route.name)

    def test_a_route_with_duplicate_step_names_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Approval Route",
                    "route_title": "Broken Route",
                    "target_doctype": DOCTYPE,
                    "priority": 1,
                    "steps": [
                        {"step_sequence": 1, "approval_step": "Same", "assignee_source": "Document Owner"},
                        {"step_sequence": 2, "approval_step": "Same", "assignee_source": "Document Owner"},
                    ],
                }
            ).insert(ignore_permissions=True)

    def test_instantiating_a_route_twice_does_not_duplicate_decisions(self):
        doc = make_document()
        first = routing.instantiate(doc)
        second = routing.instantiate(doc)
        self.assertTrue(first)
        self.assertEqual(second, [])


class TestParentOwnerApproval(PolicyTestCase):
    def test_lineage_adds_the_parent_owners_approval_as_a_distinct_step(self):
        parent = make_document()
        child = make_document(parent_document=parent.name)
        parent.append(
            "relationships",
            {"related_document": child.name, "relationship_type": "Child", "owner_approval_required": 1},
        )
        parent.save(ignore_permissions=True)

        preview = routing.preview(child.name)
        lineage_steps = [step for step in preview["steps"] if step["source"].startswith("lineage:")]
        self.assertEqual(len(lineage_steps), 1)
        self.assertEqual(lineage_steps[0]["assigned_to"], parent.document_owner)

    def test_without_the_flag_no_parent_step_is_added(self):
        parent = make_document()
        child = make_document(parent_document=parent.name)
        parent.append(
            "relationships",
            {"related_document": child.name, "relationship_type": "Child", "owner_approval_required": 0},
        )
        parent.save(ignore_permissions=True)
        preview = routing.preview(child.name)
        self.assertEqual([s for s in preview["steps"] if s["source"].startswith("lineage:")], [])

    def test_publication_is_refused_while_the_parent_owner_has_not_approved(self):
        approval_gate_off()
        parent = make_document()
        child = _with_applicability(make_document(parent_document=parent.name))
        parent.append(
            "relationships",
            {"related_document": child.name, "relationship_type": "Child", "owner_approval_required": 1},
        )
        parent.save(ignore_permissions=True)
        _version(child)

        routing.instantiate(child)
        rows = frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": DOCTYPE, "subject_name": child.name},
            fields=["name", "approval_step", "assigned_to"],
            order_by="step_sequence asc, creation asc",
        )
        for row in rows:
            if row["approval_step"].startswith(routing.PARENT_OWNER_STEP):
                continue
            approvals.record_decision(row["name"], "Approved", acting_user=row["assigned_to"])

        lifecycle.perform(child, "Submit for Review")
        lifecycle.perform(child, "Record Approval")
        self.purge_on_teardown(DOCTYPE, child.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(child, "Publish")


class TestVersioningAndPublication(PolicyTestCase):
    def test_an_uploaded_body_becomes_a_version_in_the_chain(self):
        doc = make_document()
        version = publication.upload_version(
            doc.name, change_summary="Initial upload.", body_text="The text.", version_label="1.0"
        )
        doc.reload()
        self.assertEqual(doc.current_version, version.name)
        self.assertEqual(doc.version_label, "1.0")
        self.assertEqual(doc.body_text, "The text.")
        self.assertTrue(version.body_sha256)

    def test_revert_writes_a_new_version_and_never_rewrites_one(self):
        doc = make_document()
        first = publication.upload_version(doc.name, change_summary="v1", body_text="one", version_label="1.0")
        publication.upload_version(doc.name, change_summary="v2", body_text="two", version_label="2.0")

        publication.revert(doc.name, first.name, "The second version was wrong.")
        history = versioning.version_history(DOCTYPE, doc.name)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-1]["origin"], "Reverted")
        first.reload()
        self.assertEqual(first.body_text, "one")
        self.assertFalse(int(first.is_current or 0))

    def test_a_version_cannot_be_taken_while_the_document_is_not_editable(self):
        doc = _with_applicability(make_document())
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        with self.assertRaises(frappe.ValidationError):
            publication.upload_version(doc.name, change_summary="sneaky", body_text="x")

    def test_publication_notifies_the_parties_applicability_reaches(self):
        member = make_user()
        doc = _with_applicability(make_document(), members=[member])
        version = _version(doc)
        record = publication.record_publication(doc.name, document_version=version.name)
        self.assertEqual(record.notified_count, 1)
        self.assertTrue(int(record.notification_dispatched))
        dispatched = frappe.get_all(
            "Notification Dispatch",
            filters={"subject_doctype": DOCTYPE, "subject_name": doc.name},
            pluck="recipient",
        )
        self.assertIn(member, dispatched)

    def test_a_publication_must_name_a_version_of_its_own_document(self):
        doc = make_document()
        other = make_document()
        version = _version(other)
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc(
                {
                    "doctype": "Document Publication",
                    "document": doc.name,
                    "document_version": version.name,
                    "audience_type": "All Employees",
                }
            ).insert(ignore_permissions=True)

    def test_a_view_only_rendition_closes_print_and_download(self):
        doc = make_document()
        version = _version(doc)
        record = publication.record_publication(doc.name, document_version=version.name, view_only=1)
        self.assertFalse(int(record.rendition_print))
        self.assertFalse(int(record.rendition_download))

    def test_a_reviewer_cannot_record_a_publication(self):
        doc = make_document()
        version = _version(doc)
        reviewer = make_user("Policy Reviewer")
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            publication.record_publication(doc.name, document_version=version.name)
