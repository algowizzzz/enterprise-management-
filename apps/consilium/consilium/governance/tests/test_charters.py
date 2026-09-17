"""Committee charters: the version chain, and the effective challenge."""

import frappe

from consilium.governance import charters
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_user


def make_charter(forum=None, **values):
    defaults = {"doctype": "Committee Charter", "charter_title": "Terms of Reference"}
    if forum:
        defaults["forum"] = forum
    defaults.update(values)
    return frappe.get_doc(defaults).insert(ignore_permissions=True)


class TestCharterVersions(GovernanceTestCase):
    def test_the_body_lives_in_the_version_chain(self):
        forum = make_forum()
        charter = make_charter(forum.name)

        first = charters.publish_version(charter, "Initial charter.", body_text="Mandate v1")
        self.assertEqual(first.version_number, 1)
        self.assertTrue(first.is_current)
        charter.reload()
        self.assertEqual(charter.current_version, first.name)

        second = charters.publish_version(charter, "Scope widened.", body_text="Mandate v2")
        self.assertEqual(second.version_number, 2)
        first.reload()
        self.assertFalse(first.is_current)
        self.assertEqual(first.superseded_by, second.name)

        self.assertEqual([row["version_number"] for row in charters.history(charter)], [1, 2])

    def test_a_version_needs_a_change_summary(self):
        charter = make_charter(make_forum().name)
        with self.assertRaises(frappe.ValidationError):
            charters.publish_version(charter, "")


class TestEffectiveChallenge(GovernanceTestCase):
    def test_a_new_charter_awaits_challenge(self):
        charter = make_charter(make_forum().name)
        self.assertTrue(charter.requires_review)
        self.assertIn("challenge is not cleared", "; ".join(charters.clearance_blockers(charter)))

    def test_requesting_changes_needs_the_changes_spelled_out(self):
        charter = make_charter(make_forum().name)
        with self.assertRaises(frappe.ValidationError):
            charters.record_challenge(charter, charters.CHALLENGE_CHANGES_REQUESTED)

        charter.reload()
        charters.record_challenge(
            charter, charters.CHALLENGE_CHANGES_REQUESTED, comments="Decision rights are unclear."
        )
        charter.reload()
        self.assertTrue(charter.requires_review)
        self.assertTrue(charter.is_editable)

    def test_clearing_the_challenge_removes_that_blocker(self):
        forum = make_forum()
        charter = make_charter(forum.name)
        charters.publish_version(charter, "Initial charter.", body_text="Mandate")
        charter.reload()
        charters.record_challenge(charter, charters.CHALLENGE_CLEARED, comments="Cleared.")
        charter.reload()
        self.assertFalse(charter.requires_review)

        blockers = charters.clearance_blockers(charter)
        self.assertEqual(blockers, ["no approval evidence is recorded"])

        charter.append("approval_evidence", {"evidence_type": "Meeting Minutes",
                                             "provided_by": make_user()})
        charter.save(ignore_permissions=True)
        self.assertEqual(charters.clearance_blockers(charter), [])

    def test_a_charter_cannot_expire_before_it_takes_effect(self):
        charter = make_charter(make_forum().name)
        charter.effective_from = "2026-01-01"
        charter.effective_to = "2025-01-01"
        with self.assertRaises(frappe.ValidationError):
            charter.save(ignore_permissions=True)
