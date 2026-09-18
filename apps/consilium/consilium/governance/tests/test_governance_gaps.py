"""The wave-3 governance gaps: G-7, G-15, E8-S5, O-2, O-5 and E6-S3.

Each entry point is exercised as someone who may use it and as someone who may
not, and each gate is exercised on both sides: refused while the condition
holds, allowed once it is met. The pages are rendered too, because a working
endpoint behind a page that does not render is not a working screen.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

from consilium.consilium_core import approvals
from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import charters, formation, inventory, lifecycle
from consilium.governance.tests.test_formation_portal import PortalCase, findings
from consilium.governance.tests.utils import (
    GovernanceTestCase, make_forum, make_jurisdiction, make_org_unit, make_seat, make_user, seat_role,
    taxonomy, unique,
)


def make_charter(forum=None, request=None, **values):
    doc = {"doctype": "Committee Charter", "charter_title": unique("Terms of Reference")}
    if forum:
        doc["forum"] = forum
    if request:
        doc["formation_request"] = request
    doc.update(values)
    return frappe.get_doc(doc).insert(ignore_permissions=True)


def with_version(charter):
    charters.publish_version(charter, "Initial charter.", body_text="Mandate v1")
    return frappe.get_doc("Committee Charter", charter.name)


def clear(charter):
    charters.record_challenge(frappe.get_doc("Committee Charter", charter.name), charters.CHALLENGE_CLEARED,
                              comments="Challenge satisfied.")


# ---------------------------------------------------------------- G-7 gate


class TestFormationCharterGate(PortalCase):
    """An uncleared charter challenge blocks formation approval (E33-S1)."""

    def ready_for_approval(self):
        name = self.evaluated()
        formation.raise_request_approval_steps(name)
        # Step by step in route order: Core refuses a sequential step decided
        # out of turn (E7-S4).
        while True:
            frappe.set_user("Administrator")
            step = frappe.get_all(
                "Approval Decision",
                filters={"subject_doctype": "Committee Formation Request", "subject_name": name, "is_open": 1},
                fields=["name", "assigned_to"], order_by="step_sequence asc, creation asc", limit=1,
            )
            if not step:
                break
            self.as_user(step[0]["assigned_to"])
            formation.record_request_step_decision(name, step[0]["name"], "Approved")
        frappe.set_user("Administrator")
        return name

    def test_an_uncleared_challenge_blocks_approval_until_it_is_cleared(self):
        name = self.ready_for_approval()
        frappe.set_user("Administrator")
        self.assertEqual(formation.approval_blockers(name), [], "the fixture must otherwise be approvable")

        charter = with_version(make_charter(request=name))
        blockers = formation.approval_blockers(name)
        self.assertEqual(len(blockers), 1)
        self.assertIn("charter challenge", blockers[0])
        self.assertIn(charter.name, blockers[0])

        self.purge_on_teardown("Committee Formation Request", name)
        self.as_user(self.office)
        with self.assertRaises(frappe.ValidationError):
            formation.approve_request(name)
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.get_value("Committee Formation Request", name, "is_committable"))
        audited = refusals_for("Committee Formation Request", name)
        self.assertTrue(any(row["control"] == "formation approval gate" for row in audited))

        # Changes requested is still not a clearance.
        charters.record_challenge(frappe.get_doc("Committee Charter", charter.name),
                                  charters.CHALLENGE_CHANGES_REQUESTED, comments="Say who decides.")
        self.assertTrue(formation.approval_blockers(name))

        clear(charter)
        self.assertEqual(formation.approval_blockers(name), [])
        self.as_user(self.office)
        result = formation.approve_request(name)
        self.assertTrue(result["request"]["is_committable"])

    def test_the_review_screen_lists_the_charter_blocker(self):
        name = self.ready_for_approval()
        frappe.set_user("Administrator")
        with_version(make_charter(request=name))
        self.as_user(self.office)
        context = formation.get_request_review(name)
        self.assertTrue(any("charter challenge" in b for b in context["blockers"]))


class TestStandingGate(GovernanceTestCase):
    """A forum is not found compliant over an open charter challenge."""

    def setUp(self):
        super().setUp()
        self.reviewer = make_user("Compliance Reviewer")

    def test_a_favourable_decision_is_refused_while_the_challenge_is_open(self):
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        charter = with_version(make_charter(forum.name))

        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_review(forum.name, "Compliant", reviewer=self.reviewer, comments="Looks fine.")
        self.assertFalse(frappe.db.exists("Forum Compliance Review", {"forum": forum.name}))
        audited = refusals_for("Governance Forum", forum.name)
        self.assertEqual(audited[-1]["control"], "charter challenge")

        # The portal door refuses the same way.
        frappe.set_user(self.reviewer)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_compliance_review(forum.name, "Not Applicable", comments="Out of scope.")
        frappe.set_user("Administrator")

        # A decision that sends the forum back is never blocked by the challenge.
        lifecycle.record_review(forum.name, "Non-Compliant", reviewer=self.reviewer, comments="Charter disputed.")
        self.assertEqual(frappe.db.get_value("Governance Forum", forum.name, "compliance_status"), "Non-Compliant")

        clear(charter)
        lifecycle.record_review(forum.name, "Compliant", reviewer=self.reviewer, comments="Charter cleared.")
        self.assertEqual(frappe.db.get_value("Governance Forum", forum.name, "compliance_status"), "Compliant")

    def test_a_charter_no_longer_in_force_does_not_block(self):
        forum = make_forum()
        make_charter(forum.name, effective_from=add_days(nowdate(), -400), effective_to=add_days(nowdate(), -30))
        self.assertEqual(lifecycle.standing_blockers(forum.name, "Compliant"), [])
        lifecycle.record_review(forum.name, "Compliant", reviewer=self.reviewer, comments="Fine.")

    def test_a_review_inserted_directly_is_gated_too(self):
        """The desk inserts the review record itself; `apply_review` is the backstop."""
        forum = make_forum()
        self.purge_on_teardown("Governance Forum", forum.name)
        with_version(make_charter(forum.name))
        with self.assertRaises(frappe.ValidationError):
            frappe.get_doc({"doctype": "Forum Compliance Review", "forum": forum.name, "review_type": "Initial",
                            "reviewer": self.reviewer, "decision": "Compliant"}).insert(ignore_permissions=True)


# --------------------------------------------------------------- G-15 portal


class TestCharterPortal(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.secretary = make_user("Committee Secretary")
        self.viewer = make_user("Governance Viewer")
        self.owner = make_user("Forum Owner")
        self.forum = make_forum()
        self.charter = make_charter(self.forum.name)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def versions(self):
        return frappe.db.count("Document Version", {"subject_doctype": "Committee Charter",
                                                    "subject_name": self.charter.name})

    def test_the_context_says_who_may_do_what(self):
        frappe.set_user(self.secretary)
        ctx = charters.get_forum_charters(self.forum.name)
        self.assertTrue(ctx["readable"])
        self.assertTrue(ctx["charters"][0]["can_publish"])
        self.assertFalse(ctx["can_challenge"])

        frappe.set_user(self.rgo)
        self.assertTrue(charters.get_forum_charters(self.forum.name)["can_challenge"])

        frappe.set_user(self.viewer)
        ctx = charters.get_forum_charters(self.forum.name)
        self.assertTrue(ctx["readable"])
        self.assertFalse(ctx["charters"][0]["can_publish"])

        # A forum owner reads the forum but not charters: told so, not shown them.
        frappe.set_user(self.owner)
        ctx = charters.get_forum_charters(self.forum.name)
        self.assertFalse(ctx["readable"])
        self.assertEqual(ctx["charters"], [])

    def test_a_secretary_publishes_a_version_and_the_challenge_reopens(self):
        with_version(self.charter)
        clear(self.charter)
        self.assertFalse(frappe.db.get_value("Committee Charter", self.charter.name, "requires_review"))

        frappe.set_user(self.secretary)
        result = charters.publish_charter_version(self.charter.name, "Scope widened.", body_text="Mandate v2",
                                                  version_label="2.0")
        self.assertEqual([v["version_number"] for v in result["versions"]], [2, 1])
        self.assertEqual(result["current_text"], "Mandate v2")
        self.assertTrue(result["challenge_outstanding"], "new text reopens the challenge")
        self.assertIn("challenge is not cleared", "; ".join(result["blockers"]))

    def test_a_version_needs_a_summary_and_a_body(self):
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.ValidationError):
            charters.publish_charter_version(self.charter.name, "  ", body_text="Text")
        with self.assertRaises(frappe.ValidationError):
            charters.publish_charter_version(self.charter.name, "Summary.")
        self.assertEqual(self.versions(), 0)

    def test_only_a_file_attached_to_this_charter_is_accepted(self):
        other = make_charter(self.forum.name)
        stray = frappe.get_doc({"doctype": "File", "file_name": unique("stray") + ".txt", "content": b"x",
                                "attached_to_doctype": "Committee Charter", "attached_to_name": other.name,
                                "is_private": 1}).insert(ignore_permissions=True)
        mine = frappe.get_doc({"doctype": "File", "file_name": unique("mine") + ".txt", "content": b"charter",
                               "attached_to_doctype": "Committee Charter", "attached_to_name": self.charter.name,
                               "is_private": 1}).insert(ignore_permissions=True)
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.ValidationError):
            charters.publish_charter_version(self.charter.name, "From a file.", body_file=stray.file_url)
        result = charters.publish_charter_version(self.charter.name, "From a file.", body_file=mine.file_url)
        self.assertEqual(result["versions"][0]["body_file"], mine.file_url)

    def test_a_reader_may_not_publish_and_is_audited(self):
        self.purge_on_teardown("Committee Charter", self.charter.name)
        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            charters.publish_charter_version(self.charter.name, "Mine.", body_text="Text")
        frappe.set_user("Administrator")
        self.assertEqual(self.versions(), 0)
        self.assertEqual(refusals_for("Committee Charter", self.charter.name)[-1]["control"],
                         "charter write permission")

    def test_the_challenge_belongs_to_the_governance_office(self):
        self.purge_on_teardown("Committee Charter", self.charter.name)
        with_version(self.charter)
        frappe.set_user(self.secretary)
        # A secretary may not clear their own charter, in either door.
        with self.assertRaises(frappe.PermissionError):
            charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CLEARED)
        with self.assertRaises(frappe.PermissionError):
            charters.publish_charter_version(self.charter.name, "v2", body_text="x",
                                             challenge_status=charters.CHALLENGE_CLEARED)
        frappe.set_user("Administrator")
        self.assertEqual(self.versions(), 1, "a refused publish takes no version")
        self.assertEqual(refusals_for("Committee Charter", self.charter.name)[-1]["control"],
                         "charter challenge role")

        frappe.set_user(self.rgo)
        with self.assertRaises(frappe.ValidationError):
            charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CHANGES_REQUESTED)
        with self.assertRaises(frappe.ValidationError):
            charters.record_charter_challenge(self.charter.name, "Waved Through")
        result = charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CHANGES_REQUESTED,
                                                   comments="Name the delegating authority.")
        self.assertTrue(result["challenge_outstanding"])
        self.assertEqual(result["rgo_reviewed_by"], self.rgo)
        result = charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CLEARED)
        self.assertFalse(result["challenge_outstanding"])

        # The office may record its outcome on a text in the same step as publishing it.
        result = charters.publish_charter_version(self.charter.name, "v2", body_text="Mandate v2",
                                                  challenge_status=charters.CHALLENGE_CLEARED)
        self.assertFalse(result["challenge_outstanding"])

    def test_nothing_to_challenge_without_a_version(self):
        frappe.set_user(self.rgo)
        with self.assertRaises(frappe.ValidationError):
            charters.record_charter_challenge(self.charter.name, charters.CHALLENGE_CLEARED)

    def test_starting_a_charter(self):
        bare = make_forum()
        # The viewer's refusal is logged on its own committed connection, and the
        # forum's reference comes from a series the rollback rewinds: without
        # this, the next run's forum of the same name inherits the refusal.
        self.purge_on_teardown("Governance Forum", bare.name)
        frappe.set_user(self.viewer)
        with self.assertRaises(frappe.PermissionError):
            charters.start_forum_charter(bare.name, "Terms of Reference")
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.ValidationError):
            charters.start_forum_charter(bare.name, "  ")
        view = charters.start_forum_charter(bare.name, "Terms of Reference")
        self.assertEqual(view["forum"], bare.name)
        self.assertTrue(view["challenge_outstanding"])

    def test_a_disbanded_forums_charter_is_not_revised(self):
        lifecycle.set_forum_state(self.forum.name, lifecycle.DISBANDED_STATUS)
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.ValidationError):
            charters.publish_charter_version(self.charter.name, "Late change.", body_text="x")
        self.assertFalse(charters.get_forum_charters(self.forum.name)["can_start"])


# -------------------------------------------------------------- E8-S5 portal


class TestDisbandmentPortal(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        self.authority, self.sponsor, self.chair = make_user(), make_user(), make_user()
        self.secretary = make_user("Committee Secretary")
        self.forum = make_forum(sponsor=self.sponsor)
        self.successor = make_forum()

    def rows(self, **overrides):
        named = {"Delegating Authority": self.authority, "Sponsor": self.sponsor, "Chair": self.chair}
        named.update(overrides)
        return [{"approver_role": role, "approver": user} for role, user in named.items() if user]

    def raise_plan(self, **overrides):
        frappe.set_user(self.rgo)
        try:
            return lifecycle.raise_disbandment_plan(
                self.forum.name, "Mandate Complete", "Records retained under the forum's retention class.",
                approvals=self.rows(**overrides), successor_forum=self.successor.name,
            )
        finally:
            frappe.set_user("Administrator")

    def decide(self, ctx, role, decision="Approved", user=None, comments=None):
        plan = ctx["plans"][0]
        row = next(r for r in plan["approvals"] if r["approver_role"] == role)
        frappe.set_user(user or row["approver"])
        try:
            return lifecycle.record_disbandment_decision(plan["name"], row["approval_decision"], decision,
                                                         comments=comments)
        finally:
            frappe.set_user("Administrator")

    def test_raising_names_g11s_approvers_and_asks_them(self):
        ctx = self.raise_plan()
        plan = ctx["plans"][0]
        self.assertEqual([r["approver_role"] for r in plan["approvals"]], ["Delegating Authority", "Sponsor", "Chair"])
        self.assertTrue(all(r["approval_decision"] and r["is_open"] for r in plan["approvals"]))
        self.assertEqual(plan["successor_forum"], self.successor.name)
        self.assertTrue(plan["live"])
        self.assertFalse(plan["can_execute"])
        self.assertFalse(ctx["may_raise"], "one live plan at a time")

    def test_raising_refuses_an_incomplete_or_improper_plan(self):
        frappe.set_user(self.rgo)
        for rows, why in (
            (self.rows(Chair=None), "the chair is missing"),
            (self.rows(Chair="Guest"), "a pseudo-user cannot approve"),
            (self.rows() + [{"approver_role": "Chair", "approver": make_user()}], "a role named twice"),
            (self.rows() + [{"approver_role": "Head Chef", "approver": make_user()}], "an unknown role"),
        ):
            with self.subTest(why=why):
                with self.assertRaises(frappe.ValidationError):
                    lifecycle.raise_disbandment_plan(self.forum.name, "Mandate Complete", "Retained.",
                                                     approvals=rows)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.raise_disbandment_plan(self.forum.name, "Mandate Complete", "  ", approvals=self.rows())
        with self.assertRaises(frappe.ValidationError):
            lifecycle.raise_disbandment_plan(self.forum.name, "Mandate Complete", "Retained.",
                                             approvals=self.rows(), successor_forum=self.forum.name)
        frappe.set_user("Administrator")
        self.assertFalse(frappe.db.exists("Disbandment Plan", {"forum": self.forum.name}))

        self.raise_plan()
        frappe.set_user(self.rgo)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.raise_disbandment_plan(self.forum.name, "Mandate Complete", "Retained.",
                                             approvals=self.rows())

    def test_raising_belongs_to_the_governance_office(self):
        self.purge_on_teardown("Governance Forum", self.forum.name)
        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            lifecycle.raise_disbandment_plan(self.forum.name, "Mandate Complete", "Retained.",
                                             approvals=self.rows())
        with self.assertRaises(frappe.PermissionError):
            lifecycle.disbandment_people()
        frappe.set_user("Administrator")
        self.assertEqual(refusals_for("Governance Forum", self.forum.name)[-1]["control"], "disbandment role")

    def test_decisions_are_the_approvers_or_their_delegates(self):
        ctx = self.raise_plan()
        plan = ctx["plans"][0]
        stranger = make_user("Risk Governance Office")
        self.purge_on_teardown("Disbandment Plan", plan["name"])
        with self.assertRaises(frappe.PermissionError):
            self.decide(ctx, "Sponsor", user=stranger)

        # A live delegation from the sponsor lets the delegate decide, and says so.
        delegate = make_user()
        frappe.get_doc({
            "doctype": "Authority Delegation", "delegator": self.sponsor, "delegate": delegate,
            "scope_type": "All", "valid_from": nowdate(), "valid_to": add_days(nowdate(), 30),
            "delegated_actions": [{"delegable_action": "APPROVE"}],
        }).insert(ignore_permissions=True)
        frappe.set_user(delegate)
        view = lifecycle.get_disbandment(self.forum.name)
        frappe.set_user("Administrator")
        sponsor_row = next(r for r in view["plans"][0]["approvals"] if r["approver_role"] == "Sponsor")
        self.assertTrue(sponsor_row["can_decide"])
        ctx = self.decide(ctx, "Sponsor", user=delegate)
        sponsor_row = next(r for r in ctx["plans"][0]["approvals"] if r["approver_role"] == "Sponsor")
        self.assertEqual(sponsor_row["acted_by"], delegate)
        self.assertTrue(sponsor_row["acting_delegation"])
        self.assertEqual(frappe.db.get_value("Disbandment Approval",
                                             {"approval_decision": sponsor_row["approval_decision"]}, "decision"),
                         "Approved", "the plan's row mirrors the Core decision")

        with self.assertRaises(frappe.ValidationError):
            self.decide(ctx, "Sponsor")  # already decided
        with self.assertRaises(frappe.ValidationError):
            self.decide(ctx, "Chair", decision="Rejected")  # a refusal carries its reason
        with self.assertRaises(frappe.ValidationError):
            self.decide(ctx, "Chair", decision="Bypassed")  # not offered

    def test_an_approval_of_another_plan_is_refused(self):
        ctx = self.raise_plan()
        other_forum = make_forum()
        frappe.set_user(self.rgo)
        other = lifecycle.raise_disbandment_plan(other_forum.name, "Other", "Retained.", approvals=self.rows())
        frappe.set_user(self.chair)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.record_disbandment_decision(
                ctx["plans"][0]["name"],
                next(r for r in other["plans"][0]["approvals"] if r["approver_role"] == "Chair")["approval_decision"],
                "Approved")

    def test_execution_waits_for_every_approval_then_leaves_the_forum_inactive(self):
        seat = make_seat(self.forum.name, seat_role())
        ctx = self.raise_plan()
        name = ctx["plans"][0]["name"]
        self.purge_on_teardown("Governance Forum", self.forum.name)
        ctx = self.decide(ctx, "Delegating Authority")
        self.assertIn("2 required approval(s) are undecided", ctx["plans"][0]["blockers"])

        frappe.set_user(self.rgo)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.execute_forum_disbandment(name)
        frappe.set_user("Administrator")
        self.assertTrue(frappe.db.get_value("Governance Forum", self.forum.name, "is_active"))

        self.decide(ctx, "Sponsor")
        ctx = self.decide(ctx, "Chair")
        self.assertEqual(ctx["plans"][0]["blockers"], [])

        frappe.set_user(self.secretary)
        with self.assertRaises(frappe.PermissionError):
            lifecycle.execute_forum_disbandment(name)

        frappe.set_user(self.rgo)
        self.assertTrue(lifecycle.get_disbandment(self.forum.name)["plans"][0]["can_execute"])
        result = lifecycle.execute_forum_disbandment(name)
        frappe.set_user("Administrator")
        self.assertIn(seat.name, result["executed"]["seats_closed"])
        forum = frappe.get_doc("Governance Forum", self.forum.name)
        self.assertFalse(forum.is_active)
        self.assertEqual(forum.disbandment_plan, name)
        self.assertTrue(frappe.db.exists("Governance Forum", self.forum.name), "disbanded, never deleted")

        frappe.set_user(self.rgo)
        with self.assertRaises(frappe.ValidationError):
            lifecycle.execute_forum_disbandment(name)

    def test_a_refusal_stops_the_plan_and_a_new_one_may_be_raised(self):
        ctx = self.raise_plan()
        name = ctx["plans"][0]["name"]
        self.purge_on_teardown("Governance Forum", self.forum.name)
        self.decide(ctx, "Delegating Authority")
        self.decide(ctx, "Sponsor")
        ctx = self.decide(ctx, "Chair", decision="Rejected", comments="The mandate is not complete.")
        self.assertFalse(ctx["plans"][0]["live"])
        self.assertTrue(any("refused" in b for b in ctx["plans"][0]["blockers"]))

        # Nothing is outstanding, but the refusal still stops execution.
        self.assertEqual(lifecycle.disbandment_outstanding(name), [])
        with self.assertRaises(frappe.ValidationError):
            lifecycle.execute_disbandment(name)
        self.assertTrue(frappe.db.get_value("Governance Forum", self.forum.name, "is_active"))

        self.assertTrue(lifecycle.get_disbandment(self.forum.name)["may_raise"])
        self.raise_plan()
        self.assertEqual(frappe.db.count("Disbandment Plan", {"forum": self.forum.name}), 2)

    def test_who_may_see_the_disbandment(self):
        self.raise_plan()
        nobody = make_user()
        frappe.set_user(nobody)
        with self.assertRaises(frappe.PermissionError):
            lifecycle.get_disbandment(self.forum.name)
        # The chair holds no role at all, and still sees what they are asked to decide.
        frappe.set_user(self.chair)
        view = lifecycle.get_disbandment(self.forum.name)
        self.assertEqual(len(view["plans"]), 1)
        self.assertFalse(view["may_raise"])

        frappe.set_user(self.secretary)
        actions = lifecycle.forum_page_actions(self.forum.name)["disbandment"]
        self.assertTrue(actions["visible"])
        self.assertFalse(actions["may_raise"])
        frappe.set_user(self.rgo)
        actions = lifecycle.forum_page_actions(self.successor.name)["disbandment"]
        self.assertTrue(actions["may_raise"])
        frappe.set_user(self.secretary)
        self.assertFalse(lifecycle.forum_page_actions(self.successor.name)["disbandment"]["visible"],
                         "a reader is not sent to an empty page")


# ------------------------------------------------------ E6-S3, O-2 and O-5


class TestInventoryReads(GovernanceTestCase):
    def test_tagged_filters_intersect(self):
        both, only_one = make_jurisdiction(), make_jurisdiction()
        unit = make_org_unit("Business Unit")
        a = make_forum(jurisdictions=[{"jurisdiction": both}], business_units=[{"business_unit": unit}])
        b = make_forum(jurisdictions=[{"jurisdiction": both}])
        make_forum(jurisdictions=[{"jurisdiction": only_one}], business_units=[{"business_unit": unit}])

        names = [r["name"] for r in inventory.search(tagged={"jurisdiction": both}, order_by="modified desc")]
        self.assertEqual(sorted(names), sorted([a.name, b.name]))
        names = [r["name"] for r in inventory.search(tagged={"jurisdiction": both, "business_unit": unit})]
        self.assertEqual(names, [a.name], "two dimensions narrow together, not last-one-wins")
        self.assertEqual(inventory.tagged_forum_names('{"jurisdiction": "%s", "business_unit": "%s"}' % (both, unit)),
                         [a.name])
        self.assertEqual(inventory.tagged_forum_names({}), [])
        with self.assertRaises(frappe.ValidationError):
            inventory.tagged_forum_names({"favourite_colour": "blue"})

    def test_tagged_names_respect_permission(self):
        value = make_jurisdiction()
        make_forum(jurisdictions=[{"jurisdiction": value}])
        frappe.set_user(make_user())
        with self.assertRaises(frappe.PermissionError):
            inventory.tagged_forum_names({"jurisdiction": value})

    def test_filter_values_include_retired_ones_marked(self):
        live = make_jurisdiction()
        retired = make_jurisdiction()
        frappe.db.set_value("Jurisdiction", retired, "is_active", 0)
        dims = {d["key"]: d for d in inventory.inventory_filters()}
        self.assertEqual(set(dims), {"business_unit", "risk_type", "legal_entity", "jurisdiction",
                                     "governance_responsibility"})
        values = {v["value"]: v["retired"] for v in dims["jurisdiction"]["values"]}
        self.assertFalse(values[live])
        self.assertTrue(values[retired])

    def test_the_map_draws_what_the_viewer_may_see(self):
        parent = make_forum()
        child = make_forum(parent_forum=parent.name)
        gone = make_forum()
        lateral = make_forum(upstream_links=[{"linked_forum": parent.name, "relationship_type": "Escalates To",
                                              "direction": "Upstream"},
                                             {"linked_forum": gone.name, "relationship_type": "Informs",
                                              "direction": "Upstream"}])
        lifecycle.set_forum_state(gone.name, lifecycle.DISBANDED_STATUS)

        viewer = make_user("Governance Viewer")
        frappe.set_user(viewer)
        data = inventory.forum_map()
        nodes = {n["name"]: n for n in data["nodes"]}
        self.assertEqual(nodes[child.name]["parent_forum"], parent.name)
        self.assertNotIn(gone.name, nodes, "an inactive forum is not on the map")
        links = [(l["source"], l["target"]) for l in data["links"]]
        self.assertIn((lateral.name, parent.name), links)
        self.assertNotIn((lateral.name, gone.name), links, "no link to a forum not drawn")

        frappe.set_user(make_user())
        with self.assertRaises(frappe.PermissionError):
            inventory.forum_map()


class TestForumEscalations(GovernanceTestCase):
    """O-5: the forum lists matters on its pathway; restricted ones only to the cleared."""

    def setUp(self):
        super().setUp()
        from consilium.escalation.tests.utils import EscalationTestCase

        self.forum = make_forum()
        reference = EscalationTestCase.reference_data(self)
        pathway = [{"governance_forum": self.forum.name, "role_in_escalation": "Decision"}]
        self.open_matter = frappe.get_doc(EscalationTestCase.matter_values(
            self, reference, escalation_title="Visible matter", governance_forums=pathway)).insert(
            ignore_permissions=True)
        self.sensitive = frappe.get_doc(EscalationTestCase.matter_values(
            self, reference, escalation_title="Restricted matter", sensitive=1, governance_forums=pathway)).insert(
            ignore_permissions=True)
        frappe.get_doc(EscalationTestCase.matter_values(
            self, reference, escalation_title="Elsewhere")).insert(ignore_permissions=True)

    def titles(self, user):
        frappe.set_user(user)
        try:
            result = inventory.forum_escalations(self.forum.name)
        finally:
            frappe.set_user("Administrator")
        return result, sorted(m["escalation_title"] for m in result["matters"])

    def test_restricted_matters_appear_only_to_the_cleared(self):
        from consilium.escalation.tests.utils import make_user as make_user_with

        reviewer = make_user_with("Escalation Reviewer", "Governance Viewer")
        cleared = make_user_with("Escalation Reviewer", "Governance Viewer", "Sensitive Escalation Access")

        result, titles = self.titles(reviewer)
        self.assertTrue(result["readable"])
        self.assertEqual(titles, ["Visible matter"])
        self.assertEqual(self.titles(cleared)[1], ["Restricted matter", "Visible matter"])
        role = next(m for m in result["matters"] if m["name"] == self.open_matter.name)["role_in_escalation"]
        self.assertEqual(role, "Decision")

    def test_a_viewer_without_escalation_access_is_told_so(self):
        result, titles = self.titles(make_user("Governance Viewer"))
        self.assertFalse(result["readable"])
        self.assertEqual(titles, [])

    def test_a_viewer_who_cannot_read_the_forum_is_refused(self):
        frappe.set_user(make_user("Escalation Reviewer"))
        with self.assertRaises(frappe.PermissionError):
            inventory.forum_escalations(self.forum.name)


# ------------------------------------------------------------------- pages


def render(route: str, user: str, query: dict | None = None):
    """Render a portal page inside a real request, as the regression sweep does."""
    from urllib.parse import urlencode

    from frappe.website.serve import get_response
    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    frappe.set_user(user)
    frappe.local.form_dict = frappe._dict(query or {})
    path = "/" + route + ("?" + urlencode(query) if query else "")
    frappe.local.request = Request(EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ())
    try:
        response = get_response(route or "/")
        return response.status_code, response.get_data(as_text=True)
    finally:
        frappe.set_user("Administrator")


class TestPages(GovernanceTestCase):
    def test_the_pages_render_with_their_new_sections(self):
        forum = make_forum()
        viewer = make_user("Governance Viewer")
        for route, query, marks in (
            ("forum", {"name": forum.name}, ["tab-escalations", "charter-publish-form", "forum-revision-list",
                                             "forum-extra-actions", "forum_page_actions"]),
            ("forum-disband", {"forum": forum.name}, ["raise-form", "get_disbandment"]),
            ("forums", None, ["tag-filter-fields", "tagged_forum_names"]),
            ("", None, ["forum-map", "forum-map-list", "inventory.forum_map"]),
        ):
            with self.subTest(route=route):
                status, body = render(route, self.rgo, query)
                self.assertEqual(status, 200, body[:300])
                for mark in marks:
                    self.assertIn(mark, body)
                status, body = render(route, viewer, query)
                self.assertEqual(status, 200, body[:300])

    def test_the_disbandment_page_is_closed_to_those_without_a_part_in_it(self):
        forum = make_forum()
        status, body = render("forum-disband", make_user(), {"forum": forum.name})
        self.assertEqual(status, 200)
        self.assertIn("not open to you", body)
        self.assertNotIn("raise-form", body)

    def test_a_forum_named_with_markup_is_printed_as_text(self):
        attack = "<script>alert(1)</script>"
        for route, query in (("forum", {"name": attack}), ("forum-disband", {"forum": attack})):
            with self.subTest(route=route):
                status, body = render(route, "Administrator", query)
                self.assertNotIn(attack, body)


class TestForumRevisionCard(GovernanceTestCase):
    """The History tab's revision card calls Core's `revision.history` and
    `revision.revert`; exercised here as the card calls them."""

    def test_a_revert_needs_a_reason_and_then_writes_a_new_version(self):
        from consilium.consilium_core import revision

        forum = make_forum()
        forum.reload()
        # Cadence is not a watched field, so the edit leaves the forum editable
        # (a watched-field change would lock it for review, and a locked record
        # is not reverted).
        forum.cadence = "Monthly"
        forum.save(ignore_permissions=True)
        reverter = make_user(revision._policy("Governance Forum").revert_roles[0])
        self.purge_on_teardown("Governance Forum", forum.name)

        frappe.set_user(reverter)
        history = revision.history("Governance Forum", forum.name)
        target = next(v for v in history["versions"] if v["can_revert"])
        with self.assertRaises(frappe.ValidationError):
            revision.revert("Governance Forum", forum.name, target["name"], reason="  ")
        self.assertEqual(frappe.db.get_value("Governance Forum", forum.name, "cadence"), "Monthly")
        after = revision.revert("Governance Forum", forum.name, target["name"], reason="Cadence changed in error.")
        frappe.set_user("Administrator")
        self.assertEqual(len(after["versions"]), len(history["versions"]) + 1)
        self.assertEqual(frappe.db.get_value("Governance Forum", forum.name, "cadence"), "Quarterly")
