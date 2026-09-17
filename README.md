# Consilium — Enterprise Governance, Risk & Policy

**Consilium** is an enterprise Governance, Risk & Policy platform. Three modules
under one platform, sharing one data model, one permission model and one audit
trail:

| Module | What it covers |
|---|---|
| **Governance** | Governance forum and committee lifecycle — membership, agendas, meetings, decisions, minutes, follow-up actions |
| **Policy** | Policy lifecycle from intake through drafting, review, approval, publication, attestation and retirement |
| **Escalation** | Escalation intake, routing, ownership, SLA tracking and resolution |

Consilium is built on the [Frappe framework](https://github.com/frappe/frappe)
with **PostgreSQL**, and is designed for environments where installation happens
**without internet access**. It deploys to an **air-gapped Linux server** and to
**Windows**, from the same tree, with the same commands.

The application itself lives in [`apps/consilium/`](apps/consilium/). Every
front-end asset it uses is vendored and checksummed — there is no CDN reference,
no npm or yarn step, and no dependency that needs a compiler.

---

## The deployment foundation

Consilium ships on a deployment toolchain that is part of this repository. That
toolchain is what makes an offline, Windows-and-Linux install possible at all,
and the rest of this README describes it.

The problem it solves: Frappe's official install path does not survive a
locked-down enterprise network. It is Linux-only, MariaDB-first, assumes
`git clone` from GitHub, and **Frappe is not on PyPI** (the published package is
a 0.0.1 placeholder), so a PyPI mirror does not solve it either.

So this repository also contains the **platform port**: Frappe running
**natively on Windows, on PostgreSQL**, with no WSL, no Docker, no supervisor,
no nginx and no gunicorn. The same tree runs unchanged on Linux.

---

## Current state

What is built and verified, and what is not. Everything in the first list was
run, not reasoned about.

**Verified working**

- **The application.** 57 entities in the shared Core module, with the engines
  the three business modules depend on: document versioning and revert,
  attestation, retention and legal hold, the classification rules engine,
  notifications, imports and SLA timing. 293 tests pass against a real
  PostgreSQL database.
- **Offline installation.** A single bundle carries every dependency as a built
  wheel, the framework, the application, prebuilt front-end assets and the
  installation tooling. It has been installed into a clean target **with every
  proxy variable pointed at a dead port**, so nothing could have reached the
  network. 15/15 health checks pass, the site serves, and all 44 asset bundles
  the interface references return 200.
- **Backup and restore.** Rehearsed: a backup taken, restored into a separate
  empty database, and verified by row count and by the health check on the
  restored site.
- **The interface foundation.** Design tokens, light and dark themes, a
  text-size control, and a table component doing pagination, sorting and search
  in the database rather than the browser. Verified in a real browser.
- **The platform rules**, enforced by a check that fails the build: no CDN
  reference, no package manager in the build, vendored files matching their
  checksums, no client-identifying content, and no business logic branching on a
  workflow state name.

**Not yet done**

- The three business modules are in progress; Core is complete.
- The screens are not built. The foundation they sit on is.
- No migration rehearsal on a target server. The framework describes its
  PostgreSQL support as second-class in this major version and three divergences
  between the two database backends are already known; there is no basis for
  assuming that list is complete. **This is the largest remaining unknown** and
  it can only be closed on the target.
- No load rehearsal, and no measured accessibility contrast audit.
- Certificates, ports and service accounts are undecided.

`docs/delivery/DEPLOYMENT-READINESS.md` is the full checklist.

---

## New here? Read in this order

| # | Document | Why |
|---|---|---|
| 1 | **[`HANDOVER.md`](HANDOVER.md)** | Objective, what was built, what's proven, **what success means**. ~10 min. |
| 2 | **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)** | Step by step, phase by phase, with checkpoints. |
| 3 | **[`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md)** | Glossary, the landmines, why each decision was made. |
| 4 | **[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)** | Symptom → cause → fix. |
| — | [`docs/REPORT.md`](docs/REPORT.md) | The original porting findings, with evidence. |
| — | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Deploying to Windows, an air-gapped Linux server and cloud, plus the dependency review. |
| — | [`docs/product/`](docs/product/) | The product documentation: requirements, data model, schema, architecture, glossary. |
| — | [`docs/delivery/EPICS.md`](docs/delivery/EPICS.md) | The delivery backlog: epics and stories with acceptance criteria. |
| — | [`CLAUDE.md`](CLAUDE.md) | The binding engineering principles for this repository. |

**Working in this repo, human or AI: start at [`CLAUDE.md`](CLAUDE.md).**

---

## The 60-second version of the port

Frappe's *framework* is far more portable than its *deployment story*. A static
audit of all of `frappe/` found **only 10 Windows blockers, 6 of them in test
code**. Almost everything Linux-specific lives in `bench`, its CLI.

So the port does two things:

1. **Replaces `bench`** with `winbench` — a cross-platform CLI: waitress instead
   of gunicorn, a Windows Job Object supervisor instead of supervisord, nothing
   instead of nginx, and a fork-free background worker.
2. **Patches the 8 remaining incompatibilities at runtime**, before
   `import frappe`. Each is a no-op on POSIX.

**Frappe itself is not forked**, so `git pull` on upstream keeps working.
`winbench doctor` prints exactly which patches are live.

---

## Quick start

### Windows
```powershell
git clone <this-repository-url>
cd consilium
.\scripts\bootstrap.ps1 -BenchPath C:\frappe -SiteName win.localhost
cd C:\frappe
winbench start
```

### Where git and PyPI are blocked
```powershell
winbench init C:\frappe --from-archive C:\Downloads\frappe-v15.121.0.zip --find-links C:\wheelhouse
```
Verified: builds a working bench from a downloaded zip with no `.git` anywhere
and **zero network access**. The two GitHub URLs you need are in
[`requirements-github.txt`](requirements-github.txt).

### Linux / macOS — identical commands
```bash
pip install -e winbench/
winbench init ~/frappe-bench && cd ~/frappe-bench
winbench doctor          # "(none needed on this platform)"
winbench new-site my.localhost
winbench build --production
winbench start
```

---

## Checking things

```bash
python scripts/check_availability.py --target-windows   # what your network allows (~25s)
python scripts/smoke_test.py --site <site> --port 8000  # 8 end-to-end checks
python scripts/audit_windows_compat.py apps/<app>       # POSIX-only code in an app
python -m pytest tests/ -q                              # 20 compat-layer tests
```

`smoke_test.py` fetches every JS/CSS bundle the Desk references — without nginx,
an asset regression leaves a blank page while every API check still returns 200.

---

## Command mapping

| `bench` | `winbench` | Note |
|---|---|---|
| `bench init` | `winbench init` | also `--from-archive`, `--find-links` |
| `bench new-site` | `winbench new-site` | PostgreSQL only |
| `bench --site X migrate` | `winbench migrate` | unchanged |
| `bench build` | `winbench build` | symlinks → junctions |
| *(none)* | `winbench assets` | import the committed prebuilt bundle — **no node needed** |
| `bench start` | `winbench start` | own supervisor, no Procfile |
| `bench serve` | `winbench serve` | waitress; `--proxy`, `--no-statics` |
| `bench worker` | `winbench worker` | no `os.fork()` |
| `bench schedule` | `winbench scheduler` | run exactly one |
| `bench setup supervisor` / `nginx` | *(gone)* | not needed |
| `bench doctor` | `winbench doctor` | + compat patch report |

---

## Requirements

- **Python 3.11**, **PostgreSQL 16**, and a Redis-compatible server
  (**Memurai** on Windows — Redis has no official Windows build).
- Node 22 + yarn for Frappe's own asset builds only — **and a prebuilt bundle is
  committed in [`assets/`](assets/)**, so you can skip node entirely:
  `winbench assets --import assets/frappe-assets-v15.121.0.tar.gz --copy`.
  Verified with node absent from `PATH` and `node_modules` deleted. The
  Consilium app itself has no build step at all.
- 150 pinned Python packages in [`requirements.txt`](requirements.txt) — all
  resolve from PyPI, and **none needs a C compiler on Windows**.
- Two GitHub URLs that cannot come from PyPI:
  [`requirements-github.txt`](requirements-github.txt).
