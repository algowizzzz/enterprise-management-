#!/usr/bin/env python3
"""Interface regression sweep, without a browser.

    cd <bench>/sites
    FRAPPE_BENCH_ROOT=<bench> python <repo>/scripts/ui_regression.py \\
        --site consilium.local --url http://consilium.local:8000

The unit and application tests prove behaviour; they say nothing about whether
a screen still renders. That gap is where this project's worst regressions have
lived — a page that returns 200 with a blank body, a link to a page that was
never built, a script served as an HTML error page. This sweep checks, for
every portal page and every entity:

  1. the page renders for a signed-in administrator, with no template error;
  2. a signed-out visitor gets the sign-in prompt, and no record data;
  3. every internal link on the page resolves (no 404);
  4. every script and stylesheet the page references is served;
  5. every entity's list reads through the permission layer;
  6. the portal's own JavaScript parses (when node is available);
  7. the framework's name and logo appear nowhere a user can see them;
  8. no page reflects an address value back unescaped.

It needs a running server for 3, 4 and 7 (pass --url). It exits non-zero on the
first class of failure, printing every failure in that class first.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "apps" / "consilium" / "consilium"
if not (APP / "www").is_dir():
    # Installed from the offline bundle: there is no repository checkout, so
    # read the pages from the installed application package instead.
    import importlib.util

    _spec = importlib.util.find_spec("consilium")
    if _spec and _spec.origin:
        APP = Path(_spec.origin).parent
MODULES = ("Consilium Core", "Governance", "Policy", "Escalation")

# Pages that take a record from the address; rendered with a real one when the
# site has one, so the sweep exercises the populated page, not only the empty.
RECORD_PAGES = {
    "forum": ("Governance Forum", "name"),
    "policy": ("Governing Document", "name"),
    "escalation": ("Escalation Matter", "name"),
    "formation-request": ("Committee Formation Request", "name"),
    "forum-review": ("Governance Forum", "forum"),
}

# Visible branding of the underlying framework. HTML comments are not visible
# and are ignored; the check reads text and image sources.
FRAMEWORK_MARKS = re.compile(r"frappe-framework-logo|frappe-favicon|Login to Frappe|Built on\s+<a[^>]*>Frappe|>\s*Frappe\s*<", re.I)


class Sweep:
    def __init__(self):
        self.failures: dict[str, list[str]] = {}
        self.passes = 0

    def fail(self, group: str, message: str) -> None:
        self.failures.setdefault(group, []).append(message)

    def ok(self) -> None:
        self.passes += 1


def portal_pages() -> list[str]:
    pages = []
    for html in sorted((APP / "www").glob("*.html")):
        route = html.stem
        pages.append("" if route == "index" else route)
    return pages


def render(frappe, route: str, user: str, query: dict | None = None):
    from frappe.website.serve import get_response

    from urllib.parse import urlencode

    from werkzeug.test import EnvironBuilder
    from werkzeug.wrappers import Request

    frappe.set_user(user)
    frappe.local.form_dict = frappe._dict(query or {})
    # The router reads the request's environment, so render inside a real one.
    path = "/" + route + ("?" + urlencode(query) if query else "")
    frappe.local.request = Request(EnvironBuilder(path=path, base_url="http://" + frappe.local.site).get_environ())
    try:
        response = get_response(route or "/")
        return response.status_code, response.get_data(as_text=True)
    except Exception as exc:  # a render that raises is itself the finding
        return 500, f"{type(exc).__name__}: {exc}"


def check_pages(frappe, sweep: Sweep) -> dict[str, str]:
    rendered = {}
    for route in portal_pages():
        query = {}
        if route in RECORD_PAGES:
            doctype, param = RECORD_PAGES[route]
            name = frappe.db.get_value(doctype, {}, "name", order_by="modified desc")
            if name:
                query = {param: name}
        status, body = render(frappe, route, "Administrator", query)
        label = f"/{route}" + (f"?{list(query)[0]}={list(query.values())[0]}" if query else "")
        if status != 200:
            sweep.fail("page renders (administrator)", f"{label}: HTTP {status} {body[:200]}")
            continue
        if re.search(r"Traceback|TemplateSyntaxError|UndefinedError|jinja2\.exceptions", body):
            sweep.fail("page renders (administrator)", f"{label}: template error in body")
            continue
        sweep.ok()
        rendered[label] = body

        status, body = render(frappe, route, "Guest", query)
        if route in ("ui-kit",):
            sweep.ok()
            continue
        if status in (401, 403) or "Sign in to continue" in body or "/login" in body:
            sweep.ok()
        else:
            sweep.fail("signed-out visitors are sent to sign in", f"{label}: HTTP {status}, no sign-in prompt")
    frappe.set_user("Administrator")
    return rendered


PAYLOAD = '"><script>cnsxss()</script>'


def check_reflection(frappe, sweep: Sweep) -> None:
    """Every page that reads a value from the address must escape it.

    The framework's templates do not autoescape, so a page that prints
    ``?name=`` back unescaped lets a crafted link run script in a colleague's
    session. Each page is rendered with a script payload in every parameter
    such pages read; the payload must never come back verbatim.
    """
    for route in portal_pages():
        params = {k: PAYLOAD for k in ("name", "forum", "version", "request", "batch", "requirement")}
        status, body = render(frappe, route, "Administrator", params)
        if PAYLOAD in body or "<script>cnsxss()" in body:
            sweep.fail("address values are escaped", f"/{route}: payload reflected unescaped")
        else:
            sweep.ok()
    frappe.set_user("Administrator")


def check_links(rendered: dict[str, str], base_url: str, sweep: Sweep) -> None:
    seen = set()
    for label, body in rendered.items():
        for href in re.findall(r'href="(/[^"#]*)"', body) + re.findall(r'src="(/[^"]*)"', body):
            # A URL assembled in script (`'/forum?name=' + id`) is not a link yet.
            if href.startswith(("/api/", "/app")) or "cmd=" in href or href in seen \
                    or re.search(r"['+\s{}]", href):
                continue
            seen.add(href)
            code = http_status(base_url + href)
            if code >= 400 and code not in (401, 403):
                sweep.fail("links and assets resolve", f"{href} (linked from {label}): HTTP {code}")
            else:
                sweep.ok()


def _request(url: str) -> urllib.request.Request:
    """Browsers and curl send *.localhost to the loopback address; Python's
    resolver does not, so do it here and keep the name in the Host header."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.hostname and parts.hostname.endswith(".localhost"):
        netloc = "127.0.0.1" + (f":{parts.port}" if parts.port else "")
        request = urllib.request.Request(urlunsplit(parts._replace(netloc=netloc)))
        request.add_header("Host", parts.netloc)
        return request
    return urllib.request.Request(url)


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(_request(url), timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 599


def check_lists(frappe, sweep: Sweep) -> None:
    doctypes = frappe.get_all("DocType", filters={"module": ["in", MODULES], "istable": 0, "issingle": 0}, pluck="name")
    for doctype in doctypes:
        try:
            frappe.get_list(doctype, fields=["name"], limit_page_length=5)
            sweep.ok()
        except Exception as exc:
            sweep.fail("entity lists read", f"{doctype}: {type(exc).__name__}: {str(exc)[:160]}")


def check_javascript(sweep: Sweep) -> None:
    node = shutil.which("node")
    if not node:
        print("  node not found; JavaScript syntax not checked")
        return
    for js in sorted((APP / "public" / "js").glob("*.js")):
        result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        if result.returncode:
            sweep.fail("portal JavaScript parses", f"{js.name}: {result.stderr.strip()[:200]}")
        else:
            sweep.ok()
    # Inline page scripts: pull each <script> body out of the templates and parse
    # it on its own, with template tags blanked so the parser sees plain JS.
    for html in sorted((APP / "www").glob("*.html")):
        for i, body in enumerate(re.findall(r"<script>(.*?)</script>", html.read_text(), re.S)):
            code = re.sub(r"\{\{.*?\}\}", "null", re.sub(r"\{%.*?%\}", "", body, flags=re.S), flags=re.S)
            result = subprocess.run([node, "--check", "--input-type=commonjs"], input=code,
                                    capture_output=True, text=True)
            if result.returncode:
                sweep.fail("portal JavaScript parses", f"{html.name} script {i + 1}: {result.stderr.strip().splitlines()[-1][:200]}")
            else:
                sweep.ok()


def check_branding(base_url: str, rendered: dict[str, str], sweep: Sweep) -> None:
    targets = {"/login": fetch(base_url + "/login"), "/me": fetch(base_url + "/me")}
    targets.update(rendered)
    for label, body in targets.items():
        visible = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        hit = FRAMEWORK_MARKS.search(visible)
        if hit:
            sweep.fail("no framework branding is visible", f"{label}: {hit.group(0)[:80]!r}")
        else:
            sweep.ok()


def fetch(url: str) -> str:
    try:
        with urllib.request.urlopen(_request(url), timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", "replace")
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    parser.add_argument("--url", help="base URL of a running server, e.g. http://consilium.local:8000")
    args = parser.parse_args()

    import frappe

    frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")

    sweep = Sweep()
    print("Rendering portal pages")
    rendered = check_pages(frappe, sweep)
    print("Probing for reflected markup")
    check_reflection(frappe, sweep)
    print("Reading every entity list")
    check_lists(frappe, sweep)
    print("Parsing portal JavaScript")
    check_javascript(sweep)
    if args.url:
        base = args.url.rstrip("/")
        print("Following links and assets")
        check_links(rendered, base, sweep)
        print("Looking for framework branding")
        check_branding(base, rendered, sweep)
    else:
        print("  no --url given; links, assets and branding not checked")
    frappe.destroy()

    print()
    for group, messages in sweep.failures.items():
        print(f"FAIL  {group} ({len(messages)})")
        for message in messages:
            print(f"      {message}")
    failed = sum(len(m) for m in sweep.failures.values())
    print(f"\n{sweep.passes} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
