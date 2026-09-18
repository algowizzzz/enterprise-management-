#!/usr/bin/env python3
"""Build the Consilium leadership briefing (PowerPoint) from this repository.

    .venv/bin/python scripts/deck/build_deck.py [--out PATH]

Default output: ~/Desktop/Consilium-deliverables/Consilium-Leadership-Briefing.pptx.
Use ``--out deliverables/Consilium-Leadership-Briefing.pptx`` to refresh the copy
committed with the release.

Three sources, all in this directory or the repository:

* ``facts.json``: every number and status (test counts, coverage class per
  requirement, backlog counts, entity counts). Change a number here, not in a
  slide.
* ``slides.py``: the slides in order: text, layout and speaker notes.
* ``docs/guides/images/``: the screenshots, the same set the onboarding guide
  uses, so the deck never shows a screen the guide does not.

Needs only python-pptx (``requirements-dev.txt``), lxml and Pillow, all wheels.
No network, no Node.js, no npm. The deck used to be built by a JavaScript
generator kept in a scratch directory; it was lost with that directory, which is
why this one lives in the repository.

Values computed here (``<<name>>`` in slide text) come from ``facts.json`` only.
The coverage summary is recomputed from the per-requirement classes, so a
re-grade is one edit to ``facts.json["coverage"]``. The heatmap, the coverage
chart, the "still open" list, the roadmap's first phase and the appendix trace
table all follow from that edit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import deckkit  # noqa: E402
import slides  # noqa: E402

OUT_DEFAULT = Path.home() / "Desktop" / "Consilium-deliverables" / "Consilium-Leadership-Briefing.pptx"
WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
MODULES = [("G", 19), ("P", 26), ("E", 19), ("O", 7)]


def word(n: int) -> str:
	return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def compute_values(f: dict) -> dict:
	"""Everything slide text may name as ``<<name>>``."""
	cov = f["coverage"]
	v: dict = {}
	for p, n in MODULES:
		for k in "abcd":
			v[f"{p}_{k}"] = sum(1 for i in range(1, n + 1) if cov.get(f"{p}-{i}") == k)
		v[f"{p}_full"] = v[f"{p}_a"] + v[f"{p}_b"]
	for k in "abcd":
		v[f"mand_{k}"] = sum(v[f"{p}_{k}"] for p, _ in MODULES[:3])
	v["full"] = v["mand_a"] + v["mand_b"]
	v["partly"] = v["mand_c"]
	v["missing"] = v["mand_d"]
	v["missing_word"] = word(v["missing"])
	v["missing_Word"] = word(v["missing"]).capitalize()
	v["partial_n"] = len(f["partial_tests"])
	v["partial_list"] = ", ".join(f["partial_tests"])
	t = f["tests"]
	v["tests_run"], v["tests_passed"], v["tests_seconds"] = t["run"], t["passed"], t["seconds"]
	for k, val in f["checks"].items():
		v[k] = val
	for k, val in f["entities"].items():
		v[f"ent_{k}"] = val
	for k, val in f["demo"].items():
		v[f"demo_{k}"] = val
	b = f["backlog"]
	v["stories_done"], v["stories_partial"] = sum(b["done"]), sum(b["partial"])
	v["stories_notstarted"] = sum(b["notstarted"])
	v["stories_total"] = v["stories_done"] + v["stories_partial"] + v["stories_notstarted"]
	v["orig_done"], v["orig_total"], v["stories_added"] = b["orig"][0], b["orig"][1], b["added"]
	v["ai_requests"], v["ai_succeeded"] = f["ai"]["requests"], f["ai"]["succeeded"]
	v["release"], v["briefing_date"], v["measured"] = f["release"], f["briefing_date"], f["measured"]
	return v


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
	args = ap.parse_args()
	facts = json.loads((HERE / "facts.json").read_text(encoding="utf-8"))
	d = deckkit.Deck(REPO, facts, compute_values(facts), slides.SHOTS)
	slides.build(d)
	d.prs.core_properties.title = "Consilium — Leadership briefing"
	d.prs.core_properties.author = "Consilium delivery team"
	out = args.out.expanduser()
	out.parent.mkdir(parents=True, exist_ok=True)
	d.prs.save(out)
	print(f"wrote {out}  slides: {d.slide_no}")
	if d.missing_shots:
		print("MISSING SCREENSHOTS (placeholder drawn): " + ", ".join(d.missing_shots))
		return 2
	return 0


if __name__ == "__main__":
	sys.exit(main())
