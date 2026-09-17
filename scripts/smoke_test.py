#!/usr/bin/env python3
"""End-to-end smoke test against a running winbench site.

Written after a real miss: the API returned 200 and `/app` returned 200 HTML,
but every JS/CSS bundle 404'd, so the Desk was a blank white page. An API-only
check passes that. This one asserts the *referenced assets* actually load.

    python smoke_test.py --site win.localhost --port 8000 --password admin

Exit code 0 if everything passes, 1 otherwise. Safe to run on Windows or Linux.
"""

import argparse
import re
import sys
import urllib.parse

try:
	import requests
except ImportError:
	sys.exit("smoke_test needs `requests` (it ships with frappe)")

ASSET_RE = re.compile(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"')


class Results:
	def __init__(self):
		self.failures: list[str] = []
		self.passes = 0

	def check(self, name: str, ok: bool, detail: str = "") -> bool:
		if ok:
			self.passes += 1
			print(f"  [ok ] {name}" + (f" -- {detail}" if detail else ""))
		else:
			self.failures.append(name)
			print(f"  [FAIL] {name} -- {detail}")
		return ok


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--site", default="win.localhost")
	parser.add_argument("--host", default="127.0.0.1")
	parser.add_argument("--port", type=int, default=8000)
	parser.add_argument("--user", default="Administrator")
	parser.add_argument("--password", default="admin")
	parser.add_argument(
		"--max-assets", type=int, default=25, help="How many referenced assets to fetch"
	)
	args = parser.parse_args()

	base = f"http://{args.host}:{args.port}"
	headers = {"Host": args.site}
	session = requests.Session()
	session.trust_env = False  # ignore any corporate HTTP(S)_PROXY for localhost
	results = Results()

	print(f"Smoke testing {args.site} via {base}\n")

	# 1. the app answers at all
	try:
		r = session.get(f"{base}/api/method/ping", headers=headers, timeout=30)
		results.check("api ping", r.status_code == 200 and r.json().get("message") == "pong", r.text[:80])
	except Exception as e:
		results.check("api ping", False, str(e))
		return _report(results)

	# 2. login works
	r = session.post(
		f"{base}/api/method/login",
		data={"usr": args.user, "pwd": args.password},
		headers=headers,
		timeout=30,
	)
	if not results.check("login", r.status_code == 200, r.text[:120]):
		return _report(results)
	results.check("session cookie issued", bool(session.cookies.get("sid")))

	# 3. the desk HTML renders
	r = session.get(f"{base}/app", headers=headers, timeout=60, allow_redirects=True)
	html = r.text
	results.check("desk html", r.status_code == 200 and len(html) > 10000, f"{len(html)} bytes")

	# 4. THE ONE THAT MATTERS: every asset the desk references must actually load.
	#    Without nginx, something in-process has to serve /assets. If it doesn't,
	#    the page is blank and every check above still passes.
	assets = sorted(set(ASSET_RE.findall(html)))[: args.max_assets]
	results.check("desk references assets", bool(assets), f"{len(assets)} found in /app")

	broken = []
	for path in assets:
		url = base + urllib.parse.quote(path, safe="/.-_~")
		try:
			ar = session.get(url, headers=headers, timeout=30)
			if ar.status_code != 200 or not ar.content:
				broken.append(f"{path} -> {ar.status_code}")
		except Exception as e:
			broken.append(f"{path} -> {type(e).__name__}")

	results.check(
		"all referenced assets load",
		not broken,
		f"{len(assets) - len(broken)}/{len(assets)} ok" + (f"; broken: {broken[:3]}" if broken else ""),
	)

	# 5. the workflow engine is reachable through the REST API
	r = session.get(
		f"{base}/api/resource/Workflow",
		headers=headers,
		params={"limit_page_length": 5},
		timeout=30,
	)
	results.check("workflow api", r.status_code == 200, r.text[:100])

	# 6. a doctype list view round-trips
	r = session.get(
		f"{base}/api/resource/ToDo",
		headers=headers,
		params={"limit_page_length": 5, "fields": '["name","description"]'},
		timeout=30,
	)
	results.check("doctype list api", r.status_code == 200, r.text[:100])

	return _report(results)


def _report(results: Results) -> int:
	print(f"\n{results.passes} passed, {len(results.failures)} failed")
	if results.failures:
		print("failed: " + ", ".join(results.failures))
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
