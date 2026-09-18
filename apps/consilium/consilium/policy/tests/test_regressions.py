"""Regressions found while loading a realistic demonstration organisation.

Each test here failed before its fix. They are kept apart from the behaviour
tests so the reason each exists stays readable: the docstring names the bug.
"""

from __future__ import annotations

import frappe

from consilium.policy import lifecycle, publication, routing
from consilium.policy.tests.test_lifecycle import _approve_all, _version, _with_applicability, approval_gate_off
from consilium.policy.tests.utils import PolicyTestCase, make_document

DOCTYPE = "Governing Document"


def _published(**values):
    doc = _with_applicability(make_document(**values))
    _version(doc)
    _approve_all(doc)
    lifecycle.perform(doc, "Submit for Review")
    lifecycle.perform(doc, "Record Approval")
    lifecycle.perform(doc, "Publish")
    return doc


def _open_tasks(child: str) -> list[str]:
    return frappe.get_all(
        "Metadata Remediation Task",
        filters={"subject_doctype": DOCTYPE, "subject_name": child, "trigger_event": "Parent Retired"},
        pluck="name",
    )


class TestImplementationGate(PolicyTestCase):
    def test_a_published_document_with_a_publication_record_can_be_implemented(self):
        """The publication gate asked for an empty date with ``is not set``, which
        PostgreSQL refuses for a date column — so nothing could be implemented."""
        doc = _published()
        publication.record_publication(doc.name)
        lifecycle.perform(doc, "Confirm Implementation")
        self.assertInForce(doc)

    def test_implementation_without_a_publication_record_is_still_refused(self):
        doc = _published()
        # Refusals are logged on their own connection and survive the rollback;
        # purge them, or the next test to be given this document number finds
        # a log row pointing at it.
        self.purge_on_teardown(DOCTYPE, doc.name)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Confirm Implementation")


class TestReopening(PolicyTestCase):
    def test_reopening_a_parent_does_not_tell_its_children_their_parent_retired(self):
        parent = _published()
        child = make_document(parent_document=parent.name)
        lifecycle.perform(parent, "Reopen for Change")
        self.assertEqual(_open_tasks(child.name), [])

    def test_retiring_a_parent_still_tells_its_children(self):
        parent = _published()
        child = make_document(parent_document=parent.name)
        lifecycle.perform(parent, "Retire")
        self.assertEqual(len(_open_tasks(child.name)), 1)

    def test_last_cycles_approvals_do_not_approve_a_new_version(self):
        """Decisions were matched to steps by name alone, so a reopened document
        found the previous cycle's approvals and could be republished unread."""
        doc = _published()
        self.purge_on_teardown(DOCTYPE, doc.name)
        approval_gate_off()  # the publication gate is the subject here
        lifecycle.perform(doc, "Reopen for Change")
        _version(doc, summary="Second edition.")
        doc.reload()
        status = routing.chain_status(doc)
        self.assertFalse(status["complete"])
        self.assertTrue(status["missing"], msg="every step is owed again for the new version")

        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish")

    def test_the_new_version_publishes_once_it_is_approved(self):
        doc = _published()
        lifecycle.perform(doc, "Reopen for Change")
        _version(doc, summary="Second edition.")
        doc.reload()
        _approve_all(doc)
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        lifecycle.perform(doc, "Publish")
        self.assertInForce(doc)

    def test_reinstating_a_retired_document_clears_its_retirement_date(self):
        doc = _published()
        lifecycle.perform(doc, "Retire")
        doc.reload()
        self.assertTrue(doc.retired_on)
        lifecycle.perform(doc, "Reinstate")
        doc.reload()
        self.assertFalse(doc.retired_on)


class TestMaintenanceView(PolicyTestCase):
    def test_the_limit_bounds_what_is_returned(self):
        from consilium.policy import metadata

        for _ in range(3):
            make_document(effective_on=None)
        found = metadata.incomplete_records(limit=1)
        self.assertLessEqual(len(found), 1)


class TestIntakeClock(PolicyTestCase):
    def test_fulfilling_a_request_stops_its_clock(self):
        from consilium.consilium_core import sla
        from consilium.policy import intake

        from consilium.policy.tests.test_intake import make_request

        request = make_request()
        definition = frappe.get_doc(
            {
                "doctype": "SLA Definition",
                "sla_code": frappe.generate_hash(length=8),
                "title": "Intake turnaround",
                "target_doctype": "Document Intake Request",
                "measure": "Total Open Time",
                "target_hours": 40,
                "calendar": "24x7",
            }
        ).insert(ignore_permissions=True)
        clock = sla.start_clock(definition.name, "Document Intake Request", request.name)
        frappe.db.set_value("Document Intake Request", request.name, "sla_clock", clock.name)

        base = make_document()
        overrides = {
            "document_type": base.document_type,
            "owning_operating_group": base.owning_operating_group,
            "primary_risk_category": base.primary_risk_category,
        }
        intake.create_document(request.name, **overrides)
        self.assertFalse(frappe.db.get_value("SLA Clock", clock.name, "is_open"))


class TestGatesOnEveryRoute(PolicyTestCase):
    """P-25. The workspace's workflow menu and a direct write both skipped the
    gates, so a document could be published with no approval chain."""

    def _approved_without_chain(self):
        doc = _with_applicability(make_document())
        _version(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        # Reviewed and approved through the proper route, but its approval
        # steps were never decided — possible only with the approval gate off,
        # which is how the publication gate is shown to hold on its own.
        approval_gate_off()
        lifecycle.perform(doc, "Submit for Review")
        lifecycle.perform(doc, "Record Approval")
        return doc

    def test_the_workflow_menu_cannot_publish_past_a_failing_gate(self):
        from frappe.model.workflow import apply_workflow

        doc = self._approved_without_chain()
        with self.assertRaises(frappe.ValidationError):
            apply_workflow(frappe.get_doc(DOCTYPE, doc.name), "Publish")
        self.assertNotInForce(doc)

    def test_writing_the_phase_directly_cannot_publish_either(self):
        doc = self._approved_without_chain()
        doc.reload()
        doc.lifecycle_phase = "Published"
        with self.assertRaises(frappe.ValidationError):
            doc.save(ignore_permissions=True)

    def test_the_proper_route_still_publishes_once_the_chain_is_complete(self):
        doc = self._approved_without_chain()
        _approve_all(doc)
        lifecycle.perform(doc, "Publish")
        self.assertInForce(doc)


class TestChangeLogForThePolicyOffice(PolicyTestCase):
    """The policy office was told "The change log is not available to you" on a
    document's Versions tab: the page read the framework's own change log
    (Version), which only administrators may list. The log is now read through
    Core's record history, which shows it to whoever may read the document."""

    def _changed(self, doc):
        import json

        frappe.get_doc({
            "doctype": "Version", "ref_doctype": DOCTYPE, "docname": doc.name,
            "data": json.dumps({"changed": [["lifecycle_phase", "Draft", "Review"], ["is_editable", 1, 0],
                                            ["requires_review", 0, 1]]}),
        }).insert(ignore_permissions=True)

    def test_the_policy_office_reads_a_documents_change_log(self):
        from consilium.consilium_core import evidence
        from consilium.policy.tests.utils import make_user

        doc = make_document()
        self._changed(doc)
        office = make_user("Enterprise Policy Office")
        frappe.set_user(office)
        self.assertTrue(frappe.has_permission(DOCTYPE, "read", doc=doc.name))
        changes = [e for e in evidence.record_history(DOCTYPE, doc.name)["entries"] if e["kind"] == "change"]
        self.assertTrue(changes, "the policy office sees the document's changes")
        phase = frappe.get_meta(DOCTYPE).get_label("lifecycle_phase")
        self.assertTrue(any(phase in e["summary"] for e in changes))
        # The semantic flags move with the phase; they are not news to a reader.
        for e in changes:
            for flag in ("is_editable", "Is Editable", "requires_review", "Requires Review"):
                self.assertNotIn(flag, e["summary"])

    def test_someone_who_cannot_read_the_document_gets_no_change_log(self):
        from consilium.consilium_core import evidence
        from consilium.policy.tests.utils import make_user

        doc = make_document()
        self._changed(doc)
        outsider = make_user("Escalation Owner")
        frappe.set_user(outsider)
        self.assertFalse(frappe.has_permission(DOCTYPE, "read", doc=doc.name))
        with self.assertRaises(frappe.PermissionError):
            evidence.record_history(DOCTYPE, doc.name)
