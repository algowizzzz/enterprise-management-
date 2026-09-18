"""Recording a document's approval checks its approval chain (W3-5).

Found while writing the illustrated guides: "Record Approval" moved a document
from review to approved with every routed step still undecided — or with one
rejected — and the chain was first checked at publication. Approval is now
refused until the chain is complete, by the same configured gate publication
uses, reading decisions recorded through Core. A step decided by a live
delegate of its approver counts, because Core recorded it as that approver's.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import approvals, delegation
from consilium.policy import lifecycle, routing
from consilium.policy.tests.test_lifecycle import _version, _with_applicability
from consilium.policy.tests.utils import PolicyTestCase, as_user, make_document, make_user, refusals_for

DOCTYPE = "Governing Document"
OFFICE = "Enterprise Policy Office"


def _in_review():
    doc = _with_applicability(make_document())
    _version(doc)
    lifecycle.perform(doc, "Submit for Review")
    doc.reload()
    return doc


def _open_rows(doc):
    return [
        frappe.get_doc("Approval Decision", name)
        for name in frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": DOCTYPE, "subject_name": doc.name, "is_open": 1},
            pluck="name",
            order_by="step_sequence asc, creation asc",
        )
    ]


class TestRecordApprovalChecksTheChain(PolicyTestCase):
    def test_the_gate_is_configured_on_approval(self):
        gates = {row["gate"] for row in lifecycle.gates_for(DOCTYPE, "lifecycle_phase", "Approved")}
        self.assertIn("Complete Approval Chain", gates)

    def test_approval_is_refused_while_a_step_is_undecided_and_the_refusal_is_audited(self):
        doc = _in_review()
        routing.instantiate(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Record Approval")
        doc.reload()
        self.assertTrue(int(doc.requires_review or 0), "still under review")
        refusal = refusals_for(DOCTYPE, doc.name)[-1]
        self.assertEqual(refusal["control"], "lifecycle gate")
        self.assertIn("Complete Approval Chain", refusal["refusal_reason"])

    def test_the_portal_shows_the_block_and_refuses_the_action(self):
        office = make_user(OFFICE)
        doc = _in_review()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(office):
            offered = {row["action"]: row for row in lifecycle.document_actions(doc.name)["lifecycle"]}
            self.assertTrue(any("Complete Approval Chain" in b for b in offered["Record Approval"]["blocked_by"]))
            with self.assertRaises(frappe.ValidationError):
                lifecycle.take_action(doc.name, "Record Approval")

    def test_a_rejected_step_blocks_approval(self):
        doc = _in_review()
        routing.instantiate(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        for index, row in enumerate(_open_rows(doc)):
            approvals.record_decision(row, "Rejected" if index == 0 else "Approved",
                                      comments="Reviewed.", acting_user=row.assigned_to)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Record Approval")

    def test_a_step_decided_by_a_live_delegate_counts(self):
        doc = _in_review()
        routing.instantiate(doc)
        rows = _open_rows(doc)
        first = rows[0]
        delegate = make_user()
        frappe.get_doc({
            "doctype": "Authority Delegation",
            "delegator": first.assigned_to,
            "delegate": delegate,
            "scope_type": "DocType",
            "scope_doctype": DOCTYPE,
            "valid_from": nowdate(),
            "valid_to": add_days(nowdate(), 30),
            "delegated_actions": [{"delegable_action": delegation.ACTION_APPROVE}],
        }).insert(ignore_permissions=True)
        decided = approvals.record_decision(first, "Approved", comments="On the approver's behalf.",
                                            acting_user=delegate)
        self.assertTrue(decided.acting_delegation)
        for row in rows[1:]:
            approvals.record_decision(row.name, "Approved", comments="Reviewed.", acting_user=row.assigned_to)

        lifecycle.perform(doc, "Record Approval")
        doc.reload()
        self.assertFalse(int(doc.requires_review or 0))
        self.assertTrue(routing.chain_status(doc)["complete"])
