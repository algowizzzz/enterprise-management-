# Working in this repository — guiding principles

This file is binding on everyone who works here, human or AI. If a change would
break one of the rules in **Non-negotiable rules**, the change is wrong, however
convenient it is.

This repository holds **Consilium**, an enterprise Governance, Risk & Policy
platform (governance forum / committee lifecycle, policy lifecycle, escalation
management), and the deployment toolchain it ships on: the **Frappe framework
running natively on Windows and on Linux with PostgreSQL** — no WSL, no Docker,
no supervisor, no nginx, no gunicorn.

Read [`HANDOVER.md`](HANDOVER.md) for the full picture and
[`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md) before changing anything.

## Non-negotiable rules

1. **No dependency that needs a compiler.** Every Python package in the stack
   must install from a wheel, or from a pure-Python sdist that pip can build
   with no toolchain present. A package that needs a C compiler on the target
   machine does not go in.
2. **No npm or yarn step.** The application must build and run without a package
   manager for the front end. Frappe's own asset bundle is compiled elsewhere
   and committed to [`assets/`](assets/); the runtime never needs node.
3. **No CDN reference anywhere** — not in HTML, not in CSS `@import`, not in a
   template, not in documentation examples that people will copy.
4. **Every external asset is vendored and checksummed.** Front-end libraries are
   committed under `apps/consilium/consilium/public/vendor/`, recorded in
   `VENDOR.md` with version and source, and hashed in `SHA256SUMS`. Adding an
   asset without both entries is incomplete work.
5. **It must install and run with no internet access.** An install that reaches
   the network is a bug, even when the network happens to be available. Note
   that `pip --no-index` still honours `git+https://` direct references — see
   KNOWLEDGE-BASE §2.2.
6. **Windows and Linux parity.** One tree, one set of commands, no per-platform
   fork. Anything that only works on one platform must be isolated behind the
   compatibility layer and must degrade explicitly, not silently.
7. **PostgreSQL only.** No MariaDB/MySQL-specific SQL, schema or assumptions.
8. **Verify by running, never by asserting.** A claim that something works is
   worth nothing without the command and its output. "The API returned 200" is
   not evidence the UI works — a blank-page bug shipped that way once.
9. **No client-identifying content, ever.** No customer or organisation names,
   no individual names, no internal hostnames, system names or project
   codenames, no named third-party products a particular customer happens to
   use, and nothing that identifies a customer by implication. Generic
   enterprise constraints ("no compiler", "no npm", "no internet at install
   time", "corporate proxy", "locked-down workstation") are legitimate and
   belong here; who has them does not.

## Technical invariants

1. **Never fork or edit Frappe's source.** Frappe lives in `<bench>/apps/frappe`
   and must stay pristine so `git pull` keeps working. Windows fixes go in
   `winbench/winbench/compat.py` as runtime patches.
2. **Every compat patch must be a no-op on POSIX.** Start each with
   `if not IS_WINDOWS: return <original>`. This is what lets one codebase serve
   a Windows workstation and a Linux server.
3. **Every patch needs a test** in `tests/test_compat.py` that simulates Windows
   (set `compat.IS_WINDOWS = True` and remove the POSIX API being replaced).
4. **Do not add `PyPika` to `requirements.txt`.** PyPI's PyPika 0.48.9 is a
   different library from Frappe's fork of the same version, and it fails
   silently. See KNOWLEDGE-BASE §2.1.

## Layout

```
apps/consilium/                 the Consilium application (Frappe app)
  consilium/governance/           governance forum & committee lifecycle
  consilium/policy/               policy lifecycle
  consilium/escalation/           escalation management
  consilium/public/vendor/        vendored, checksummed front-end libraries
winbench/winbench/
  cli.py          the `winbench` command (init, new-site, serve, worker, ...)
  compat.py       the 8 runtime patches -- the heart of the port
  worker.py       fork-free RQ worker (Windows has no os.fork)
  procs.py        process supervisor using Windows Job Objects
  services.py     Postgres/Redis/node health checks
  layout.py       bench directory model
scripts/
  bootstrap.ps1             one-shot Windows setup
  check_availability.py     what the network allows
  smoke_test.py             end-to-end check against a running site
  audit_windows_compat.py   static AST audit for POSIX-only code
tests/test_compat.py        20 tests, run anywhere, need no services
assets/                     prebuilt Frappe asset bundle (so node is never needed)
```

## Verify before you claim anything works

```bash
python -m pytest tests/ -q                                   # expect 20 passed
python scripts/smoke_test.py --site <site> --port 8000       # expect 8 passed
python scripts/audit_windows_compat.py <bench>/apps/frappe/frappe --severity BLOCKER
python scripts/check_availability.py --target-windows        # ~25s
```

Expected baselines are tabulated in KNOWLEDGE-BASE §5. If a number differs from
the baseline, investigate before proceeding — do not update the baseline to
match.

## Things that will bite you

- `signal.SIGUSR1`, `os.fork`, `os.nice`, `preexec_fn`, `resource`, and literal
  `/tmp` paths do not exist on Windows. The audit script finds them.
- `pip --no-index` still fetches `git+https://` direct references.
- `pip download --platform` requires `--no-deps` with our flattened requirements.
- Frappe must be installed **editable**, or `winbench build` cannot find
  `package.json`.
- Run exactly one scheduler process, or every scheduled job fires twice.

## Style

Match the existing code: tabs for indentation in Python (Frappe's convention,
which `winbench` follows), docstrings that explain *why* a workaround exists and
what the trade-off is, not just what the code does. Comments in this codebase
carry the institutional memory — keep that standard.
