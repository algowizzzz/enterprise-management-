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
git clone <this-repository-url>
cd consilium
python scripts/check_availability.py --target-windows
```

The script drives pip against **whatever index you have configured**, so an
internal package mirror is exercised exactly as a real install would exercise
it.

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
2. **Vendor into your internal package repository.** Publish `frappe` and the
   PyPika fork as internal packages. Most enterprises already have this
   pattern.
3. **Manual download + offline wheelhouse** (Phase 1b). Works today with no
   network exception at all, but you own patching.

The two URLs, and what to do with each, are in
[`../requirements-github.txt`](../requirements-github.txt).

---

## Phase 1 — A running site on a managed Windows workstation

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
cd consilium
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
> **A prebuilt bundle for v15.121.0 is committed to this repo**, so you do not
> need a machine with node at all:
>
> ```powershell
> winbench assets --import assets/frappe-assets-v15.121.0.tar.gz --copy
> ```
>
> To regenerate it for a different Frappe version, on any machine with node:
>
> ```powershell
> winbench build --production
> winbench assets --export assets/frappe-assets-<version>.tar.gz
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
python C:\path\to\consilium\scripts\smoke_test.py --site win.localhost --port 8000
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
platform can carry Consilium's approval and audit requirements.

---

## Phase 3 — Air-gapped Linux server

This is the production path, and it is three steps: fill in one file, run one
command, run one check. Everything else — the Python environment, the site,
the assets, the reference data, the PDF engine, the systemd units, the
reverse proxy and TLS — is done by the deployment kit from the offline bundle,
with no network access. What the kit does and the evidence that it works are in
[`delivery/DEPLOYMENT-READINESS.md`](delivery/DEPLOYMENT-READINESS.md).

> Docker was used only on the build machine to simulate a clean, network-less
> Linux host during the rehearsal. The server needs none, and nothing in the
> kit uses it.

### 3a — On the connected build machine: build the bundle

Any machine with internet access and this repository's development
environment (a Mac or Linux laptop is fine), for an x86_64 server running
Python 3.11:

```bash
python deploy/make_bundle.py --frappe-src <framework source tree> --out dist/ \
    --target-platform linux_x86_64 --target-python 3.11 \
    --name consilium-bundle-linux-x86_64-py311
```

It downloads the server's wheels, builds only pure-Python ones locally, checks
that every dependency the server will ask for is present, adds the PDF engine
packages (checked against pinned checksums), and refuses to write a bundle that
cannot install offline. Carry the one `.tar.gz` across.

### 3b — On the server: prerequisites (the administrators, from the distribution's repositories)

| Needed | RHEL / Rocky / Alma 9 | Ubuntu 22.04 |
|---|---|---|
| Python 3.11 with venv | `python3.11` | `python3.11 python3.11-venv` |
| PostgreSQL 16 client | `postgresql` (module `postgresql:16`) or PGDG `postgresql16` | `postgresql-client-16` (PGDG) |
| PostgreSQL 16 server, Redis | local or remote; reachable from this host | same |
| systemd, reverse proxy | present; `nginx` (or Caddy) | present; `nginx` |
| Small utilities | `which file util-linux` | present by default |
| PDF engine libraries | `fontconfig freetype libX11 libXext libXrender libjpeg-turbo libpng xorg-x11-fonts-75dpi xorg-x11-fonts-Type1` | `fontconfig libfreetype6 libx11-6 libxext6 libxrender1 libjpeg-turbo8 libpng16-16 xfonts-75dpi xfonts-base` |
| A TLS certificate and key for the public hostname | from the organisation's CA | same |

The installer checks each of these before it changes anything and says what is
missing. It needs no compiler, no Node.js and no internet access.

### 3c — On the server: fill in the configuration

```bash
tar xzf consilium-bundle-linux-x86_64-py311.tar.gz
sudo install -d -m 0750 /etc/consilium /etc/consilium/secrets
sudo cp consilium-bundle/install/consilium.conf.example /etc/consilium/consilium.conf
sudo vi /etc/consilium/consilium.conf
# secrets: one file each, readable by root only
sudo sh -c 'umask 077; printf "%s\n" "<database role password>" > /etc/consilium/secrets/db_password'
sudo sh -c 'umask 077; printf "%s\n" "<postgres superuser password>" > /etc/consilium/secrets/db_root_password'
python3 consilium-bundle/install/kit.py check-config --config /etc/consilium/consilium.conf
```

`check-config` lists every problem at once, by section and key. It refuses a
password written into the file: secrets are always `*_file` or `*_env`.

### 3d — Install

```bash
sudo consilium-bundle/install/install.sh --config /etc/consilium/consilium.conf --bundle consilium-bundle
```

About two and a half minutes on the rehearsal host. It ends with the health
check (17 checks) and prints where the installation is. Re-run it after any
change to the configuration; it changes only what differs.

### 3e — Verify

```bash
sudo /opt/consilium/deploy/verify.sh --config /etc/consilium/consilium.conf
```

This is Checkpoints 1, 2 and 3 as automated checks — smoke test 8/8 with a
session created on the server (no password needed), the workflow primitives
(Phase 2: a throwaway workflow, a Workflow Action and a Version row, cleaned
up afterwards), a real PDF, `winbench doctor` reporting no patches needed, no
network access during install, the interface sweep, no page or asset loading
anything from another host, TLS through the proxy, services and exactly one
scheduler. It writes `/opt/consilium/logs/readiness-<timestamp>.md`; keep it
with the change record.

### Checkpoint 3
> ✅ `verify.sh` ends with "All 14 checks passed" and the readiness report says
> **READY**.

### Later: upgrade, backup, restore

```bash
sudo /opt/consilium/deploy/upgrade.sh --config /etc/consilium/consilium.conf --bundle <new bundle>.tar.gz
sudo /opt/consilium/deploy/backup.sh  --config /etc/consilium/consilium.conf
sudo /opt/consilium/deploy/restore.sh --config /etc/consilium/consilium.conf --from /var/backups/consilium/<set> --yes
```

`upgrade.sh` takes a backup first, installs the new release beside the current
one, migrates, starts, checks health, and on failure prints the exact rollback
commands. Details in [`OPERATIONS.md`](OPERATIONS.md).

### Development-style Linux bench (not for production)

`winbench init` / `winbench new-site` / `winbench start` still work on Linux
exactly as on Windows (Phase 1), and the sites directory is byte-compatible
with upstream `bench`. Use the kit above for a server.

---

## Phase 4 — Managed cloud infrastructure (optional)

Using AWS names as an example:

- **Managed PostgreSQL (e.g. RDS)** — set `db_host` / `db_port` in
  `sites/common_site_config.json`. Site creation needs `CREATE DATABASE`, so use
  the master user for `winbench new-site`, then switch to a restricted role.
- **Managed Redis (e.g. ElastiCache)** — set `redis_cache` and `redis_queue`.
  With TLS or auth, use `rediss://` and put credentials in the URL.
- **Behind a load balancer or CDN:**
  ```bash
  winbench serve --proxy --no-statics
  ```
  `--proxy` trusts `X-Forwarded-*` so Frappe builds correct URLs.
  `--no-statics` hands `/assets` to the CDN or object store instead of the app
  process.
- **Containers or VMs** — containerise or run under systemd. Prefer one process
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

## Windows acceptance script

Nothing has been run on Windows yet. Everything Windows-specific is covered by
tests that simulate it (`tests/test_compat.py`, 22 tests) and a static audit,
which is good evidence and not proof. Whoever has the first managed Windows
workstation: work through this in order, and record the output of every step.

1. **Machine facts.** `winver`; `systeminfo | findstr /B /C:"OS"`; whether the
   profile is redirected to a sync folder; the corporate proxy settings.
2. **Prerequisites.** Python 3.11 (`py -3.11 -V`), PostgreSQL 16 (service
   running), Memurai or another Redis-compatible service on two ports.
3. **Bundle for Windows**, built on the connected machine:
   `python deploy/make_bundle.py --frappe-src <src> --target-platform win_amd64 --target-python 3.11 --name consilium-bundle-win`.
   Record whether it completes (the Windows wheel set has not been built in
   this rehearsal).
4. **Offline install.** Disconnect the network (or block it at the firewall),
   then from the unpacked bundle:
   `.\install\install.ps1 -Target C:\consilium -Site consilium.local -DbPort 5432 -AdminPassword <pw>`.
   Expect every step to pass and the health check to end 17/17 (the PDF
   engine check fails unless the patched-Qt wkhtmltopdf Windows build is
   installed — record it either way). Keep `C:\consilium\logs\pip-install.log`.
5. **Doctor.** `cd C:\consilium; .\env\Scripts\python -m winbench.cli doctor` —
   every service `[ok]`, and the list of *applied* patches (on Windows they are
   live, unlike on Linux).
6. **Start.** `.\env\Scripts\python -m winbench.cli start` in one window.
7. **Smoke.** `.\env\Scripts\python .\deploy\smoke_test.py --site consilium.local --port 8000 --password <pw>` → `8 passed, 0 failed`.
8. **Browser.** Open http://127.0.0.1:8000, sign in, open a JSON field
   (code editor loads), print a governing document to PDF.
9. **Phase 2 primitives.** `.\env\Scripts\python .\deploy\acceptance.py --site consilium.local workflow`
   (run from `C:\consilium\sites`) → `"ok": true`.
10. **Workers and scheduler.** Leave `start` running 10 minutes; in the desk,
    Scheduled Job Log shows each job once per interval.
11. **Backup and restore.** `.\env\Scripts\python -m winbench.cli backup`,
    then restore the database file into a *new* site with the framework's
    `restore` command. This exercises the Windows answer to the framework's
    `file` probe added in this release.
12. **Services.** `.\deploy\service\windows\register-services.ps1 -InstallDir C:\consilium -Site consilium.local -Credential (Get-Credential .\svc-consilium)`;
    reboot; the three tasks are running and the site answers.
13. **Report** what broke, with the command and its output.

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
