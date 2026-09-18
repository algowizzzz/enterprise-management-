"""The policy module's remaining wave-3 items, each pinned by what it must do.

E11-S2 search and the owner filter; E11-S5 change and retirement notices; the
reporting sections P-4, P-12 and P-22 ask for; P-26 dispositions; E15-S5
correction in place; the glossary on the document page and on upload; lineage
that does not name what the viewer may not read; violation transitions; intake
fulfilment; approved gate exceptions; attestation campaigns from a document;
the reviewer's return; and the regulatory-change import (P-6, O-7).

As everywhere in this module's tests, nothing asserts on a state name: records
move by configured actions and are read back through their flags. Tests that
provoke an audited refusal purge the refusal log on teardown.
"""

from __future__ import annotations

import csv
import io

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import approvals, importing, versioning
from consilium.policy import (
    attestation,
    disposition,
    glossary,
    intake,
    lifecycle,
    lineage,
    metadata,
    monitoring,
    publication,
    regulatory_import,
    reporting,
    repository,
    routing,
)
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_document,
    make_user,
    make_user_group,
    refusals_for,
    unique,
)

DOCTYPE = "Governing Document"
OFFICE = "Enterprise Policy Office"
OWNER = "Policy Owner"
REVIEWER = "Policy Reviewer"


# --------------------------------------------------------------------- helpers


def _with_applicability(doc, members):
    group = make_user_group(members)
    doc.append(
        "applicability",
        {"scope_type": "Organization Unit", "scope_value": doc.owning_operating_group, "notification_group": group},
    )
    doc.save(ignore_permissions=True)
    return doc


def _version(doc, label="1.0", body="The first text."):
    version = versioning.create_version(doc, change_summary=f"Version {label}.", origin="Uploaded",
                                        version_label=label, body_text=body)
    frappe.db.set_value(DOCTYPE, doc.name, {"current_version": version.name, "version_label": label})
    doc.reload()
    return version


def _approve_all(doc):
    """Decide every routed step affirmatively, in sequence, as its assignee."""
    routing.instantiate(doc)
    for _attempt in range(20):
        rows = frappe.get_all(
            "Approval Decision",
            filters={"subject_doctype": DOCTYPE, "subject_name": doc.name, "is_open": 1},
            fields=["name"],
            order_by="step_sequence asc, creation asc",
        )
        if not rows:
            return
        row = frappe.get_doc("Approval Decision", rows[0]["name"])
        approvals.record_decision(row, "Approved", comments="Content reviewed.", acting_user=row.assigned_to)


def _audience_document(**values):
    member = make_user()
    doc = _with_applicability(make_document(**values), [member])
    _version(doc)
    return doc, member


def _publish(doc):
    lifecycle.perform(doc, "Submit for Review")
    _approve_all(doc)
    lifecycle.perform(doc, "Record Approval")
    lifecycle.perform(doc, "Publish")
    doc.reload()
    return doc


def _dispatches(document, recipient=None, subject_like=None):
    filters = {"subject_doctype": DOCTYPE, "subject_name": document}
    if recipient:
        filters["recipient"] = recipient
    if subject_like:
        filters["rendered_subject"] = ["like", subject_like]
    return frappe.get_all("Notification Dispatch", filters=filters, fields=["recipient", "rendered_subject",
                                                                            "rendered_body"])


def _dispositions(document):
    return frappe.get_all("Document Disposition", filters={"document": document},
                          fields=["*"], order_by="creation asc")


# ------------------------------------------------------------------ E11-S2


class TestSearch(PolicyTestCase):
    def test_search_finds_the_current_versions_text_when_the_record_carries_none(self):
        marker = frappe.generate_hash(length=12)
        doc = make_document()
        _version(doc, body=f"Only the version says {marker}.")
        self.assertFalse(frappe.db.get_value(DOCTYPE, doc.name, "body_text"))
        self.assertIn(doc.name, [row["name"] for row in repository.search(text=marker)])

    def test_the_owner_filter_and_the_abstract(self):
        marker = frappe.generate_hash(length=10)
        doc = make_document(document_name=f"Rates {marker}", document_abstract="Covers the cover ratio.")
        other = make_document(document_name=f"Rates {marker} other")
        found = [row["name"] for row in repository.search(text="cover ratio", document_owner=doc.document_owner)]
        self.assertEqual(found, [doc.name])
        by_owner = [row["name"] for row in repository.search(text=marker, document_owner=other.document_owner)]
        self.assertEqual(by_owner, [other.name])

    def test_a_restricted_document_is_neither_found_nor_counted_for_someone_not_named(self):
        marker = frappe.generate_hash(length=10)
        secret = make_document(document_name=f"Secret {marker}", handling_classification="Restricted")
        reviewer = make_user(REVIEWER)
        with as_user(reviewer):
            self.assertNotIn(secret.name, [row["name"] for row in repository.search(text=marker)])
            self.assertNotIn(secret.document_owner, [row["user"] for row in repository.owners()])
        self.assertIn(secret.name, [row["name"] for row in repository.search(text=marker)])

    def test_the_inventory_page_offers_the_owner_filter_and_content_search(self):
        from consilium.policy.tests.test_portal_actions import TestPages

        status, body = TestPages._render(self, "policies", make_user(OWNER), {})
        self.assertEqual(status, 200)
        self.assertIn('id="f-owner"', body)
        self.assertIn("repository.search", body)
        # The filters are written back to the address, so a view can be shared.
        self.assertIn("function writeAddress()", body)
        self.assertIn("history.replaceState", body)
        self.assertRegex(body, r"function applyFilters\(\) \{\s*writeAddress\(\);")


# ------------------------------------------------------ E11-S5, P-26, E13


class TestChangeAndRetirement(PolicyTestCase):
    def test_first_publication_is_not_announced_as_a_change(self):
        doc, member = _audience_document()
        _publish(doc)
        self.assertEqual(_dispatches(doc.name, member, "Changed:%"), [])

    def test_a_new_version_in_force_is_announced_to_the_audience(self):
        doc, member = _audience_document()
        _publish(doc)
        publication.record_publication(doc.name)
        lifecycle.perform(doc, "Reopen for Change")
        publication.upload_version(doc.name, change_summary="Thresholds lowered.", body_text="Second text.",
                                   version_label="2.0")
        doc.reload()
        _publish(doc)
        sent = _dispatches(doc.name, member, "Changed:%")
        self.assertEqual(len(sent), 1)
        self.assertIn("2.0", sent[0]["rendered_subject"])
        self.assertIn("Thresholds lowered.", sent[0]["rendered_body"])

    def test_retirement_records_a_disposition_tells_the_audience_and_deletes_nothing(self):
        code = unique("RC")
        frappe.get_doc({"doctype": "Retention Class", "class_code": code, "title": "Seven years",
                        "retention_period_months": 84, "trigger_event": "Retirement",
                        "disposition_action": "Review", "is_active": 1}).insert(ignore_permissions=True)
        doc, member = _audience_document(retention_class=code)
        _publish(doc)
        office = make_user(OFFICE)
        with as_user(office):
            lifecycle.take_action(doc.name, "Retire", comments="Superseded by the group framework.")
        doc.reload()
        self.assertFalse(int(doc.is_active))
        retired = [row for row in _dispositions(doc.name) if row.disposition_kind == disposition.RETIRED]
        self.assertEqual(len(retired), 1)
        row = retired[0]
        self.assertEqual(row.decided_by, office)
        self.assertEqual(row.reason, "Superseded by the group framework.")
        self.assertEqual(row.retention_class, code)
        self.assertEqual(str(row.disposition_due_on), str(frappe.utils.add_months(doc.retired_on, 84)))
        self.assertIn(code, row.retention_outcome)
        for person in (member, doc.document_owner):
            self.assertEqual(len(_dispatches(doc.name, person, "Retired:%")), 1)
        # Nothing is deleted: the record and its whole chain are still there.
        self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))
        self.assertTrue(versioning.current_version(DOCTYPE, doc.name))

    def test_retiring_from_the_portal_needs_a_reason(self):
        doc, _member = _audience_document()
        _publish(doc)
        with as_user(make_user(OFFICE)), self.assertRaises(frappe.ValidationError):
            lifecycle.take_action(doc.name, "Retire")
        self.assertTrue(frappe.db.get_value(DOCTYPE, doc.name, "is_active"))

    def test_a_disposition_cannot_be_rewritten(self):
        doc, _member = _audience_document()
        _publish(doc)
        lifecycle.perform(doc, "Retire")
        row = frappe.get_doc("Document Disposition", _dispositions(doc.name)[-1].name)
        self.purge_on_teardown("Document Disposition", row.name)
        row.reason = "Changed afterwards."
        with self.assertRaises(frappe.PermissionError):
            row.save(ignore_permissions=True)

    def test_change_and_retirement_requests_are_fulfilled_by_the_documents_movement(self):
        doc, _member = _audience_document()
        requester = make_user(OWNER)

        def request(kind, why):
            req = frappe.get_doc({"doctype": "Document Intake Request", "request_type": kind,
                                  "subject_document": doc.name, "requester": requester,
                                  "business_justification": why, "change_classification": "Minor",
                                  "workflow_state": intake.STATE_REQUESTED}).insert(ignore_permissions=True)
            intake.start_service_level(req)
            return req.name

        change = request("Change", "Lower the thresholds.")
        retire = request("Retire", "The activity has been wound down.")
        _publish(doc)
        self.assertFalse(frappe.db.get_value("Document Intake Request", change, "is_open"))
        self.assertTrue(frappe.db.get_value("Document Intake Request", retire, "is_open"))
        clock = frappe.db.get_value("Document Intake Request", change, "sla_clock")
        if clock:
            self.assertFalse(frappe.db.get_value("SLA Clock", clock, "is_open"))

        lifecycle.perform(doc, "Retire")
        self.assertFalse(frappe.db.get_value("Document Intake Request", retire, "is_open"))
        # Nobody gave a reason at the time, so the request's justification is the reason.
        reason = [row for row in _dispositions(doc.name) if row.disposition_kind == disposition.RETIRED][0].reason
        self.assertIn("wound down", reason)


# ------------------------------------------------------------- P-26, item 13


class TestReviewerReturn(PolicyTestCase):
    def test_the_review_state_is_edited_by_the_owner_not_the_reviewer(self):
        workflow = frappe.get_doc("Workflow", "Governing Document Lifecycle")
        editors = {row.allow_edit for row in workflow.states}
        self.assertNotIn(REVIEWER, editors)

    def test_a_reviewer_returns_with_comments_and_the_owner_is_told(self):
        doc, _member = _audience_document()
        lifecycle.perform(doc, "Submit for Review")
        reviewer = make_user(REVIEWER)
        with as_user(reviewer):
            with self.assertRaises(frappe.ValidationError):
                lifecycle.take_action(doc.name, "Return to Drafting")
            lifecycle.take_action(doc.name, "Return to Drafting", comments="Section 4 contradicts the parent.")
        doc.reload()
        self.assertTrue(int(doc.is_editable))
        row = _dispositions(doc.name)[-1]
        self.assertEqual(row.disposition_kind, disposition.REVIEW_RETURNED)
        self.assertEqual(row.decided_by, reviewer)
        self.assertEqual(row.originator, doc.document_owner)
        sent = _dispatches(doc.name, doc.document_owner, "Review Returned:%")
        self.assertEqual(len(sent), 1)
        self.assertIn("Section 4 contradicts the parent.", sent[0]["rendered_body"])

    def test_a_reviewer_cannot_edit_the_content(self):
        doc, _member = _audience_document()
        lifecycle.perform(doc, "Submit for Review")
        reviewer = make_user(REVIEWER)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(reviewer):
            fetched = frappe.get_doc(DOCTYPE, doc.name)
            fetched.document_abstract = "Rewritten by the reviewer."
            with self.assertRaises(frappe.PermissionError):
                fetched.save()
            with self.assertRaises(frappe.PermissionError):
                publication.upload_new_version(doc.name, change_summary="Reviewer text.", body_text="x")

    def test_accepting_a_review_records_it(self):
        doc, _member = _audience_document()
        lifecycle.perform(doc, "Submit for Review")
        _approve_all(doc)
        lifecycle.perform(doc, "Record Approval")
        self.assertEqual(_dispositions(doc.name)[-1].disposition_kind, disposition.REVIEW_ACCEPTED)
        with as_user(doc.document_owner):
            self.assertEqual(len(disposition.document_dispositions(doc.name)), 1)


# ------------------------------------------------------------------- item 11


class TestGateExceptions(PolicyTestCase):
    def _approved_awaiting_publication(self):
        from consilium.policy.tests.test_lifecycle import approval_gate_off

        doc, _member = _audience_document()
        lifecycle.perform(doc, "Submit for Review")
        # No approvals: Publish is gated. Reaching Approved so needs the
        # approval-chain gate on Approved off; the publication gate's exception
        # path is the subject here.
        approval_gate_off()
        lifecycle.perform(doc, "Record Approval")
        return doc

    def test_requested_by_the_owner_approved_by_the_office_then_it_clears_the_gate(self):
        doc = self._approved_awaiting_publication()
        office = make_user(OFFICE)
        with as_user(doc.document_owner):
            ctx = lifecycle.request_gate_exception(doc.name, "Regulator deadline; approvals gathered on paper.")
        pending = ctx["pending_exception_authorisations"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(ctx["exception_authorisations"], [])
        with as_user(office):
            ctx = lifecycle.approve_gate_exception(pending[0]["name"])
            self.assertEqual([row["name"] for row in ctx["exception_authorisations"]], [pending[0]["name"]])
            lifecycle.take_action(doc.name, "Publish", exception_authorisation=pending[0]["name"])
        self.assertTrue(frappe.db.get_value(DOCTYPE, doc.name, "is_active"))

    def test_nobody_approves_their_own_request(self):
        doc = self._approved_awaiting_publication()
        office = make_user(OFFICE)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(office):
            ctx = lifecycle.request_gate_exception(doc.name, "Asked and granted by one person.")
            with self.assertRaises(frappe.PermissionError):
                lifecycle.approve_gate_exception(ctx["pending_exception_authorisations"][0]["name"])
        self.assertTrue(any(row["control"] == "exception authorisation segregation"
                            for row in refusals_for(DOCTYPE, doc.name)))

    def test_an_approval_by_someone_without_the_standing_does_not_clear_a_gate(self):
        doc = self._approved_awaiting_publication()
        self.purge_on_teardown(DOCTYPE, doc.name)
        forged = frappe.get_doc({
            "doctype": "Exception Authorisation", "subject_doctype": DOCTYPE, "subject_name": doc.name,
            "exception_type": lifecycle.GATE_EXCEPTION_TYPE, "justification": "Approved by a colleague.",
            "requested_by": doc.document_owner, "approved_by": make_user(OWNER), "approved_on": frappe.utils.now(),
        }).insert(ignore_permissions=True)
        self.assertNotIn(forged.name, [row["name"] for row in lifecycle.usable_exception_authorisations(doc)])
        with self.assertRaises(frappe.ValidationError):
            lifecycle.perform(doc, "Publish", exception_authorisation=forged.name)
        self.assertFalse(frappe.db.get_value(DOCTYPE, doc.name, "is_active"))

    def test_a_self_approved_step_bypass_does_not_excuse_other_gates(self):
        doc = self._approved_awaiting_publication()
        office = make_user(OFFICE)
        self_approved = frappe.get_doc({
            "doctype": "Exception Authorisation", "subject_doctype": DOCTYPE, "subject_name": doc.name,
            "exception_type": "Approval Bypass", "justification": "One step bypassed.",
            "requested_by": office, "approved_by": office, "approved_on": frappe.utils.now(),
        }).insert(ignore_permissions=True)
        self.assertEqual(lifecycle.usable_exception_authorisations(doc), [])
        self.assertIn("nobody approves their own", lifecycle.approval_unfit(self_approved.as_dict()))


# ------------------------------------------------------------------ E15-S5


class TestMetadataCorrection(PolicyTestCase):
    def test_a_published_document_is_corrected_with_a_reason_and_no_new_version(self):
        doc, _member = _audience_document()
        _publish(doc)
        versions = frappe.db.count("Document Version", {"subject_doctype": DOCTYPE, "subject_name": doc.name})
        with as_user(doc.document_owner):
            form = metadata.correction_form(doc.name)
            self.assertTrue(form["can_correct"])
            fields = {row["fieldname"] for row in form["fields"]}
            self.assertIn("next_review_on", fields)
            self.assertNotIn("body_text", fields)
            self.assertNotIn("lifecycle_phase", fields)
            with self.assertRaises(frappe.ValidationError):
                metadata.correct_metadata(doc.name, "next_review_on", "2027-03-31")  # no reason
            result = metadata.correct_metadata(doc.name, "next_review_on", "2027-03-31",
                                               reason="The review date was keyed a year late.")
        doc.reload()
        self.assertEqual(str(doc.next_review_on), "2027-03-31")
        self.assertTrue(int(doc.is_active))
        self.assertEqual(
            frappe.db.count("Document Version", {"subject_doctype": DOCTYPE, "subject_name": doc.name}), versions
        )
        self.assertIn("keyed a year late", result["history"][0]["content"])

    def test_content_and_lifecycle_are_not_correctable(self):
        doc = make_document()
        for fieldname in ("body_text", "lifecycle_phase", "current_version"):
            with self.assertRaises(frappe.ValidationError):
                metadata.correct(DOCTYPE, doc.name, {fieldname: "x"}, reason="Trying.")

    def test_a_reviewer_is_refused(self):
        doc = make_document()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)):
            self.assertFalse(metadata.correction_form(doc.name)["can_correct"])
            with self.assertRaises(frappe.PermissionError):
                metadata.correct_metadata(doc.name, "effective_on", "2026-01-01", reason="Reviewer.")


# ------------------------------------------------------------ items 6 and 7


class TestGlossaryOnThePage(PolicyTestCase):
    def test_an_upload_is_held_to_the_glossary(self):
        from consilium.policy.tests.test_naming_glossary import make_term

        official = unique("Risk Appetite Statement")
        synonym = unique("Appetite Note")
        make_term(official, synonyms=[synonym])
        doc = make_document()
        self.purge_on_teardown(DOCTYPE, doc.name)
        before = frappe.db.count("Document Version", {"subject_doctype": DOCTYPE, "subject_name": doc.name})
        with self.assertRaises(frappe.ValidationError):
            publication.upload_version(doc.name, change_summary="New text.", body_text=f"Each {synonym} is signed.")
        self.assertEqual(
            frappe.db.count("Document Version", {"subject_doctype": DOCTYPE, "subject_name": doc.name}), before
        )
        self.assertTrue(any(row["control"] == "glossary enforcement" for row in refusals_for(DOCTYPE, doc.name)))
        publication.upload_version(doc.name, change_summary="New text.", body_text=f"Each {official} is signed.")

    def test_the_document_page_reads_the_terms_in_context(self):
        from consilium.policy.tests.test_portal_actions import TestPages

        doc = make_document()
        status, body = TestPages._render(self, "policy", doc.document_owner, {"name": doc.name})
        self.assertEqual(status, 200)
        self.assertIn("glossary.in_context", body)


# ------------------------------------------------------------------- item 8


class TestLineageVisibility(PolicyTestCase):
    def test_a_restricted_child_is_not_named_to_someone_who_cannot_read_it(self):
        parent = make_document()
        open_child = make_document(parent_document=parent.name)
        secret_child = make_document(parent_document=parent.name, handling_classification="Restricted")
        grandchild = make_document(parent_document=secret_child.name)
        reviewer = make_user(REVIEWER)
        with as_user(reviewer):
            seen = lineage.lineage_of(parent.name)
        names = [row["document"] for row in seen["children"]]
        self.assertIn(open_child.name, names)
        self.assertNotIn(secret_child.name, names)
        self.assertNotIn(secret_child.name, seen["descendants"])
        # The walk still goes through it: a readable grandchild is still found.
        self.assertIn(grandchild.name, seen["descendants"])
        full = lineage.lineage_of(parent.name)
        self.assertIn(secret_child.name, full["descendants"])


# ------------------------------------------------------------------- item 9


class TestViolationTransitions(PolicyTestCase):
    def _violation(self, doc, **values):
        return frappe.get_doc({
            "doctype": "Policy Violation", "document": doc.name, "violation_type": "Control", "severity": "High",
            "identified_on": nowdate(), "description": "Threshold exceeded without sign-off.",
            **values,
        }).insert(ignore_permissions=True)

    def _closing_status(self):
        from consilium.consilium_core import state_flags

        for status in monitoring._options("Policy Violation", "violation_status"):
            flags = state_flags.flags_for("Policy Violation", "violation_status", status) or {}
            if not flags.get("is_open"):
                return status
        raise AssertionError("no closing status is configured")

    def test_a_violation_cannot_be_logged_closed(self):
        doc = make_document()
        with self.assertRaises(frappe.ValidationError):
            self._violation(doc, violation_status=self._closing_status(), resolution_note="Done.")

    def test_closing_needs_a_note_and_a_closed_violation_stays_closed(self):
        doc = make_document()
        violation = self._violation(doc)
        self.purge_on_teardown("Policy Violation", violation.name)
        opening = violation.violation_status
        violation.violation_status = self._closing_status()
        with self.assertRaises(frappe.ValidationError):
            violation.save(ignore_permissions=True)
        violation.reload()
        violation.violation_status = self._closing_status()
        violation.resolution_note = "Control redesigned and retested."
        violation.save(ignore_permissions=True)
        self.assertTrue(violation.resolved_on)
        violation.reload()
        violation.violation_status = opening
        with self.assertRaises(frappe.ValidationError):
            violation.save(ignore_permissions=True)
        self.assertTrue(any(row["control"] == "violation transition"
                            for row in refusals_for("Policy Violation", violation.name)))

    def test_the_owner_moves_a_violation_from_the_portal_and_a_reviewer_may_not(self):
        doc = make_document()
        violation = self._violation(doc)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            monitoring.update_violation(violation.name, self._closing_status(), resolution_note="x")
        with as_user(doc.document_owner):
            ctx = monitoring.update_violation(violation.name, self._closing_status(),
                                              resolution_note="Retrained the team.")
        row = [v for v in ctx["violations"] if v["name"] == violation.name][0]
        self.assertFalse(int(row["is_open"]))


# ------------------------------------------------------------------ item 12


class TestAttestationCampaign(PolicyTestCase):
    def test_the_office_opens_a_campaign_for_the_documents_audience(self):
        doc, member = _audience_document()
        _publish(doc)
        office = make_user(OFFICE)
        with as_user(office):
            ctx = attestation.open_campaign(doc.name, add_days(nowdate(), 30))
        self.assertEqual(ctx["campaign"]["created"], 1)
        tasks = frappe.get_all("Attestation Task", filters={"campaign": ctx["campaign"]["name"]},
                               fields=["assigned_to", "subject_name"])
        self.assertEqual(tasks, [{"assigned_to": member, "subject_name": doc.name}])
        self.assertEqual(len(_dispatches(doc.name, member, "Attestation requested:%")), 1)
        board = attestation.document_campaigns(doc.name)
        self.assertEqual([row["name"] for row in board], [ctx["campaign"]["name"]])

    def test_only_the_office_opens_one_and_only_for_a_document_in_force(self):
        doc, _member = _audience_document()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(OFFICE)), self.assertRaises(frappe.ValidationError):
            attestation.open_campaign(doc.name, add_days(nowdate(), 30))  # not in force
        _publish(doc)
        with as_user(doc.document_owner), self.assertRaises(frappe.PermissionError):
            attestation.open_campaign(doc.name, add_days(nowdate(), 30))


# ---------------------------------------------------------- P-4, P-12, P-22


class TestReporting(PolicyTestCase):
    def test_sections_count_only_what_the_viewer_may_read(self):
        parent = make_document()
        make_document(parent_document=parent.name)
        secret = make_document(parent_document=parent.name, handling_classification="Restricted")
        for doc in (parent, secret):
            frappe.get_doc({"doctype": "Policy Violation", "document": doc.name, "violation_type": "Process",
                            "severity": "Low", "identified_on": nowdate(),
                            "description": "Found in testing."}).insert(ignore_permissions=True)
        office, owner = make_user(OFFICE), make_user(OWNER)
        with as_user(office):
            wide = reporting.policy_sections()
        with as_user(owner):
            narrow = reporting.policy_sections()

        def family(sections):
            return [row for row in sections["families"] if row["document"] == parent.name][0]

        def open_names(sections):
            return {row["document"] for row in sections["violations"]["open_violations"]}

        self.assertEqual(family(wide)["members"], 2)
        self.assertEqual(family(narrow)["members"], 1)
        self.assertIn(secret.name, open_names(wide))
        self.assertNotIn(secret.name, open_names(narrow))
        self.assertIn(parent.name, open_names(narrow))

    def test_export_is_the_same_rows_as_a_file(self):
        parent = make_document()
        make_document(parent_document=parent.name)
        text = reporting.export("families")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertIn(parent.name, [row["document"] for row in rows])
        with self.assertRaises(frappe.ValidationError):
            reporting.export("salaries")

    def test_a_spreadsheet_formula_is_exported_as_text(self):
        self.assertEqual(reporting._cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")


# ------------------------------------------------------------ P-6, O-7


class TestRegulatoryChangeImport(PolicyTestCase):
    def _requirement(self, code):
        return frappe.get_doc({"doctype": "Regulatory Requirement", "regulatory_requirement_code": code,
                               "regulatory_requirement_name": f"Rule {code}", "citation": f"Art. {code}",
                               "summary": "The original obligation.", "is_active": 1}).insert(ignore_permissions=True)

    def test_the_profile_is_seeded_and_registered(self):
        profile = regulatory_import.ensure_profile()
        self.assertEqual(frappe.db.get_value("Import Profile", profile, "target_doctype"), "Regulatory Requirement")
        self.assertIn("consilium.policy.regulatory_import.prepare_changes",
                      frappe.get_hooks("consilium_import_preparers").get("Regulatory Requirement"))

    def test_a_change_file_updates_what_changed_leaves_blanks_alone_and_tells_the_citers(self):
        changed, unchanged = self._requirement(unique("REQ")), self._requirement(unique("REQ"))
        doc = make_document(regulatory_required=1,
                            regulatory_references=[{"regulatory_requirement": changed.name}])
        new_code = unique("REQ")
        content = (
            "Change Reference,Code,Name,Citation,Summary\n"
            f"CHG-1,{changed.name},,,The tightened obligation.\n"
            f"CHG-2,{unchanged.name},,,The original obligation.\n"
            f"CHG-3,{new_code},A new rule,Art. 9,Brand new.\n"
        )
        review = importing.upload_batch(regulatory_import.ensure_profile(), "changes.csv", content)
        outcome = importing.commit_reviewed_batch(review["batch"]["name"])
        self.assertEqual(outcome["outcome"]["committed"], 2)
        self.assertEqual(outcome["outcome"]["skipped"], 1)

        changed.reload()
        self.assertEqual(changed.summary, "The tightened obligation.")
        self.assertEqual(changed.citation, f"Art. {changed.name}")  # the blank cell left it alone
        self.assertTrue(frappe.db.exists("Regulatory Requirement", new_code))
        self.assertTrue(frappe.db.exists("External Reference", {"subject_name": changed.name,
                                                                "external_key": "CHG-1"}))
        messages = {row["row_number"]: row["messages"] for row in outcome["rows"]}
        self.assertTrue(any("Summary" in m for m in messages[1]))
        self.assertTrue(any("no substantive change" in m for m in messages[2]))
        self.assertTrue(_dispatches(doc.name, doc.document_owner))
