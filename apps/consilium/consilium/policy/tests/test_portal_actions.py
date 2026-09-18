"""The policy module's portal entry points: every action, and its refusals.

Each entry point here is what a button on ``/policy`` or ``/policy-intake``
posts to. Every one asks two questions on the way in — does the caller's
standing carry the action, and does the record's stage offer it now — so each
has a test for the good case and one for each refusal: the wrong role (audited,
so those tests purge the refusal log) and the wrong stage.

As elsewhere in this module's tests, no assertion names a state. Records are
moved by performing configured actions and read back through their flags.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_months, getdate, nowdate

from consilium.consilium_core import approvals, versioning
from consilium.policy import horizon, intake, lifecycle, monitoring, publication, routing
from consilium.policy.tests.utils import (
    PolicyTestCase,
    as_user,
    make_coverage_area,
    make_user_group,
    unique,
)
from consilium.policy.tests.utils import make_document as _make_document
from consilium.policy.tests.utils import make_user as _new_user

DOCTYPE = "Governing Document"
OFFICE = "Enterprise Policy Office"
OWNER = "Policy Owner"
REVIEWER = "Policy Reviewer"
AUDIT = "Consilium Audit"

# --------------------------------------------------------------------------
# A pool of people, created once
#
# The framework refuses to create more than 60 users an hour on a site
# (``throttle_user_creation``), and on a shared test site every other suite's
# committed users count towards that. A suite that makes a fresh user for each
# assertion then fails part-way through with "Throttled". So the people these
# tests need are a small pool, created once and committed, and each test takes
# them in order: within one test the n-th person asked for with a given set of
# roles is always a different person from the (n-1)-th.
# --------------------------------------------------------------------------

POOL_SIZES = {(): 5, (OWNER,): 6, (OFFICE,): 2, (REVIEWER,): 2, (AUDIT,): 1}
_taken: dict = {}


def _pool_email(roles: tuple, n: int) -> str:
    key = "-".join(role.lower().replace(" ", "") for role in roles) or "plain"
    return f"portal-{key}-{n}@example.com"


def ensure_pool() -> None:
    # The throttle guards against runaway sign-ups, which a fixture is not; the
    # framework's own bulk paths step round it the same way.
    previous = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        for roles, size in POOL_SIZES.items():
            for n in range(1, size + 1):
                email = _pool_email(roles, n)
                if not frappe.db.exists("User", email):
                    _new_user(*roles, email=email)
    finally:
        frappe.flags.in_import = previous
    frappe.db.commit()


def make_user(*roles: str) -> str:
    key = tuple(roles)
    n = _taken.get(key, 0) + 1
    _taken[key] = n
    if n > POOL_SIZES.get(key, 0):
        raise AssertionError(f"The test pool has only {POOL_SIZES.get(key, 0)} people with roles {key}.")
    return _pool_email(key, n)


def make_document(**values):
    values.setdefault("owner_user", make_user(OWNER))
    values.setdefault("document_approver", make_user(OWNER))
    return _make_document(**values)


class PortalCase(PolicyTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_pool()

    def setUp(self):
        super().setUp()
        _taken.clear()

MINOR_ANSWERS = {"q_scope": "local", "q_obligation": "no", "q_control": "no"}


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
    version = versioning.create_version(doc, change_summary=summary, origin="Uploaded", version_label="1.0")
    frappe.db.set_value(DOCTYPE, doc.name, {"current_version": version.name, "version_label": "1.0"})
    doc.reload()
    return version


def _ready(owner=None, approver=None):
    """A draft with applicability and a version: everything publication will ask for but approval."""
    values = {}
    if owner:
        values["owner_user"] = owner
    if approver:
        values["document_approver"] = approver
    doc = _with_applicability(make_document(**values))
    _version(doc)
    return doc


def _in_review(**kwargs):
    doc = _ready(**kwargs)
    lifecycle.perform(doc, "Submit for Review")
    doc.reload()
    return doc


def _approve_all(doc):
    routing.instantiate(doc)
    for name in approvals.outstanding(DOCTYPE, doc.name):
        row = frappe.get_doc("Approval Decision", name)
        approvals.record_decision(row, "Approved", comments="Content reviewed.", acting_user=row.assigned_to)


def _in_force(**kwargs):
    doc = _in_review(**kwargs)
    _approve_all(doc)
    lifecycle.perform(doc, "Record Approval")
    lifecycle.perform(doc, "Publish")
    doc.reload()
    return doc


def _approval_gate_off():
    """See test_lifecycle.approval_gate_off: publication-gate tests reach
    Approved with the chain incomplete, which the approval gate now refuses."""
    from consilium.policy.tests.test_lifecycle import approval_gate_off

    approval_gate_off()


def _open_decisions(doc):
    return approvals.outstanding(DOCTYPE, doc.name)


# --------------------------------------------------------------------------
# Lifecycle actions (P-25)
# --------------------------------------------------------------------------


class TestLifecycleActions(PortalCase):
    def test_the_owner_submits_for_review_from_the_portal(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        with as_user(owner):
            offered = {row["action"]: row for row in lifecycle.document_actions(doc.name)["lifecycle"]}
            self.assertTrue(offered["Submit for Review"]["offered"])
            result = lifecycle.take_action(doc.name, "Submit for Review")
        self.assertEqual(result["stage"], "review")
        doc.reload()
        self.assertTrue(int(doc.requires_review))

    def test_an_action_another_role_takes_is_refused_and_audited(self):
        doc = _ready()
        reviewer = make_user(REVIEWER)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(reviewer):
            offered = {row["action"]: row for row in lifecycle.document_actions(doc.name)["lifecycle"]}
            self.assertFalse(offered["Submit for Review"]["offered"])
            with self.assertRaises(frappe.PermissionError):
                lifecycle.take_action(doc.name, "Submit for Review")
        doc.reload()
        self.assertTrue(int(doc.is_editable))
        self.assertFalse(int(doc.requires_review))

    def test_an_action_not_configured_from_this_phase_is_refused(self):
        office = make_user(OFFICE)
        doc = _ready()
        with as_user(office), self.assertRaises(frappe.ValidationError):
            lifecycle.take_action(doc.name, "Publish")

    def test_a_reviewer_returns_a_document_to_drafting(self):
        """The configured role is the grant: a reviewer holds no write permission
        on the document and is still the one configured to send it back."""
        doc = _in_review()
        reviewer = make_user(REVIEWER)
        with as_user(reviewer):
            result = lifecycle.take_action(doc.name, "Return to Drafting",
                                           comments="The scope section contradicts the parent framework.")
        self.assertEqual(result["stage"], "drafting")

    def test_a_failing_gate_is_shown_before_and_refused_after(self):
        office = make_user(OFFICE)
        doc = _in_review()
        _approval_gate_off()  # the publication gate is the subject here
        lifecycle.perform(doc, "Record Approval")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(office):
            offered = {row["action"]: row for row in lifecycle.document_actions(doc.name)["lifecycle"]}
            self.assertTrue(any("Complete Approval Chain" in b for b in offered["Publish"]["blocked_by"]))
            with self.assertRaises(frappe.ValidationError):
                lifecycle.take_action(doc.name, "Publish")
        self.assertNotInForce(doc)

    def test_an_approved_exception_authorisation_excuses_the_gate(self):
        office = make_user(OFFICE)
        doc = _in_review()
        _approval_gate_off()  # the publication gate is the subject here
        lifecycle.perform(doc, "Record Approval")
        authorisation = frappe.get_doc(
            {"doctype": "Exception Authorisation", "subject_doctype": DOCTYPE, "subject_name": doc.name,
             "exception_type": "Approval Bypass", "justification": "Emergency regulatory deadline.",
             # Approved by the policy office, and not by the person who asked:
             # anything less does not excuse a gate (lifecycle.approval_unfit).
             "requested_by": office, "approved_by": make_user(OFFICE), "approved_on": frappe.utils.now()}
        ).insert(ignore_permissions=True)
        with as_user(office):
            ctx = lifecycle.document_actions(doc.name)
            self.assertIn(authorisation.name, [row["name"] for row in ctx["exception_authorisations"]])
            lifecycle.take_action(doc.name, "Publish", exception_authorisation=authorisation.name)
        self.assertInForce(doc)

    def test_an_unapproved_exception_authorisation_is_not_accepted(self):
        office = make_user(OFFICE)
        doc = _in_review()
        _approval_gate_off()  # the publication gate is the subject here
        lifecycle.perform(doc, "Record Approval")
        pending = frappe.get_doc(
            {"doctype": "Exception Authorisation", "subject_doctype": DOCTYPE, "subject_name": doc.name,
             "exception_type": "Approval Bypass", "justification": "Asked for, not granted.",
             "requested_by": office}
        ).insert(ignore_permissions=True)
        with as_user(office), self.assertRaises(frappe.ValidationError):
            lifecycle.take_action(doc.name, "Publish", exception_authorisation=pending.name)
        self.assertNotInForce(doc)

    def test_a_stranger_sees_nothing(self):
        doc = _ready()
        with as_user(make_user()), self.assertRaises(frappe.PermissionError):
            lifecycle.document_actions(doc.name)


# --------------------------------------------------------------------------
# The approval chain (P-8, P-25, P-26)
# --------------------------------------------------------------------------


class TestApprovalChain(PortalCase):
    def test_raising_the_steps_assigns_and_tells_each_approver(self):
        approver = make_user(OWNER)
        office = make_user(OFFICE)
        doc = _in_review(approver=approver)
        with as_user(office):
            before = lifecycle.document_actions(doc.name)
            self.assertTrue(before["actions"]["raise_approval_steps"])
            self.assertTrue(before["approval"]["unraised"])
            after = routing.raise_steps(doc.name)
        self.assertFalse(after["approval"]["unraised"])
        self.assertFalse(after["actions"]["raise_approval_steps"])
        self.assertTrue(_open_decisions(doc))
        told = frappe.get_all("Notification Dispatch",
                              filters={"subject_doctype": DOCTYPE, "subject_name": doc.name}, pluck="recipient")
        self.assertIn(approver, told)

    def test_raising_twice_is_refused(self):
        office = make_user(OFFICE)
        doc = _in_review()
        with as_user(office):
            routing.raise_steps(doc.name)
            with self.assertRaises(frappe.ValidationError):
                routing.raise_steps(doc.name)

    def test_steps_are_not_raised_while_drafting(self):
        office = make_user(OFFICE)
        doc = _ready()
        with as_user(office), self.assertRaises(frappe.ValidationError):
            routing.raise_steps(doc.name)
        self.assertFalse(_open_decisions(doc))

    def test_steps_are_not_raised_without_a_version(self):
        office = make_user(OFFICE)
        doc = _with_applicability(make_document())
        lifecycle.perform(doc, "Submit for Review")
        with as_user(office), self.assertRaises(frappe.ValidationError):
            routing.raise_steps(doc.name)

    def test_a_reviewer_cannot_raise_the_steps(self):
        doc = _in_review()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            routing.raise_steps(doc.name)

    def test_the_assignee_decides_and_the_chain_completes(self):
        approver = make_user(OWNER)
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        with as_user(approver):
            ctx = lifecycle.document_actions(doc.name)
            self.assertTrue(ctx["actions"]["record_step_decision"])
            # One step at a time, as the screen offers them: a sequential step
            # is offered only once the steps ahead are decided (E7-S4).
            while ctx["approval"]["decidable"]:
                ctx = routing.decide_step(doc.name, ctx["approval"]["decidable"][0], "Approved",
                                          "Content reviewed.")
        self.assertTrue(ctx["approval"]["chain"]["complete"])
        self.assertFalse(ctx["actions"]["record_step_decision"])

    def test_a_stranger_cannot_decide_a_step(self):
        doc = _in_review()
        routing.instantiate(doc)
        step = _open_decisions(doc)[0]
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(OWNER)), self.assertRaises(frappe.PermissionError):
            routing.decide_step(doc.name, step, "Approved")
        self.assertIn(step, _open_decisions(doc))

    def test_a_live_delegate_decides_in_the_approvers_place(self):
        approver = make_user(OWNER)
        delegate = make_user()
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        frappe.get_doc(
            {"doctype": "Authority Delegation", "delegator": approver, "delegate": delegate, "scope_type": "All",
             "valid_from": nowdate(), "valid_to": add_days(nowdate(), 10),
             "delegated_actions": [{"delegable_action": "APPROVE"}]}
        ).insert(ignore_permissions=True)
        step = _open_decisions(doc)[0]
        with as_user(delegate):
            # A delegate with no policy role still reaches the document through the step.
            self.assertTrue(lifecycle.may_view(doc))
            queued = [row for row in routing.my_open_steps() if row["document"] == doc.name]
            self.assertTrue(queued and all(row["on_behalf"] for row in queued))
            routing.decide_step(doc.name, step, "Approved", "On behalf of the approver.")
        row = frappe.get_doc("Approval Decision", step)
        self.assertEqual(row.acted_by, delegate)
        self.assertTrue(row.acting_delegation)

    def test_an_objection_carries_its_reason(self):
        approver = make_user(OWNER)
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        first, second = _open_decisions(doc)[:2]
        with as_user(approver):
            for step, decision in ((first, "Changes Requested"), (second, "Rejected")):
                with self.assertRaises(frappe.ValidationError):
                    routing.decide_step(doc.name, step, decision, "")
            # A request for changes keeps the step open, for the approver to
            # decide again once the changes are made...
            ctx = routing.decide_step(doc.name, first, "Changes Requested", "Section 3 contradicts the standard.")
            self.assertIn(first, ctx["approval"]["decidable"])
            self.assertEqual(frappe.db.get_value("Approval Decision", first, "comments"),
                             "Section 3 contradicts the standard.")
            # ...and, being open, it holds the sequential steps behind it back
            # (E7-S4) until it is decided again.
            self.assertNotIn(second, ctx["approval"]["decidable"])
            routing.decide_step(doc.name, first, "Approved", "Section 3 corrected.")
            # A rejection closes a step as an objection the chain cannot pass.
            ctx = routing.decide_step(doc.name, second, "Rejected", "Out of appetite.")
        chain = ctx["approval"]["chain"]
        self.assertFalse(chain["complete"])
        self.assertIn(frappe.db.get_value("Approval Decision", second, "approval_step"), chain["objections"])

    def test_the_queue_lists_only_the_callers_steps(self):
        approver = make_user(OWNER)
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        with as_user(approver):
            self.assertIn(doc.name, {row["document"] for row in routing.my_open_steps()})
        with as_user(make_user(OWNER)):
            self.assertNotIn(doc.name, {row["document"] for row in routing.my_open_steps()})

    def test_the_office_bypasses_a_step_with_a_written_exception(self):
        office = make_user(OFFICE)
        doc = _in_review()
        routing.instantiate(doc)
        step = _open_decisions(doc)[0]
        with as_user(office):
            ctx = routing.bypass_step(doc.name, step, "The approver is on extended leave; the board chair agreed.")
        row = frappe.get_doc("Approval Decision", step)
        self.assertFalse(int(row.is_open))
        self.assertTrue(row.exception_authorisation)
        self.assertEqual(frappe.db.get_value("Exception Authorisation", row.exception_authorisation, "approved_by"),
                         office)
        self.assertNotIn(row.approval_step, ctx["approval"]["chain"]["objections"])

    def test_a_bypass_without_justification_is_refused(self):
        office = make_user(OFFICE)
        doc = _in_review()
        routing.instantiate(doc)
        step = _open_decisions(doc)[0]
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(office), self.assertRaises(frappe.ValidationError):
            routing.bypass_step(doc.name, step, "  ")
        self.assertIn(step, _open_decisions(doc))

    def test_nobody_bypasses_their_own_step(self):
        office = make_user(OFFICE)
        doc = _in_review(approver=office)
        routing.instantiate(doc)
        step = _open_decisions(doc)[0]
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(office), self.assertRaises(frappe.PermissionError):
            routing.bypass_step(doc.name, step, "I would rather not decide it.")

    def test_an_owner_cannot_bypass_a_step(self):
        owner = make_user(OWNER)
        doc = _in_review(owner=owner)
        routing.instantiate(doc)
        step = _open_decisions(doc)[0]
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(owner), self.assertRaises(frappe.PermissionError):
            routing.bypass_step(doc.name, step, "It is my document.")

    def test_an_approver_without_read_access_sees_the_approval_and_nothing_else(self):
        approver = make_user()
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        with as_user(approver):
            ctx = lifecycle.document_actions(doc.name)
            self.assertFalse(ctx["readable"])
            self.assertEqual(ctx["lifecycle"], [])
            self.assertTrue(ctx["approval"]["decidable"])
            self.assertFalse(ctx["actions"]["upload_version"])
            with self.assertRaises(frappe.PermissionError):
                horizon.document_reviews(doc.name)


# --------------------------------------------------------------------------
# Versions (P-3, P-9)
# --------------------------------------------------------------------------


class TestVersions(PortalCase):
    def test_the_owner_uploads_a_new_version_as_text(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        with as_user(owner):
            ctx = publication.upload_new_version(doc.name, "Tightened section 4.", body_text="The new text.",
                                                 version_label="1.1")
        current = [row for row in ctx["versions"] if row["is_current"]][0]
        self.assertEqual(current["version_label"], "1.1")
        self.assertEqual(len(ctx["versions"]), 2)

    def test_a_file_attached_to_the_document_becomes_a_version(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        attached = frappe.get_doc(
            {"doctype": "File", "file_name": unique("body") + ".txt", "attached_to_doctype": DOCTYPE,
             "attached_to_name": doc.name, "content": b"Policy text", "is_private": 1}
        ).insert(ignore_permissions=True)
        with as_user(owner):
            publication.upload_new_version(doc.name, "Uploaded the signed-off draft.", body_file=attached.file_url)
        self.assertEqual(versioning.current_version(DOCTYPE, doc.name).body_file, attached.file_url)

    def test_a_file_attached_elsewhere_is_refused(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        other = _ready()
        attached = frappe.get_doc(
            {"doctype": "File", "file_name": unique("body") + ".txt", "attached_to_doctype": DOCTYPE,
             "attached_to_name": other.name, "content": b"Someone else's text", "is_private": 1}
        ).insert(ignore_permissions=True)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            publication.upload_new_version(doc.name, "Borrowed body.", body_file=attached.file_url)

    def test_a_version_needs_a_body(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            publication.upload_new_version(doc.name, "Nothing attached.")

    def test_no_version_is_taken_once_the_document_is_settled(self):
        office = make_user(OFFICE)
        doc = _in_review()
        _approve_all(doc)
        lifecycle.perform(doc, "Record Approval")
        with as_user(office), self.assertRaises(frappe.ValidationError):
            publication.upload_new_version(doc.name, "Too late.", body_text="Text.")

    def test_a_reviewer_cannot_upload_a_version(self):
        doc = _ready()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            publication.upload_new_version(doc.name, "Not mine to change.", body_text="Text.")

    def test_a_revert_writes_a_new_version(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        first = versioning.current_version(DOCTYPE, doc.name).name
        with as_user(owner):
            publication.upload_new_version(doc.name, "Second draft.", body_text="Second.")
            ctx = publication.revert_version(doc.name, first, "The second draft went too far.")
        self.assertEqual(len(ctx["versions"]), 3)
        self.assertEqual(versioning.current_version(DOCTYPE, doc.name).origin, "Reverted")

    def test_a_revert_across_phases_is_refused(self):
        """A snapshot carries the phase; reverting to one from another phase would
        move the document through its lifecycle without the workflow."""
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        first = versioning.current_version(DOCTYPE, doc.name).name
        with as_user(owner):
            publication.upload_new_version(doc.name, "Second draft.", body_text="Second.")
        lifecycle.perform(doc, "Submit for Review")
        with as_user(owner):
            ctx = lifecycle.document_actions(doc.name)
            self.assertFalse([row for row in ctx["versions"] if row["name"] == first][0]["revertible"])
            with self.assertRaises(frappe.ValidationError):
                publication.revert_version(doc.name, first, "Back to the first draft.")
        doc.reload()
        self.assertTrue(int(doc.requires_review))

    def test_a_revert_needs_its_justification(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        first = versioning.current_version(DOCTYPE, doc.name).name
        with as_user(owner):
            publication.upload_new_version(doc.name, "Second draft.", body_text="Second.")
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            publication.revert_version(doc.name, first, "")


# --------------------------------------------------------------------------
# Publication (P-19)
# --------------------------------------------------------------------------


class TestPublication(PortalCase):
    def test_the_office_records_a_publication_and_the_audience_is_told(self):
        office = make_user(OFFICE)
        doc = _in_force()
        with as_user(office):
            self.assertTrue(lifecycle.document_actions(doc.name)["actions"]["record_publication"])
            ctx = publication.publish_record(doc.name, "All Employees", allow_print=1, allow_download=1)
        row = ctx["publications"][0]
        self.assertEqual(row["document_version"], doc.current_version)
        self.assertTrue(row["rendition_print"])
        self.assertGreater(row["notified_count"], 0)

    def test_a_view_only_publication_closes_print_and_download(self):
        office = make_user(OFFICE)
        doc = _in_force()
        with as_user(office):
            ctx = publication.publish_record(doc.name, "All Employees", view_only=1, allow_print=1, allow_download=1)
        row = ctx["publications"][0]
        self.assertFalse(row["rendition_print"])
        self.assertFalse(row["rendition_download"])

    def test_a_targeted_publication_names_its_audience(self):
        office = make_user(OFFICE)
        doc = _in_force()
        with as_user(office):
            with self.assertRaises(frappe.ValidationError):
                publication.publish_record(doc.name, "Targeted Groups", audiences=[])
            ctx = publication.publish_record(
                doc.name, "Targeted Groups", audiences=[{"audience_kind": "Role", "audience_value": OWNER}])
        self.assertEqual(ctx["publications"][0]["audiences"][0]["audience_value"], OWNER)

    def test_an_owner_cannot_record_a_publication(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(owner), self.assertRaises(frappe.PermissionError):
            publication.publish_record(doc.name, "All Employees")

    def test_nothing_is_published_before_it_is_in_force(self):
        office = make_user(OFFICE)
        doc = _in_review()
        with as_user(office), self.assertRaises(frappe.ValidationError):
            publication.publish_record(doc.name, "All Employees")

    def test_a_publication_is_withdrawn_once(self):
        office = make_user(OFFICE)
        doc = _in_force()
        with as_user(office):
            ctx = publication.publish_record(doc.name, "All Employees")
            name = ctx["publications"][0]["name"]
            ctx = publication.withdraw_publication(name)
            self.assertTrue(ctx["publications"][0]["withdrawn_on"])
            self.assertFalse(ctx["actions"]["withdraw_publication"])
            with self.assertRaises(frappe.ValidationError):
                publication.withdraw_publication(name)

    def test_an_owner_cannot_withdraw_a_publication(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        name = publication.record_publication(doc.name).name
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(owner), self.assertRaises(frappe.PermissionError):
            publication.withdraw_publication(name)


# --------------------------------------------------------------------------
# Review cycles and horizon scans (P-10, P-5)
# --------------------------------------------------------------------------


class TestReviewsAndScans(PortalCase):
    def test_a_review_is_opened_once_and_concluded_with_its_outcome(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        frappe.db.set_value(DOCTYPE, doc.name, "review_frequency_months", 12)
        with as_user(owner):
            ctx = horizon.open_review(doc.name, add_months(nowdate(), 2))
            self.assertEqual(len(ctx["open_cycles"]), 1)
            self.assertFalse(ctx["actions"]["open_review_cycle"])
            with self.assertRaises(frappe.ValidationError):
                horizon.open_review(doc.name, add_months(nowdate(), 3))
            ctx = horizon.conclude_review(ctx["open_cycles"][0], "No Change", "Still fit for purpose.")
        self.assertFalse(ctx["open_cycles"])
        self.assertEqual(getdate(frappe.db.get_value(DOCTYPE, doc.name, "next_review_on")),
                         getdate(add_months(nowdate(), 12)))

    def test_a_review_is_not_opened_while_drafting(self):
        owner = make_user(OWNER)
        doc = _ready(owner=owner)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            horizon.open_review(doc.name, add_months(nowdate(), 2))

    def test_a_review_concludes_with_notes(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        with as_user(owner):
            cycle = horizon.open_review(doc.name, add_months(nowdate(), 2))["open_cycles"][0]
            with self.assertRaises(frappe.ValidationError):
                horizon.conclude_review(cycle, "No Change", " ")
            with self.assertRaises(frappe.ValidationError):
                horizon.conclude_review(cycle, "Whatever", "Notes.")

    def test_a_reviewer_cannot_open_a_review(self):
        doc = _in_force()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            horizon.open_review(doc.name, add_months(nowdate(), 2))

    def test_a_scan_that_triggers_review_opens_the_cycle(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        area = make_coverage_area()
        with as_user(owner):
            ctx = horizon.record_scan(
                doc.name, "This quarter", "A consultation proposes new reporting duties.", "Review Triggered",
                coverage_areas=[area],
                sources=[{"source_type": "Consultation", "reference": "Consultation paper 7"}],
            )
        scan = ctx["scans"][0]
        self.assertTrue(scan["resulting_review_cycle"])
        self.assertIn(scan["resulting_review_cycle"], ctx["open_cycles"])

    def test_a_scan_names_its_sources(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            horizon.record_scan(doc.name, "This quarter", "Read nothing.", "No Change",
                                coverage_areas=[make_coverage_area()], sources=[])

    def test_a_reviewer_cannot_record_a_scan(self):
        doc = _in_force()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            horizon.record_scan(doc.name, "This quarter", "Summary.", "No Change",
                                coverage_areas=[make_coverage_area()],
                                sources=[{"source_type": "Consultation", "reference": "Paper"}])


# --------------------------------------------------------------------------
# Monitoring and violations (P-11, P-22)
# --------------------------------------------------------------------------


def _activity(doc, responsible, active=1):
    return frappe.get_doc(
        {"doctype": "Monitoring Activity", "document": doc.name, "activity_title": unique("Check"),
         "frequency": "Quarterly", "responsible": responsible, "is_active": active}
    ).insert(ignore_permissions=True)


class TestMonitoring(PortalCase):
    def test_the_owner_records_a_result_and_the_due_date_moves(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        activity = _activity(doc, owner)
        with as_user(owner):
            ctx = monitoring.record_result(activity.name, "Q3", "Effective", findings="Sample of 25, no exceptions.")
        self.assertEqual(ctx["results"][0]["outcome"], "Effective")
        self.assertTrue(frappe.db.get_value("Monitoring Activity", activity.name, "next_due_on"))

    def test_the_responsible_person_records_whatever_their_role(self):
        responsible = make_user()
        doc = _in_force()
        activity = _activity(doc, responsible)
        with as_user(responsible):
            # They may not read the document, so they are refused at the door...
            with self.assertRaises(frappe.PermissionError):
                monitoring.record_result(activity.name, "Q3", "Effective", findings="Done.")
        reader = make_user(REVIEWER)
        activity = _activity(doc, reader)
        with as_user(reader):
            # ...but a reader named responsible records it without a writing role.
            ctx = monitoring.record_result(activity.name, "Q3", "Not Effective", findings="Two failures.")
        self.assertEqual(ctx["results"][0]["performed_by"], reader)

    def test_a_reader_not_responsible_cannot_record(self):
        doc = _in_force()
        activity = _activity(doc, make_user(OWNER))
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(REVIEWER)), self.assertRaises(frappe.PermissionError):
            monitoring.record_result(activity.name, "Q3", "Effective", findings="Done.")

    def test_an_inactive_activity_takes_no_result(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        activity = _activity(doc, owner, active=0)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            monitoring.record_result(activity.name, "Q3", "Effective", findings="Done.")

    def test_a_performed_check_records_its_findings(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        activity = _activity(doc, owner)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            monitoring.record_result(activity.name, "Q3", "Effective")

    def test_a_reviewer_logs_a_violation(self):
        reviewer = make_user(REVIEWER)
        doc = _in_force()
        with as_user(reviewer):
            self.assertTrue(monitoring.document_monitoring(doc.name)["actions"]["log_violation"])
            ctx = monitoring.log_violation(doc.name, "Control", "High", "Reconciliations skipped for a month.",
                                           occurred_on=add_days(nowdate(), -20))
        row = ctx["violations"][0]
        self.assertTrue(int(row["is_open"]))
        self.assertEqual(row["severity"], "High")

    def test_an_auditor_cannot_log_a_violation(self):
        doc = _in_force()
        self.purge_on_teardown(DOCTYPE, doc.name)
        with as_user(make_user(AUDIT)):
            self.assertFalse(monitoring.document_monitoring(doc.name)["actions"]["log_violation"])
            with self.assertRaises(frappe.PermissionError):
                monitoring.log_violation(doc.name, "Control", "High", "Seen in testing.")

    def test_a_violation_is_not_identified_before_it_occurred(self):
        owner = make_user(OWNER)
        doc = _in_force(owner=owner)
        with as_user(owner), self.assertRaises(frappe.ValidationError):
            monitoring.log_violation(doc.name, "Process", "Low", "Out of order.",
                                     identified_on=nowdate(), occurred_on=add_days(nowdate(), 5))


# --------------------------------------------------------------------------
# Intake (P-16)
# --------------------------------------------------------------------------

REQUEST = "Document Intake Request"


class TestIntake(PortalCase):
    def _raise(self, requester, **values):
        document_type = values.pop("document_type", None) or make_document().document_type
        with as_user(requester):
            return intake.raise_request(
                "Create", "The regulator has changed its expectations.",
                proposed_document_name=unique("Proposed"), proposed_document_type=document_type, **values
            )["request"]["name"]

    def test_an_owner_raises_a_request_and_answers_its_questions(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester):
            ctx = intake.request_context(name)
            self.assertTrue(ctx["actions"]["classify"])
            self.assertEqual({q["code"] for q in ctx["questions"]["questions"]}, set(MINOR_ANSWERS))
            ctx = intake.classify_request(name, MINOR_ANSWERS)
        self.assertEqual(ctx["explanation"]["effective_outcome"], "Minor")
        self.assertTrue(ctx["request"]["sla_clock"])
        self.assertFalse(ctx["actions"]["classify"])

    def test_raising_a_request_needs_the_right_to_create_one(self):
        with as_user(make_user(AUDIT)), self.assertRaises(frappe.PermissionError):
            intake.raise_request("Create", "Because.", proposed_document_name="A name",
                                 proposed_document_type=make_document().document_type)

    def test_a_change_request_names_its_document(self):
        with as_user(make_user(OWNER)), self.assertRaises(frappe.ValidationError):
            intake.raise_request("Change", "Because.")

    def test_only_the_requester_or_the_office_classifies(self):
        name = self._raise(make_user(OWNER))
        self.purge_on_teardown(REQUEST, name)
        with as_user(make_user(OWNER)), self.assertRaises(frappe.PermissionError):
            intake.classify_request(name, MINOR_ANSWERS)
        with as_user(make_user(OFFICE)):
            self.assertEqual(intake.classify_request(name, MINOR_ANSWERS)["explanation"]["effective_outcome"], "Minor")

    def test_a_classified_request_is_not_classified_again(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester):
            intake.classify_request(name, MINOR_ANSWERS)
            with self.assertRaises(frappe.ValidationError):
                intake.classify_request(name, MINOR_ANSWERS)

    def test_an_answer_outside_the_rule_set_is_refused(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester), self.assertRaises(frappe.ValidationError):
            intake.classify_request(name, {**MINOR_ANSWERS, "q_scope": "galactic"})

    def test_the_requester_challenges_once(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester):
            intake.classify_request(name, MINOR_ANSWERS)
            ctx = intake.challenge_request(name, "It touches a regulatory obligation.")
            self.assertEqual(ctx["request"]["challenged_by"], requester)
            self.assertFalse(ctx["actions"]["challenge"])
            with self.assertRaises(frappe.ValidationError):
                intake.challenge_request(name, "Again.")

    def test_only_the_office_overrides(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester):
            intake.classify_request(name, MINOR_ANSWERS)
        self.purge_on_teardown(REQUEST, name)
        with as_user(requester), self.assertRaises(frappe.PermissionError):
            intake.override_request(name, "Major", "I would like it treated as major.")
        with as_user(make_user(OFFICE)):
            ctx = intake.override_request(name, "Major", "It alters a regulatory obligation after all.")
        self.assertEqual(ctx["explanation"]["effective_outcome"], "Major")
        self.assertEqual(ctx["explanation"]["outcome"], "Minor")

    def test_the_office_creates_the_document(self):
        requester = make_user(OWNER)
        template = make_document()
        name = self._raise(requester, document_type=template.document_type)
        with as_user(requester):
            intake.classify_request(name, MINOR_ANSWERS)
        office = make_user(OFFICE)
        with as_user(office):
            ctx = intake.create_from_request(
                name, "Records Handling Standard", template.document_type, template.owning_operating_group,
                template.primary_risk_category, requester, requester,
            )
        created = ctx["request"]["created_document"]
        self.assertTrue(created)
        self.assertFalse(int(ctx["request"]["is_open"]))
        self.assertEqual(routing.change_classification_of(frappe.get_doc(DOCTYPE, created)), "Minor")

    def test_the_requester_cannot_create_the_document(self):
        requester = make_user(OWNER)
        template = make_document()
        name = self._raise(requester)
        with as_user(requester):
            intake.classify_request(name, MINOR_ANSWERS)
        self.purge_on_teardown(REQUEST, name)
        with as_user(requester), self.assertRaises(frappe.PermissionError):
            intake.create_from_request(name, "Mine", template.document_type, template.owning_operating_group,
                                       template.primary_risk_category, requester, requester)

    def test_no_document_is_created_before_classification(self):
        office = make_user(OFFICE)
        template = make_document()
        name = self._raise(make_user(OWNER))
        with as_user(office), self.assertRaises(frappe.ValidationError):
            intake.create_from_request(name, "Early", template.document_type, template.owning_operating_group,
                                       template.primary_risk_category, office, office)

    def test_a_withdrawal_carries_its_reason(self):
        requester = make_user(OWNER)
        name = self._raise(requester)
        with as_user(requester):
            with self.assertRaises(frappe.ValidationError):
                intake.withdraw_request(name, "")
            ctx = intake.withdraw_request(name, "No longer needed.")
        self.assertFalse(int(ctx["request"]["is_open"]))
        self.assertFalse(any(ctx["actions"].values()))


# --------------------------------------------------------------------------
# The pages render
# --------------------------------------------------------------------------


class TestPages(PortalCase):
    def _render(self, route, user, query):
        from urllib.parse import urlencode

        from frappe.website.serve import get_response
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        frappe.set_user(user)
        frappe.local.form_dict = frappe._dict(query)
        path = "/" + route + "?" + urlencode(query)
        frappe.local.request = Request(EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ())
        response = get_response(route)
        return response.status_code, response.get_data(as_text=True)

    def test_the_document_page_renders_for_a_reader_and_an_approver(self):
        approver = make_user()
        doc = _in_review(approver=approver)
        routing.instantiate(doc)
        status, body = self._render("policy", make_user(OWNER), {"name": doc.name})
        self.assertEqual(status, 200)
        self.assertIn("lifecycle.document_actions", body)
        self.assertIn('id="tab-versions"', body)
        status, body = self._render("policy", approver, {"name": doc.name})
        self.assertEqual(status, 200)
        self.assertNotIn('id="tab-versions"', body)
        self.assertIn('id="tab-approval"', body)

    def test_the_intake_page_renders(self):
        status, body = self._render("policy-intake", make_user(OWNER), {})
        self.assertEqual(status, 200)
        self.assertIn("Request a document", body)
