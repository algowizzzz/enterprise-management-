"""Only what this platform is for, for everyone but its administrators (E31-S3).

``scope.py`` hides the framework's out-of-scope workspaces, modules and website
pages from everyday users, and leaves them to system administrators, who need
them to run the platform. It does so as configuration re-applied on every
migrate. These tests apply it and then look from both sides: an everyday person
must not see the framework's tooling, and an administrator must still have it.
"""

from __future__ import annotations

import frappe

from consilium.consilium_core import scope
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.test_portal_pages import render
from consilium.consilium_core.tests.utils import CoreTestCase

PEOPLE = PersonaPool()


def tearDownModule():
	PEOPLE.remove()


def workspace_roles(workspace: str) -> list[str]:
	return sorted(frappe.get_all("Has Role", filters={"parent": workspace, "parenttype": "Workspace"}, pluck="role"))


def sidebar(user: str) -> set[str]:
	from frappe.desk.desktop import get_workspace_sidebar_items

	previous = frappe.session.user
	frappe.set_user(user)
	try:
		return {page["name"] for page in get_workspace_sidebar_items()["pages"]}
	finally:
		frappe.set_user(previous)


class ScopeCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		PEOPLE.attach(
			cls,
			{
				"policy_owner": ("Policy Owner",),
				"escalation_owner": ("Escalation Owner",),
				"system_manager": ("System Manager",),
			},
		)

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		scope.restrict_workspaces()
		scope.ensure_module_profile()
		frappe.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_cache()
		super().tearDown()


class TestWorkspaces(ScopeCase):
	def test_framework_workspaces_are_for_administrators_only(self):
		present = [w for w in scope.FRAMEWORK_WORKSPACES if frappe.db.exists("Workspace", w)]
		self.assertTrue(present, "none of the framework's workspaces exist on this site")
		for workspace in present:
			with self.subTest(workspace=workspace):
				self.assertEqual(workspace_roles(workspace), sorted(scope.ADMIN_ROLES))

	def test_each_consilium_workspace_goes_to_the_roles_that_read_it(self):
		for workspace, doctype in scope.CONSILIUM_WORKSPACES.items():
			if not frappe.db.exists("Workspace", workspace):
				continue
			with self.subTest(workspace=workspace):
				roles = workspace_roles(workspace)
				self.assertEqual(roles, scope._roles_that_read(doctype))
				self.assertIn("System Manager", roles)
				self.assertNotIn("Guest", roles)
				self.assertNotIn("All", roles)

	def test_the_administration_workspace_is_for_administration_roles(self):
		if not frappe.db.exists("Workspace", scope.ADMINISTRATION_WORKSPACE):
			self.skipTest("no administration workspace on this site")
		self.assertEqual(workspace_roles(scope.ADMINISTRATION_WORKSPACE), sorted(scope.ADMINISTRATION_ROLES))

	def test_restricting_twice_changes_nothing(self):
		before = {w: workspace_roles(w) for w in (*scope.FRAMEWORK_WORKSPACES, *scope.CONSILIUM_WORKSPACES)}
		scope.restrict_workspaces()
		after = {w: workspace_roles(w) for w in before}
		self.assertEqual(before, after)

	def test_an_everyday_user_does_not_see_the_framework_workspaces(self):
		pages = sidebar(self.policy_owner)
		for workspace in scope.FRAMEWORK_WORKSPACES:
			with self.subTest(workspace=workspace):
				self.assertNotIn(workspace, pages)
		if frappe.db.exists("Workspace", "Policy"):
			self.assertIn("Policy", pages)

	def test_an_administrator_keeps_them(self):
		pages = sidebar(self.system_manager)
		present = [w for w in ("Users", "Build", "Integrations") if frappe.db.exists("Workspace", w)]
		for workspace in present:
			with self.subTest(workspace=workspace):
				self.assertIn(workspace, pages)


class TestModuleProfile(ScopeCase):
	def test_the_profile_blocks_every_installed_out_of_scope_module(self):
		profile = frappe.get_doc("Module Profile", scope.MODULE_PROFILE)
		installed = set(frappe.get_all("Module Def", pluck="name"))
		self.assertEqual(
			sorted(row.module for row in profile.block_modules),
			sorted(m for m in scope.BLOCKED_MODULES if m in installed),
		)
		self.assertNotIn("Consilium Core", {row.module for row in profile.block_modules})

	def test_a_new_everyday_user_gets_the_profile(self):
		self.assertEqual(frappe.db.get_value("User", self.policy_owner, "module_profile"), scope.MODULE_PROFILE)
		self.assertEqual(frappe.db.get_value("User", self.escalation_owner, "module_profile"), scope.MODULE_PROFILE)
		blocked = frappe.get_doc("User", self.policy_owner).get_blocked_modules()
		for module in ("Website", "Contacts"):
			if frappe.db.exists("Module Def", module):
				self.assertIn(module, blocked)

	def test_an_administrator_is_exempt(self):
		self.assertFalse(frappe.db.get_value("User", self.system_manager, "module_profile"))
		self.assertFalse(frappe.db.get_value("User", "Administrator", "module_profile"))

	def _user(self, *roles, user_type="System User", module_profile=None):
		doc = frappe.new_doc("User")
		doc.name = doc.email = "scope-probe@example.com"
		doc.user_type = user_type
		doc.module_profile = module_profile
		for role in roles:
			doc.append("roles", {"role": role})
		return doc

	def test_the_hook_decides_by_role_and_type(self):
		cases = [
			(self._user("Policy Owner"), scope.MODULE_PROFILE),
			(self._user("Policy Owner", "System Manager"), None),
			(self._user(user_type="Website User"), None),
			(self._user("Policy Owner", module_profile="Hand Picked"), "Hand Picked"),
		]
		for doc, expected in cases:
			with self.subTest(roles=[r.role for r in doc.roles], user_type=doc.user_type):
				scope.apply_module_profile(doc)
				self.assertEqual(doc.module_profile, expected)
				if expected == scope.MODULE_PROFILE:
					# The hook runs after the framework's own copy of the profile's
					# modules, so it has to make that copy itself.
					self.assertTrue(doc.block_modules, "the profile was named but nothing was blocked")
		administrator = self._user("Policy Owner")
		administrator.name = "Administrator"
		scope.apply_module_profile(administrator)
		self.assertIsNone(administrator.module_profile)

	def test_existing_users_without_a_profile_are_given_it_and_administrators_are_not(self):
		frappe.db.set_value("User", self.policy_owner, "module_profile", None)
		frappe.db.set_value("User", self.system_manager, "module_profile", None)
		scope.apply_to_existing_users(scope.MODULE_PROFILE)
		self.assertEqual(frappe.db.get_value("User", self.policy_owner, "module_profile"), scope.MODULE_PROFILE)
		self.assertFalse(frappe.db.get_value("User", self.system_manager, "module_profile"))


class TestWebsiteRedirects(ScopeCase):
	CASES = {
		"blog": "/",
		"blog/some-post": "/",
		"contact": "/",
		"about": "/",
		"newsletters": "/",
		"search": "/",
		"list": "/",
		"third_party_apps": "/",
		"apps": "/app",
	}

	def test_every_out_of_scope_page_is_declared(self):
		hooked = {rule["source"] for rule in frappe.get_hooks("website_redirects")}
		for source in (r"/blog(/.*)?", "/contact", "/about", r"/newsletters(/.*)?", "/apps", "/search", "/list"):
			self.assertIn(source, hooked)

	def test_the_router_sends_them_home(self):
		from frappe.website.path_resolver import resolve_redirect

		for path, target in self.CASES.items():
			with self.subTest(path=path):
				frappe.cache.hdel("website_redirects", path)
				frappe.flags.redirect_location = None
				with self.assertRaises(frappe.Redirect):
					resolve_redirect(path)
				self.assertEqual(frappe.flags.redirect_location, target)
		frappe.flags.redirect_location = None

	def test_a_visitor_following_a_link_is_redirected(self):
		for path in ("blog", "contact"):
			with self.subTest(path=path):
				status, _ = render(path, "Guest")
				self.assertIn(status, (301, 302, 307, 308))
		frappe.flags.redirect_location = None

	def test_portal_pages_are_not_redirected(self):
		from frappe.website.path_resolver import resolve_redirect

		for path in ("forums", "policies", "escalations", "tasks"):
			with self.subTest(path=path):
				frappe.flags.redirect_location = None
				resolve_redirect(path)
				self.assertFalse(frappe.flags.redirect_location)
