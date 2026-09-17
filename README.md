# Enterprise Management Platform — Frappe on Windows + PostgreSQL

The foundation for an enterprise governance platform — policy management,
escalation, committee workflow, approvals — built on the
[Frappe framework](https://github.com/frappe/frappe), the open-source platform
ERPNext is built on and a credible ServiceNow alternative.

This repository is the **platform port**: Frappe running **natively on Windows,
on PostgreSQL**, with no WSL, no Docker, no supervisor, no nginx and no
gunicorn. The same tree runs unchanged on Linux and AWS.

Built because Frappe's official install path does not survive an enterprise
network: it is Linux-only, MariaDB-first, and **Frappe is not on PyPI** (the
published package is a 0.0.1 placeholder), so a PyPI mirror does not solve it.

**Status: working, and never yet run on a real Windows machine.** Everything was
verified on Linux; Windows paths are covered by tests that simulate Windows.
Running it on a real laptop is the first job. See
[`HANDOVER.md`](HANDOVER.md) §4.

---

## New here? Read in this order

| # | Document | Why |
|---|---|---|
| 1 | **[`HANDOVER.md`](HANDOVER.md)** | Objective, what we built, what's proven, **what success means**. ~10 min. |
| 2 | **[`docs/RUNBOOK.md`](docs/RUNBOOK.md)** | Step by step, phase by phase, with checkpoints. |
| 3 | **[`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md)** | Glossary, the landmines, why each decision was made. |
| 4 | **[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)** | Symptom → cause → fix. |
| — | [`docs/REPORT.md`](docs/REPORT.md) | The original findings, with evidence. |
| — | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Linux / on-prem / AWS + dependency review. |
| — | [`CLAUDE.md`](CLAUDE.md) | Context for AI agents working in this repo. |

**AI agents: start at [`CLAUDE.md`](CLAUDE.md).**

---

## The 60-second version

Frappe's *framework* is far more portable than its *deployment story*. A static
audit of all of `frappe/` found **only 10 Windows blockers, 6 of them in test
code**. Almost everything Linux-specific lives in `bench`, its CLI.

So we did two things:

1. **Replaced `bench`** with `winbench` — a cross-platform CLI: waitress instead
   of gunicorn, a Windows Job Object supervisor instead of supervisord, nothing
   instead of nginx, and a fork-free background worker.
2. **Patched the 8 remaining incompatibilities at runtime**, before
   `import frappe`. Each is a no-op on POSIX.

**Frappe itself is not forked**, so `git pull` on upstream keeps working.
`winbench doctor` prints exactly which patches are live.

---

## Quick start

### Windows
```powershell
git clone https://github.com/algowizzzz/enterprise-management-.git
cd enterprise-management-
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
- Node 22 + yarn for asset builds only; the runtime needs neither.
- 150 pinned Python packages in [`requirements.txt`](requirements.txt) — all
  resolve from PyPI, and **none needs a C compiler on Windows**.
- Two GitHub URLs that cannot come from PyPI:
  [`requirements-github.txt`](requirements-github.txt).
