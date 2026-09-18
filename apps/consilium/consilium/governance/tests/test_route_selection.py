"""G-8: the formation approval path is chosen by forum type and by materiality.

"Approval paths may differ by materiality of change and by forum type." A
``Formation Approval Route`` now narrows on request type, forum type and
materiality, and ``formation.resolve_route`` takes the most specific active
route that fits. These tests raise real steps from real routes and read back
which steps were raised; no assertion names a workflow state.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core.tests.utils import refusals_for
from consilium.governance import formation, setup
from consilium.governance.tests.test_formation import assess_all, make_request
from consilium.governance.tests.utils import GovernanceTestCase, make_forum, make_forum_type, make_user, unique


def make_route(steps, **keys) -> str:
    """A route of ``(title, sequence, field on the request)`` steps, narrowed by ``keys``."""
    route = frappe.get_doc(
        {
            "doctype": "Formation Approval Route",
            "route_title": unique("Route"),
            "request_type": keys.pop("request_type", "Any"),
            "change_materiality": keys.pop("change_materiality", "Any"),
            "is_active": 1,
            **keys,
        }
    )
    for title, sequence, field in steps:
        route.append("steps", {"step_title": title, "step_sequence": sequence, "mode": "Sequential",
                               "assign_to_field": field, "is_active": 1})
    return route.insert(ignore_permissions=True).name


def raised_steps(request) -> list[str]:
    formation.raise_approval_steps(request)
    return frappe.get_all(
        "Approval Decision",
        filters={"subject_doctype": "Committee Formation Request", "subject_name": request.name},
        pluck="approval_step",
        order_by="step_sequence asc, approval_step asc",
    )


def change_request(materiality: str | None, **values):
    return make_request(request_type="Modify", subject_forum=make_forum().name, change_materiality=materiality,
                        **values)


class TestTheForumTypeChoosesThePath(GovernanceTestCase):
    def test_two_forum_types_raise_different_steps(self):
        board_like, working_like = make_forum_type(), make_forum_type()
        route_a = make_route([("Delegating Authority Approval", 1, "delegating_authority"),
                              ("Sponsor Endorsement", 2, "forum_sponsor")], forum_type=board_like)
        route_b = make_route([("Sponsor Endorsement Only", 1, "forum_sponsor")], forum_type=working_like)

        first = assess_all(make_request(forum_type=board_like))
        second = assess_all(make_request(forum_type=working_like))

        self.assertEqual(raised_steps(first), ["Delegating Authority Approval", "Sponsor Endorsement"])
        self.assertEqual(raised_steps(second), ["Sponsor Endorsement Only"])
        first.reload()
        second.reload()
        self.assertEqual(first.approval_route, route_a)
        self.assertEqual(second.approval_route, route_b)

    def test_a_type_with_no_route_of_its_own_follows_the_standard_route(self):
        make_route([("Sponsor Endorsement Only", 1, "forum_sponsor")], forum_type=make_forum_type())
        request = assess_all(make_request())
        self.assertEqual(len(raised_steps(request)), 3)
        request.reload()
        self.assertEqual(request.approval_route, setup.DEFAULT_ROUTE_TITLE)

    def test_an_inactive_route_is_not_chosen(self):
        forum_type = make_forum_type()
        route = make_route([("Sponsor Endorsement Only", 1, "forum_sponsor")], forum_type=forum_type)
        frappe.db.set_value("Formation Approval Route", route, "is_active", 0)
        self.assertEqual(formation.resolve_route(make_request(forum_type=forum_type)).name,
                         setup.DEFAULT_ROUTE_TITLE)


class TestMaterialityChoosesThePath(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        setup.ensure_routed_paths()
        # The material-change route ends with the head of risk governance.
        make_user("Head of Risk Governance")

    def test_two_materialities_raise_different_steps(self):
        minor = assess_all(change_request("Minor"))
        material = assess_all(change_request("Material"))

        minor_steps = raised_steps(minor)
        material_steps = raised_steps(material)

        self.assertEqual(minor_steps, ["Risk Governance Office Evaluation", "Sponsor Endorsement"])
        self.assertIn("Head of Risk Governance Sign-off", material_steps)
        self.assertIn("Delegating Authority Approval", material_steps)
        self.assertNotEqual(minor_steps, material_steps)
        minor.reload()
        material.reload()
        self.assertEqual(minor.approval_route, "Minor Change Approval")
        self.assertEqual(material.approval_route, "Material Change Approval")

    def test_a_significant_change_with_no_route_of_its_own_follows_the_standard_route(self):
        request = assess_all(change_request("Significant"))
        self.assertEqual(formation.resolve_route(request).name, setup.DEFAULT_ROUTE_TITLE)

    def test_the_most_specific_route_wins(self):
        forum_type = make_forum_type()
        type_only = make_route([("Type Step", 1, "forum_sponsor")], forum_type=forum_type)
        type_and_materiality = make_route([("Type And Materiality Step", 1, "forum_sponsor")],
                                          forum_type=forum_type, change_materiality="Material")
        everything = make_route([("Everything Step", 1, "forum_sponsor")], forum_type=forum_type,
                                change_materiality="Minor", request_type="Modify")

        # Two dimensions each: the shipped "Material Change Approval" names the
        # request type and materiality, this one the forum type and
        # materiality. The forum type is the more deliberate choice, so it wins.
        material = change_request("Material", forum_type=forum_type)
        self.assertEqual(formation.resolve_route(material).name, type_and_materiality)
        # Three dimensions beat any two.
        minor = change_request("Minor", forum_type=forum_type)
        self.assertEqual(formation.resolve_route(minor).name, everything)
        # A new forum of the type: only the type route and the standard route fit.
        self.assertEqual(formation.resolve_route(make_request(forum_type=forum_type)).name, type_only)

    def test_a_change_without_a_materiality_is_refused_when_submitted_and_audited(self):
        request = change_request(None)
        self.purge_on_teardown("Committee Formation Request", request.name)
        with self.assertRaises(frappe.ValidationError):
            formation.submit_request(request.name)
        audited = refusals_for("Committee Formation Request", request.name)
        self.assertEqual(audited[-1]["control"], "formation change materiality")

    def test_a_change_without_a_materiality_is_refused_approval_steps(self):
        request = assess_all(change_request(None))
        self.purge_on_teardown("Committee Formation Request", request.name)
        with self.assertRaises(frappe.ValidationError):
            formation.raise_approval_steps(request)
        self.assertFalse(formation.outstanding_steps(request))

    def test_a_draft_change_may_be_saved_without_one(self):
        request = change_request(None)
        self.assertTrue(request.is_editable)


class TestTheScreensShowIt(GovernanceTestCase):
    def setUp(self):
        super().setUp()
        setup.ensure_routed_paths()

    def test_the_review_screen_names_the_route_and_what_chose_it(self):
        request = change_request("Minor")
        route = formation.review_context(request)["route"]
        self.assertEqual(route["name"], "Minor Change Approval")
        self.assertFalse(route["raised"])
        self.assertIn("minor change", route["chosen_by"])
        self.assertEqual(formation.review_context(request)["request"]["change_materiality"], "Minor")

    def test_the_intake_form_offers_the_materialities(self):
        from consilium.www import create_forum

        context = frappe._dict()
        create_forum.get_context(context)
        self.assertEqual(context.materiality_options, ["Minor", "Significant", "Material"])

    def test_the_formation_request_page_shows_the_materiality(self):
        import os

        with open(os.path.join(frappe.get_app_path("consilium", "www"), "formation-request.html")) as handle:
            page = handle.read()
        self.assertIn("Materiality of change", page)
        self.assertIn("routeText()", page)
