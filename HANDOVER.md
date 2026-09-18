# Handover — Consilium and its deployment toolchain

**Read this first.** It assumes you know nothing about this project, and is
written for an engineering and deployment team picking it up cold.
Total read time: about 10 minutes. Then go to [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

---

## 0. What the product is

**Consilium** is an enterprise Governance, Risk & Policy platform. It has three
modules on one platform, one data model, one permission model and one audit
trail:

- **Governance** — governance forum and committee lifecycle: membership,
  agendas, meetings, decisions, minutes, follow-up actions.
- **Policy** — policy lifecycle: intake, drafting, review, approval,
  publication, attestation, retirement.
- **Escalation** — escalation intake, routing, ownership, SLA tracking and
  resolution.

It is built on the Frappe framework with PostgreSQL, and must install and run in
an environment with **no internet access** — both on a managed corporate Windows
workstation (development, and small deployments) and on an air-gapped Linux
server (staging and production).

The application code is in [`apps/consilium/`](apps/consilium/). The rest of
this document is about the **deployment toolchain** that gets it installed and
running, which is the larger and harder part of the repository.

---

## 1. What is Frappe, and why build on it?

[Frappe](https://github.com/frappe/frappe) is an open-source, metadata-driven
application framework. ERPNext is built on it. For our purposes the relevant
part is that it ships, out of the box, the primitives a governance platform
needs — the ones you would otherwise buy a commercial GRC platform for:

| Frappe primitive | What Consilium uses it for |
|---|---|
| **Workflow** (states + transitions + role gates) | Policy approvals and exceptions, sign-off chains |
| **Workflow Action** | Immutable record of who approved what, when |
| **Assignment Rule** | Escalation routing |
| **Role / Permission / User Permission** | Committee membership, segregation of duties |
| **Version** (audit trail) | Automatic field-level change history |
| **Notification** | Email/alert on state change or SLA breach |
| **DocType** | Define a new record type without writing a migration |
| **Server Script / Client Script** | Business rules without forking the framework |
| **Report / Dashboard / Web Form** | Management reporting, intake forms |

All of the above were tested and are working (see §4).

**The objective:** run this governance platform inside a restricted enterprise
network — policy management, escalation, committee workflow — on infrastructure
the deploying organisation already runs, with no per-seat licensing of a
commercial GRC product.

---

## 2. Why the toolchain exists (the actual problem)

Frappe's official install path does not survive a locked-down enterprise
network. It assumes:

- **Linux only.** Development is expected to happen on managed Windows laptops.
- **`bench`**, its CLI, which shells out through bash and generates
  **supervisor** and **nginx** configs. All POSIX-only.
- **MariaDB**, where the standard for this platform is **PostgreSQL**.
- **`git clone` from GitHub**, plus two dependencies pinned to *GitHub URLs*.
- **gunicorn**, a pre-fork server that cannot run on Windows at all.

And critically: **Frappe is not on PyPI.** The package published as `frappe` is
a 0.0.1 placeholder. So an internal package mirror does not solve this on its
own.

**The toolchain in this repo is the workaround.** It makes Frappe run natively
on Windows, on PostgreSQL, with no WSL, no Docker, no supervisor, no nginx and
no gunicorn — and reduces the ask on a corporate network to **two GitHub URLs**
(or zero, via the offline path in §5).

---

## 3. What was built

**Frappe is not forked.** That was a deliberate constraint: a fork means owning
security patches forever. Everything here is either an external launcher or a
runtime patch applied before `import frappe`, so `git pull` on upstream Frappe
keeps working.

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

### The application, at release 1.0.0 (2026-09-18)

The build is finished. Everything below was measured on a clean site, not
asserted.

- **Tests:** 1453 application tests, OK (0 failures, 0 errors, 1433 s).
  `pytest tests/` 57 passed. Interface sweep (`scripts/ui_regression.py`) 302
  passed, 0 failed.
  Browser journeys (`scripts/browser_journeys.py`) 11/11. Platform rules
  (`scripts/check_platform_rules.py`) 6/6.
- **Size:** 144 entities (Core 64, Governance 24, Policy 38, Escalation 18),
  378 PostgreSQL tables on the demonstration site, 11 scheduled jobs. A
  scratch DocType, `ABC`, is untracked in
  `apps/consilium/consilium/consilium_core/doctype/abc/` and installed on the
  demonstration site. It is not product code and is not counted here. Remove
  it before the final commit and the bundle build.
- **Demonstration data:** `deploy/demo_data.py` rebuilds the demonstration site
  from scratch in about 27 s, idempotently, with no failed section. It holds 14
  forums, 15 governing documents, 157 versions, 15 escalations, 67 meetings, 24
  motions, 137 votes, 92 attestation tasks and 23 personas. Passwords are never
  committed: `deploy/demo_logins.py` issues random ones per run into a file
  outside the repository (see
  [`docs/delivery/DEMO-LOGINS.md`](docs/delivery/DEMO-LOGINS.md)).
- **Interface:** a two-row header with global search ("/" or Ctrl/Cmd+K,
  permission-filtered) and role-filtered menus: Home, My work, Governance,
  Policies, Escalations, Insights, Admin. Lists export to CSV.
- **Integrations:** Admin → Integrations (`/integrations`) connects:
  - the AI endpoint, which is tested end to end against an OpenAI-compatible
    provider; the help assistant answers with citations;
  - the external document editor ("Open in Doc AI");
  - the horizon-scanning platform;
  - e-mail over SMTP or Microsoft Graph.

  It also shows the single sign-on redirect URI.
- **Deployment kit:** rehearsed air-gapped on Rocky Linux 9, with `verify.sh`
  14/14 after install and after upgrade. See
  [`docs/delivery/DEPLOYMENT-READINESS.md`](docs/delivery/DEPLOYMENT-READINESS.md).
- **Requirement coverage and backlog:**
  [`docs/delivery/REQUIREMENTS-COVERAGE.md`](docs/delivery/REQUIREMENTS-COVERAGE.md)
  and [`docs/delivery/EPICS.md`](docs/delivery/EPICS.md). The index of every
  delivery document is [`docs/delivery/README.md`](docs/delivery/README.md).

**Known gaps still open:**

- On the desk, a reviewer cannot return a document to drafting. The portal can.
- Voting has no attendance entry.
- Time To First Action is not shown.
- No real Windows run.
- No RHEL 8 or Ubuntu 22.04 rehearsal.
- Python 3.11 on x86_64 is required: the framework's `hiredis` pin blocks 3.12,
  and `psutil` blocks ARM.
- Real certificates, the identity provider, the mail route (an SMTP relay or a
  Microsoft Graph app registration) and load testing need the target
  environment.
- The offline bundle must be rebuilt from the final commit.

### The toolchain: verified working

Everything below was executed end to end, not reasoned about:

- Site creation on **PostgreSQL 16** (238 tables)
- ORM, query builder, REST API
- **Login and the full Desk UI** over HTTP
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

All of the above ran on Linux. Windows-specific code paths are covered by 22
tests that *simulate* Windows (forcing the platform flag and removing the POSIX
APIs), plus an integration check that all 8 patches apply to real Frappe. That
is good evidence, not proof.

**The single most valuable thing you can do on day one is run
`scripts/bootstrap.ps1` on a managed corporate Windows laptop and report what
breaks.**

Also unverified:
- **PDF generation on Windows.** On Linux it is now proven: the bundle carries
  `wkhtmltopdf`, and `verify.sh` renders a governing document to PDF on the
  Rocky Linux 9 rehearsal host. On Windows it needs the official Windows build
  of the binary, so it is a prerequisite rather than a blocker, but it is
  unproven there.
- The realtime/socket.io server (Node-based; should be fine, not exercised).

---

## 5. How to install and run it

Full step-by-step instructions, with checkpoints, are in
[`docs/RUNBOOK.md`](docs/RUNBOOK.md); deployment-target detail is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). In outline:

**Prerequisites:** Python 3.11, PostgreSQL 16, and a Redis-compatible server
(Memurai on Windows — Redis has no official Windows build). Node is *not*
needed: a prebuilt Frappe asset bundle is committed in `assets/`.

**Connected install (Windows):**
```powershell
.\scripts\bootstrap.ps1 -BenchPath C:\frappe -SiteName win.localhost
cd C:\frappe; winbench start
```

**Offline install (no git, no PyPI, no internet):** build a wheelhouse and
download the Frappe archive on a connected machine, transfer both, then
```powershell
winbench init C:\frappe --from-archive C:\Downloads\frappe-v15.121.0.zip --find-links C:\wheelhouse
winbench new-site win.localhost
winbench assets --import assets/frappe-assets-v15.121.0.tar.gz --copy
winbench start
```

**Linux — identical commands**, with `pip install -e winbench/` first. The
compatibility patches are inert there, so you are running stock Frappe with a
different launcher.

---

## 6. What success means

Work through these in order. Each is objectively testable — no judgement calls.

### Phase 0 — Network clearance *(no install; ~25 seconds)*
```bash
python scripts/check_availability.py --target-windows
```
- ✅ **Success:** all 145 PyPI packages resolve, and you know exactly which
  GitHub URLs (if any) are blocked.
- Expected outcome: the 145 pass; the two GitHub URLs may be blocked. That is
  the *expected* result, not a failure — it is the ask for the network team, and
  the offline path in §5 avoids it entirely.

### Phase 1 — A running site on one Windows workstation
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
- If this works, the platform can carry Consilium's approval and audit
  requirements.

### Phase 3 — The same tree runs on the air-gapped Linux server
- ✅ **Success:** identical commands, `winbench doctor` reports
  `(none needed on this platform)`, smoke test passes, and the install made no
  network connections.
- This proves there is no Windows fork to maintain.

### Phase 4 — Managed cloud infrastructure (optional)
- ✅ **Success:** running against a managed PostgreSQL service and a managed
  Redis service, behind a load balancer, with
  `winbench serve --proxy --no-statics`.
- ⚠️ Run **exactly one** scheduler process across the whole deployment. Frappe's
  scheduler does not elect a leader — two schedulers means every scheduled job
  fires twice.

### Definition of done for this handover
Phases 0–2 complete on one managed Windows laptop, with a written list of
anything that broke. Phases 3–4 can follow.

---

## 7. Known risks — read before committing to this

| Risk | Severity | Detail |
|---|---|---|
| **PostgreSQL support in v15 is second-class** | **High** | Frappe prints *"PostgreSQL support is limited to Frappe v16 and above. Fixes for earlier versions will not be added"* on every `new-site`. **Recommendation: rebase onto v16 (`develop`) before building modules.** All porting work here is version-agnostic. |
| **Windows workers have no crash isolation** | **Medium** | No `fork`, so a job that segfaults takes its worker down. Mitigation: run several supervised workers. Linux deployments are unaffected — they keep the fork-based worker. |
| **PyPika fork substitution** | **Medium** | PyPI's PyPika 0.48.9 is a *different library* from Frappe's fork of the same version. It installs cleanly and runs basic queries — it fails **silently**. See the knowledge base. |
| **Never run on Windows** | **Medium** | See §4. Front-load Phase 1. |
| **PDF unproven** | **Low** | Prerequisite binary, not a port issue. |

---

## 8. How to split the work

**For AI agents:** [`CLAUDE.md`](CLAUDE.md) has the repository's binding rules,
the technical invariants, and the verification commands. Point agents at that
first.

Good AI-suited tasks: running the audit against new Frappe apps, extending the
compat layer, writing Consilium DocTypes and workflows, expanding the test
suite.

**For the humans:**
- Phase 0's network conversation — a person has to make that ask.
- Phase 1 on real hardware, and reporting what breaks.
- The v15-vs-v16 decision (§7). That is an architecture call, not a code change.

**The one invariant:** *do not fork Frappe.* If something needs changing in the
framework, add a patch to `winbench/winbench/compat.py` with a test, and keep it
a no-op on POSIX. The moment we fork, we own Frappe's security patching forever.

---

## 9. Where everything is

| Path | What |
|---|---|
| [`apps/consilium/`](apps/consilium/) | **The Consilium application** — governance, policy, escalation |
| [`docs/product/`](docs/product/) | Requirements, data model, PostgreSQL schema, architecture, glossary |
| [`docs/delivery/EPICS.md`](docs/delivery/EPICS.md) | Delivery backlog: epics and stories |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | **Step-by-step setup.** Start here after this file. |
| [`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md) | Why each decision was made; the landmines; glossary |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Symptom → cause → fix |
| [`docs/REPORT.md`](docs/REPORT.md) | The original porting findings, with evidence |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Windows, air-gapped Linux, cloud, and the dependency review |
| `requirements.txt` | 150 pinned PyPI packages |
| `requirements-github.txt` | The 2 required GitHub URLs (+1 optional) |
| `scripts/` | bootstrap, availability check, smoke test, compat auditor |
| `winbench/` | The CLI and the compatibility layer |
| `assets/` | Prebuilt Frappe asset bundle, so no machine needs node |
| `tests/` | 57 toolchain tests: 22 for the compat layer, the deployment kit (Microsoft Graph keys included), the install layout |
