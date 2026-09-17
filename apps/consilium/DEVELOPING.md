# Developing Consilium

For engineers adding to this application. Read `docs/product/05-glossary.md`
first if the domain vocabulary is new to you, then `docs/product/02-data-model.md`.

---

## Layout

```
apps/consilium/
  consilium/
    consilium_core/    shared entities and the engines every module uses
    governance/        governance forum and committee lifecycle
    policy/            policy lifecycle
    escalation/        escalation intake, routing and resolution
    public/            stylesheets, scripts, vendored libraries
    templates/         Jinja layouts
    www/               portal pages
  specs/               entity specifications, one JSON file per entity
  scripts/             the generator and the checkers
```

The shared module is called **`Consilium Core`**, not `Core`. Module names in
this framework are global to a site, and the framework already owns `Core`.
Naming ours `Core` makes the framework resolve its own entities to our app and
the site fails to install. This is not a style preference.

---

## Adding an entity

Entities are **generated from specs**, never written by hand.

1. Write `specs/<module>/<entity_name>.json`. Copy the shape from an existing
   one — `specs/consilium_core/risk_category.json` is a good short example,
   `organization_unit.json` shows a tree.

2. Generate:
   ```
   python scripts/make_doctype.py specs/<module>/<entity_name>.json
   ```
   This writes the entity definition, a controller and a test file. It will not
   overwrite a controller or test you have already edited.

3. Migrate, then look at the real table:
   ```
   FRAPPE_BENCH_ROOT=<bench> python -m frappe.utils.bench_helper frappe \
       --site <site> migrate
   psql -d <db> -c '\d "tab<Entity Name>"'
   ```

The generator rejects specs that declare a framework-maintained field, name a
link target that does not exist, duplicate a field name, or put a child table on
a child table. Those are all mistakes that migrate cleanly and fail later.

**Why generate.** Entity definitions are long, and small inconsistencies between
them cause disproportionate trouble: a missing `search_fields` makes a link field
unusable in a picker, a missing permission row locks a role out of something
nobody notices for weeks. The spec carries the decisions; the generator supplies
the boilerplate and the house conventions.

---

## Rules that are enforced, not merely encouraged

`python scripts/check_platform_rules.py` fails the build on each of these. CI
runs it first, because it needs no dependencies.

### Nothing branches on a workflow state string

```python
# No.
if self.compliance_status == "Pending":
    ...

# Yes.
if self.requires_review:
    ...
```

Workflow states are configuration. A state renamed, or an approval step inserted,
should be an afternoon's configuration rather than a code change — and it only is
if no logic depends on the state's name. Core maintains the semantic flags
(`is_editable`, `is_active`, `requires_review`, and others) from a mapping table.

When you add a workflow state, add its `Workflow State Flag` row to
`consilium_core/setup/state_flag_seed.py`. If you do not, `apply_state_flags`
throws on the unmapped state rather than leaving stale flags — deliberately, so
the omission surfaces immediately rather than as a permission that quietly stops
working.

### Nothing is fetched at run time

No CDN references, no external fonts, no package manager in the build. The target
environment has no internet access, so anything fetched at run time is not slow
there, it is absent. Front-end libraries are vendored under `public/vendor/` with
recorded checksums.

To upgrade a vendored library: download the published distribution, replace the
files, update `VENDOR.md` and regenerate `SHA256SUMS`. Do not add a package
manager to do this.

### Nothing identifies a client

This repository is public. No organisation names, no personal names, no
commercial product names — in code, comments, field labels, fixtures, test data
or commit messages. Where a category of external system must be referred to, name
the category: "an external AI services platform", "a GRC platform".

---

## Use the Core engines

Do not write a second implementation of any of these. They exist once, in
`consilium_core/`, because all three modules need them and three
implementations means three subtly different answers to the same question.

| Need | Use |
|---|---|
| Versioning, revert | `versioning.py` |
| Periodic attestation | `attestation.py` |
| Retention, legal hold, disposal | `retention.py` |
| Decision rules from data | `classification.py` |
| Notifications | the notification layer and its channel adapters |
| Time limits and breaches | the SLA clock and business calendar |
| File import and export | the import pipeline |
| Semantic workflow flags | `state_flags.py` |

---

## Testing

```
FRAPPE_BENCH_ROOT=<bench> python -m frappe.utils.bench_helper frappe \
    --site <site> run-tests --app consilium
```

Testing is disabled on a new site; set `allow_tests` to true once.

Every entity needs create, read, update, permission and validation coverage.
Every behaviour needs its **failure** path tested, not only its happy path — a
test that only proves the good case passes tells you nothing about the control
you just wrote. Permission tests must attempt the action as a role that should
not be allowed it, and assert the refusal.

Prefer a test that exercises the real database over one that mocks it. The
schema is where most of the surprises live.

---

## Working on several modules at once

Modules are developed independently and migrated together. If you are working on
one module while someone else works on another:

- Stay inside your own module directory and your own specs directory.
- Do not edit `hooks.py`, `modules.txt` or anything in `consilium_core/`.
  Ask for the change instead.
- Use your own site and your own database, so a migration you break is yours
  alone.

A Link to an entity another module owns is fine and expected. It will not resolve
until both modules are migrated into the same site, which is the integration
step — not a reason to create a duplicate of somebody else's entity.
