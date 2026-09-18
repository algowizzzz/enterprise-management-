"""The offline bundle carries the illustrated guide the platform shows.

The guide reader (/guide) and the help assistant read ``docs/guides`` at
runtime, from the folder the deployment kit names in ``assistant_docs_path``
(``<install>/docs``, copied from the bundle's ``docs/``). A bundle without the
chapters has an empty guide; one without a picture has a broken image on every
screen that uses it. Neither fails an install, so both are checked here.

Run with:  python -m pytest tests -q
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "deploy"))

import make_bundle  # noqa: E402

GUIDES = REPO / "docs" / "guides"


def test_the_bundle_lists_the_guides_folder():
	assert "guides" in make_bundle.ASSISTANT_DOCS


@pytest.mark.skipif(not GUIDES.is_dir(), reason="docs/guides is not in this checkout")
def test_the_bundle_carries_every_chapter_and_every_picture(tmp_path):
	copied = make_bundle.copy_assistant_docs(REPO, tmp_path / "docs")
	guides = tmp_path / "docs" / "guides"
	chapters = sorted(p.name for p in GUIDES.glob("[0-9][0-9]-*.md"))
	assert chapters, "the guide has no chapters"
	assert sorted(p.name for p in guides.glob("[0-9][0-9]-*.md")) == chapters
	assert (guides / "README.md").is_file()
	pictures = sorted(p.relative_to(GUIDES).as_posix() for p in (GUIDES / "images").rglob("*.png"))
	assert pictures, "the guide has no pictures"
	for picture in pictures:
		assert (guides / picture).is_file(), picture
	assert make_bundle.guide_image_gaps(guides) == []
	assert copied >= len(chapters) + len(pictures)
	# What the platform needs to find the folder by `assistant_docs_path`: the
	# user guide beside it (corpus.docs_dir checks for it).
	assert (tmp_path / "docs" / "USER-GUIDE.md").is_file()


def test_a_missing_picture_is_reported(tmp_path):
	(tmp_path / "images" / "area").mkdir(parents=True)
	(tmp_path / "images" / "area" / "there.png").write_bytes(b"\x89PNG")
	(tmp_path / "01-one.md").write_text("# One\n\n![Here](images/area/there.png)\n\n![Gone](images/area/gone.png)\n")
	assert make_bundle.guide_image_gaps(tmp_path) == ["01-one.md: images/area/gone.png"]


def test_the_current_release_refuses_to_bundle_without_the_guides(tmp_path, monkeypatch):
	source = tmp_path / "repo"
	docs = source / "docs"
	(docs / "product").mkdir(parents=True)
	for name in ("USER-GUIDE.md", "ADMIN-GUIDE.md", "product/05-glossary.md"):
		(docs / name).write_text("# Doc\n")
	monkeypatch.setattr(make_bundle, "REPO", source)
	with pytest.raises(SystemExit, match="docs/guides is missing"):
		make_bundle.copy_assistant_docs(source, tmp_path / "out")


def test_an_earlier_release_without_the_guides_still_bundles(tmp_path):
	source = tmp_path / "old-release"
	docs = source / "docs"
	(docs / "product").mkdir(parents=True)
	for name in ("USER-GUIDE.md", "ADMIN-GUIDE.md", "product/05-glossary.md"):
		(docs / name).write_text("# Doc\n")
	assert make_bundle.copy_assistant_docs(source, tmp_path / "out") == 3
