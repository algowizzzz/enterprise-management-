"""The guide reader (/guide) and its picture endpoint (consilium_core/guide.py).

What these hold the reader to:

* **Rendering.** A chapter becomes cleaned HTML with an anchor on every
  heading, its sections as the sidebar's contents, links between chapters
  pointed at the reader and pictures at the endpoint, lazily loaded.
* **Sanitising.** A chapter carrying script, event handlers or ``javascript:``
  links renders none of them. The files are documents, not code under review.
* **Pictures.** Only a picture a readable chapter uses is served; a path that
  climbs out of the images folder, names another file type, or follows a link
  out of the folder is refused.
* **Audience.** The administrators' chapter is missing from everyone else's
  contents, search and links, a 403 by address, and its pictures are refused.
* **Visitors.** A signed-out visitor gets the sign-in card, no chapter text and
  no pictures.
* **Search**, and the help assistant's sources pointing into the reader.

Most tests read the real guide in ``docs/guides``; the sanitising and
path tests build a small guide of their own in a temporary folder and point
the site's ``assistant_docs_path`` at it, as an installation does.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import frappe

from consilium.consilium_core import guide, navigation
from consilium.consilium_core.assistant import corpus
from consilium.consilium_core.tests.portal_personas import PersonaPool
from consilium.consilium_core.tests.test_portal_pages import PAYLOAD, render, signed_out
from consilium.consilium_core.tests.utils import CoreTestCase

ADMIN_CHAPTER = "09-administration"
PEOPLE = PersonaPool()

#: A 1x1 transparent PNG.
PNG = bytes.fromhex(
	"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
	"1f15c4890000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
)


def tearDownModule():
	PEOPLE.remove()


class GuideCase(CoreTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		PEOPLE.attach(cls, {
			"reader": ("Policy Owner",),
			"administrator": ("Consilium Administrator",),
			"nobody": (),
		})

	def setUp(self):
		super().setUp()
		if not guide.guides_dir():
			self.skipTest("docs/guides is not beside this checkout and assistant_docs_path is not set")

	def tearDown(self):
		frappe.local.request = None
		frappe.set_user("Administrator")
		super().tearDown()


class TestRendering(GuideCase):
	def test_every_chapter_renders_with_anchored_headings(self):
		for chapter in guide.catalogue():
			with self.subTest(chapter=chapter["id"]):
				page = guide.render(chapter["id"], admin=True)
				self.assertTrue(page["html"].startswith("<h1 id="), chapter["id"])
				self.assertNotIn("<script", page["html"])
				for entry in page["toc"]:
					self.assertIn(f'id="{entry["anchor"]}"', page["html"])

	def test_a_chapter_has_its_sections_links_and_pictures(self):
		page = guide.render("04-policies", admin=False)
		self.assertEqual(page["title"], "4. Policies")
		anchors = {entry["text"]: entry["anchor"] for entry in page["toc"]}
		self.assertEqual(anchors["4.1 The policy library"], "4-1-the-policy-library")
		self.assertIn({"level": 3, "text": "Details", "anchor": "details"}, page["toc"])
		html = page["html"]
		# Pictures come from the endpoint, lazily, with their size reserved.
		self.assertIn(f'src="{guide.IMAGE_ENDPOINT}?file=policies/library.png"', html)
		self.assertIn('loading="lazy"', html)
		self.assertIn('width="', html)
		self.assertNotIn('src="images/', html)
		# Links to other chapters open them in the reader, not as files.
		welcome = guide.render("00-welcome", admin=False)["html"]
		self.assertIn('href="/guide?chapter=08-your-first-day"', welcome)
		self.assertNotIn('.md"', welcome + html)

	def test_a_repeated_heading_gets_a_distinct_anchor(self):
		for chapter in guide.catalogue():
			anchors = [h["anchor"] for h in guide.render(chapter["id"], admin=True)["headings"]]
			self.assertEqual(len(anchors), len(set(anchors)), chapter["id"])

	def test_the_landing_page_lists_chapters_as_cards_not_the_table(self):
		frappe.set_user(self.reader)
		page = guide.page(None)
		self.assertEqual(page["current"], guide.INDEX)
		self.assertNotIn("<table", page["html"])
		self.assertEqual(page["next"]["id"], "00-welcome")
		self.assertIsNone(page["prev"])

	def test_previous_and_next_follow_the_readers_chapters(self):
		frappe.set_user(self.reader)
		page = guide.page("08-your-first-day")
		self.assertEqual(page["prev"]["id"], "07-help-and-ai")
		# The administrators' chapter is skipped for everyone else.
		self.assertEqual(page["next"]["id"], "10-questions-and-answers")
		frappe.set_user(self.administrator)
		self.assertEqual(guide.page("08-your-first-day")["next"]["id"], ADMIN_CHAPTER)

	def test_the_page_renders_a_chapter_for_a_signed_in_reader(self):
		status, body = render("guide", self.reader, {"chapter": "04-policies"})
		self.assertEqual(status, 200)
		self.assertIn("4.1 The policy library", body)
		self.assertIn("User guide", body)
		self.assertIn("Previous", body)
		self.assertIn("/assets/consilium/js/consilium-guide.js", body)

	def test_the_home_page_helper_lists_chapters_with_summaries(self):
		frappe.set_user(self.reader)
		chapters = guide.cns_guide_chapters()
		self.assertEqual(chapters[0]["id"], "00-welcome")
		for chapter in chapters:
			self.assertEqual(set(chapter), {"id", "number", "title", "summary", "short", "admin", "url", "icon"})
			self.assertTrue(chapter["summary"] and chapter["title"])
			self.assertTrue(chapter["url"].startswith("/guide?chapter="))
			self.assertLessEqual(len(chapter["short"]), 111)


class TestAudience(GuideCase):
	def test_the_admin_chapter_is_hidden_from_everyone_else(self):
		for user in (self.reader, self.nobody):
			with self.subTest(user=user):
				frappe.set_user(user)
				ids = [c["id"] for c in guide.cns_guide_chapters()]
				self.assertNotIn(ADMIN_CHAPTER, ids)
				self.assertIn("04-policies", ids)
		frappe.set_user(self.administrator)
		self.assertIn(ADMIN_CHAPTER, [c["id"] for c in guide.cns_guide_chapters()])

	def test_the_admin_chapter_by_address_is_refused_to_everyone_else(self):
		status, body = render("guide", self.reader, {"chapter": ADMIN_CHAPTER})
		self.assertEqual(status, 403)
		self.assertNotIn("9.5 Branding", body)
		frappe.set_user(self.reader)
		self.assertRaises(frappe.PermissionError, guide.page, ADMIN_CHAPTER)

	def test_administrators_read_the_admin_chapter_in_its_own_group(self):
		for user in (self.administrator, "Administrator"):
			with self.subTest(user=user):
				status, body = render("guide", user, {"chapter": ADMIN_CHAPTER})
				self.assertEqual(status, 200)
				self.assertIn("9.5 Branding", body)
				self.assertIn("Admin guide", body)

	def test_links_to_the_admin_chapter_are_plain_text_for_everyone_else(self):
		href = f'href="/guide?chapter={ADMIN_CHAPTER}"'
		self.assertNotIn(href, guide.render("04-policies", admin=False)["html"])
		self.assertIn(href, guide.render("04-policies", admin=True)["html"])

	def test_the_admin_chapters_pictures_are_refused_to_everyone_else(self):
		admin_only = guide.referenced_images(True) - guide.referenced_images(False)
		self.assertTrue(admin_only, "chapter 9 uses no picture of its own")
		picture = sorted(admin_only)[0]
		self.assertRaises(frappe.PermissionError, guide.resolve_image, picture, False)
		self.assertTrue(guide.resolve_image(picture, True).is_file())

	def test_the_menus_link_the_guide(self):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		def urls(user):
			frappe.set_user(user)
			frappe.local.request = Request(EnvironBuilder(path="/", base_url="http://" + frappe.local.site).get_environ())
			return {item["url"] for menu in navigation.cns_nav() for g in menu["groups"] for item in g["items"]}

		self.assertIn("/guide", urls(self.nobody))
		self.assertNotIn(f"/guide?chapter={ADMIN_CHAPTER}", urls(self.reader))
		self.assertIn(f"/guide?chapter={ADMIN_CHAPTER}", urls(self.administrator))

	def test_the_administration_page_links_the_admin_guide(self):
		status, body = render("admin", "Administrator")
		self.assertEqual(status, 200)
		self.assertIn(f'href="/guide?chapter={ADMIN_CHAPTER}"', body)


class TestVisitors(GuideCase):
	def test_a_visitor_gets_the_sign_in_card_and_no_chapter(self):
		for query in ({}, {"chapter": "04-policies"}, {"chapter": ADMIN_CHAPTER}, {"q": "minutes"}):
			with self.subTest(query=query):
				status, body = render("guide", "Guest", query)
				self.assertTrue(signed_out(status, body))
				self.assertNotIn("4.1 The policy library", body)
				self.assertNotIn("cns-guide-article", body)

	def test_a_visitor_is_given_no_chapters_and_no_pictures(self):
		frappe.set_user("Guest")
		self.assertEqual(guide.cns_guide_chapters(), [])
		for method in (guide.image, guide.get_chapters, guide.search_guide):
			self.assertNotIn(method, frappe.guest_methods)
			self.assertIn(method, frappe.whitelisted)


class TestAddressValues(GuideCase):
	def test_an_unknown_chapter_is_not_found_and_not_echoed(self):
		for value in (PAYLOAD, "../../../etc/passwd", "04-policies/../09-administration", "99-nothing"):
			with self.subTest(value=value):
				status, body = render("guide", self.reader, {"chapter": value})
				self.assertEqual(status, 404)
				self.assertNotIn("<script>cnsxss()", body)

	def test_the_search_text_is_escaped(self):
		status, body = render("guide", self.reader, {"q": PAYLOAD})
		self.assertEqual(status, 200)
		self.assertNotIn(PAYLOAD, body)
		self.assertNotIn("<script>cnsxss()", body)
		self.assertIn("&lt;script&gt;cnsxss()", body)


class TestSearch(GuideCase):
	def test_a_question_finds_the_section_that_answers_it(self):
		frappe.set_user(self.reader)
		results = guide.search("record minutes")
		self.assertTrue(results)
		self.assertIn("/guide?chapter=03-governance#3-8-meetings-and-minutes", [r["url"] for r in results])
		for result in results:
			self.assertEqual(set(result), {"chapter", "chapter_title", "section", "excerpt", "url"})

	def test_search_keeps_to_the_readers_chapters(self):
		frappe.set_user(self.reader)
		self.assertNotIn(ADMIN_CHAPTER, {r["chapter"] for r in guide.search("approval routes routing rules")})
		frappe.set_user(self.administrator)
		self.assertIn(ADMIN_CHAPTER, {r["chapter"] for r in guide.search("approval routes routing rules")})

	def test_empty_or_stopword_searches_return_nothing(self):
		frappe.set_user(self.reader)
		self.assertEqual(guide.search(""), [])
		self.assertEqual(guide.search("the and of"), [])

	def test_the_search_page_lists_results(self):
		status, body = render("guide", self.reader, {"q": "record minutes"})
		self.assertEqual(status, 200)
		self.assertIn("3.8 Meetings and minutes", body)

	def test_the_assistants_sources_point_into_the_reader(self):
		index = corpus.get_index()
		chunks = [c for c in index.chunks if c["source"] == "guide-04-policies"]
		self.assertTrue(chunks)
		html = guide.render("04-policies", admin=True)["html"]
		for chunk in chunks:
			self.assertTrue(chunk["guide_href"].startswith("/guide?chapter=04-policies"), chunk["guide_href"])
			_, _, anchor = chunk["guide_href"].partition("#")
			if anchor:
				self.assertIn(f'id="{anchor}"', html)
		library = next(c for c in chunks if c["title"].endswith("4.1 The policy library"))
		self.assertEqual(library["guide_href"], "/guide?chapter=04-policies#4-1-the-policy-library")


class TestPictures(GuideCase):
	def test_a_picture_is_served_privately_with_a_validator(self):
		frappe.set_user(self.reader)
		response = guide.image("policies/library.png")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.mimetype, "image/png")
		self.assertIn("private", response.headers["Cache-Control"])
		self.assertIn("max-age=", response.headers["Cache-Control"])
		self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
		self.assertTrue(response.headers.get("ETag"))

	def test_paths_out_of_the_images_folder_are_refused(self):
		for path in (
			"../../../../etc/passwd", "policies/../../README.md", "/etc/passwd", "policies/../../../x.png",
			"policies\\..\\..\\x.png", "..%2F..%2Fx.png", "policies/library.txt", "policies/library.png.md",
			"policies/nothing-here.png", "", None, "policies", "a/b/c.png",
		):
			with self.subTest(path=path):
				self.assertRaises(frappe.DoesNotExistError, guide.resolve_image, path, True)


class TestUntrustedGuide(GuideCase):
	"""A guide of our own, with hostile content, in a folder the site is pointed at."""

	def setUp(self):
		super().setUp()
		self.tmp = Path(tempfile.mkdtemp(prefix="cns-guide-"))
		docs = self.tmp / "docs"
		(docs / "guides" / "images" / "area").mkdir(parents=True)
		(docs / "USER-GUIDE.md").write_text("# User guide\n\nText.\n")
		(docs / "guides" / "images" / "area" / "shot.png").write_bytes(PNG)
		outside = self.tmp / "secret.png"
		outside.write_bytes(PNG)
		self.linked = True
		try:
			os.symlink(outside, docs / "guides" / "images" / "area" / "escape.png")
		except (OSError, NotImplementedError):
			self.linked = False  # no symlink privilege (a Windows workstation)
		(docs / "guides" / "00-hostile.md").write_text(
			"# 0. Hostile\n\n"
			"<script>cnsxss()</script>\n\n"
			'<img src="x" onerror="cnsxss()">\n\n'
			'<a href="javascript:cnsxss()">run</a> and [also](javascript:cnsxss())\n\n'
			'<div style="background:url(javascript:x)" onclick="cnsxss()">styled</div>\n\n'
			"<iframe src=\"https://example.com\"></iframe>\n\n"
			"## Pictures\n\n"
			"![Fine](images/area/shot.png)\n\n"
			"![Climbing](images/../../secret.png)\n\n"
			"![Linked out](images/area/escape.png)\n\n"
			"[Admin](09-admin.md) [Other docs](../USER-GUIDE.md) [Web](https://example.com/x)\n"
		)
		(docs / "guides" / "09-admin.md").write_text("# 9. Admin\n\n![Admin shot](images/area/shot.png)\n")
		self._previous = frappe.conf.get("assistant_docs_path")
		frappe.conf.assistant_docs_path = str(docs)
		corpus.clear_cache()

	def tearDown(self):
		if self._previous is None:
			frappe.conf.pop("assistant_docs_path", None)
		else:
			frappe.conf.assistant_docs_path = self._previous
		corpus.clear_cache()
		shutil.rmtree(self.tmp, ignore_errors=True)
		super().tearDown()

	def test_the_site_setting_is_where_the_guide_is_read_from(self):
		self.assertEqual(guide.guides_dir(), self.tmp / "docs" / "guides")
		self.assertEqual([c["id"] for c in guide.catalogue()], ["00-hostile", "09-admin"])

	def test_script_handlers_and_script_links_are_removed(self):
		html = guide.render("00-hostile", admin=False)["html"]
		for bad in ("<script", "onerror", "onclick", "javascript:", "<iframe", "style="):
			self.assertNotIn(bad, html.lower())
		self.assertIn('rel="noopener noreferrer"', html)  # the external link stays, safely
		self.assertIn('href="https://example.com/x"', html)
		self.assertNotIn("USER-GUIDE.md", html)
		# The admin chapter link is plain text for a non-administrator.
		self.assertNotIn("09-admin", html)

	def test_only_a_picture_inside_the_folder_is_used_or_served(self):
		html = guide.render("00-hostile", admin=False)["html"]
		self.assertIn("file=area/shot.png", html)
		self.assertNotIn("secret.png", html)
		self.assertTrue(guide.resolve_image("area/shot.png", False).is_file())
		if self.linked:
			self.assertRaises(frappe.DoesNotExistError, guide.resolve_image, "area/escape.png", False)
