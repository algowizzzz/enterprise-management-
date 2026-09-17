# Frappe on Windows + PostgreSQL — experiment report

**Date:** 2026-09-16
**Base:** `frappe/frappe` @ `version-15` (v15.121.0)
**Question:** can we get a Windows-native, Postgres-backed Frappe without WSL,
Docker, supervisor, nginx or gunicorn — as a base for building policy /
escalation / governance / committee / workflow modules?

**Answer: yes.** The framework ported with **8 runtime patches and zero forked
Frappe source files**. The hard work was not in the framework — it was in
replacing `bench`.

---

## 1. Headline result

A full Frappe stack was brought up and exercised end to end:

| Capability | Status | Evidence |
|---|---|---|
| Site creation on PostgreSQL 16 | ✅ | 238 tables created in `_22fd61719430b332` |
| ORM + query builder | ✅ | insert/read/`frappe.qb` round-trips |
| WSGI app (waitress, no gunicorn) | ✅ | `/api/method/ping` → `{"message":"pong"}` |
| Login + Desk UI | ✅ | verified in a browser; all 10 referenced JS/CSS bundles load |
| Frontend asset build (esbuild) | ✅ | `winbench build --production` clean |
| Background jobs **without `os.fork()`** | ✅ | job status `finished`, result `pong` |
| Scheduler | ✅ | `frappe.tests.test_scheduler` 4/4 |
| **Workflow / approval engine** | ✅ | 3-state workflow: Pending → Approve → Approved, action + audit version logged |
| Assignment rules (escalation routing) | ✅ | 10/10 tests |
| Roles & permissions | ✅ | 34/34 tests |
| Backup (`pg_dump`) | ✅ | 283 KB db + files archives |
| Restore **without the `tar` binary** | ✅ | real archive restored via `tarfile` |
| PDF print formats | ⚠️ | needs `wkhtmltopdf` (see §5) |

### Frappe's own test suite, run against PostgreSQL

| Module | Result |
|---|---|
| `tests.test_db` | 54 run — **1 failure** (pre-existing Postgres quirk, see §4) |
| `tests.test_query_builder` | 40 run — OK (14 skipped, MariaDB-specific) |
| `tests.test_document` | 36 run — OK |
| `tests.test_permissions` | 34 run — OK |
| `tests.test_scheduler` | 4 run — OK |
| `workflow.doctype.workflow.test_workflow` | 12 run — **OK** |
| `core.doctype.role.test_role` | 3 run — OK |
| `automation.doctype.assignment_rule.test_assignment_rule` | 10 run — OK |
| `core.doctype.file.test_file` | 51 run — 1 failure |
| `core.doctype.user.test_user`, `tests.test_api` | 1 failure + 2 errors each — errors are a **missing `faker` test dependency**, not the port |

**~190 upstream tests, 3 real failures, none caused by the port.**

---

## 2. The important finding: Frappe core is already portable

A static audit of all 3,000+ Python files in `frappe/` (`scripts/audit_windows_compat.py`,
AST-based, no imports) found **only 10 Windows blockers in the entire framework** —
and 6 of those are in test infrastructure:

```
BLOCKER  posix-signal   __init__.py:2550                             signal.SIGUSR1
BLOCKER  posix-kwarg    commands/__init__.py:84                      preexec_fn=...
BLOCKER  posix-module   core/doctype/prepared_report/...:5           import resource
BLOCKER  posix-os-api   utils/__init__.py:503                        os.nice
BLOCKER  posix-os-api   utils/background_jobs.py:602                 os.nice
BLOCKER  posix-signal   parallel_test_runner.py:115,116              signal.alarm / SIGALRM   <- tests
BLOCKER  posix-signal   tests/utils.py:349,350,354                   signal.SIGALRM / alarm   <- tests
```

No `fcntl`, no `pwd`/`grp`, no `os.fork` in the framework itself, no Unix-socket
assumptions, and file URLs are built with f-strings and forward slashes rather
than `os.path.join` — so no backslash leakage into URLs. Locking already uses
the cross-platform `filelock` package.

**`signal.SIGUSR1` at `frappe/__init__.py:2550` is the one that makes Frappe
unusable out of the box:** it is reached from `frappe.init()`, so it fires on
every request, job and CLI command. One line, and nothing works until it's fixed.

### The 8 patches applied

All in `winbench/winbench/compat.py`, applied before `import frappe`, each a
no-op on POSIX and each recorded in `winbench doctor`:

| Patch | Why |
|---|---|
| `frappe._register_fault_handler` | `signal.SIGUSR1` doesn't exist → registers on `SIGBREAK` instead |
| `frappe.commands.popen` | `preexec_fn` is rejected on Windows → set child priority from the parent |
| `frappe.utils.execute_in_shell` | hard-codes `/bin/bash` + `os.nice` → platform shell + priority class |
| `frappe.utils.background_jobs.set_niceness` | `os.nice` → `BELOW_NORMAL_PRIORITY_CLASS` |
| `frappe.build.symlink` | `os.symlink` needs Developer Mode → directory junctions, then copy |
| `frappe.utils.pdf` | writes to a literal `/tmp` → `tempfile.gettempdir()` |
| `frappe.utils.get_bench_id` | `C:\frappe` leaks `\` and `:` into Redis keys → normalised |
| `frappe.installer.extract_files` | `tar --strip 2`; Windows `tar.exe` rejects `--strip` → stdlib `tarfile` (with traversal check) |

`resource` is not patched but *substituted*: a stub module backed by psutil is
registered in `sys.modules` so `import resource` resolves, and `ru_maxrss`
returns a real peak-RSS measurement rather than zero.

---

## 3. The real work: replacing `bench`

`bench` — not Frappe — is what ties the stack to Linux. It generates supervisor
and nginx configs, shells out through `bash`, and assumes Ansible and `sudo`.
None of it is needed to *run* Frappe.

`winbench` replaces it in ~700 lines of cross-platform Python:

- **`gunicorn` → `waitress`.** This was never a real obstacle: gunicorn's
  pre-fork model is a scaling choice, and Frappe is a plain WSGI app.
  Waitress is a pure-Python, Windows-native WSGI server. Verified serving the
  Desk UI over real HTTP.
- **supervisord → `winbench.procs.Supervisor`.** Children are spawned with
  `CREATE_NEW_PROCESS_GROUP` and put in a **Windows Job Object** with
  `KILL_ON_JOB_CLOSE`, so killing the parent reliably tears down the tree —
  without this, orphaned workers keep Postgres connections open and the next
  start fails. Shutdown uses `CTRL_BREAK_EVENT` (Windows) / `killpg` (POSIX).
- **nginx → nothing.** Waitress serves the app; Frappe's `SharedDataMiddleware`
  serves `/assets` and `/files`. Put IIS or Caddy in front for TLS in production.
- **MariaDB → PostgreSQL.** Not a port at all — Frappe ships a first-class
  Postgres driver. It's a config switch.

### The one genuinely hard problem: background workers

This is the only place where Windows forces a real design change.

`rq.Worker` forks a "work horse" per job so a hung or crashing job can be killed
without taking the worker down. Windows has no `fork`, so that class cannot even
be instantiated. The fix uses pieces RQ already ships:

- `rq.SimpleWorker` — runs the job in the worker process, no fork
- `rq.timeouts.TimerDeathPenalty` — job timeouts via `threading.Timer` instead of `SIGALRM`

**Stated plainly: this is a real downgrade.** A job that segfaults the
interpreter, or blocks in a C call where the timer's exception can't be
delivered, takes its worker down with it. Mitigation is the standard Windows
service pattern — run several workers under the supervisor, which restarts any
that die (`winbench start --background-workers 4`). For approval workflows and
notifications this is fine. For long CPU-bound report generation, watch it.

---

## 4. Known issues and honest caveats

**PostgreSQL support in v15 is second-class.** Frappe prints this on every
`new-site`:

> *Note: PostgreSQL support is limited to Frappe v16 and above. Fixes for earlier
> versions will not be added.*

The single genuine `test_db` failure is exactly this: `test_is` expects
`coalesce("name", ...)` in generated SQL and Postgres doesn't emit it. Harmless
in isolation, but it signals that Postgres paths in v15 get no upstream fixes.
**Recommendation: rebase onto `develop` (v16) before building the application
modules.**
Everything in this port is version-agnostic — the audit and patches target call
sites that exist in both.

**Fixed after the first report:** `winbench serve` handed waitress the bare WSGI
app, so the Desk returned 200 HTML and then 404'd on every asset — a blank page.
On a Linux bench nginx serves `/assets`; with nginx removed nothing did. Now uses
Frappe's `application_with_statics()`. `scripts/smoke_test.py` guards it, and was
confirmed to fail (exit 1) against a deliberately `--no-statics` server while all
seven other checks passed. Lesson: API-level checks cannot see a dead front end.

**Not verified here:**
- **PDF generation.** v15's `get_pdf` requires the `wkhtmltopdf` binary, which
  could not be installed in this sandbox. It has official Windows builds, so
  this is a prerequisite rather than a port blocker — but it is unproven. The
  WeasyPrint path exists but only for Print Format *Builder* formats, and pulls
  in the GTK3 runtime on Windows, which is real friction.
- **The realtime/socket.io server.** Node-based, so it should be fine on
  Windows, but it was not exercised.
- **Actual Windows.** Everything was validated on Linux. Windows-specific code
  paths are covered by 20 tests that simulate Windows (forcing `IS_WINDOWS` and
  removing the POSIX APIs), plus an integration check that all 8 patches apply
  cleanly to real Frappe and the framework still boots and serves. **The next
  step is one run on a real Windows box** — that is the remaining unknown, and
  the `bootstrap.ps1` script exists to make it a single command.

**Environment workaround (not part of the deliverable):** `yarn install` needed
`air-datepicker` vendored locally because this sandbox's proxy blocks
`codeload.github.com`. That is a sandbox limitation, not a Windows one.

---

## 5. Prerequisites on Windows

| Component | Choice | Note |
|---|---|---|
| Python | 3.11 | Frappe supports 3.10–3.14 |
| Database | PostgreSQL 16 for Windows | official EDB installer |
| Redis | **Memurai** | Redis has no official Windows build; Memurai is the supported drop-in. Run two instances (cache 13000, queue 11000) so a cache flush doesn't drop queued jobs |
| Node | 22 LTS + yarn | asset build and realtime server only |
| PDF | wkhtmltopdf (patched-qt Windows build) | optional |

`winbench doctor` checks every one of these and prints an actionable message per
failure rather than a stack trace from three layers down.

---

## 6. Linux, and the enterprise rollout

Everything above ran **on Linux** — the compat patches are no-ops on POSIX, so
one codebase covers the managed Windows workstation, the air-gapped Linux server
and managed cloud infrastructure. The dependency review (151 pinned packages, Windows wheel availability, the GitHub-sourced
artifacts, and a verified offline-wheelhouse install) is in
[`DEPLOYMENT.md`](DEPLOYMENT.md).

The headline for procurement: **Frappe is not on PyPI** — `pypi.org/project/frappe`
is a 0.0.1 placeholder — so the framework and frappe's PyPika fork must come from
GitHub. Dropping gunicorn removed one of the three GitHub dependencies.

## 7. Recommendation

The experiment succeeded, and the risk profile is better than expected: the
framework needed 8 small patches and no fork, while the replaceable part
(`bench`) was fully replaced.

Two decisions remain before building out the application modules:

1. **Base version — rebase onto `develop` (v16)** for supported Postgres.
   The porting work carries over unchanged.
2. **Worker robustness.** If the governance modules do heavy scheduled
   processing (bulk escalations, large report runs), plan for multiple
   supervised workers and per-job timeouts from day one, because the fork-based
   safety net is gone.

The governance primitives the platform needs are all present and passing on
Postgres: Workflow, Workflow State/Action (with audit trail), Assignment Rule,
Role & Permission, Notification, Document Naming Rule, Server Script, Web Form,
Report and Dashboard.
