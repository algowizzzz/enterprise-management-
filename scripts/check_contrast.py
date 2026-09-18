#!/usr/bin/env python3
"""Check the colour pairs the portal and the workspace theme rely on, against WCAG 2.x AA.

    python scripts/check_contrast.py            # table of every pair; exit 1 on a failure
    python scripts/check_contrast.py --quiet    # failures only

Why it exists. Colours live in three stylesheets (tokens.css, the portal theme
theme-hybrid.css, and the workspace theme desk-theme.css), and a pair that
passes today fails the day someone nudges one token. Nothing else notices:
the page still renders, the tests still pass. So the pairs are read out of the
stylesheets themselves -- not copied here -- and checked every time.

What it checks, for the light and the dark theme:
  - tokens.css on its own (the base every portal page starts from);
  - tokens.css with theme-hybrid.css over it (what the portal shows);
  - desk-theme.css (what the workspace shows).
Body-size text needs 4.5:1. A form field's edge is a non-text boundary and
needs 3:1 (WCAG 1.4.11).

Translucent surfaces. A frosted header or menu has no single background: what
shows through depends on where it is. Each translucent surface is therefore
composited over the WORST case: every ambient glow of the page backdrop
stacked at full strength over the base colour, which never happens on screen.
A pair that passes here passes everywhere.

The brand. Portal Branding replaces the primary colour ramp at run time. The
pairs that involve it use the default brand, derived exactly as
consilium_core/branding.py derives it (the two small helpers are mirrored
below); a deployment with its own colour should re-run with --primary.

Plain Python, standard library only; no site or server needed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSS = REPO / "apps" / "consilium" / "consilium" / "public" / "css"

TEXT, NON_TEXT = 4.5, 3.0
DEFAULT_PRIMARY = "#1d3557"


# ------------------------------------------------------------------ parsing

def blocks(path: Path) -> dict[str, dict[str, str]]:
	"""Custom properties per top-level selector, in file order.

	Rules inside @media / @supports are skipped: they are the reduced-
	transparency and fallback variants, which only ever make surfaces more
	opaque (and so contrast higher) than the rules checked here.
	"""
	text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
	out: dict[str, dict[str, str]] = {}
	depth, start, selector = 0, 0, None
	for i, ch in enumerate(text):
		if ch == "{":
			if depth == 0:
				selector = " ".join(text[start:i].split())
				body_start = i + 1
			depth += 1
		elif ch == "}":
			depth -= 1
			if depth == 0:
				if selector and not selector.startswith("@"):
					body = text[body_start:i]
					props = out.setdefault(selector, {})
					for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body):
						props[name] = " ".join(value.split())
				start = i + 1
	return out


def layer(path: Path, *selectors: str) -> dict[str, str]:
	found = blocks(path)
	merged: dict[str, str] = {}
	for selector in selectors:
		merged.update(found.get(selector, {}))
	return merged


# ------------------------------------------------------------------ colours

Colour = tuple[float, float, float, float]


def parse_colour(value: str) -> Colour | None:
	value = value.strip().lower()
	m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", value)
	if m:
		h = m.group(1)
		if len(h) == 3:
			h = "".join(c * 2 for c in h)
		return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
	m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
	if m:
		r, g, b, a = m.groups()
		return (float(r), float(g), float(b), float(a) if a is not None else 1.0)
	if value == "white":
		return (255, 255, 255, 1.0)
	return None


def resolve(tokens: dict[str, str], value: str, seen: tuple = ()) -> str:
	"""Follow var(--x, fallback) chains to a literal value."""
	m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)", value.strip())
	if not m:
		return value
	name, fallback = m.groups()
	if name in seen:
		raise ValueError(f"circular reference at {name}")
	if name in tokens:
		return resolve(tokens, tokens[name], seen + (name,))
	if fallback:
		return resolve(tokens, fallback, seen + (name,))
	raise KeyError(name)


def colour(tokens: dict[str, str], name: str) -> Colour:
	value = resolve(tokens, tokens[name]) if name.startswith("--") else name
	parsed = parse_colour(value)
	if parsed is None:
		raise ValueError(f"{name} is not a plain colour ({value})")
	return parsed


def over(top: Colour, below: Colour) -> Colour:
	a = top[3]
	return (a * top[0] + (1 - a) * below[0], a * top[1] + (1 - a) * below[1], a * top[2] + (1 - a) * below[2], 1.0)


def luminance(c: Colour) -> float:
	def channel(v):
		v = v / 255
		return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
	return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])


def ratio(a: Colour, b: Colour) -> float:
	hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
	return (hi + 0.05) / (lo + 0.05)


def hexed(c: Colour) -> str:
	return "#" + "".join(f"{round(v):02x}" for v in c[:3])


# Mirrors consilium_core/branding.py (_mix and the ramp brand_style() writes).
def _mix(colour_hex: str, towards: str, amount: float) -> str:
	a = [int(colour_hex[i:i + 2], 16) for i in (1, 3, 5)]
	b = [int(towards[i:i + 2], 16) for i in (1, 3, 5)]
	return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def brand_tokens(primary: str, dark: bool) -> dict[str, str]:
	if dark:
		return {"--cns-primary": _mix(primary, "#ffffff", 0.5), "--cns-primary-500": _mix(primary, "#ffffff", 0.42)}
	on_primary = "#111111" if luminance(parse_colour(primary)) > 0.45 else "#ffffff"
	return {"--cns-primary-600": primary, "--cns-primary-500": _mix(primary, "#ffffff", 0.08),
		"--cns-primary-700": _mix(primary, "#000000", 0.18), "--cns-on-primary": on_primary}


# ------------------------------------------------------------------ the pairs

def worst_backdrop(tokens: dict[str, str], dark: bool) -> Colour:
	"""The page backdrop with every ambient glow stacked at full strength."""
	base = colour(tokens, "--hy-base")
	glows = [parse_colour(m) for m in re.findall(r"rgba\([^)]*\)", tokens.get("--hy-ambient", ""))]
	stacked = base
	for glow in glows:
		stacked = over(glow, stacked)
	return stacked


def portal_pairs(tokens: dict[str, str], themed: bool, dark: bool):
	"""(label, foreground, background, needs) for one theme of the portal."""
	c = lambda name: colour(tokens, name)  # noqa: E731
	page, card = c("--cns-surface-page"), c("--cns-surface")
	pairs = [
		("Body text on the page", c("--cns-text"), page, TEXT),
		("Muted text on the page", c("--cns-text-muted"), page, TEXT),
		("Muted text on a card", c("--cns-text-muted"), card, TEXT),
		("Muted text on a card header / table head", c("--cns-text-muted"), c("--cns-surface-muted"), TEXT),
		("Secondary text on a card", c("--cns-text-secondary"), card, TEXT),
		("Link on a card", c("--cns-text-link"), card, TEXT),
		("Field border against a card", c("--cns-border-field"), card, NON_TEXT),
		("Field border against the page", c("--cns-border-field"), page, NON_TEXT),
	]
	for status in ("success", "warning", "danger", "info", "neutral"):
		pairs.append((f"{status.capitalize()} pill text", c(f"--cns-{status}-fg"), c(f"--cns-{status}-bg"), TEXT))
	if not dark:
		pairs.append(("Button text on the brand colour", c("--cns-on-primary"), c("--cns-primary-600"), TEXT))
	if themed:
		backdrop = worst_backdrop(tokens, dark)
		chrome, pop, tile = (over(c(n), backdrop) for n in ("--hy-chrome", "--hy-pop", "--hy-tile"))
		pairs += [
			("Muted text on the page backdrop (worst case)", c("--cns-text-muted"), backdrop, TEXT),
			("Header text on the frosted header (worst case)", c("--cns-text"), chrome, TEXT),
			("Menu label on the frosted header (worst case)", c("--cns-text-secondary"), chrome, TEXT),
			("Menu description in a frosted menu (worst case)", c("--cns-text-muted"), pop, TEXT),
			("Muted text on a glass tile (worst case)", c("--cns-text-muted"), tile, TEXT),
			("Body text on a glass tile (worst case)", c("--cns-text"), tile, TEXT),
			("Idle lifecycle step", c("--hy-path-idle-fg"), c("--hy-path-idle"), TEXT),
		]
	return pairs


def desk_pairs(tokens: dict[str, str], dark: bool):
	c = lambda name: colour(tokens, name)  # noqa: E731
	card, page = c("--dk-card"), c("--dk-page")
	return [
		("Label on a form section", c("--dk-label"), card, TEXT),
		("Field border against a form section", c("--dk-field-border"), card, NON_TEXT),
		("Field border against the page", c("--dk-field-border"), page, NON_TEXT),
		("Primary button text", c("--dk-on-brand"), c("--dk-brand"), TEXT),
		("Record link in a list (brand colour)", c("--dk-brand"), card, TEXT),
	]


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--primary", default=DEFAULT_PRIMARY, help="brand primary colour to check with (#rrggbb)")
	parser.add_argument("--quiet", action="store_true", help="print failures only")
	args = parser.parse_args()
	if not re.fullmatch(r"#[0-9a-fA-F]{6}", args.primary):
		parser.error("--primary must be #rrggbb")
	primary = args.primary.lower()

	tokens_css, theme_css, desk_css = CSS / "tokens.css", CSS / "theme-hybrid.css", CSS / "desk-theme.css"
	base_light = layer(tokens_css, ":root")
	base_dark = {**base_light, **layer(tokens_css, '[data-theme="dark"]')}
	sets = [
		("tokens.css", "light", {**base_light, **brand_tokens(primary, False)}, False),
		("tokens.css", "dark", {**base_dark, **brand_tokens(primary, True)}, False),
		("portal theme", "light", {**base_light, **layer(theme_css, ":root", ':root:not([data-theme="dark"])'),
			**brand_tokens(primary, False)}, True),
		("portal theme", "dark", {**base_dark, **layer(theme_css, ":root", ':root[data-theme="dark"]'),
			**brand_tokens(primary, True)}, True),
	]
	rows = []
	for name, mode, tokens, themed in sets:
		for label, fg, bg, needs in portal_pairs(tokens, themed, mode == "dark"):
			rows.append((name, mode, label, fg, bg, needs))
	desk_light = {**layer(desk_css, ":root", ':root:not([data-theme="dark"])'), "--cns-desk-brand": primary,
		"--cns-desk-on-brand": brand_tokens(primary, False)["--cns-on-primary"]}
	desk_dark = {**layer(desk_css, ":root", '[data-theme="dark"]'), "--cns-desk-brand-dark": _mix(primary, "#ffffff", 0.5)}
	for mode, tokens in (("light", desk_light), ("dark", desk_dark)):
		for label, fg, bg, needs in desk_pairs(tokens, mode == "dark"):
			rows.append(("workspace theme", mode, label, fg, bg, needs))

	failures = 0
	for name, mode, label, fg, bg, needs in rows:
		r = ratio(fg, bg)
		ok = r >= needs
		failures += not ok
		if ok and args.quiet:
			continue
		print(f"{'pass' if ok else 'FAIL'}  {name:15} {mode:5}  {label:50} {hexed(fg)} on {hexed(bg)}  "
			f"{r:5.2f}:1 (needs {needs}:1)")
	print(f"\n{len(rows) - failures}/{len(rows)} pairs meet WCAG AA (brand {primary}).")
	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(main())
