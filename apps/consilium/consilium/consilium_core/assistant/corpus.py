"""The assistant's knowledge: the guides, the glossary and the page map, ranked
by a small BM25 index written in plain Python.

Why no model and no library. The platform must run with no internet access and
nothing that needs a compiler, so the built-in assistant cannot lean on an
embedding service or a numerical package. It does not need to: the corpus is a
few hundred short sections written by the people who built the system, the
questions use the same vocabulary, and BM25 over that is fast (well under a
millisecond per question) and predictable — the same question always gets the
same sections, which matters when an answer is audited.

Sources, and who may see each:

* ``docs/USER-GUIDE.md`` — everyone signed in.
* ``docs/ADMIN-GUIDE.md`` — administrators only. It describes configuration and
  operations that an ordinary user can do nothing with, and some of it is
  better not spelled out to everyone (how impersonation works, for example).
* ``docs/guides/NN-*.md`` — the illustrated onboarding guide, the
  screen-by-screen walkthroughs. Everyone, except chapter 9 (administration),
  which is for administrators.
* ``docs/product/05-glossary.md`` — everyone; each table row is also a glossary
  entry for "what does X mean".
* Published ``Guide Article`` records — the governance office's own guidance.
* Published, enterprise-scope ``Glossary Term`` records. Terms scoped to one
  document are left out: that document may be confidential, and the assistant
  cannot tell the asker's standing towards it from here.
* The page map in ``pages.py``.

The index is built on first use and cached in the process, keyed by site. It
is rebuilt when the fingerprint changes: each file's modification time and
size, and the count and latest modification of each record source. Checking the
fingerprint costs two small queries per question.

**Where the documents are.** In a development checkout the ``docs/`` folder sits
at the repository root, above the app. An installation from a wheel does not
carry it; point ``assistant_docs_path`` in the site configuration at a copy of
the folder. Without either, the assistant still answers from the page map, the
glossary records and the guide articles, and says nothing it cannot back up.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from pathlib import Path

import frappe

from consilium.consilium_core.assistant import pages as page_map

USER_GUIDE = "USER-GUIDE.md"
ADMIN_GUIDE = "ADMIN-GUIDE.md"
GLOSSARY = os.path.join("product", "05-glossary.md")
GUIDES = "guides"
#: Onboarding-guide chapters only administrators can act on: chapter 9,
#: "Administration without code" (docs/guides/09-administration.md). Every other
#: chapter, including the glossary (11-) and questions and answers (10-), is for
#: everyone.
ADMIN_CHAPTERS = ("09-",)

#: BM25's two constants, at their customary values. k1 limits how much a word
#: repeated in one section counts; b how much a long section is discounted.
K1 = 1.4
B = 0.75

STOPWORDS = frozenset(
	"""a an and are as at be been but by can could did do does doing done for from get got had has
	have how i if in into is it its just me my no not of on once or our out over own so some such
	than that the their them then there these they this those through to too under up very was we
	were what when where which while who whom why will with would you your yours here there please
	want need able one ones see seen show look find also still""".split()
)

_WORD = re.compile(r"[a-z0-9]+")
_CACHE: dict[str, tuple[tuple, "Index"]] = {}


# --------------------------------------------------------------------- text


def stem(word: str) -> str:
	"""A deliberately crude suffix-stripper.

	It only has to map a question's words and a section's words onto the same
	form ("reviews", "reviewing", "reviewed" → "review"); it is applied to both
	sides, so a stem that is not a real word does no harm.
	"""
	if len(word) > 4 and word.endswith("ies"):
		return word[:-3] + "y"
	if len(word) > 5 and word.endswith("ing"):
		return word[:-3]
	if len(word) > 4 and word.endswith("ed"):
		return word[:-2]
	if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
		return word[:-1]
	return word


def tokens(text: str) -> list[str]:
	# Single letters are the debris of contractions ("can't" → "can", "t").
	return [stem(w) for w in _WORD.findall((text or "").lower()) if len(w) > 1 and w not in STOPWORDS]


def plain(markdown: str) -> str:
	"""Markdown to readable plain text: no emphasis marks, no table pipes."""
	text = markdown or ""
	text = re.sub(r"`([^`]*)`", r"\1", text)
	text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
	text = re.sub(r"\*([^*\s][^*]*)\*", r"\1", text)
	text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
	lines = []
	for line in text.splitlines():
		stripped = line.strip()
		if re.fullmatch(r"\|?[\s:|-]+\|?", stripped) and "-" in stripped:
			continue  # a table's separator row
		if stripped.startswith("|"):
			cells = [c.strip() for c in stripped.strip("|").split("|")]
			stripped = " — ".join(c for c in cells if c)
		lines.append(stripped)
	return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def excerpt(text: str, query_tokens: list[str], limit: int = 320) -> str:
	"""The line or two of a section that best matches the question."""
	lines = [ln.strip(" -•\t") for ln in plain(text).splitlines() if ln.strip() and not ln.startswith("```")]
	if not lines:
		return ""
	wanted = set(query_tokens)
	best = max(range(len(lines)), key=lambda i: (len(wanted & set(tokens(lines[i]))), -i))
	out = lines[best]
	nxt = best + 1
	while len(out) < limit * 0.6 and nxt < len(lines):
		out = out + " " + lines[nxt]
		nxt += 1
	if len(out) > limit:
		out = out[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
	return out


def html_to_text(html: str) -> str:
	"""Text from a rich-text field. Block tags become line breaks and cells
	spaces, so a table's cells do not run together into one word."""
	import html as htmllib  # noqa: PLC0415

	text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/tr|/h[1-6])\s*/?>", "\n", html or "")
	text = re.sub(r"(?i)<\s*/?(td|th)[^>]*>", " ", text)
	text = re.sub(r"<[^>]+>", "", text)
	text = htmllib.unescape(text)
	return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def slug(text: str) -> str:
	return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


# ------------------------------------------------------------------ sources


def docs_dir() -> Path | None:
	"""Where the guides are: the site's override, else the repository checkout."""
	override = frappe.conf.get("assistant_docs_path")
	if override and Path(override, USER_GUIDE).exists():
		return Path(override)
	here = Path(__file__).resolve()
	for parent in list(here.parents)[:7]:
		candidate = parent / "docs"
		if (candidate / USER_GUIDE).exists():
			return candidate
	return None


#: Where a user-guide section applies in the portal, by a word in its heading.
#: Order matters: the first match wins.
_SECTION_ROUTES = (
	("governance office", "/formation-requests"),
	("my work", "/tasks"),
	("insight", "/reports"),
	("forum", "/forums"),
	("polic", "/policies"),
	("escalation", "/escalations"),
	("report", "/reports"),
	("home", "/"),
	("help assistant", None),
)


def _route_for_heading(heading: str, default: str | None) -> str | None:
	lowered = heading.lower()
	for word, route in _SECTION_ROUTES:
		if word in lowered:
			return route
	return default


def chunk_markdown(text: str, *, source: str, label: str, audience: str,
                   default_route: str | None) -> list[dict]:
	"""Split a guide at its headings. A section carries its parent's heading,
	so "4. Policies › The lifecycle" is found by a question about policies."""
	chunks = []
	path: list[str] = []
	route_stack: list[str | None] = []
	body: list[str] = []
	heading = None

	def flush():
		if heading is None:
			return
		content = "\n".join(body).strip()
		if not content:
			return
		title = " › ".join(path)
		chunks.append({
			"id": f"{source}:{slug(title)}",
			"source": source,
			"label": label,
			"title": title,
			"text": content,
			"audience": audience,
			"href": route_stack[-1] if route_stack else default_route,
			"kind": "guide",
		})

	in_code = False
	for line in text.splitlines():
		if line.startswith("```"):
			in_code = not in_code
		match = None if in_code else re.match(r"^(#{1,4})\s+(.*)$", line)
		if match:
			flush()
			level = len(match.group(1))
			heading = match.group(2).strip()
			depth = max(level - 1, 1)
			path = path[: depth - 1] + [heading]
			route_stack = route_stack[: depth - 1]
			parent_route = route_stack[-1] if route_stack else default_route
			route_stack.append(_route_for_heading(heading, parent_route) if audience == "all" else default_route)
			body = []
		else:
			body.append(line)
	flush()
	return chunks


def glossary_entries(text: str) -> list[dict]:
	"""Each bold first cell of a table row in the glossary is a term."""
	entries = []
	section = ""
	for line in text.splitlines():
		if line.startswith("#"):
			section = line.lstrip("#").strip()
			continue
		# "| **Standard** (governing document type) | ... |": the bold part is
		# the term, anything after it in the cell qualifies it.
		match = re.match(r"^\|\s*\*\*(.+?)\*\*([^|]*)\|(.+)\|\s*$", line)
		if not match:
			continue
		term = match.group(1).strip()
		qualifier = match.group(2).strip()
		if qualifier:
			term = f"{term} {qualifier}"
		cells = [c.strip() for c in match.group(3).split("|")]
		definition = plain(cells[0])
		note = plain(" ".join(c for c in cells[1:] if c))
		if note:
			definition = f"{definition} ({note})" if definition else note
		entries.append({"term": term, "definition": definition, "section": section, "source": "Glossary"})
	return entries


def guide_anchor(article: str) -> str:
	"""The element id a guide article is rendered under on the home page.

	The home page's script builds the same id from the article's name; both
	sides keep to letters, digits and hyphens so the fragment needs no escaping.
	"""
	return "guide-" + re.sub(r"[^a-z0-9-]+", "-", (article or "").lower()).strip("-")


def _record_sources() -> tuple[list[dict], list[dict]]:
	"""Published guide articles and enterprise glossary terms, as chunks and entries."""
	chunks, entries = [], []
	if frappe.db.table_exists("Guide Article"):
		for row in frappe.get_all(
			"Guide Article",
			filters={"is_published": 1},
			fields=["name", "title", "category", "body", "applies_to_module"],
			order_by="display_order asc, name asc",
		):
			chunks.append({
				"id": f"guide-article:{row.name}",
				"source": "guide-article",
				"label": "Home-page guide",
				"title": row.title,
				"text": html_to_text(row.body),
				"audience": "all",
				# The article's own place on the home page, not the page's top.
				# The home page used to show an article only when its category
				# had a slot there, so the assistant cited "The policy lifecycle"
				# and linked to a page it never appeared on. Every published
				# article now renders there under this anchor (see index.html).
				"href": f"/#{guide_anchor(row.name)}",
				"kind": "guide",
				"extra": f"{row.category} {row.applies_to_module}",
			})
	if frappe.db.table_exists("Glossary Term"):
		for row in frappe.get_all(
			"Glossary Term",
			filters={"term_status": "Published", "scope_level": "Enterprise"},
			fields=["name", "term", "definition"],
		):
			entries.append({
				"term": row.term,
				"definition": html_to_text(row.definition),
				"section": "Glossary term",
				"source": "Glossary Term",
			})
	return chunks, entries


def _page_chunks() -> list[dict]:
	chunks = []
	for route, page in page_map.PAGES.items():
		tasks = page.get("tasks", [])
		text = page["purpose"] + "\n" + "\n".join(
			f"{t['label']}: {' '.join(t['steps'])}" for t in tasks
		)
		chunks.append({
			"id": f"page:{route}",
			"source": "page",
			"label": "Portal page",
			"title": page["title"],
			"text": text,
			"audience": "admin" if page.get("admin_only") else "all",
			"href": route,
			"kind": "page",
			"extra": " ".join(t["keywords"] for t in tasks),
		})
	return chunks


# -------------------------------------------------------------------- index


class Index:
	"""BM25 over a list of chunks. Heading words count three times over body
	words: a section titled "Raising an escalation" is about raising one."""

	def __init__(self, chunks: list[dict], glossary: list[dict]):
		self.chunks = chunks
		self.glossary = glossary
		self.freqs: list[Counter] = []
		self.lengths: list[int] = []
		self.postings: dict[str, list[int]] = {}
		for i, chunk in enumerate(chunks):
			terms = tokens(chunk["text"]) + tokens(chunk["title"]) * 3 + tokens(chunk.get("extra", "")) * 2
			counts = Counter(terms)
			self.freqs.append(counts)
			self.lengths.append(len(terms) or 1)
			for term in counts:
				self.postings.setdefault(term, []).append(i)
		self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
		total = len(chunks)
		self.idf = {
			term: math.log(1 + (total - len(docs) + 0.5) / (len(docs) + 0.5))
			for term, docs in self.postings.items()
		}

	def search(self, query: str, *, allow=lambda chunk: True, boost=None, limit: int = 5) -> list[tuple[float, dict]]:
		terms = tokens(query)
		scores: dict[int, float] = {}
		for term in set(terms):
			idf = self.idf.get(term)
			if not idf:
				continue
			for i in self.postings[term]:
				tf = self.freqs[i][term]
				norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lengths[i] / self.avg_length))
				scores[i] = scores.get(i, 0.0) + idf * norm
		ranked = []
		for i, score in scores.items():
			chunk = self.chunks[i]
			if not allow(chunk):
				continue
			if boost:
				score *= boost(chunk)
			ranked.append((score, chunk))
		ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
		return ranked[:limit]


def _fingerprint(directory: Path | None) -> tuple:
	parts: list = [str(directory)]
	if directory:
		for name in (USER_GUIDE, ADMIN_GUIDE, GLOSSARY, *_guide_chapters(directory)):
			path = directory / name
			try:
				stat = path.stat()
				parts.append((name, stat.st_mtime_ns, stat.st_size))
			except OSError:
				parts.append((name, None))
	for doctype in ("Guide Article", "Glossary Term"):
		if frappe.db.table_exists(doctype):
			row = frappe.get_all(doctype, fields=["count(name) as n", "max(modified) as m"], order_by="")[0]
			parts.append((doctype, row.n, str(row.m)))
	return tuple(parts)


def _guide_chapters(directory: Path) -> list[str]:
	"""The numbered chapters of the illustrated guides, in order."""
	folder = directory / GUIDES
	if not folder.is_dir():
		return []
	return [os.path.join(GUIDES, p.name) for p in sorted(folder.glob("[0-9][0-9]-*.md"))]


def build(directory: Path | None) -> Index:
	chunks: list[dict] = []
	glossary: list[dict] = []
	if directory:
		sources = (
			(USER_GUIDE, "user-guide", "User guide", "all", None),
			(ADMIN_GUIDE, "admin-guide", "Administrator guide", "admin", "/admin"),
			(GLOSSARY, "glossary", "Glossary", "all", None),
		)
		for name, source, label, audience, route in sources:
			path = directory / name
			if not path.exists():
				continue
			text = path.read_text(encoding="utf-8")
			if source == "glossary":
				glossary.extend(glossary_entries(text))
				# The glossary's tables are long runs of unrelated terms; as
				# sections they would match almost anything. Its terms are
				# served by the definition lookup instead.
				continue
			chunks.extend(chunk_markdown(text, source=source, label=label, audience=audience,
			                             default_route=route))
		for name in _guide_chapters(directory):
			admin = Path(name).name.startswith(ADMIN_CHAPTERS)
			# Pictures are for readers; their alt text and paths would only
			# add noise words to the index.
			text = "\n".join(line for line in (directory / name).read_text(encoding="utf-8").splitlines()
			                 if not line.lstrip().startswith("!["))
			chapter_chunks = chunk_markdown(
				text, source=f"guide-{Path(name).stem}", label="Illustrated guide",
				audience="admin" if admin else "all", default_route="/admin" if admin else None,
			)
			# Each section's place in the in-platform reader (/guide?chapter=…#…):
			# the assistant cites it there rather than as a file nobody can open.
			# ``href`` stays the portal page the section is about, which ranks it.
			try:
				from consilium.consilium_core import guide  # noqa: PLC0415

				guide.annotate_chunks(Path(name).stem, chapter_chunks)
			except Exception:
				frappe.log_error(title="Guide anchors could not be worked out")
			chunks.extend(chapter_chunks)
	record_chunks, record_entries = _record_sources()
	chunks.extend(record_chunks)
	chunks.extend(_page_chunks())
	# Record terms first: a term the policy office has published overrides the
	# design glossary's wording of the same term.
	return Index(chunks, record_entries + glossary)


def get_index() -> Index:
	directory = docs_dir()
	key = frappe.local.site or ""
	fingerprint = _fingerprint(directory)
	cached = _CACHE.get(key)
	if cached and cached[0] == fingerprint:
		return cached[1]
	index = build(directory)
	_CACHE[key] = (fingerprint, index)
	return index


def clear_cache() -> None:
	_CACHE.clear()


# ----------------------------------------------------------------- glossary


def _norm_term(text: str) -> str:
	text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
	words = [w for w in text.split() if w not in ("a", "an", "the")]
	return " ".join(stem(w) for w in words)


def define(index: Index, phrase: str) -> dict | None:
	"""The glossary entry for a phrase: exact first, then one naming it."""
	wanted = _norm_term(phrase)
	if not wanted:
		return None
	for entry in index.glossary:
		# "Standard (governing document type)" is the term "Standard";
		# "Exemption / deviation" is two names for one term.
		bare = re.sub(r"\s*\([^)]*\)", "", entry["term"])
		names = [bare] + [part.strip() for part in re.split(r"\s*/\s*|\s*,\s*", bare)]
		if wanted == _norm_term(entry["term"]) or any(wanted == _norm_term(n) for n in names):
			return entry
	# "the lifecycle gate" → "Document Lifecycle Gate": the phrase inside a
	# longer term, only when the phrase is specific enough to mean something.
	if len(wanted) >= 5:
		for entry in index.glossary:
			if re.search(rf"\b{re.escape(wanted)}\b", _norm_term(entry["term"])):
				return entry
	return None
