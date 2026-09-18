#!/usr/bin/env python3
"""Check that an installation is actually working.

platform-rules: exempt — this file names CDN hosts in order to detect them.

Installing without error is not the same as working. The most expensive failure
mode this project has already hit was a site that answered every request with
HTTP 200 while serving a blank page, because the asset bundle had been copied in
a way that left a dangling symlink. Nothing errored. Everything looked installed.

So these checks look for evidence rather than absence of error, and each one
says what to do when it fails.

    python deploy/healthcheck.py --site consilium.local

Exit code 0 if every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

results: list[tuple[str, bool, str, str]] = []


def check(name: str):
    """Register a check. The function returns a detail string, or raises."""
    def decorator(fn):
        try:
            detail = fn()
            results.append((name, True, detail or "", ""))
        except AssertionError as e:
            results.append((name, False, "", str(e)))
        except Exception as e:  # noqa: BLE001 — a check that crashes is a failure
            results.append((name, False, "", f"{type(e).__name__}: {e}\n{DIM}{traceback.format_exc(limit=2)}{RESET}"))
        return fn
    return decorator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    args = parser.parse_args()

    sites_path = Path(args.sites_path).resolve()
    site_path = sites_path / args.site

    # ------------------------------------------------------------------ layout
    @check("Site directory exists")
    def _():
        assert site_path.is_dir(), (
            f"{site_path} does not exist. Run this from the sites directory, or pass "
            f"--sites-path."
        )
        return str(site_path)

    @check("Site configuration is readable")
    def _():
        config = json.loads((site_path / "site_config.json").read_text())
        assert config.get("db_name"), "site_config.json has no db_name"
        return f"database {config['db_name']}"

    # -------------------------------------------------------------- the engine
    import frappe  # imported here so the layout checks report first

    @check("Framework imports")
    def _():
        return f"frappe {frappe.__version__}"

    frappe.init(site=args.site, sites_path=str(sites_path))
    frappe.connect()

    @check("Database answers")
    def _():
        (one,) = frappe.db.sql("select 1")[0]
        assert one == 1
        version = frappe.db.sql("select version()")[0][0]
        return version.split(",")[0]

    @check("Database is PostgreSQL")
    def _():
        assert frappe.conf.db_type == "postgres", (
            f"db_type is {frappe.conf.db_type!r}. This product is built and tested on "
            f"PostgreSQL only."
        )
        return "postgres"

    @check("Cache answers")
    def _():
        url = urlparse(frappe.conf.redis_cache)
        with socket.create_connection((url.hostname, url.port or 6379), timeout=3):
            pass
        frappe.cache().set_value("consilium_healthcheck", "ok", expires_in_sec=30)
        assert frappe.cache().get_value("consilium_healthcheck") == "ok", (
            "the cache accepted a write but did not return it"
        )
        return frappe.conf.redis_cache

    # ------------------------------------------------------------ the app
    @check("Application is installed on the site")
    def _():
        installed = frappe.get_installed_apps()
        assert "consilium" in installed, (
            f"installed apps are {installed}. Run: install-app consilium"
        )
        return ", ".join(installed)

    @check("Application tables exist")
    def _():
        expected = frappe.get_all("DocType", filters={"module": ["like", "%"]},
                                  fields=["name", "module"])
        ours = [d for d in expected if d.module in
                ("Consilium Core", "Governance", "Policy", "Escalation")]
        assert ours, "no DocTypes belong to the application's modules"
        tables = set(frappe.db.get_tables())
        missing = [d.name for d in ours
                   if not frappe.get_meta(d.name).issingle
                   and f"tab{d.name}" not in tables]
        assert not missing, (
            f"{len(missing)} entities have no table: {missing[:5]}. Run a migration."
        )
        return f"{len(ours)} entities, all with tables"

    @check("An administrator account exists and is enabled")
    def _():
        enabled = frappe.db.get_value("User", "Administrator", "enabled")
        assert enabled, "the Administrator account is disabled"
        return "Administrator enabled"

    # ------------------------------------------------------------------ assets
    @check("Front-end assets are present and readable")
    def _():
        assets = sites_path / "assets"
        assert assets.is_dir(), (
            f"{assets} does not exist. Unpack the asset bundle; without it the "
            f"interface loads but renders blank."
        )
        # A dangling symlink is the specific failure this guards against: the
        # directory entry exists, so a naive check passes, but nothing can be read
        # through it and every asset request 404s while the page still returns 200.
        dangling = [p for p in assets.iterdir() if p.is_symlink() and not p.exists()]
        assert not dangling, (
            f"dangling asset links: {[p.name for p in dangling]}. "
            f"These serve a blank interface while returning HTTP 200."
        )
        # os.walk rather than Path.rglob: before Python 3.13, rglob does not
        # descend into symlinked directories, and a development bench serves
        # assets through exactly those links — so rglob counts nothing and a
        # working install reports as broken.
        files = [f for _, _, names in os.walk(assets, followlinks=True) for f in names]
        js = [f for f in files if f.endswith(".js")]
        css = [f for f in files if f.endswith(".css")]
        assert js and css, f"found {len(js)} scripts and {len(css)} stylesheets; expected many of each"
        return f"{len(js)} scripts, {len(css)} stylesheets"

    @check("Libraries loaded on demand are present")
    def _():
        # The Desk fetches these by URL the first time a screen needs them, so a
        # bundle without them passes every other check and then breaks the first
        # JSON field anyone opens.
        base = sites_path / "assets" / "frappe" / "node_modules"
        wanted = ["ace-builds/src-noconflict/ace.js", "ace-builds/src-min-noconflict/ace.js",
                  "frappe-gantt/dist/frappe-gantt.min.js", "html5-qrcode/html5-qrcode.min.js",
                  "qz-tray/qz-tray.js", "js-sha256/build/sha256.min.js"]
        missing = [w for w in wanted if not (base / w).is_file()]
        assert not missing, (
            f"missing under {base}: {missing}. Re-import the asset bundle; without these "
            f"every JSON and Code field fails to load its editor."
        )
        return f"{len(wanted)} files, including the code editor"

    @check("Served assets match the application source")
    def _():
        # Assets reach the web server either by a link to the application's
        # public directory or by a copy of it. A copy is the safer choice on
        # Windows, where links need a privilege the installer may not hold — but
        # a copy goes stale the moment the application changes, and a stale copy
        # fails silently: the page loads, the old stylesheet applies, and nothing
        # anywhere reports a problem. So compare the two.
        import consilium
        source = Path(consilium.__file__).parent / "public"
        served = sites_path / "assets" / "consilium"
        assert served.exists(), (
            f"{served} does not exist. The application's assets are not being served. "
            f"Run the asset install step."
        )
        if served.is_symlink():
            return "served by link; always current"

        stale = []
        for path in source.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            counterpart = served / path.relative_to(source)
            if not counterpart.exists():
                stale.append(f"{path.relative_to(source)} is not served")
            elif counterpart.read_bytes() != path.read_bytes():
                stale.append(f"{path.relative_to(source)} differs from source")
        assert not stale, (
            f"the served copy is out of date: {stale[:5]}. "
            f"Re-run the asset install step. A stale copy serves the old files "
            f"without reporting any error."
        )
        return f"served by copy; {sum(1 for p in source.rglob('*') if p.is_file())} files current"

    @check("Vendored libraries are present and unmodified")
    def _():
        import hashlib
        import consilium
        vendor = Path(consilium.__file__).parent / "public" / "vendor"
        sums = vendor / "SHA256SUMS"
        if not sums.exists():
            return "no checksum file; skipped"
        bad = []
        for line in sums.read_text().splitlines():
            if not line.strip():
                continue
            digest, _, rel = line.partition("  ")
            target = vendor / rel.lstrip("./")
            if not target.exists():
                bad.append(f"{rel} missing")
                continue
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != digest:
                bad.append(f"{rel} altered")
        assert not bad, f"vendored files do not match their checksums: {bad}"
        return f"{len(sums.read_text().splitlines())} files verified"

    @check("Nothing references an external host")
    def _():
        import consilium
        root = Path(consilium.__file__).parent
        offenders = []
        for path in list(root.rglob("*.html")) + list(root.rglob("*.js")) + list(root.rglob("*.css")):
            if "vendor" in path.parts or path.suffix == ".map":
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            for marker in ("//cdn.", "cdnjs.", "jsdelivr", "unpkg.com",
                           "fonts.googleapis.com", "ajax.googleapis.com"):
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")
        assert not offenders, (
            f"external references found: {offenders[:5]}. The target has no internet "
            f"access, so these will simply fail there."
        )
        return "no CDN or external font references"

    # --------------------------------------------------------------------- PDF
    @check("PDF engine present")
    def _():
        # Every PDF — print, download, email attachment — goes through the
        # wkhtmltopdf binary. Without it the interface works until someone asks
        # for a PDF, and then shows a server error. The build with patched Qt
        # is the one the framework needs: the unpatched build a distribution
        # ships renders without headers, footers or page numbers.
        import shutil
        import subprocess

        exe = shutil.which("wkhtmltopdf") or next(
            (p for p in ("/usr/local/bin/wkhtmltopdf", "/usr/bin/wkhtmltopdf") if os.path.exists(p)), None)
        assert exe, (
            "wkhtmltopdf is not installed, so PDF downloads fail with a server error. The offline "
            "bundle carries the 0.12.6 packages under vendor/wkhtmltopdf/; re-run install.sh, which "
            "installs the one for this system."
        )
        version = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        assert "0.12.6" in version, f"{exe} reports {version!r}; 0.12.6 is required"
        assert "patched qt" in version.lower(), (
            f"{exe} reports {version!r}: the unpatched build renders PDFs without headers, footers "
            f"or page breaks. Install the bundled 0.12.6 (with patched qt) package instead."
        )
        # The framework's PDF library does not search PATH itself: it runs
        # `which wkhtmltopdf`, so both have to work for the service account.
        found = subprocess.run(["which", "wkhtmltopdf"], capture_output=True, text=True) \
            if shutil.which("which") else None
        assert found and found.returncode == 0, (
            "the `which` command is missing or cannot find wkhtmltopdf on PATH; the PDF library the "
            "framework uses looks the engine up that way, so every PDF fails. Install `which`."
        )
        return f"{version} at {exe}"

    # ----------------------------------------------------------------- workers
    @check("Background queues are reachable")
    def _():
        url = urlparse(frappe.conf.redis_queue)
        with socket.create_connection((url.hostname, url.port or 6379), timeout=3):
            pass
        return frappe.conf.redis_queue

    @check("Scheduled jobs are registered")
    def _():
        count = frappe.db.count("Scheduled Job Type")
        assert count > 0, (
            "no scheduled job types are registered; periodic reviews, attestation "
            "reminders and retention disposal will never run"
        )
        return f"{count} job types"

    frappe.destroy()

    # ----------------------------------------------------------------- report
    width = max(len(name) for name, *_ in results) + 2
    print()
    for name, ok, detail, error in results:
        mark = f"{GREEN}pass{RESET}" if ok else f"{RED}FAIL{RESET}"
        print(f"  {mark}  {name:<{width}} {DIM}{detail}{RESET}")
        if error:
            for line in error.splitlines():
                print(f"        {RED}{line}{RESET}")

    passed = sum(1 for _, ok, *_ in results if ok)
    total = len(results)
    print()
    if passed == total:
        print(f"  {GREEN}{passed}/{total} checks passed. The installation is healthy.{RESET}\n")
        return 0
    print(f"  {RED}{passed}/{total} checks passed. The installation is not ready to use.{RESET}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
