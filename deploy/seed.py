#!/usr/bin/env python3
"""Load reference data into a site.

A freshly installed system has no risk categories, no organisation units and no
forum types, so nothing can be created in it. This loads a starting set from
`deploy/reference/*.json` so an installation is usable immediately.

    python deploy/seed.py --site consilium.local

The data here is a **generic starting point**, not anyone's real taxonomy. It
exists so the system works out of the box and so demonstrations have something
to show. Every value is editable in the application, and a deploying
organisation is expected to replace it with their own — through the interface
or by CSV import.

Loading is idempotent: running it twice changes nothing the second time, and it
never overwrites a value an administrator has edited. Records are matched on
their code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


def load_file(frappe, path: Path) -> tuple[int, int, int]:
    payload = json.loads(path.read_text())
    doctype = payload["doctype"]
    key = payload["key_field"]
    records = payload["records"]

    if not frappe.db.exists("DocType", doctype):
        print(f"  {path.name}: {doctype} is not installed on this site; skipped")
        return 0, 0, len(records)

    created = skipped = 0
    for record in records:
        identifier = record[key]
        if frappe.db.exists(doctype, {key: identifier}):
            skipped += 1
            continue
        doc = frappe.new_doc(doctype)
        doc.update(record)
        doc.insert(ignore_permissions=True)
        created += 1

    return created, skipped, 0


def complete_setup(frappe) -> str:
    """Mark the site's first-run setup as done.

    A freshly created site sends every user to the setup wizard and refuses to
    show anything else until it is finished. The wizard asks for a company name,
    a fiscal year and similar details that mean nothing here — this product
    configures itself through its own reference data, not through that wizard.

    Left alone it is a hard block on an unattended installation: the installer
    finishes, the health check passes, and the first person to open the system
    is trapped on a form they cannot meaningfully answer.

    Completion is tracked per application on `Installed Application`, not in
    System Settings, which is the non-obvious part.
    """
    if frappe.is_setup_complete():
        return "already complete"

    frappe.db.set_value("Installed Application", {"app_name": "frappe"},
                        "is_setup_complete", 1)
    settings = frappe.get_single("System Settings")
    if not settings.time_zone:
        settings.time_zone = "UTC"
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()

    # Verify against the database rather than through `frappe.is_setup_complete()`.
    # That helper reads through the query cache, which within the same process
    # still holds the pre-write value and reports failure for a write that in
    # fact succeeded.
    remaining = frappe.db.sql(
        """select count(*) from "tabInstalled Application"
           where app_name in ('frappe', 'erpnext') and coalesce(is_setup_complete, 0) = 0"""
    )[0][0]
    if remaining:
        return "FAILED — the site will show the setup wizard to every user"
    return "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", required=True)
    parser.add_argument("--sites-path", default=".")
    parser.add_argument("--only", help="load one file by name, for example risk_category.json")
    args = parser.parse_args()

    import frappe

    frappe.init(site=args.site, sites_path=str(Path(args.sites_path).resolve()))
    frappe.connect()
    frappe.set_user("Administrator")

    print(f"\nPreparing {args.site}\n")
    print(f"  first-run setup{'':<22} {complete_setup(frappe)}")

    files = sorted(REFERENCE_DIR.glob("*.json"))
    if args.only:
        files = [f for f in files if f.name == args.only]
    if not files:
        print("no reference files found")
        return 1

    total_created = total_skipped = total_missing = 0
    print()
    for path in files:
        created, skipped, missing = load_file(frappe, path)
        total_created += created
        total_skipped += skipped
        total_missing += missing
        if missing:
            continue
        note = f"{created} created"
        if skipped:
            note += f", {skipped} already present"
        print(f"  {path.stem:<36} {note}")

    frappe.db.commit()
    frappe.destroy()

    print(f"\n  {total_created} records created, {total_skipped} already present.")
    if total_missing:
        print(f"  {total_missing} records skipped because their entity is not installed.")
    print("  This is a generic starting set. Replace it with your own taxonomy.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
