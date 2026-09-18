"""Adding a lifecycle state without a schema change (W3-5).

Found while writing the illustrated guides: a new state on the Governing
Document workflow ("Legal Review") was refused — "Lifecycle Phase cannot be
'Legal Review'" — because the workflow ran on the phase field, a Select with
fixed options that Customize Form will not edit.

A site now switches the workflow onto ``workflow_state`` once
(``lifecycle.derive_phase_from_state``), after which the phase follows the
state: each state's Workflow State Flag row names the phase it belongs to.
These tests switch, add a state the way an administrator would — a Workflow row
and a flag row, nothing else — and take a document through it. Everything is
rolled back with the test, and the base class clears the caches.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import state_flags
from consilium.policy import lifecycle
from consilium.policy.tests.test_lifecycle import _approve_all, _version, _with_applicability
from consilium.policy.tests.utils import PolicyTestCase, make_document, refusals_for

DOCTYPE = "Governing Document"
WORKFLOW = "Governing Document Lifecycle"
OFFICE = "Enterprise Policy Office"
NEW_STATE = "Legal Review"


def _ensure(doctype: str, name: str, values: dict) -> None:
    if not frappe.db.exists(doctype, name):
        frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def add_legal_review() -> None:
    """What the administrator does, and all of it: a state and two transitions
    on the Workflow, and one Workflow State Flag row naming the phase."""
    _ensure("Workflow State", NEW_STATE, {"workflow_state_name": NEW_STATE})
    _ensure("Workflow Action Master", "Send to Legal", {"workflow_action_name": "Send to Legal"})
    workflow = frappe.get_doc("Workflow", WORKFLOW)
    workflow.append("states", {"state": NEW_STATE, "doc_status": "0", "allow_edit": OFFICE})
    workflow.append("transitions", {"state": "Review", "action": "Send to Legal", "next_state": NEW_STATE,
                                    "allowed": OFFICE, "allow_self_approval": 1})
    workflow.append("transitions", {"state": NEW_STATE, "action": "Record Approval", "next_state": "Approved",
                                    "allowed": OFFICE, "allow_self_approval": 1})
    workflow.save(ignore_permissions=True)
    frappe.get_doc({
        "doctype": "Workflow State Flag",
        "target_doctype": DOCTYPE,
        "state_field": "workflow_state",
        "state_value": NEW_STATE,
        "phase": "Review",
        # Under legal review nobody edits the text: that is why it is its own state.
        "is_editable": 0, "is_active": 0, "requires_review": 1, "is_open": 1,
        "is_committable": 0, "requires_statement": 0, "is_affirmative": 0,
    }).insert(ignore_permissions=True)
    state_flags.clear_cache(DOCTYPE)
    frappe.clear_cache(doctype=DOCTYPE)


class TestDerivedPhase(PolicyTestCase):
    def test_before_the_switch_the_new_state_is_refused_as_the_guides_found(self):
        _ensure("Workflow State", NEW_STATE, {"workflow_state_name": NEW_STATE})
        doc = make_document()
        doc.reload()
        doc.lifecycle_phase = NEW_STATE
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_switching_moves_no_document(self):
        before = make_document()
        _version(_with_applicability(before))
        lifecycle.perform(before, "Submit for Review")
        result = lifecycle.derive_phase_from_state()
        self.assertTrue(result["switched"])
        self.assertEqual(frappe.get_cached_doc("Workflow", WORKFLOW).workflow_state_field, "workflow_state")
        before.reload()
        self.assertEqual((before.workflow_state, before.lifecycle_phase), ("Review", "Review"))
        self.assertTrue(int(before.requires_review or 0))
        self.assertFalse(lifecycle.derive_phase_from_state()["switched"], "running it again changes nothing")

    def test_a_new_state_is_a_workflow_row_and_a_flag_row(self):
        lifecycle.derive_phase_from_state()
        add_legal_review()

        doc = _with_applicability(make_document())
        doc.reload()
        self.assertEqual((doc.workflow_state, doc.lifecycle_phase), ("Draft", "Draft"))
        _version(doc)
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Send to Legal")
        doc.reload()
        self.assertEqual(doc.workflow_state, NEW_STATE)
        self.assertEqual(doc.lifecycle_phase, "Review", "the phase comes from the state's flag row")
        self.assertEqual((int(doc.is_editable), int(doc.requires_review)), (0, 1),
                         "and the flags from the state, not from the phase")

        lifecycle.perform(doc, "Record Approval")
        doc.reload()
        self.assertEqual((doc.workflow_state, doc.lifecycle_phase), ("Approved", "Approved"))
        lifecycle.perform(doc, "Publish")
        self.assertInForce(doc)

    def test_gates_are_asked_of_the_phase_a_state_belongs_to(self):
        lifecycle.derive_phase_from_state()
        add_legal_review()
        doc = _with_applicability(make_document())
        _version(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Send to Legal")
        self.purge_on_teardown(DOCTYPE, doc.name)
        # Approved's gates are configured on the phase; the chain is undecided.
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Record Approval")
        self.assertIn("Complete Approval Chain", refusals_for(DOCTYPE, doc.name)[-1]["refusal_reason"])

    def test_the_phase_cannot_be_written_past_its_state(self):
        lifecycle.derive_phase_from_state()
        doc = _with_applicability(make_document())
        self.purge_on_teardown(DOCTYPE, doc.name)
        doc.reload()
        doc.lifecycle_phase = "Published"
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)
        self.assertTrue(any(r["control"] == "lifecycle phase" for r in refusals_for(DOCTYPE, doc.name)))

    def test_a_state_whose_flag_row_names_no_phase_is_refused(self):
        lifecycle.derive_phase_from_state()
        add_legal_review()
        frappe.db.set_value("Workflow State Flag", {"target_doctype": DOCTYPE, "state_field": "workflow_state",
                                                    "state_value": NEW_STATE}, "phase", None)
        doc = _with_applicability(make_document())
        _version(doc)
        lifecycle.perform(doc, "Submit for Review")
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Send to Legal")

    def test_a_misspelt_phase_is_refused_where_it_is_typed(self):
        # Found writing the guides: "Legal" was saved, and the first move then
        # failed with a message about missing flags. It is refused on save now.
        row = {"doctype": "Workflow State Flag", "target_doctype": DOCTYPE, "state_field": "workflow_state",
               "state_value": f"{NEW_STATE} (spelling)", "is_editable": 0, "is_active": 0, "requires_review": 1,
               "is_open": 1, "is_committable": 0, "requires_statement": 0, "is_affirmative": 0}
        with self.assertRaises(frappe.ValidationError) as refused:
            frappe.get_doc({**row, "phase": "Legal"}).insert(ignore_permissions=True)
        self.assertIn("Review", str(refused.exception))  # the message lists the phases to use
        frappe.get_doc({**row, "phase": "Review"}).insert(ignore_permissions=True)
