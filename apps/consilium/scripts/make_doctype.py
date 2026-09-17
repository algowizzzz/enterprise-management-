#!/usr/bin/env python3
"""Generate Frappe DocType definitions from compact specs.

A DocType in Frappe is a JSON document plus a Python controller. Written by
hand the JSON is long and easy to get subtly wrong, and small inconsistencies
between DocTypes cause real problems later — a missing `search_fields` makes a
link field unusable, a missing permission row locks a role out, an inconsistent
naming rule breaks integrations.

So DocTypes here are written as short specs and generated. The spec carries the
decisions; this script supplies the boilerplate and the house conventions.

    python scripts/make_doctype.py specs/governance/*.json

Conventions applied automatically:
  - standard permission rows, unless the spec overrides them
  - `track_changes` on by default, which is what gives us the audit trail
  - a controller file with a validate hook, if one does not already exist
  - a test file, if one does not already exist
  - field order derived from the field list
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "consilium"

MODULE_DIRS = {
    "Consilium Core": "consilium_core",
    "Governance": "governance",
    "Policy": "policy",
    "Escalation": "escalation",
}

DEFAULT_PERMISSIONS = [
    {
        "role": "System Manager",
        "read": 1, "write": 1, "create": 1, "delete": 1,
        "report": 1, "export": 1, "share": 1, "print": 1, "email": 1,
    }
]

# Fields the framework maintains on every table. Listed here so specs never
# declare them by accident and so the schema document can be generated from one
# source of truth.
FRAMEWORK_FIELDS = (
    "name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
    "_user_tags", "_comments", "_assign", "_liked_by",
)


def snake(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def validate_spec(spec: dict, path: Path) -> list[str]:
    problems = []
    for key in ("name", "module", "fields"):
        if not spec.get(key):
            problems.append(f"missing required key: {key}")

    module = spec.get("module")
    if module and module not in MODULE_DIRS:
        problems.append(f"unknown module {module!r}; expected one of {sorted(MODULE_DIRS)}")

    seen = set()
    for field in spec.get("fields", []):
        fieldname = field.get("fieldname")
        if not fieldname:
            problems.append(f"field without a fieldname: {field}")
            continue
        if fieldname in FRAMEWORK_FIELDS:
            problems.append(f"{fieldname!r} is maintained by the framework; remove it")
        if fieldname in seen:
            problems.append(f"duplicate fieldname: {fieldname}")
        seen.add(fieldname)
        if not field.get("fieldtype"):
            problems.append(f"{fieldname}: missing fieldtype")
        if field.get("fieldtype") in ("Link", "Table", "Table MultiSelect") and not field.get("options"):
            problems.append(f"{fieldname}: {field['fieldtype']} needs `options` naming the target DocType")

    autoname = spec.get("autoname", "")
    if autoname.startswith("field:"):
        target = autoname.split(":", 1)[1]
        if target not in seen:
            problems.append(f"autoname refers to {target!r}, which is not a field")

    return [f"{path.name}: {p}" for p in problems]


def build_doctype(spec: dict) -> dict:
    fields = [dict(f) for f in spec["fields"]]
    doc = {
        "actions": [],
        "allow_rename": spec.get("allow_rename", 0),
        "creation": spec.get("creation", timestamp()),
        "doctype": "DocType",
        "editable_grid": 1,
        "engine": "InnoDB",  # ignored on PostgreSQL; the framework still expects the key
        "field_order": [f["fieldname"] for f in fields],
        "fields": fields,
        "index_web_pages_for_search": 0,
        "links": spec.get("links", []),
        "modified": timestamp(),
        "modified_by": "Administrator",
        "module": spec["module"],
        "name": spec["name"],
        "owner": "Administrator",
        "permissions": spec.get("permissions", DEFAULT_PERMISSIONS),
        "sort_field": spec.get("sort_field", "modified"),
        "sort_order": spec.get("sort_order", "DESC"),
        "states": [],
        "track_changes": spec.get("track_changes", 1),
    }

    for key in (
        "autoname", "naming_rule", "title_field", "search_fields", "is_submittable",
        "istable", "is_tree", "quick_entry", "track_seen", "description",
        "default_sort_field", "show_title_field_in_link", "nsm_parent_field",
    ):
        if key in spec:
            doc[key] = spec[key]

    return doc


CONTROLLER_TEMPLATE = '''"""{name} — controller.

{description}
"""

from frappe.model.document import Document


class {klass}(Document):
    def validate(self):
        pass
'''

TEST_TEMPLATE = '''"""Tests for {name}."""

from frappe.tests.utils import FrappeTestCase


class Test{klass}(FrappeTestCase):
    def test_placeholder(self):
        self.assertTrue(True)
'''


def write_doctype(spec: dict) -> list[Path]:
    module_dir = MODULE_DIRS[spec["module"]]
    slug = snake(spec["name"])
    klass = spec["name"].replace(" ", "").replace("-", "")
    target = APP_ROOT / APP_NAME / module_dir / "doctype" / slug
    target.mkdir(parents=True, exist_ok=True)

    written = []

    init = target / "__init__.py"
    if not init.exists():
        init.write_text("")
        written.append(init)

    json_path = target / f"{slug}.json"
    json_path.write_text(json.dumps(build_doctype(spec), indent=1, sort_keys=True) + "\n")
    written.append(json_path)

    controller = target / f"{slug}.py"
    if not controller.exists():
        controller.write_text(
            CONTROLLER_TEMPLATE.format(
                name=spec["name"],
                klass=klass,
                description=spec.get("description", "Generated from a spec; see scripts/make_doctype.py."),
            )
        )
        written.append(controller)

    test = target / f"test_{slug}.py"
    if not test.exists():
        test.write_text(TEST_TEMPLATE.format(name=spec["name"], klass=klass))
        written.append(test)

    return written


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv]
    if not paths:
        print(__doc__)
        return 2

    specs = []
    problems = []
    for path in paths:
        try:
            spec = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            problems.append(f"{path.name}: invalid JSON — {e}")
            continue
        problems.extend(validate_spec(spec, path))
        specs.append(spec)

    if problems:
        print("Specs rejected:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1

    for spec in specs:
        written = write_doctype(spec)
        print(f"{spec['name']:<40} {len(spec['fields']):>3} fields  ->  {written[-1].parent}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
