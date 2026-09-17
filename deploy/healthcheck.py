#!/usr/bin/env python3
"""Check that an installation is actually working.

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
        js = list(assets.rglob("*.js"))
        css = list(assets.rglob("*.css"))
        assert js and css, f"found {len(js)} scripts and {len(css)} stylesheets; expected many of each"
        return f"{len(js)} scripts, {len(css)} stylesheets"

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
