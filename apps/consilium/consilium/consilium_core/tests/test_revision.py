"""Revision chain and revert for forums and escalation matters (G-9, E-12).

The properties under test: a version is written for a change a person made and
not for a save that changed nothing; a revert restores content and never the
state, the handling restriction or the review record; it is refused, audited,
without a reason, without the right, in a locked state and across a boundary
the record may not re-cross; a sensitive matter's history is as invisible as the
matter; and a forum reverted on a watched field goes back for review.
"""

import frappe

from consilium.consilium_core import revision, versioning
from consilium.consilium_core.tests.utils import purge_refusals, refusals_for
from consilium.escalation import resolution
from consilium.escalation.tests.fixtures import retry_on_deadlock
from consilium.escalation.tests.utils import EscalationTestCase, as_user, make_user
from consilium.governance import lifecycle, setup
from consilium.governance.tests.utils import GovernanceTestCase, make_forum


def chain(doctype: str, name: str) -> list[dict]:
    return frappe.get_all(
        "Document Version",
        filters={"subject_doctype": doctype, "subject_name": name},
        fields=["name", "version_number", "origin", "is_current", "change_summary"],
        order_by="version_number asc",
    )


class TestMatterRevision(EscalationTestCase):
    def setUp(self):
        super().setUp()
        # A setUp that fails never reaches tearDown; without this its aborted
        # transaction would fail every test after it.
        self.addCleanup(frappe.db.rollback)
        self._purge = []
        retry_on_deadlock(self.build)

    def build(self):
        self.reference = self.reference_data()
        self.owner = self.reference["user"]
        self.matter = self.make_matter(self.reference, escalation_trigger="The first trigger.")

    def tearDown(self):
        for doctype, name in self._purge:
            purge_refusals(doctype, name)
        super().tearDown()

    def purge_on_teardown(self, doctype: str, name: str) -> None:
        self._purge.append((doctype, name))

    def edit(self, **values):
        doc = frappe.get_doc("Escalation Matter", self.matter.name)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc

    # ---------------------------------------------------------- snapshots

    def test_creation_and_each_real_change_write_a_version(self):
        self.assertEqual([v.origin for v in chain("Escalation Matter", self.matter.name)], ["Authored"])
        self.edit(escalation_trigger="A second trigger.")
        versions = chain("Escalation Matter", self.matter.name)
        self.assertEqual([v.version_number for v in versions], [1, 2])
        self.assertIn("Escalation Trigger", versions[-1].change_summary)
        self.assertTrue(versions[-1].is_current)

    def test_a_save_that_changes_nothing_writes_nothing(self):
        self.edit()
        self.edit(escalation_trigger="The first trigger.")
        self.assertEqual(len(chain("Escalation Matter", self.matter.name)), 1)

    def test_a_record_from_before_tracking_keeps_its_prior_state_as_a_baseline(self):
        values = self.matter_values(self.reference, escalation_trigger="Before tracking.")
        doc = frappe.get_doc(values)
        doc.flags[revision.SKIP_FLAG] = True
        doc.insert(ignore_permissions=True)
        self.assertEqual(chain("Escalation Matter", doc.name), [])

        doc = frappe.get_doc("Escalation Matter", doc.name)
        doc.escalation_trigger = "After tracking."
        doc.save(ignore_permissions=True)
        versions = chain("Escalation Matter", doc.name)
        self.assertEqual([v.origin for v in versions], ["Migrated", "Authored"])
        first = versioning.as_dict(frappe.db.get_value("Document Version", versions[0].name, "metadata_snapshot"))
        self.assertEqual(first["escalation_trigger"], "Before tracking.")

    # ------------------------------------------------------------- revert

    def test_revert_restores_content_but_not_state_or_handling(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        open_states = [t["value"] for t in resolution.status_targets(self.matter)]
        self.edit(escalation_trigger="A second trigger.", description="Rewritten.", status=open_states[0])

        with as_user(self.owner):
            result = revision.revert("Escalation Matter", self.matter.name, first.name, "The rewrite was wrong.")

        doc = frappe.get_doc("Escalation Matter", self.matter.name)
        self.assertEqual(doc.escalation_trigger, "The first trigger.")
        self.assertEqual(doc.description, self.matter.description)
        self.assertEqual(doc.status, open_states[0], "a revert never moves the state")

        versions = chain("Escalation Matter", self.matter.name)
        self.assertEqual(versions[-1].origin, "Reverted")
        self.assertTrue(versions[-1].is_current)
        self.assertEqual(len(versions), 3, "history is kept; the revert is a new version")
        log = frappe.get_doc("Version Revert Log", result["revert_log"])
        self.assertEqual(log.target_version, first.name)
        self.assertEqual(log.resulting_version, versions[-1].name)
        self.assertEqual(log.reverted_by, self.owner)
        self.assertEqual(log.justification, "The rewrite was wrong.")

    def test_the_head_after_a_revert_is_what_the_record_holds(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        open_states = [t["value"] for t in resolution.status_targets(self.matter)]
        self.edit(escalation_trigger="A second trigger.", status=open_states[0])
        revision.revert_record("Escalation Matter", self.matter.name, first.name, "Undo.")
        count = len(chain("Escalation Matter", self.matter.name))
        # Saving the reverted record unchanged must not report the state the
        # target version held as a change.
        self.edit()
        self.assertEqual(len(chain("Escalation Matter", self.matter.name)), count)

    def test_revert_keeps_the_handling_restriction(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        self.edit(sensitive=1, escalation_trigger="Now restricted.")
        revision.revert_record("Escalation Matter", self.matter.name, first.name, "Undo the trigger.")
        self.assertEqual(frappe.db.get_value("Escalation Matter", self.matter.name, "sensitive"), 1)

    def test_a_revert_without_a_reason_is_refused_and_audited(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        self.edit(escalation_trigger="A second trigger.")
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(self.owner), self.assertRaises(frappe.ValidationError):
            revision.revert("Escalation Matter", self.matter.name, first.name, "   ")
        self.assertIn("revert justification", [r.control for r in refusals_for("Escalation Matter", self.matter.name)])

    def test_a_revert_by_someone_without_the_role_is_refused_and_audited(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        self.edit(escalation_trigger="A second trigger.")
        reviewer = make_user("Escalation Reviewer")  # may write the matter, may not revert it
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with as_user(reviewer), self.assertRaises(frappe.PermissionError):
            revision.revert("Escalation Matter", self.matter.name, first.name, "Because.")
        self.assertIn("revert role", [r.control for r in refusals_for("Escalation Matter", self.matter.name)])
        self.assertEqual(frappe.db.get_value("Escalation Matter", self.matter.name, "escalation_trigger"),
                         "A second trigger.")

    def test_a_closed_matter_cannot_be_reverted(self):
        first = chain("Escalation Matter", self.matter.name)[0]
        self.make_closure(self.matter)
        closing = resolution.closing_states()[0]["value"]
        self.edit(status=closing, response_template_completed=1)
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with self.assertRaises(frappe.ValidationError):
            revision.revert_record("Escalation Matter", self.matter.name, first.name, "Reopen it.")
        self.assertIn("revert state boundary",
                      [r.control for r in refusals_for("Escalation Matter", self.matter.name)])
        history = revision.history_of(frappe.get_doc("Escalation Matter", self.matter.name))
        self.assertFalse(any(v["can_revert"] for v in history["versions"]))

    def test_a_version_from_the_other_side_of_closure_cannot_be_restored(self):
        self.make_closure(self.matter)
        closing = resolution.closing_states()[0]["value"]
        self.edit(status=closing, response_template_completed=1, escalation_trigger="Closed wording.")
        at_rest = chain("Escalation Matter", self.matter.name)[-1]
        reopening = [t["value"] for t in resolution.status_targets(frappe.get_doc("Escalation Matter", self.matter.name))][0]
        self.edit(status=reopening, escalation_trigger="Reopened wording.")
        self.purge_on_teardown("Escalation Matter", self.matter.name)
        with self.assertRaises(frappe.ValidationError):
            revision.revert_record("Escalation Matter", self.matter.name, at_rest.name, "Back to the closed text.")
        self.assertEqual(frappe.db.get_value("Escalation Matter", self.matter.name, "escalation_trigger"),
                         "Reopened wording.")

    def test_a_version_of_another_record_is_refused(self):
        other = self.make_matter(self.reference)
        self.edit(escalation_trigger="A second trigger.")
        foreign = chain("Escalation Matter", other.name)[0]
        with self.assertRaises(frappe.ValidationError):
            revision.revert_record("Escalation Matter", self.matter.name, foreign.name, "Wrong record.")

    def test_a_sensitive_matters_history_is_invisible_without_access(self):
        self.edit(sensitive=1, escalation_trigger="Restricted.")
        uncleared = make_user("Escalation Owner")
        with as_user(uncleared):
            with self.assertRaises(frappe.PermissionError) as hidden:
                revision.history("Escalation Matter", self.matter.name)
            with self.assertRaises(frappe.PermissionError) as missing:
                revision.history("Escalation Matter", "ESC-DOES-NOT-EXIST")
            first = chain("Escalation Matter", self.matter.name)[0]
            with self.assertRaises(frappe.PermissionError):
                revision.revert("Escalation Matter", self.matter.name, first.name, "Probe.")
        # A hidden matter and a missing one answer alike.
        self.assertEqual(str(hidden.exception).replace(self.matter.name, "X"),
                         str(missing.exception).replace("ESC-DOES-NOT-EXIST", "X"))
        cleared = make_user("Escalation Owner", "Sensitive Escalation Access")
        with as_user(cleared):
            self.assertTrue(revision.history("Escalation Matter", self.matter.name)["versions"])

    def test_history_says_which_versions_may_be_reverted(self):
        self.edit(escalation_trigger="A second trigger.")
        with as_user(self.owner):
            history = revision.history("Escalation Matter", self.matter.name)
        by_number = {v["version_number"]: v for v in history["versions"]}
        self.assertTrue(history["can_revert"])
        self.assertTrue(by_number[1]["can_revert"])
        self.assertFalse(by_number[2]["can_revert"], "the current version is not a revert target")
        auditor = make_user("Consilium Audit")
        with as_user(auditor):
            history = revision.history("Escalation Matter", self.matter.name)
        self.assertFalse(history["can_revert"])
        self.assertFalse(any(v["can_revert"] for v in history["versions"]))


class TestForumRevision(GovernanceTestCase):
    def setUp(self):
        # A setUp that fails never reaches tearDown; without this its aborted
        # transaction would fail every test after it.
        self.addCleanup(frappe.db.rollback)
        retry_on_deadlock(super().setUp)
        self.forum = make_forum(cadence="Quarterly", description="The original mandate.")

    def edit(self, **values):
        doc = frappe.get_doc("Governance Forum", self.forum.name)
        doc.update(values)
        doc.save(ignore_permissions=True)
        return doc

    def test_an_unwatched_change_is_reverted_without_a_review(self):
        first = chain("Governance Forum", self.forum.name)[0]
        self.edit(cadence="Monthly")
        state = frappe.db.get_value("Governance Forum", self.forum.name, "compliance_status")
        with as_user(self.rgo):
            revision.revert("Governance Forum", self.forum.name, first.name, "Cadence was changed in error.")
        doc = frappe.get_doc("Governance Forum", self.forum.name)
        self.assertEqual(doc.cadence, "Quarterly")
        self.assertEqual(doc.compliance_status, state)
        self.assertEqual(chain("Governance Forum", self.forum.name)[-1].origin, "Reverted")
        self.assertTrue(frappe.db.exists("Version Revert Log", {"subject_name": self.forum.name}))

    def test_reverting_a_watched_field_sends_the_forum_back_for_review(self):
        first = chain("Governance Forum", self.forum.name)[0]
        self.edit(description="A materially different mandate.")          # watched: now locked for review
        lifecycle.set_forum_state(self.forum.name, "Compliant")           # the review cleared it
        with as_user(self.rgo):
            revision.revert("Governance Forum", self.forum.name, first.name, "Restore the approved mandate.")
        doc = frappe.get_doc("Governance Forum", self.forum.name)
        self.assertEqual(doc.description, "The original mandate.")
        self.assertEqual(doc.compliance_status, setup.FORUM_REVIEW_STATE)
        self.assertFalse(doc.is_editable)
        self.assertTrue(frappe.get_all("ToDo", filters={"reference_type": "Governance Forum",
                                                        "reference_name": self.forum.name}))

    def test_a_forum_locked_for_review_cannot_be_reverted(self):
        first = chain("Governance Forum", self.forum.name)[0]
        self.edit(description="A materially different mandate.")
        self.purge_on_teardown("Governance Forum", self.forum.name)
        with as_user(self.rgo), self.assertRaises(frappe.ValidationError):
            revision.revert("Governance Forum", self.forum.name, first.name, "Undo.")
        self.assertIn("revert state boundary",
                      [r.control for r in refusals_for("Governance Forum", self.forum.name)])

    def test_a_forum_is_reverted_only_by_the_governance_office(self):
        first = chain("Governance Forum", self.forum.name)[0]
        self.edit(cadence="Monthly")
        compliance = make_user("Compliance Reviewer")  # writes forums, does not revert them
        self.purge_on_teardown("Governance Forum", self.forum.name)
        with as_user(compliance), self.assertRaises(frappe.PermissionError):
            revision.revert("Governance Forum", self.forum.name, first.name, "Undo.")
        self.assertEqual(frappe.db.get_value("Governance Forum", self.forum.name, "cadence"), "Monthly")

    def test_lifecycle_and_derived_fields_are_never_restored(self):
        first = chain("Governance Forum", self.forum.name)[0]
        lifecycle.set_forum_state(self.forum.name, "Compliant")
        self.edit(cadence="Monthly")
        revision.revert_record("Governance Forum", self.forum.name, first.name, "Undo the cadence.")
        doc = frappe.get_doc("Governance Forum", self.forum.name)
        self.assertEqual(doc.compliance_status, "Compliant")
        names = [df.fieldname for df in revision.restorable_fields("Governance Forum")]
        for kept in ("compliance_status", "committee_chair", "secretary", "is_editable", "confidential",
                     "disbanded_on"):
            self.assertNotIn(kept, names)
