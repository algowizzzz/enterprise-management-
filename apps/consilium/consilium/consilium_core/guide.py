"""The onboarding guide, read inside the platform (``/guide``).

The illustrated guide in ``docs/guides/`` was written to be printed or opened
as a file. People asked to read it where they work instead, so this module
turns it into pages: one per chapter, with its sections as a table of contents,
its pictures served by the platform, and a search across every chapter.

Where the files are. The same place the help assistant reads them from
(``corpus.docs_dir``): the repository's ``docs/`` folder in a development
checkout, or the folder the ``assistant_docs_path`` site setting names in an
installation, which the deployment kit sets. One resolution, so the assistant
and the reader can never disagree about which copy of the guide is current.

Why server-side rendering. There is no npm step and no CDN, and the vendored
libraries hold no markdown renderer. The framework already depends on
``markdown2`` (pure Python) and on ``bleach``, so the chapter is rendered once
on the server, cleaned, and cached until the file changes.

Why the output is sanitised although we wrote the files. The guides are
documents, edited by people who are not reviewing for script injection, and in
an installation they are a folder on disk anyone with file access can change.
The framework's Jinja does not autoescape, so whatever this module returns is
printed as it stands. ``bleach`` keeps a short list of tags and attributes, and
every link and picture address is then rewritten from a value this module
checked — nothing from the file is trusted to reach the page as written.

Who sees what. Chapter 9 (administration) is for administrators, the same rule
the assistant applies (``corpus.ADMIN_CHAPTERS``). Everyone else does not see it
in the contents, is refused it by address, gets no search hit from it, has
links to it shown as plain text, and cannot fetch a picture only it uses.
"""

from __future__ import annotations

import re
from pathlib import Path

import frappe

from consilium.consilium_core.assistant import corpus

ADMIN_ROLES = ("System Manager", "Consilium Administrator")

#: The landing page: README.md, with its chapter table replaced by cards.
INDEX = "index"

#: The address of the picture endpoint below. The ``file`` argument is the path
#: under ``docs/guides/images/``.
IMAGE_ENDPOINT = "/api/method/consilium.consilium_core.guide.image"

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}

#: A chapter id as the files are named: two digits, a hyphen, a lower-case slug.
_CHAPTER_ID = re.compile(r"^[0-9]{2}-[a-z0-9][a-z0-9-]{0,60}$")

#: A picture path: one folder, one file, lower-case letters, digits, hyphens and
#: underscores, and one of three extensions. No dots in the folder, no leading
#: slash, no second level, so ``..`` and absolute paths cannot be spelled at all.
#: The resolved path is still checked to sit inside the images folder.
_IMAGE_PATH = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}/[a-z0-9][a-z0-9_-]{0,80}\.(?:png|jpe?g|svg)$")

_IMAGE_REF = re.compile(r"!\[[^\]]*\]\(\s*(images/[^)\s]+)")

#: One icon per chapter, for the landing page's cards and the home page's.
ICONS = {
	0: "bi-flag",
	1: "bi-compass",
	2: "bi-inbox",
	3: "bi-diagram-3",
	4: "bi-file-earmark-text",
	5: "bi-exclamation-diamond",
	6: "bi-bar-chart",
	7: "bi-chat-square-text",
	8: "bi-calendar-check",
	9: "bi-sliders",
	10: "bi-question-circle",
	11: "bi-book",
}

#: What survives cleaning. Enough for the guides' prose, tables, lists, notes
#: and pictures; nothing that runs, loads or styles.
ALLOWED_TAGS = frozenset({
	"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "strong", "em", "b", "i",
	"code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "img", "hr", "br",
	"del", "s", "sup", "sub", "kbd",
})
ALLOWED_ATTRIBUTES = {
	"a": ["href", "title"],
	"img": ["src", "alt", "title"],
	"th": ["colspan", "rowspan"],
	"td": ["colspan", "rowspan"],
	"ol": ["start"],
}

_catalogue_cache: dict[str, tuple[tuple, list[dict]]] = {}
_render_cache: dict[tuple, dict] = {}


# ------------------------------------------------------------------ viewer


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	return bool(set(frappe.get_roles(user)).intersection(ADMIN_ROLES))


# ---------------------------------------------------------------- chapters


def guides_dir() -> Path | None:
	"""``docs/guides``, wherever the assistant finds ``docs``."""
	docs = corpus.docs_dir()
	if not docs:
		return None
	folder = docs / corpus.GUIDES
	return folder if folder.is_dir() else None


def _stat(path: Path) -> tuple:
	try:
		st = path.stat()
		return (path.name, st.st_mtime_ns, st.st_size)
	except OSError:
		return (path.name, None)


def _heading(text: str) -> str | None:
	in_code = False
	for line in text.splitlines():
		if line.startswith("```"):
			in_code = not in_code
		elif not in_code and line.startswith("# "):
			return corpus.plain(line[2:]).strip()
	return None


def _first_paragraph(text: str) -> str:
	para: list[str] = []
	for line in text.splitlines():
		stripped = line.strip()
		if stripped.startswith(("#", "|", "!", ">", "-", "```")) or not stripped:
			if para:
				break
			continue
		para.append(stripped)
	return corpus.plain(" ".join(para))


def _readme_summaries(readme: Path) -> dict[str, str]:
	"""``{"04-policies.md": "The policy library, ..."}`` from the README's table."""
	out: dict[str, str] = {}
	if not readme.is_file():
		return out
	for line in readme.read_text(encoding="utf-8").splitlines():
		match = re.match(r"^\|\s*\[[^\]]+\]\(([0-9]{2}-[a-z0-9-]+\.md)\)\s*\|(.+)\|\s*$", line)
		if match:
			out[match.group(1)] = corpus.plain(match.group(2)).strip()
	return out


def _shorten(text: str, limit: int = 110) -> str:
	if len(text) <= limit:
		return text
	return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def catalogue() -> list[dict]:
	"""Every chapter, in order, whoever is asking. Cached until a file changes."""
	folder = guides_dir()
	if not folder:
		return []
	files = [p for p in sorted(folder.glob("[0-9][0-9]-*.md")) if _CHAPTER_ID.match(p.stem)]
	key = str(folder)
	fingerprint = (key, _stat(folder / "README.md"), *(_stat(p) for p in files))
	cached = _catalogue_cache.get(key)
	if cached and cached[0] == fingerprint:
		return cached[1]
	summaries = _readme_summaries(folder / "README.md")
	chapters = []
	for path in files:
		text = path.read_text(encoding="utf-8")
		number = int(path.stem[:2])
		summary = summaries.get(path.name) or _first_paragraph(text)
		chapters.append({
			"id": path.stem,
			"number": number,
			"title": _heading(text) or path.stem,
			"summary": summary,
			"short": _shorten(summary),
			"admin": path.name.startswith(corpus.ADMIN_CHAPTERS),
			"url": chapter_url(path.stem),
			"icon": ICONS.get(number, "bi-journal-text"),
			"images": frozenset(ref[len("images/"):] for ref in _IMAGE_REF.findall(text)),
			"path": path,
		})
	_catalogue_cache[key] = (fingerprint, chapters)
	return chapters


def visible_chapters(user: str | None = None) -> list[dict]:
	admin = is_admin(user)
	return [c for c in catalogue() if admin or not c["admin"]]


def find_chapter(chapter_id: str | None) -> dict | None:
	"""The chapter with exactly this id, or None. The only way an address value
	becomes a chapter: it is compared against the real list, never used as a
	path."""
	if not isinstance(chapter_id, str) or not _CHAPTER_ID.match(chapter_id):
		return None
	return next((c for c in catalogue() if c["id"] == chapter_id), None)


def chapter_url(chapter_id: str, anchor: str | None = None) -> str:
	url = "/guide" if chapter_id == INDEX else f"/guide?chapter={chapter_id}"
	return f"{url}#{anchor}" if anchor else url


def admin_guide_url() -> str:
	"""The administrators' chapter's address, wherever the guide numbers it
	(the Admin menu and the administration page link to it)."""
	try:
		return next((c["url"] for c in catalogue() if c["admin"]), "/guide")
	except Exception:
		return "/guide"


def public(chapter: dict) -> dict:
	"""A chapter without the server-side details (its path, its pictures)."""
	return {k: chapter[k] for k in ("id", "number", "title", "summary", "short", "admin", "url", "icon")}


# --------------------------------------------------------------- rendering


def _png_size(path: Path) -> tuple[int, int] | None:
	"""Width and height from a PNG's header, so the page reserves the space and
	does not jump as lazily loaded pictures arrive."""
	try:
		with path.open("rb") as fh:
			head = fh.read(24)
	except OSError:
		return None
	if len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
		return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
	return None


def _strip_chapter_table(text: str) -> str:
	"""The README without its table of chapters: the landing page draws the
	chapters as cards, filtered to the viewer."""
	return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))


def _markdown(text: str) -> str:
	import bleach
	import markdown2

	html = markdown2.markdown(text, extras={"tables": None, "fenced-code-blocks": None, "strike": None,
		"cuddled-lists": None})
	return bleach.clean(str(html), tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
		protocols=["http", "https", "mailto"], strip=True, strip_comments=True)


def _link_target(href: str, chapters: dict[str, dict], admin: bool) -> tuple[str | None, bool]:
	"""Where a link in a chapter should go: ``(address, external)``, or
	``(None, False)`` when the link should become plain text.

	Links between chapters (``04-policies.md#section``) become reader addresses;
	anything else relative (another folder of the documentation, a file on disk)
	has no address in the platform and is dropped.
	"""
	href = (href or "").strip()
	if href.startswith(("http://", "https://", "mailto:")):
		return href, True
	target, _, fragment = href.partition("#")
	anchor = corpus.slug(fragment) or None
	if not target:
		return (f"#{anchor}" if anchor else None), False
	name = target.rsplit("/", 1)[-1] if target.startswith("./") else target
	if name == "README.md":
		return chapter_url(INDEX, anchor), False
	if name.endswith(".md"):
		chapter = chapters.get(name[:-3])
		if chapter and (admin or not chapter["admin"]):
			return chapter_url(chapter["id"], anchor), False
	return None, False


def _image_src(src: str) -> str | None:
	rel = (src or "").strip()
	if rel.startswith("./"):
		rel = rel[2:]
	if not rel.startswith("images/"):
		return None
	rel = rel[len("images/"):]
	return rel if _IMAGE_PATH.match(rel) else None


def _inside(images: Path, rel: str) -> Path | None:
	"""The picture's file if it really is inside the images folder: resolved,
	so a link inside the folder that points out of it is not followed."""
	base = images.resolve()
	path = (base / rel).resolve()
	if path.is_relative_to(base) and path.is_file() and path.suffix.lower() in IMAGE_TYPES:
		return path
	return None


def render(chapter_id: str, admin: bool) -> dict | None:
	"""A chapter as sanitised HTML with its contents.

	Returns ``{"title", "html", "toc", "headings"}``: ``toc`` is the chapter's
	sections (level 2 and 3) for the sidebar, ``headings`` every heading down to
	level 4 with its anchor, for the assistant's source links. Cached per chapter,
	per audience (a link to the administrators' chapter is plain text for
	everyone else) and per file version.
	"""
	folder = guides_dir()
	if not folder:
		return None
	chapters = {c["id"]: c for c in catalogue()}
	if chapter_id == INDEX:
		path = folder / "README.md"
		if not path.is_file():
			return None
	else:
		chapter = chapters.get(chapter_id)
		if not chapter:
			return None
		path = chapter["path"]
	key = (str(path), chapter_id, bool(admin), _stat(path), tuple(sorted(chapters)))
	if key in _render_cache:
		return _render_cache[key]

	from bs4 import BeautifulSoup

	text = path.read_text(encoding="utf-8")
	if chapter_id == INDEX:
		text = _strip_chapter_table(text)
	soup = BeautifulSoup(_markdown(text), "html.parser")
	images = folder / "images"

	title = None
	toc: list[dict] = []
	headings: list[dict] = []
	used: set[str] = set()
	for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
		label = " ".join(tag.get_text(" ", strip=True).split())
		base = corpus.slug(label) or "section"
		anchor, n = base, 2
		while anchor in used:
			anchor, n = f"{base}-{n}", n + 1
		used.add(anchor)
		level = int(tag.name[1])
		tag["id"] = anchor
		headings.append({"level": level, "text": label, "base": base, "anchor": anchor})
		if level == 1 and title is None:
			title = label
		if level in (2, 3):
			toc.append({"level": level, "text": label, "anchor": anchor})
			mark = soup.new_tag("a", href=f"#{anchor}")
			mark["class"] = "cns-guide-anchor"
			mark["aria-label"] = f"Link to this section: {label}"
			mark.string = "#"
			tag.append(" ")
			tag.append(mark)

	for link in soup.find_all("a"):
		if "cns-guide-anchor" in (link.get("class") or []):
			continue
		href, external = _link_target(link.get("href", ""), chapters, admin)
		if not href:
			link.unwrap()
			continue
		link.attrs = {"href": href}
		if external:
			link["rel"] = "noopener noreferrer"
			link["target"] = "_blank"

	for img in soup.find_all("img"):
		rel = _image_src(img.get("src", ""))
		alt = img.get("alt", "")
		file = _inside(images, rel) if rel else None
		if not file:
			img.replace_with(soup.new_string(alt))
			continue
		src = f"{IMAGE_ENDPOINT}?file={rel}"
		img.attrs = {"src": src, "alt": alt, "loading": "lazy", "decoding": "async"}
		size = _png_size(file) if file.suffix.lower() == ".png" else None
		if size:
			img["width"], img["height"] = str(size[0]), str(size[1])
		zoom = soup.new_tag("a", href=src, target="_blank", rel="noopener")
		zoom["class"] = "cns-guide-zoom"
		zoom["title"] = "Open the picture full size"
		img.wrap(zoom)
		parent = zoom.parent
		# A picture on its own line is a figure, captioned with its description.
		if parent is not None and parent.name == "p" and len(
				[c for c in parent.contents if not (isinstance(c, str) and not c.strip())]) == 1:
			parent.name = "figure"
			parent["class"] = "cns-guide-figure"
			if alt:
				caption = soup.new_tag("figcaption")
				caption.string = alt
				parent.append(caption)

	for table in soup.find_all("table"):
		wrap = soup.new_tag("div")
		wrap["class"] = "cns-guide-table"
		table.wrap(wrap)
	for note in soup.find_all("blockquote"):
		note["class"] = "cns-guide-note"

	result = {"title": title or chapter_id, "html": str(soup), "toc": toc, "headings": headings}
	if len(_render_cache) > 128:
		_render_cache.clear()
	_render_cache[key] = result
	return result


def annotate_chunks(chapter_id: str, chunks: list[dict]) -> None:
	"""Give the assistant's sections of a chapter their place in the reader.

	The assistant splits a chapter at its headings, in order; the reader gives
	each heading an anchor, in the same order, suffixing repeats (a second
	"Details" becomes ``details-2``). Walking both lists together pairs each
	section with the anchor the reader actually printed, so a source link lands
	on the section it quoted.
	"""
	rendered = render(chapter_id, admin=True)
	headings = rendered["headings"] if rendered else []
	pos = 0
	for chunk in chunks:
		wanted = corpus.slug(corpus.plain(chunk["title"].split(" › ")[-1]))
		anchor = None
		for i in range(pos, len(headings)):
			if headings[i]["base"] == wanted:
				anchor = headings[i]["anchor"] if headings[i]["level"] > 1 else None
				pos = i + 1
				break
		chunk["chapter"] = chapter_id
		chunk["guide_href"] = chapter_url(chapter_id, anchor)


# ------------------------------------------------------------------ search


def search(query: str | None, user: str | None = None, limit: int = 20) -> list[dict]:
	"""Sections of the chapters the viewer may read, best match first.

	The assistant's index already holds every chapter split at its headings
	and ranks them with BM25; this asks it for chapter sections only, filtered
	to the viewer's chapters.
	"""
	query = (query or "").strip()[:100]
	wanted = corpus.tokens(query)
	if not wanted:
		return []
	visible = {c["id"]: c for c in visible_chapters(user)}
	if not visible:
		return []
	index = corpus.get_index()
	ranked = index.search(query, allow=lambda chunk: chunk.get("chapter") in visible, limit=limit)
	# A long tail of sections that share one common word with the question is
	# noise; keep those within reach of the best match.
	top = ranked[0][0] if ranked else 0
	out = []
	for score, chunk in ranked:
		if score < top * 0.3:
			break
		chapter = visible[chunk["chapter"]]
		out.append({
			"chapter": chapter["id"],
			"chapter_title": chapter["title"],
			"section": chunk["title"].split(" › ")[-1],
			"excerpt": corpus.excerpt(chunk["text"], wanted, limit=220),
			"url": chunk.get("guide_href") or chapter["url"],
		})
	return out


# ----------------------------------------------------------------- pictures


def referenced_images(admin: bool) -> set[str]:
	"""The pictures the viewer's chapters use: the only ones served."""
	return {img for c in catalogue() if admin or not c["admin"] for img in c["images"]}


def resolve_image(rel: str | None, admin: bool) -> Path:
	"""The file for a picture path, or an exception.

	Refused unless the path is spelled the way the guide spells pictures, is
	used by a chapter the viewer may read, has a picture extension, and resolves
	to a file inside the images folder.
	"""
	if not isinstance(rel, str) or not _IMAGE_PATH.match(rel):
		raise frappe.DoesNotExistError("No such picture in the guide.")
	folder = guides_dir()
	if not folder:
		raise frappe.DoesNotExistError("The guide is not installed on this server.")
	if rel not in referenced_images(admin):
		if rel in referenced_images(True):
			raise frappe.PermissionError("This picture belongs to the administrators' chapter.")
		raise frappe.DoesNotExistError("No such picture in the guide.")
	path = _inside(folder / "images", rel)
	if not path:
		raise frappe.DoesNotExistError("No such picture in the guide.")
	return path


@frappe.whitelist(methods=["GET"])
def image(file: str | None = None):
	"""A picture from the guide, for signed-in people.

	Served privately (it is behind sign-in) with a day's cache and a validator,
	so a chapter's pictures load once per day, not once per page. A picture is
	never rendered as a document: ``nosniff`` stops a browser guessing a type,
	and an SVG opened on its own runs in a sandbox with no script.
	"""
	from werkzeug.wrappers import Response

	path = resolve_image(file, is_admin())
	stat = path.stat()
	response = Response(path.read_bytes(), mimetype=IMAGE_TYPES[path.suffix.lower()])
	response.headers["Cache-Control"] = "private, max-age=86400"
	response.headers["X-Content-Type-Options"] = "nosniff"
	response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
	response.set_etag(f"{stat.st_mtime_ns:x}-{stat.st_size:x}")
	response.last_modified = int(stat.st_mtime)
	request = getattr(frappe.local, "request", None)
	if request is not None:
		response.make_conditional(request)
	return response


# ------------------------------------------------------------- page, API


def page(chapter_id: str | None, query: str | None = None) -> dict:
	"""Everything the ``/guide`` page draws, for the signed-in viewer.

	Raises ``PageDoesNotExistError`` for a chapter that is not in the guide and
	``PermissionError`` for the administrators' chapter asked for by someone
	else — the framework turns those into its 404 and 403 pages.
	"""
	admin = is_admin()
	chapters = visible_chapters()
	query = (query or "").strip()[:100]
	out = {
		"available": guides_dir() is not None and bool(chapters),
		"user_chapters": [public(c) for c in chapters if not c["admin"]],
		"admin_chapters": [public(c) for c in chapters if c["admin"]],
		"current": INDEX,
		"current_admin": False,
		"title": "Guide",
		"html": "",
		"toc": [],
		"prev": None,
		"next": None,
		"query": query,
		"results": None,
	}
	if chapter_id:
		chapter = find_chapter(chapter_id)
		if not chapter:
			raise frappe.PageDoesNotExistError("That chapter is not in the guide.")
		if chapter["admin"] and not admin:
			raise frappe.PermissionError(
				"This chapter is for administrators. The rest of the guide is open to you."
			)
		out["current"] = chapter["id"]
		out["current_admin"] = chapter["admin"]
	if not out["available"]:
		return out
	if query:
		out["results"] = search(query)
		out["title"] = "Search the guide"
		return out
	rendered = render(out["current"], admin)
	if rendered:
		out.update(title=rendered["title"], html=rendered["html"], toc=rendered["toc"])
	order = [INDEX] + [c["id"] for c in chapters]
	by_id = {c["id"]: public(c) for c in chapters}
	by_id[INDEX] = {"id": INDEX, "title": "About this guide", "url": chapter_url(INDEX)}
	at = order.index(out["current"])
	out["prev"] = by_id[order[at - 1]] if at > 0 else None
	out["next"] = by_id[order[at + 1]] if at + 1 < len(order) else None
	return out


def cns_guide_chapters() -> list[dict]:
	"""The chapters the viewer may read, for templates (the home page's guide
	cards): ``id``, ``number``, ``title``, ``summary`` (the README's line),
	``short`` (the same, cut to about 110 characters), ``admin``, ``url`` and
	``icon`` (a Bootstrap Icons class). Empty for a signed-out visitor or when
	the guide is not installed; never raises, so a page using it always draws."""
	if frappe.session.user == "Guest":
		return []
	try:
		return [public(c) for c in visible_chapters()]
	except Exception:
		frappe.log_error(title="Guide chapters could not be listed")
		return []


@frappe.whitelist(methods=["GET"])
def get_chapters() -> list[dict]:
	"""The chapters the caller may read (see ``cns_guide_chapters``)."""
	return [public(c) for c in visible_chapters()]


@frappe.whitelist(methods=["GET"])
def search_guide(q: str | None = None) -> list[dict]:
	"""Sections matching ``q`` in the chapters the caller may read."""
	return search(q)
