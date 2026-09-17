# Runbook — from nothing to a running Frappe site

Follow in order. Each phase ends with a **checkpoint** you can objectively pass
or fail. If a checkpoint fails, go to [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
before continuing — later phases assume earlier ones passed.

Read [`../HANDOVER.md`](../HANDOVER.md) first if you haven't.

---

## Phase 0 — Find out what your network allows

**Do this before installing anything.** It takes ~25 seconds and writes nothing
outside a temp directory.

```bash
git clone https://github.com/algowizzzz/enterprise-management-.git
cd enterprise-management-
python scripts/check_availability.py --target-windows
```

The script drives pip against **whatever index you have configured**, so an
internal Artifactory/Nexus mirror is exercised exactly as a real install would
exercise it.

### Reading the output

```
  [ok  ] PyPI packages -- 143 win_amd64 wheels + 7 pure-Python sdists
  [FAIL] frappe framework -- HTTP 403
  [FAIL] PyPika (frappe fork) -- HTTP 403
  [warn] air-datepicker (npm) -- HTTP 403
```

- `[ok]` on PyPI packages → **the hard part is done.** All 150 dependencies are
  reachable, and none needs a C compiler on Windows.
- `[FAIL]` on the two GitHub items → **expected, and not a dead end.** This is
  precisely the ask for your network team (see below).
- `[warn]` → optional. Not a blocker.

### Checkpoint 0
> ✅ You know whether the 150 PyPI packages resolve, and which of the GitHub
> URLs are blocked.

### If the GitHub URLs are blocked

Three options, in order of preference:

1. **Ask for an allowlist exception** for `github.com/frappe/*`, ideally scoped
   to one build machine. Narrow, auditable, and keeps `git pull` working for
   security updates. *This is the recommended route.*
2. **Vendor into Artifactory.** Publish `frappe` and the PyPika fork as internal
   packages. Your enterprise probably already has this pattern.
3. **Manual download + offline wheelhouse** (Phase 1b). Works today with no
   network exception at all, but you own patching.

The two URLs, and what to do with each, are in
[`../requirements-github.txt`](../requirements-github.txt).

---

## Phase 1 — A running site on a Windows laptop

### Prerequisites

| Component | How | Needed for |
|---|---|---|
| Python 3.11 | `winget install Python.Python.3.11` | everything |
| PostgreSQL 16 | `winget install PostgreSQL.PostgreSQL.16` | everything |
| **Memurai** | <https://www.memurai.com> | everything (Redis has no official Windows build) |
| Node 22 + yarn | `winget install OpenJS.NodeJS.LTS` | asset build only |
| wkhtmltopdf | official Windows build | PDF print formats only |

**Redis note:** Frappe wants two logical instances — cache on **13000**, queue on
**11000**. One works, but flushing the cache would also drop queued jobs.
Configure two Memurai instances.

**Choosing a bench path:** keep it short, no spaces, and **not** on OneDrive or
any sync client — Frappe's asset tree is deep and file-locking sync clients
corrupt builds. `C:\frappe` is a good choice.

### 1a — Normal install (network reachable)

```powershell
cd enterprise-management-
.\scripts\bootstrap.ps1 -BenchPath C:\frappe -SiteName win.localhost
```

That installs prerequisites via winget, creates the bench, runs `winbench
doctor`, creates the site and builds assets. It will prompt for the
Administrator password and the Postgres superuser password.

### 1b — Restricted install (no git, no PyPI, no network)

**On a connected machine**, build the transfer bundle:

```bash
# 1. the dependency wheelhouse (~230 MB)
pip download -r requirements.txt -d wheelhouse

# 2. the PyPika FORK -- see the warning in the knowledge base
pip wheel --no-deps -w wheelhouse \
  "PyPika @ git+https://github.com/frappe/pypika@2c50e6142b2d61d2d243e466fdd5dc03b3d918f2"
rm -f wheelhouse/PyPika-*.tar.gz      # drop the upstream sdist pip also pulls

# 3. the framework itself -- a plain browser download works
#    https://github.com/frappe/frappe/archive/refs/tags/v15.121.0.zip
```

Copy `wheelhouse/`, the zip, and this repo to the target machine, then:

```powershell
pip install -e .\winbench
winbench init C:\frappe --from-archive C:\Downloads\frappe-v15.121.0.zip --find-links C:\wheelhouse
```

Verified: this completes with **zero GitHub contacts** and produces a working
bench. `--from-archive` works because Frappe builds with flit, which reads its
version from `frappe/__init__.py` rather than from git metadata.

### 1c — Create the site and build assets

```powershell
cd C:\frappe
winbench doctor                      # every service must be [ok]
winbench new-site win.localhost
winbench build --production
winbench start
```

> ### ⚠️ If `winbench build` / yarn fails, you are not blocked
>
> **This is the step most likely to fail on a corporate network**, and it is the
> only step that needs node and yarn. Assets are static build output — compile
> them once anywhere, and move them. **The runtime never needs node or yarn.**
>
> ```powershell
> # on any machine that has working node + yarn
> winbench build --production
> winbench assets --export frappe-assets.tar.gz     # ~15 MB
>
> # on the locked-down laptop -- no node, no yarn, no node_modules
> winbench assets --import frappe-assets.tar.gz --copy
> ```
>
> Verified: a bench with `node_modules` absent and node removed from `PATH`
> entirely serves the full Desk this way and passes all 8 smoke checks.
>
> Use `--copy` on Windows: it copies the files instead of symlinking, which
> needs no Developer Mode and no admin rights.
>
> Common yarn failures and fixes are in
> [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md#build); if you want to fix yarn
> rather than route around it, start there.

`winbench start` runs the web server, background workers and scheduler under one
supervisor. Ctrl+C stops the whole tree.

### Checkpoint 1
```powershell
python C:\path\to\enterprise-management-\scripts\smoke_test.py --site win.localhost --port 8000
```
> ✅ `8 passed, 0 failed`, **and** you can open <http://127.0.0.1:8000> in a
> browser and log in as `Administrator`.

Add `127.0.0.1  win.localhost` to `C:\Windows\System32\drivers\etc\hosts` to
reach the site by name.

**Why the browser check matters as well as the smoke test:** we shipped a bug
where the API returned 200 and the Desk HTML returned 200, but every JS bundle
404'd — a blank white page. The smoke test now catches exactly that, but look at
it with your own eyes the first time.

---

## Phase 2 — Prove the governance primitives

In the Desk UI:

1. **Workflow State** → create `Pending`, `Approved`, `Rejected`.
2. **Workflow Action Master** → create `Approve`, `Reject`.
3. **Workflow** → new, on document type `ToDo`, active, with those three states
   and transitions `Pending --Approve--> Approved` and
   `Pending --Reject--> Rejected`, both gated to `System Manager`.
4. Create a **ToDo**. It should come up in state `Pending`.
5. Click **Approve**.

### Checkpoint 2
> ✅ The document moves to `Approved`, a **Workflow Action** row exists, and a
> **Version** row records the change.

That is the audit trail a governance platform lives on. If this works, the
platform can do what we need.

---

## Phase 3 — On-prem Linux server

Same repo, same commands. The compatibility patches are no-ops on POSIX, so you
are running stock Frappe with a different launcher.

```bash
pip install -e winbench/
winbench init ~/frappe-bench
cd ~/frappe-bench
winbench doctor        # expect: "(none needed on this platform)"
winbench new-site prod.internal
winbench build --production
winbench start
```

You have a genuine choice here:

- **Keep `winbench`** — one toolchain across both environments, no supervisor or
  nginx config to maintain. Recommended for a first rollout.
- **Switch to upstream `bench`** — the battle-tested production topology
  (supervisor + nginx + gunicorn). The sites directory `winbench` creates is
  byte-compatible with `bench`, so you can switch later without migrating.

### Checkpoint 3
> ✅ Smoke test passes on Linux, and `winbench doctor` reports no patches needed.

---

## Phase 4 — AWS

- **RDS PostgreSQL** — set `db_host` / `db_port` in
  `sites/common_site_config.json`. Site creation needs `CREATE DATABASE`, so use
  the RDS master user for `winbench new-site`, then switch to a restricted role.
- **ElastiCache Redis** — set `redis_cache` and `redis_queue`. With TLS or auth,
  use `rediss://` and put credentials in the URL.
- **Behind an ALB or CloudFront:**
  ```bash
  winbench serve --proxy --no-statics
  ```
  `--proxy` trusts `X-Forwarded-*` so Frappe builds correct URLs.
  `--no-statics` hands `/assets` to CloudFront or S3 instead of the app process.
- **ECS/Fargate or EC2** — containerise or run under systemd. Prefer one process
  type per task.

> ⚠️ **Run exactly one scheduler process across the entire deployment.** Frappe's
> scheduler does not elect a leader. Two schedulers means every scheduled job —
> every escalation, every notification — fires twice. Run it as its own
> single-replica task, and start your web/worker tasks with
> `winbench start --no-scheduler`.

### Checkpoint 4
> ✅ Smoke test passes against the load-balanced URL, and a scheduled job runs
> exactly once per interval.

---

## Everyday commands

| Task | Command |
|---|---|
| Start everything | `winbench start` |
| Web server only | `winbench serve --site <site>` |
| One worker | `winbench worker --site <site>` |
| Scheduler | `winbench scheduler --site <site>` |
| Check services + patches | `winbench doctor` |
| Apply schema changes | `winbench migrate` |
| Rebuild assets | `winbench build --production` |
| Export assets for another machine | `winbench assets --export <file>.tar.gz` |
| Install assets without node | `winbench assets --import <file>.tar.gz --copy` |
| Relink assets (no build) | `winbench assets --copy` |
| Backup (db + files) | `winbench backup` |
| Python REPL on a site | `winbench console` |
| List sites | `winbench list-sites` |
| Health-check a running site | `python scripts/smoke_test.py --site <site>` |
| Audit an app for Windows issues | `python scripts/audit_windows_compat.py apps/<app>` |
