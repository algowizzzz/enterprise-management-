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

    files = sorted(REFERENCE_DIR.glob("*.json"))
    if args.only:
        files = [f for f in files if f.name == args.only]
    if not files:
        print("no reference files found")
        return 1

    total_created = total_skipped = total_missing = 0
    print(f"\nLoading reference data into {args.site}\n")
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
