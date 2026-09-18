"""E3-S2: a retired taxonomy value is not offered, and still resolves where it is used.

The picker's search is exercised two ways: named explicitly (as a link field
with a query would), and through the ``standard_queries`` hook the way the
framework resolves it for every link field with no query of its own. The
entry in ``hooks.py`` is written out as a literal, so the test checks that it
still matches ``taxonomy.STANDARD_QUERIES``.
"""


import frappe
from frappe.desk.form.load import get_title_values_for_link_and_dynamic_link_fields
from frappe.client import validate_link
from frappe.desk.search import get_link_title, search_link

from consilium.consilium_core import taxonomy
from consilium.consilium_core.tests.test_entities import TAXONOMIES
from consilium.consilium_core.tests.utils import CoreTestCase, make_user, unique


def _values(results):
    return [row["value"] for row in results]


class TestActiveOnlySearch(CoreTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        self.tag = unique("RETIRE").upper()
        self.live = self._risk_type("Live")
        self.retired = self._risk_type("Retired")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _risk_type(self, label: str) -> str:
        return frappe.get_doc({
            "doctype": "Risk Type", "risk_type_code": f"{self.tag}-{label.upper()}",
            "risk_type_name": f"{self.tag} {label} risk", "tier": 1,
        }).insert(ignore_permissions=True).name

    def _retire(self, name: str) -> None:
        doc = frappe.get_doc("Risk Type", name)
        doc.is_active = 0
        doc.save(ignore_permissions=True)

    def test_the_hook_entry_covers_every_taxonomy_and_each_carries_the_flag(self):
        self.assertEqual(set(taxonomy.STANDARD_QUERIES), set(TAXONOMIES))
        for doctype, method in taxonomy.STANDARD_QUERIES.items():
            with self.subTest(doctype=doctype):
                self.assertTrue(frappe.get_meta(doctype).has_field("is_active"))
                self.assertEqual(frappe.get_attr(method), taxonomy.active_only_search)

    def test_a_retired_value_is_not_offered_but_a_live_one_is(self):
        self._retire(self.retired)
        offered = _values(search_link("Risk Type", self.tag, query=taxonomy.SEARCH))
        self.assertIn(self.live, offered)
        self.assertNotIn(self.retired, offered)
        # Matched by title as well as code, and shaped as the framework shapes it.
        by_title = search_link("Risk Type", f"{self.tag} Live", query=taxonomy.SEARCH)
        self.assertEqual(_values(by_title), [self.live])
        self.assertEqual(by_title[0]["label"], f"{self.tag} Live risk")

    def test_through_the_standard_queries_hook(self):
        self._retire(self.retired)
        # hooks.py registers the search for every taxonomy type, and a link
        # picker therefore offers only the live value: the gap E3-S2 names.
        registered = frappe.get_hooks("standard_queries")
        for doctype, method in taxonomy.STANDARD_QUERIES.items():
            self.assertEqual(registered.get(doctype), [method], doctype)
        self.assertEqual(_values(search_link("Risk Type", self.tag)), [self.live])

    def test_a_record_made_before_retirement_still_shows_the_value(self):
        # A child risk type made while its parent was live, then the parent retired.
        child = frappe.get_doc({
            "doctype": "Risk Type", "risk_type_code": f"{self.tag}-CHILD", "risk_type_name": f"{self.tag} child",
            "tier": 2, "parent_risk_type": self.retired,
        }).insert(ignore_permissions=True)
        self._retire(self.retired)

        # Not offered for a new record...
        self.assertNotIn(self.retired, _values(search_link("Risk Type", self.tag, query=taxonomy.SEARCH)))
        # ...but the existing record still loads, validates, resaves and shows the name.
        child = frappe.get_doc("Risk Type", child.name)
        self.assertEqual(child.parent_risk_type, self.retired)
        child.description = "Edited after the parent was retired."
        child.save(ignore_permissions=True)
        self.assertEqual(get_link_title("Risk Type", self.retired), f"{self.tag} Retired risk")
        titles = get_title_values_for_link_and_dynamic_link_fields(child)
        self.assertEqual(titles.get(f"Risk Type::{self.retired}"), f"{self.tag} Retired risk")
        self.assertEqual(validate_link("Risk Type", self.retired).get("name"), self.retired)

    def test_a_caller_that_asks_for_retired_values_gets_them(self):
        self._retire(self.retired)
        asked = _values(search_link("Risk Type", self.tag, query=taxonomy.SEARCH,
                                    filters={"is_active": 0}))
        self.assertEqual(asked, [self.retired])
        # Other filters are honoured alongside the active-only rule.
        narrowed = _values(search_link("Risk Type", self.tag, query=taxonomy.SEARCH,
                                       filters=[["Risk Type", "tier", "=", 2]]))
        self.assertEqual(narrowed, [])

    def test_permissions_still_apply(self):
        # Taxonomies are readable by every signed-in user ("All"), so an ordinary
        # user is offered the same live values; a guest is not offered any.
        self._retire(self.retired)
        frappe.set_user(make_user())
        self.assertEqual(_values(search_link("Risk Type", self.tag, query=taxonomy.SEARCH)), [self.live])
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError):
            taxonomy.active_only_search("Risk Type", self.tag, "name", 0, 10, None)
