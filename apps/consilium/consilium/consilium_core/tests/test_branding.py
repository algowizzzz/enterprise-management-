"""The portal's brand, from one record to every screen (E31-S1, E31-S2).

``branding.py`` promises that a deploying organisation changes one record and
the portal, the framework's sign-in page, the workspace and the browser tab all
follow — and that the framework's own name is never what a person sees. These
tests hold it to that, by writing the record and reading what comes out the
other end, not by inspecting the record.

The brand is cached in three places (the brand dictionary, the framework's
cached single documents, and a per-process asset fingerprint), and a rolled
back test leaves all three holding values the database no longer has. So every
test drops them on the way out; without that, one test's portal name would
become the next test's — or the next engineer's — default.
"""

from __future__ import annotations

import os
import re
import tempfile
from unittest import mock

import frappe

from consilium.consilium_core import branding
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.test_portal_pages import render
from consilium.consilium_core.tests.utils import CoreTestCase, unique

PEOPLE = PersonaPool()


def tearDownModule():
	PEOPLE.remove()


class BrandingCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		PEOPLE.attach(cls, {"colleague": ("Governance Viewer",)})

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self._drop_caches()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		self._drop_caches()
		super().tearDown()

	@staticmethod
	def _drop_caches():
		branding.clear_cache()
		branding._version_cache.clear()
		for doctype in ("Portal Branding", "Website Settings", "System Settings", "Navbar Settings"):
			frappe.clear_document_cache(doctype, doctype)

	def set_brand(self, **values):
		"""Write the record the way an administrator would: through its form."""
		doc = frappe.get_single("Portal Branding")
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc


class TestGetBrand(BrandingCase):
	def test_an_unsaved_record_gives_the_defaults(self):
		for key in ("portal_name", "primary_colour", "hero_title"):
			frappe.db.set_single_value("Portal Branding", key, None)
		self._drop_caches()
		brand = branding.get_brand()
		self.assertEqual(brand["portal_name"], branding.DEFAULTS["portal_name"])
		self.assertEqual(brand["primary_colour"], branding.DEFAULTS["primary_colour"])
		self.assertEqual(brand["logo_url"], branding.DEFAULT_LOGO)
		self.assertEqual(brand["favicon_url"], branding.DEFAULT_FAVICON)
		self.assertFalse(brand["has_custom_logo"])

	def test_saved_values_win_over_the_defaults(self):
		name = unique("Portal")
		self.set_brand(portal_name=name, primary_colour="#224466", logo="/files/brand-logo.png")
		brand = branding.get_brand()
		self.assertEqual(brand["portal_name"], name)
		self.assertEqual(brand["primary_colour"], "#224466")
		self.assertEqual(brand["logo_url"], "/files/brand-logo.png")
		self.assertTrue(brand["has_custom_logo"])

	def test_saving_the_record_clears_the_cached_brand(self):
		self.set_brand(portal_name=unique("Before"))
		branding.get_brand()
		after = unique("After")
		self.set_brand(portal_name=after)
		self.assertEqual(branding.get_brand()["portal_name"], after)

	def test_only_same_host_paths_are_used_for_images(self):
		for unsafe in (
			"https://example.com/logo.png",
			"//example.com/logo.png",
			"/files/logo'.png",
			'/files/logo".png',
			"/files/logo).png",
			"/private/files/logo.png",
			"javascript:alert(1)",
		):
			with self.subTest(value=unsafe):
				self.assertEqual(branding._safe_url(unsafe), "")
		self.assertEqual(branding._safe_url("/files/logo.png"), "/files/logo.png")
		self.assertEqual(branding._safe_url("/assets/consilium/images/x.svg"), "/assets/consilium/images/x.svg")

	def test_an_external_logo_falls_back_to_the_default(self):
		frappe.db.set_single_value("Portal Branding", "logo", "https://example.com/logo.png")
		self._drop_caches()
		self.assertEqual(branding.get_brand()["logo_url"], branding.DEFAULT_LOGO)

	def test_a_colour_that_is_not_six_hex_digits_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.set_brand(primary_colour="red")


class TestAssetUrl(BrandingCase):
	def _public(self, root):
		for folder in ("css", "js"):
			os.makedirs(os.path.join(root, "public", folder))
		path = os.path.join(root, "public", "css", "portal.css")
		with open(path, "w") as f:
			f.write("a{}")
		return path

	def test_the_url_carries_a_fingerprint(self):
		url = branding.asset_url("/assets/consilium/css/consilium.css")
		self.assertRegex(url, r"^/assets/consilium/css/consilium\.css\?v=[0-9a-f]{10}$")
		self.assertEqual(url, branding.asset_url("/assets/consilium/css/consilium.css"))

	def test_the_fingerprint_changes_when_a_file_does(self):
		with tempfile.TemporaryDirectory() as root:
			path = self._public(root)
			with mock.patch.object(branding.frappe, "get_app_path", return_value=root), \
					mock.patch.dict(frappe.conf, {"developer_mode": 1}):
				before = branding.asset_url("/x.css")
				with open(path, "w") as f:
					f.write("a{color:red}")
				os.utime(path, ns=(1, 2_000_000_000_000_000_000))
				after = branding.asset_url("/x.css")
		self.assertNotEqual(before, after)

	def test_outside_developer_mode_the_fingerprint_is_taken_once(self):
		with tempfile.TemporaryDirectory() as root:
			path = self._public(root)
			with mock.patch.object(branding.frappe, "get_app_path", return_value=root), \
					mock.patch.dict(frappe.conf, {"developer_mode": 0}):
				before = branding.asset_url("/x.css")
				os.utime(path, ns=(1, 2_000_000_000_000_000_000))
				after = branding.asset_url("/x.css")
		self.assertEqual(before, after)


class TestBrandStyle(BrandingCase):
	def test_the_primary_colour_reaches_the_tokens(self):
		self.set_brand(primary_colour="#224466", accent_colour="#aa5500")
		css = branding.brand_style()
		self.assertIn("--cns-primary-600:#224466;", css)
		self.assertIn("--cns-accent:#aa5500;", css)
		self.assertIn(':root[data-theme="dark"]', css)

	def test_a_bad_stored_colour_falls_back_to_the_default(self):
		frappe.db.set_single_value("Portal Branding", "primary_colour", "#12'}body{x")
		self._drop_caches()
		css = branding.brand_style()
		self.assertIn(f"--cns-primary-600:{branding.DEFAULTS['primary_colour']};", css)
		self.assertNotIn("body{x", css)

	def test_text_on_a_light_brand_colour_is_dark(self):
		self.set_brand(primary_colour="#f5f5f5")
		self.assertIn("--cns-on-primary:#111111;", branding.brand_style())
		self.set_brand(primary_colour="#1d3557")
		self.assertIn("--cns-on-primary:#ffffff;", branding.brand_style())

	def test_an_uploaded_typeface_is_declared_and_used(self):
		self.set_brand(font_family="House Sans", font_regular="/files/house.woff2", font_bold="/files/house-bold.ttf")
		css = branding.brand_style()
		self.assertIn('@font-face{font-family:"House Sans";src:url("/files/house.woff2") format("woff2");font-weight:400;', css)
		self.assertIn('src:url("/files/house-bold.ttf") format("truetype");font-weight:700;', css)
		self.assertIn('--cns-font-sans:"House Sans"', css)

	def test_a_typeface_from_elsewhere_is_ignored(self):
		frappe.db.set_single_value("Portal Branding", "font_family", 'Evil"}body{')
		frappe.db.set_single_value("Portal Branding", "font_regular", "https://example.com/font.woff2")
		self._drop_caches()
		css = branding.brand_style()
		self.assertNotIn("@font-face", css)
		self.assertNotIn("example.com", css)
		self.assertNotIn("--cns-font-sans", css)


class TestTheme(BrandingCase):
	"""The portal's look (theme-hybrid.css) and the workspace theme.

	The contract with Portal Branding is an order: the theme's defaults first,
	the saved brand after, so the brand wins. These tests hold the page to that
	order and each header style to its class.
	"""

	def test_the_theme_loads_after_the_portal_styles_and_before_the_brand(self):
		status, body = render("", "Administrator")
		self.assertEqual(status, 200)
		positions = [body.find(marker) for marker in
			("/css/brand.css", "/css/assistant.css", "/css/theme-hybrid.css", 'id="cns-brand"')]
		self.assertNotIn(-1, positions, "a stylesheet or the brand block is missing from the page")
		self.assertEqual(positions, sorted(positions), "the theme must come after the portal CSS and before the brand")

	def test_each_header_style_sets_its_class(self):
		for style, wanted in (("Glass", "cns-header-glass"), ("White", "cns-header-light"), ("Primary colour", None)):
			with self.subTest(style=style):
				self.set_brand(header_style=style)
				self._drop_caches()
				status, body = render("", "Administrator")
				self.assertEqual(status, 200)
				classes = re.search(r'<body class="([^"]*)"', body).group(1).split()
				for name in ("cns-header-glass", "cns-header-light"):
					if name == wanted:
						self.assertIn(name, classes)
					else:
						self.assertNotIn(name, classes)

	def test_the_default_header_is_glass_in_the_code_and_the_form(self):
		self.assertEqual(branding.DEFAULTS["header_style"], "Glass")
		field = frappe.get_meta("Portal Branding").get_field("header_style")
		self.assertEqual(field.default, "Glass")
		self.assertEqual(field.options.split("\n"), ["Glass", "Primary colour", "White"])

	def test_the_patch_moves_only_the_old_default(self):
		from consilium.patches.v0_1 import default_header_to_glass

		frappe.db.set_single_value("Portal Branding", "header_style", "Primary colour")
		default_header_to_glass.execute()
		self.assertEqual(frappe.db.get_single_value("Portal Branding", "header_style"), "Glass")
		frappe.db.set_single_value("Portal Branding", "header_style", "White")
		default_header_to_glass.execute()
		self.assertEqual(frappe.db.get_single_value("Portal Branding", "header_style"), "White")

	def test_the_workspace_is_given_the_brand_colour(self):
		self.set_brand(primary_colour="#224466")
		self._drop_caches()
		bootinfo = frappe._dict()
		branding.boot_session(bootinfo)
		self.assertEqual(bootinfo.consilium_brand["primary"], "#224466")
		self.assertEqual(bootinfo.consilium_brand["on_primary"], "#ffffff")
		self.assertEqual(bootinfo.consilium_brand["primary_dark"], branding._mix("#224466", "#ffffff", 0.5))
		self.set_brand(primary_colour="#f5f5f5")
		self._drop_caches()
		branding.boot_session(bootinfo)
		self.assertEqual(bootinfo.consilium_brand["on_primary"], "#111111")

	def test_the_workspace_theme_and_its_boot_hook_are_registered(self):
		self.assertIn("/assets/consilium/css/desk-theme.css", frappe.get_hooks("app_include_css"))
		self.assertIn("consilium.consilium_core.branding.boot_session", frappe.get_hooks("boot_session"))
		for name in ("theme-hybrid.css", "desk-theme.css"):
			self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("consilium"), "public", "css", name)))


class TestFrameworkBranding(BrandingCase):
	def test_saving_the_record_renames_the_framework_screens(self):
		name = unique("Portal")
		self.set_brand(portal_name=name, organisation_name="", logo="/files/brand-logo.png")
		website = frappe.get_single("Website Settings")
		self.assertEqual(website.app_name, name)
		self.assertEqual(website.app_logo, "/files/brand-logo.png")
		self.assertEqual(website.splash_image, "/files/brand-logo.png")
		self.assertEqual(website.favicon, branding.DEFAULT_FAVICON)
		self.assertEqual(website.footer_powered, name, "an empty footer says what the site is built on")
		self.assertEqual(frappe.db.get_single_value("System Settings", "app_name"), name)
		self.assertEqual(frappe.get_single("Navbar Settings").app_logo, "/files/brand-logo.png")

	def test_the_footer_names_the_organisation_when_there_is_one(self):
		self.set_brand(portal_name=unique("Portal"), organisation_name="Example Organisation")
		self.assertEqual(frappe.get_single("Website Settings").footer_powered, "Example Organisation")

	def test_framework_help_links_are_hidden(self):
		branding.apply_framework_branding()
		navbar = frappe.get_single("Navbar Settings")
		for row in navbar.help_dropdown:
			target = (row.route or "") + (row.action or "")
			if row.action in branding._HIDDEN_HELP_ACTIONS or any(h in target for h in branding._HIDDEN_HELP_HOSTS):
				with self.subTest(item=row.item_label):
					self.assertTrue(row.hidden, f"{row.item_label} still leads to the framework's site")
		for row in navbar.settings_dropdown:
			if row.item_label in branding._HIDDEN_SETTINGS_LABELS:
				self.assertTrue(row.hidden)

	def test_it_is_idempotent(self):
		branding.apply_framework_branding()
		first = frappe.get_single("Website Settings").as_dict()
		branding.apply_framework_branding()
		second = frappe.get_single("Website Settings").as_dict()
		for key in ("app_name", "app_logo", "favicon", "splash_image", "footer_powered"):
			self.assertEqual(first[key], second[key])

	def test_the_brand_reaches_the_portal_pages_and_the_sign_in_page(self):
		name = unique("Portal")
		self.set_brand(portal_name=name, primary_colour="#224466")
		for route, user in (("", "Administrator"), ("forums", self.colleague), ("", "Guest")):
			with self.subTest(route=route, user=user):
				status, body = render(route, user)
				self.assertEqual(status, 200)
				self.assertRegex(body, rf"<title>[^<]*{re.escape(name)}[^<]*</title>")
				self.assertIn("--cns-primary-600:#224466;", body)
		status, body = render("login", "Guest")
		self.assertEqual(status, 200)
		self.assertIn(name, body)
		visible = re.sub(r"<!--.*?-->", "", body, flags=re.S)
		self.assertNotRegex(visible, r"Login to Frappe|>\s*Frappe\s*<|frappe-framework-logo")


class TestPeople(BrandingCase):
	def test_a_visitor_may_not_ask(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			branding.people()

	def test_a_colleague_gets_display_names_only(self):
		frappe.set_user(self.colleague)
		names = branding.people()
		self.assertIn(self.colleague, names)
		self.assertEqual(names[self.colleague], "Test Person")
		self.assertNotIn("Guest", names)
		for value in names.values():
			self.assertIsInstance(value, str)

	def test_template_helpers_refuse_a_visitor(self):
		frappe.set_user("Guest")
		self.assertFalse(branding.cns_can_read("Governance Forum"))
		self.assertFalse(branding.cns_has_any_role("Guest", "System Manager"))
		frappe.set_user(self.colleague)
		self.assertTrue(branding.cns_has_any_role("Governance Viewer"))
		self.assertFalse(branding.cns_has_any_role("System Manager"))
