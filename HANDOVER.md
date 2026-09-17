# Handover — Frappe on Windows + PostgreSQL

**Read this first.** It assumes you know nothing about this project.
Total read time: about 10 minutes. Then go to [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

---

## 1. What is Frappe, and why do we care?

[Frappe](https://github.com/frappe/frappe) is an open-source, metadata-driven
application framework. ERPNext is built on it. For our purposes the relevant
part is that it ships, out of the box, the primitives an enterprise governance
platform needs — the things you would otherwise buy ServiceNow for:

| Frappe primitive | What we'd use it for |
|---|---|
| **Workflow** (states + transitions + role gates) | Policy exception approvals, sign-off chains |
| **Workflow Action** | Immutable record of who approved what, when |
| **Assignment Rule** | Routing and escalation |
| **Role / Permission / User Permission** | Committee membership, segregation of duties |
| **Version** (audit trail) | Automatic field-level change history |
| **Notification** | Email/alert on state change or SLA breach |
| **DocType** | Define a new record type without writing a migration |
| **Server Script / Client Script** | Business rules without forking the framework |
| **Report / Dashboard / Web Form** | Management reporting, intake forms |

All of the above were tested and are working (see §4).

**The objective:** stand up a Frappe-based governance platform inside BMO —
policy management, escalation, committee workflow — without ServiceNow licensing.

---

## 2. Why this repo exists (the actual problem)

Frappe's official install path does not survive an enterprise network. It
assumes:

- **Linux only.** Developers here are on Windows laptops.
- **`bench`**, its CLI, which shells out through bash and generates
  **supervisor** and **nginx** configs. All POSIX-only.
- **MariaDB**, where our standard is **PostgreSQL**.
- **`git clone` from GitHub**, plus two dependencies pinned to *GitHub URLs*.
- **gunicorn**, a pre-fork server that cannot run on Windows at all.

And critically: **Frappe is not on PyPI.** The package published as `frappe` is
a 0.0.1 placeholder. So an internal Artifactory/Nexus mirror does not solve this
on its own.

**This repo is the workaround.** It makes Frappe run natively on Windows, on
PostgreSQL, with no WSL, no Docker, no supervisor, no nginx and no gunicorn —
and reduces the enterprise ask to **two GitHub URLs**.

---

## 3. What we built

**We did not fork Frappe.** That was a deliberate constraint: a fork means
owning security patches forever. Everything here is either an external launcher
or a runtime patch applied before `import frappe`, so `git pull` on upstream
Frappe keeps working.

Two pieces:

### `winbench` — a cross-platform replacement for `bench`

`bench` is an orchestration layer, not the framework. Frappe itself does not need
it. `winbench` replaces it in ~800 lines of portable Python:

| `bench` does | `winbench` does |
|---|---|
| generates supervisor configs | its own supervisor using **Windows Job Objects** |
| generates nginx configs | nothing — serves `/assets` and `/files` in-process |
| runs gunicorn | **waitress** (pure-Python WSGI, Windows-native) |
| forks a worker per job | **`SimpleWorker` + `TimerDeathPenalty`** (no `fork`) |
| `git clone` to install | also `--from-archive` (a downloaded .zip) |
| assumes PyPI reachable | `--find-links` for a fully offline wheelhouse |

### The compatibility layer — 8 runtime patches

An AST audit of all of `frappe/` found **only 10 Windows blockers, 6 of them in
test code**. The framework is far more portable than its deployment story
suggests. `winbench/winbench/compat.py` patches the rest at import time. Each
patch is a **no-op on POSIX**, which is why the same code runs on Linux.

The one that matters most: `signal.SIGUSR1` in `frappe/__init__.py` is reached
from `frappe.init()` — so it fires on *every* request, job and CLI command. One
line, and nothing works on Windows until it's handled.

Full list and rationale: [`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md).

---

## 4. Status: what is proven, and what is not

### Verified working

Everything below was executed end to end, not reasoned about:

- Site creation on **PostgreSQL 16** (238 tables)
- ORM, query builder, REST API
- **Login and the full Desk UI** over HTTP (screenshots exist)
- Frontend asset build (esbuild)
- Background jobs **without `os.fork()`**
- **A 3-state approval workflow**: Pending → Approve → Approved, with the
  action and an audit Version row written
- Roles, permissions, assignment rules
- `pg_dump` backup, and restore **without the `tar` binary**
- **~190 of Frappe's own tests** against PostgreSQL — 3 failures, none ours
- A **fully offline install** from a downloaded zip with **no `.git` anywhere**
  and **zero network access**

### NOT yet verified — this is your job

> **Nothing has ever run on an actual Windows machine.**

All of the above ran on Linux. Windows-specific code paths are covered by 20
tests that *simulate* Windows (forcing the platform flag and removing the POSIX
APIs), plus an integration check that all 8 patches apply to real Frappe. That
is good evidence, not proof.

**The single most valuable thing you can do on day one is run
`scripts/bootstrap.ps1` on a real BMO laptop and report what breaks.**

Also unverified:
- **PDF generation** — needs the `wkhtmltopdf` binary, which could not be
  installed in our test environment. It has official Windows builds, so this is
  a prerequisite rather than a blocker, but it is unproven.
- The realtime/socket.io server (Node-based; should be fine, not exercised).

---

## 5. What success means

Work through these in order. Each is objectively testable — no judgement calls.

### Phase 0 — Network clearance *(no install; ~25 seconds)*
```bash
python scripts/check_availability.py --target-windows
```
- ✅ **Success:** all 150 PyPI packages resolve, and you know exactly which
  GitHub URLs (if any) are blocked.
- Expected outcome: the 150 pass; the two GitHub URLs may be blocked. That is
  the *expected* result, not a failure — it is the ask for your network team.

### Phase 1 — A running site on one Windows laptop
```powershell
.\scripts\bootstrap.ps1 -BenchPath C:\frappe -SiteName win.localhost
cd C:\frappe; winbench start
python scripts\smoke_test.py --site win.localhost --port 8000
```
- ✅ **Success:** `8 passed, 0 failed`, and you can log into the Desk in a
  browser as `Administrator`.
- This is the real milestone. Everything before it is preparation.

### Phase 2 — Governance primitives work
- ✅ **Success:** you can build a Workflow through the UI, move a document
  through its states, and see a `Workflow Action` and a `Version` row created.
- If this works, the platform can do what we need it to do.

### Phase 3 — The same tree runs on the on-prem Linux server
- ✅ **Success:** identical commands, `winbench doctor` reports
  `(none needed on this platform)`, smoke test passes.
- This proves we are not maintaining a Windows fork.

### Phase 4 — AWS
- ✅ **Success:** running against **RDS PostgreSQL** and **ElastiCache Redis**,
  behind an ALB, with `winbench serve --proxy --no-statics`.
- ⚠️ Run **exactly one** scheduler process across the whole deployment. Frappe's
  scheduler does not elect a leader — two schedulers means every scheduled job
  fires twice.

### Definition of done for this handover
Phases 0–2 complete on one BMO laptop, with a written list of anything that
broke. Phases 3–4 can follow.

---

## 6. Known risks — read before committing to this

| Risk | Severity | Detail |
|---|---|---|
| **PostgreSQL support in v15 is second-class** | **High** | Frappe prints *"PostgreSQL support is limited to Frappe v16 and above. Fixes for earlier versions will not be added"* on every `new-site`. **Recommendation: rebase onto v16 (`develop`) before building modules.** All porting work here is version-agnostic. |
| **Windows workers have no crash isolation** | **Medium** | No `fork`, so a job that segfaults takes its worker down. Mitigation: run several supervised workers. Linux/AWS are unaffected — they keep the fork-based worker. |
| **PyPika fork substitution** | **Medium** | PyPI's PyPika 0.48.9 is a *different library* from Frappe's fork of the same version. It installs cleanly and runs basic queries — it fails **silently**. See the knowledge base. |
| **Never run on Windows** | **Medium** | See §4. Front-load Phase 1. |
| **PDF unproven** | **Low** | Prerequisite binary, not a port issue. |

---

## 7. How to split the work

**For the AI agents:** [`CLAUDE.md`](CLAUDE.md) has the project context, the
invariants that must not be broken, and the verification commands. Point agents
at that first.

Good AI-suited tasks: running the audit against new Frappe apps, extending the
compat layer, writing DocTypes and workflows, expanding the test suite.

**For the humans:**
- Phase 0's network conversation — a person has to make that ask.
- Phase 1 on real hardware, and reporting what breaks.
- The v15-vs-v16 decision (§6). That is an architecture call, not a code change.

**The one invariant:** *do not fork Frappe.* If something needs changing in the
framework, add a patch to `winbench/winbench/compat.py` with a test, and keep it
a no-op on POSIX. The moment we fork, we own Frappe's security patching forever.

---

## 8. Where everything is

| Path | What |
|---|---|
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | **Step-by-step setup.** Start here after this file. |
| [`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md) | Why each decision was made; the landmines; glossary |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Symptom → cause → fix |
| [`docs/REPORT.md`](docs/REPORT.md) | The original findings, with evidence |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Linux / on-prem / AWS, and the dependency review |
| `requirements.txt` | 150 pinned PyPI packages |
| `requirements-github.txt` | The 2 required GitHub URLs (+1 optional) |
| `scripts/` | bootstrap, availability check, smoke test, compat auditor |
| `winbench/` | The CLI and the compatibility layer |
| `tests/` | 20 tests for the compat layer |
