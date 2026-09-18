# Deployment readiness

The deploying team installs and operates this system. They do not build it,
and they should not have to work anything out. So "ready" means: one file to
fill in, one command per operation, every command run end to end on a clean
Linux host with no network, and a written list of what only the real server
can confirm.

Status: **✅ done and verified by running it** · **◑ partly verified** · **○ not verified here**

## Where it stands (final, 2026-09-18)

**Release 1.0.0** (`apps/consilium/consilium/__init__.py`). The deployment kit
(`deploy/install.sh`, `verify.sh`, `upgrade.sh`, `backup.sh`, `restore.sh`,
`consilium.conf.example`) was rehearsed **air-gapped on Rocky Linux 9**:
`verify.sh` **14/14** after a fresh install and again after an upgrade. The
operator's procedure is [`docs/RUNBOOK.md`](../RUNBOOK.md). The evidence below
is unchanged from that rehearsal.

The application those checks ran against has since been finished and measured
on a clean site: **1372 tests, OK** (0 failures, 0 errors, 1248 s). Other
results: `pytest tests/` 51 passed; interface sweep 274 passed, 0 failed;
browser journeys 8/8; platform rules 6/6. The demonstration site is rebuilt
from scratch in about 27 s with no failed section. Feature status is in
[`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md) and
[`EPICS.md`](EPICS.md).

**Since the rehearsal.** Playwright, greenlet and pyee moved to
`requirements-dev.txt`, because they are development tools and never belong on a
server. The runtime set is now **139 wheels + 6 pure-Python sdists**, with
nothing that needs a compiler. The bundle in the evidence (153 wheels) was built
before that change. **The offline bundle must be rebuilt from the final
commit**, then installed and verified the same way. That is the first step of
the real deployment.

**Still open before go-live** (each is detailed below):

| | Gap | Why it is still open |
|---|---|---|
| ○ | A real Windows run | No Windows machine was available. The installer and service scripts are written; the acceptance script is in RUNBOOK |
| ○ | RHEL 8 and Ubuntu 22.04 rehearsals | Only Rocky Linux 9 was run (disk on the build machine) |
| ◑ | Platform pins | **Python 3.11 on x86_64 is required.** The framework's `hiredis==2.2.3` pin has no Python 3.12 wheel; `psutil==5.9.8` has no ARM (aarch64) wheel |
| ○ | Real certificates, identity provider, SMTP | Need the organisation's CA, IdP registration and mail relay. OIDC was proven end to end against a mock provider; LDAP is configured but unexercised |
| ○ | Load testing on real hardware | The numbers in §7 are indicative only (a laptop, under emulation) |
| ○ | Bundle from the final commit | See above |

---

## What the operator does

On the Linux server, as root, after the host prerequisites below are in place:

```bash
tar xzf consilium-bundle-linux-x86_64-py311.tar.gz          # one file, carried across
install -d -m 0750 /etc/consilium /etc/consilium/secrets
cp consilium-bundle/install/consilium.conf.example /etc/consilium/consilium.conf
vi /etc/consilium/consilium.conf                            # the only file anyone edits
consilium-bundle/install/install.sh --config /etc/consilium/consilium.conf --bundle consilium-bundle
/opt/consilium/deploy/verify.sh     --config /etc/consilium/consilium.conf
```

`install.sh` creates the service account, the Python environment (from the
bundle, with no network), the site, the front-end assets, the reference data,
the site settings from the configuration, the PDF engine, the systemd units and
the reverse-proxy/TLS configuration, starts everything and runs the health
check. It is idempotent: after editing the configuration, run it again.
`verify.sh` runs the acceptance checks below and writes a readiness report to
`/opt/consilium/logs/readiness-<timestamp>.md`.

Later operations are one command each, driven by the same file:
`upgrade.sh --bundle <new bundle>`, `backup.sh`, `restore.sh --from <backup>`,
`verify.sh`. The full procedure is [`docs/RUNBOOK.md`](../RUNBOOK.md) Phase 3;
day-to-day operation is [`docs/OPERATIONS.md`](../OPERATIONS.md).

### Host prerequisites (installed by the server's administrators, from the distribution's own repositories)

| What | Why | Checked by |
|---|---|---|
| Python **3.11**, with `venv` (RHEL 9: `python3.11`; Ubuntu 22.04: `python3.11` + `python3.11-venv`) | The bundle's compiled wheels are built for one Python version; the manifest says which | `install.sh`, before changing anything |
| PostgreSQL **16** client tools (`psql`, `pg_dump`); the server may be remote | Backups need `pg_dump` of the server's major version or newer | `install.sh` |
| A reachable PostgreSQL 13+ (16 tested) and a reachable Redis | Data, cache and job queue | `install.sh` |
| **systemd** | Runs the web server, workers, scheduler and nightly backup | `install.sh` renders units into `config/` if it is absent |
| A reverse proxy: **nginx** (tested) or **Caddy** | TLS termination; the application listens on 127.0.0.1 only | `install.sh` (`nginx -t` before reload) |
| `which` and `file` | The framework's PDF library runs `which` to find the PDF engine; its restore runs `file` on the backup | `install.sh` refuses without them (both were missing on a minimal RHEL 9) |
| The PDF engine's system libraries (fontconfig, freetype, libX11, libXext, libXrender, libjpeg, libpng, the 75dpi and Type1 X fonts) | The bundled wkhtmltopdf package links against them | `install.sh` installs the package with repositories disabled and names what is missing |

Nothing else: no compiler, no Node.js, no npm, no internet access, and **no
container runtime**.

> **Docker was used only on the build machine**, as a test harness, to
> simulate a clean, network-less Linux host for the rehearsal below. The
> product does not use, mention or need Docker, and the server needs none.

---

## 1. Getting the software there

| | Item | Evidence | Still needs the real target |
|---|---|---|---|
| ✅ | One archive carries everything | `deploy/make_bundle.py --target-platform linux_x86_64 --target-python 3.11` on the Mac build machine: **153 wheels, 537 files, 336 MB**, 88 s with a warm cache. Carries the wheelhouse, the prebuilt assets, the deployment kit, the requirement set, the service/proxy templates, the help-assistant documents and the PDF engine packages. [`02-bundle-build.log`](evidence/linux-rehearsal/02-bundle-build.log) | — |
| ✅ | Built for the target from any machine | `--target-platform` downloads the target's published wheels (142) and builds only pure-Python ones locally (6); anything that would need a compiler is refused at build time | Build for the real server's architecture (x86_64 assumed) |
| ✅ | Dependencies checked **for the target**, not the build machine | pip judges environment markers by the machine it runs on, so a Linux-only dependency is invisible from a Mac. The builder now reads every wheel's metadata and evaluates markers for the target, for the first and a late patch release of its Python. It found one real gap: `redis` needs `async-timeout` on Python ≤ 3.11.2 (Ubuntu 22.04 ships 3.11.0), which is not in `requirements.txt`; the builder now adds it | — |
| ✅ | Bundle verifies itself | SHA-256 of every file checked before anything changes: "all 537 files match their recorded checksums" | — |
| ✅ | The correct PyPika fork, by content | The builder hashes `pypika/terms.py` inside the wheel against the fork's known hash (`a9764727b433119d`) and refuses the PyPI package of the same version | — |
| ✅ | PDF engine carried and checksummed | The project's official wkhtmltopdf **0.12.6.1-3** (patched Qt) packages — Ubuntu 22.04 `.deb` (installs on 24.04), RHEL 8 and 9 `.rpm` — for the bundle's architecture, each pinned by SHA-256 in `make_bundle.py` (the project publishes none) and recorded in `MANIFEST.json` with its source URL | — |
| ✅ | Help assistant's documents shipped | `docs/USER-GUIDE.md`, `docs/ADMIN-GUIDE.md`, `docs/product/05-glossary.md`, `docs/guides/` go in the bundle's `docs/`; the installer copies them to `<install_dir>/docs` and sets `assistant_docs_path` in `common_site_config.json` (bench-wide, so a restored site gets it too) | — |
| ◑ | Which targets the pinned set supports | Surveyed with `pip install --dry-run --only-binary` for every compiled dependency: **x86_64 + Python 3.11: complete.** x86_64 + 3.12: blocked by `hiredis==2.2.3` (the framework's pin; no cp312 wheel). aarch64: blocked by `psutil==5.9.8` (no aarch64 wheel at all) | Confirm the server is x86_64. For Python 3.12 (Ubuntu 24.04's only Python) the two pins need raising — see "needs a decision" |

## 2. Installing

| | Item | Evidence | Still needs the real target |
|---|---|---|---|
| ✅ | One configuration file, validated | `deploy/consilium.conf.example`: site, hostname, paths, service account, database, Redis, TLS, ports, workers, SMTP, time zone, admin email, SSO (off), AI endpoint (off), backups. `kit.py check-config` reports **every** problem at once, by section and key; refuses unknown keys, literal secrets (secrets are `*_file` or `*_env` only), world-readable secret files, a shared cache/queue Redis, backups inside the install directory. 23 tests in `tests/test_kit.py` | The real values |
| ✅ | No network during install — proven | Target container on a Docker `--internal` network: no default route, DNS for `pypi.org` fails, TCP to PyPI "Network is unreachable" ([`20-airgap-proof.txt`](evidence/linux-rehearsal/20-airgap-proof.txt)). pip ran with `--no-index`, `PIP_NO_INDEX=1`, `PIP_CONFIG_FILE=/dev/null` and every proxy variable pointed at a dead port; its full debug log is searched afterwards: **0 network lines**, recorded in `logs/install-evidence.json` and re-checked by `verify.sh` | — |
| ✅ | Fresh install, air-gapped, RHEL-family 9 | Rocky Linux 9 (x86_64), PostgreSQL 16 and Redis 7 reachable only on the private network: `install.sh` **2 min 23 s** end to end, health check 17/17. [`21-rocky-install.log`](evidence/linux-rehearsal/21-rocky-install.log) | RHEL 8, Ubuntu 22.04 not run (disk on the build machine); RHEL 9 proper rather than a rebuild |
| ✅ | Idempotent | Re-run on the installed host: 18–50 s, nothing recreated, 17/17 again. Refuses to create a site over an existing database of the same name (the framework would drop it) unless `--recreate-database` | — |
| ✅ | Branding and scope trimming applied | `install.sh` always runs `migrate`, which runs the application's after-migrate steps | — |
| ✅ | Site settings from the configuration | Scheduler enabled (a site that skips the setup wizard has it **off**, and looks healthy while never sending a reminder), time zone, admin email, `host_name`, outgoing mail, SSO, AI endpoint | SMTP was left off in the rehearsal: the save-time connection test to a real mail server is unexercised |
| ✅ | Both database models | `superuser` (installer creates database and role) rehearsed; `provisioned` (`--no-setup-db`, no superuser on disk) implemented, not rehearsed | Rehearse `provisioned` against the database team's instance |
| ◑ | Windows installer | `deploy/install.ps1` fixed for the same offline bugs (see below). Not run — no Windows machine | Run it (acceptance script in RUNBOOK) |

## 3. Knowing it works — `verify.sh`

The milestone criteria of HANDOVER §6 as automated checks. Fresh install:
**14/14 passed** ([report](evidence/linux-rehearsal/23-rocky-readiness-fresh-install.md)); after the
upgrade rehearsal: **14/14 passed** ([report](evidence/linux-rehearsal/66-rocky-readiness-after-upgrade.md)).

| | Check | Evidence (rehearsal) |
|---|---|---|
| ✅ | Services: every unit active; **exactly one scheduler process**; web answers | `consilium-web`, `-scheduler`, `-worker@1`, `@2` active; 1 scheduler process |
| ✅ | Health check (now 17 checks, incl. PDF engine) | 17/17 |
| ✅ | **Phase 1**: sign-in by a server-created session (no password known to the verifier); smoke test 8/8; desk loads every referenced asset | 8 passed, 0 failed |
| ✅ | **Phase 2**: a throwaway workflow on ToDo; document created in the first state, approved; an open Workflow Action completed by the approval; a Version row recording the state change; everything removed afterwards | `{"ok": true, ... "cleanup": "removed everything it created"}` |
| ✅ | **PDF**: a governing document rendered through the framework's print path; bytes checked (`%PDF-` header, `%%EOF`, ≥ 1 page) | after upgrade: GDOC-00015, 27 984 bytes, 2.6 s |
| ✅ | **Phase 3**: `winbench doctor` says "(none needed on this platform)"; every install and upgrade made no network access | 0 network lines in every pip log; internet unreachable from the host |
| ✅ | Interface regression sweep | 237 passed, 0 failed |
| ✅ | **No-CDN**: every page a signed-in user sees and every script and stylesheet it loads, fetched and scanned for anything that makes a browser fetch from another host | 9 pages, 30 scripts/stylesheets, none external |
| ✅ | **TLS** through the proxy: handshake verified for the hostname, HSTS present, plain HTTP redirects | TLSv1.3; `http://…/app → 301 https://…` |
| ✅ | Scheduler enabled for the site | enabled, 11 application jobs registered |

## 4. Migration rehearsal (a real site's data on this release)

| | Item | Evidence |
|---|---|---|
| ✅ | Backup of the demo site | Framework backup with files, taken on the development machine: database 614 KB compressed (40 MB on disk), files, site config with encryption key |
| ✅ | Restored into a new site on the air-gapped host and migrated | `restore.sh --from <dir> --as-site migrated.example.internal --db-name consilium_migrated`: restore **40 s**, migrate **7 s**, total **56 s**, health 17/17. [`30-migration-rehearsal.log`](evidence/linux-rehearsal/30-migration-rehearsal.log) |
| ✅ | Nothing lost | Forums 15, governing documents 17, escalations 15, formation requests 8, users 64, versions 628, workflow actions 80, comments 151, files 7, tables 379 — identical before and after ([source](evidence/linux-rehearsal/31-counts-source.txt), [migrated](evidence/linux-rehearsal/31-counts-migrated.txt)) |
| ✅ | Works | Smoke 8/8 by session; UI regression sweep **239 passed, 0 failed** ([log](evidence/linux-rehearsal/32-migrated-site-checks.log)) |
| ○ | On the target's own PostgreSQL | Only the target settles whether PostgreSQL behaves differently there (v15's support for it is second-class) |

## 5. Upgrade rehearsal (previous release → this one)

Previous release = the last commit (`c2c8a91`), bundled with `make_bundle.py
--source <git worktree of HEAD>`; this release = the working tree.

| | Item | Evidence |
|---|---|---|
| ✅ | Previous release installed by the kit, then loaded with data | 136 entities; demonstration data loaded where that release's code allowed (15 governing documents, 25 users, 30 document versions, 4 attestation campaigns, …; 122 non-empty tables) |
| ✅ | `upgrade.sh --bundle <this release>` | **1 min 29 s**: backup (1 s) → new environment beside the old (no network) → maintenance on, services stopped → switch → **migrate 27 s** → assets, reference data, settings → services started → health 17/17. [`63-upgrade-run.log`](evidence/linux-rehearsal/63-upgrade-run.log) |
| ✅ | **No data loss** | Row counts of every table before and after: **0 tables with fewer rows**; growth only from migration (new entities 136 → 143, workspaces, notification templates, …). One framework-recorded deletion: the scheduled-job entry for `reviews.overdue_reviews`, because this release's `hooks.py` no longer schedules it (see "needs the application team"). [`65-upgrade-counts-diff.txt`](evidence/linux-rehearsal/65-upgrade-counts-diff.txt) |
| ✅ | Verified after upgrade | 14/14, including a real governing document's PDF |
| ◑ | Rollback | Printed on failure: re-point `env` at the previous release and `restore.sh` the pre-upgrade backup. The rehearsal found the kit pruning the **previous** release right after upgrading (so there was nothing to roll back to) — fixed; the rollback itself was not exercised | Exercise it once before the first production upgrade |
| — | Manual steps | None beyond `upgrade.sh`. The previous release had no runtime JavaScript libraries (code editor) in its asset archive and failed that health check on its own install; the upgrade fixed it |

## 6. Running it

| | Item | Evidence | Still needs the real target |
|---|---|---|---|
| ✅ | systemd units | `deploy/service/systemd/`: `consilium-web`, `consilium-worker@N`, `consilium-scheduler` (one), `consilium-socketio` (installed, inert: needs Node.js, not shipped), `consilium.target`, `consilium-backup.service` + `.timer`. Run as the service account with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectHome`, write access to the install directory only. **`systemd-analyze verify`: exit 0, no findings** on Rocky 9; units started and enabled by the installer | — |
| ✅ | Workers and scheduler actually run the jobs | All 11 application jobs (incl. `reminders.daily`, `sla.sweep`, `resolution.sweep_breaches`, `notification.retry_failed`, `reminders.hourly`) made due, then run by the scheduler and the two workers within 21 s; each **exactly once**; one scheduler process. [`24-scheduler-workers.txt`](evidence/linux-rehearsal/24-scheduler-workers.txt) | Effects on real data over a real day |
| ✅ | Reverse proxy with TLS | `deploy/service/nginx/consilium.conf` (TLS 1.2/1.3, HSTS, redirect, 50 MB bodies, 180 s timeouts) installed and `nginx -t` passed (nginx 1.24); `deploy/service/caddy/consilium.caddy` for Caddy hosts (explicit certificate, so no public CA is ever contacted) — Caddy not run | Real certificate chain from the organisation's CA |
| ✅ | Backup and restore by the kit | `backup.sh`: 2.3 s, 4 files + `BACKUP.json` with SHA-256s, mode 0600, retention pruning. `restore.sh --yes` in place: **24 s**, services back up, health 17/17 ([log](evidence/linux-rehearsal/50-backup-restore.log)). Nightly by `consilium-backup.timer` | Timer firing overnight; copying backups off the host |
| ✅ | Certificates, ports and service accounts | Written down: [OPERATIONS.md § Certificates, ports and service accounts](../OPERATIONS.md#certificates-ports-and-service-accounts) | The organisation's decisions on CA, names and firewall |
| ◑ | Windows services | `deploy/service/windows/register-services.ps1`: Task Scheduler tasks per role, each running winbench's own supervisor (Job Objects) under a service account or gMSA. **Not run** | Windows acceptance script |
| ○ | Log shipping, metrics, alerting | Logs are files and the journal; nothing collects them | The organisation's monitoring |

## 7. Load (indicative only)

`scripts/load_test.py` (standard library only): server-created sessions for 20
demonstration personas, then 16 requests — 11 portal pages (3 of them real
records) and 5 API calls — back to back with no think time, 30 s per level,
against the migrated site.

**Hardware, plainly:** a laptop (Apple M2, 8 cores, 16 GB; the container VM had 8 GB) running the
x86_64 server **under Rosetta emulation** in a container, with PostgreSQL and
Redis in two more containers on the same laptop; one application process with
8 threads (as `consilium-web` runs it). Emulation alone costs a large factor.
These numbers say the design holds up and nothing errors under concurrency;
they say nothing about production capacity.

| Threads | Requests | Req/s | p50 ms | p95 ms | p99 ms | Max ms | Errors |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 299 | 9.9 | 109 | 225 | 263 | 309 | 0 |
| 5 | 323 | 10.7 | 545 | 815 | 1174 | 1336 | 0 |
| 10 | 357 | 11.7 | 882 | 1556 | 2123 | 2349 | 0 |
| 25 | 401 | 12.5 | 1982 | 2722 | 3079 | 3429 | 0 |

Throughput is flat from 5 threads: one Python process is saturated, so
latency grows with the queue. The lever is more web processes, not threads.
135 requests were refused with HTTP 403 by the permission layer — personas
reading records their role may not see (`/policy`, the governing-document and
escalation lists) — and are reported separately, not as errors.
[`33-load-test.log`](evidence/linux-rehearsal/33-load-test.log), [JSON](evidence/linux-rehearsal/33-load-test.json)

○ **Real numbers need the real server**, with more than one web process.

## 8. Single sign-on

| | Item | Evidence |
|---|---|---|
| ✅ | OpenID Connect, end to end, offline | `scripts/mock_oidc_provider.py` (standard library; test tool only) on 127.0.0.1; `[sso] mode = oidc` in the configuration; `install.sh` re-run configured a "Custom" Social Login Key with sign-ups **denied**. A browser-like client (`tests/linux_harness/sso_demo.py`) took the button from the sign-in page over HTTPS, went through authorize → code → token → userinfo, and was **signed in as the existing account**: same user id, same creation time, a `corporate_sso` social-login row added, no new user. A person the provider vouched for but with no account was **refused (403, "Signup is Disabled")** and not created. [`41-sso-oidc-demo.txt`](evidence/linux-rehearsal/41-sso-oidc-demo.txt) |
| ✅ | Off by default | `mode = none` in the example; setting it back and re-running disabled the provider ("off (provider 'corporate_sso' disabled)") |
| ◑ | LDAP / Active Directory | `[sso] mode = ldap` fills the framework's LDAP Settings (StartTLS or LDAPS, trusted CA required, no account creation unless `allow_signup`). `ldap3` 2.9.1 and `pyasn1` are **pure-Python wheels** (`py2.py3-none-any`), already in the requirement set — allowed under the no-compiler rule. Not exercised against a directory |
| ○ | Real identity provider | Redirect URI registration, claims, group mapping |

## 9. Windows

| | Item | Evidence |
|---|---|---|
| ✅ | Simulated | `tests/test_compat.py` **22 passed** (Windows flag forced, POSIX APIs removed), including a new test for restore on Windows. `audit_windows_compat.py` on the framework: 10 blockers, 6 in test code — the known baseline, all handled by the compatibility layer; on the application: 0 |
| ✅ | Found by the rehearsal, fixed for Windows | The framework's restore runs the Unix `file` utility first; Windows has none, so **every restore would have failed on Windows**. The existing `execute_in_shell` patch now answers that probe itself on Windows (no-op on POSIX), with tests |
| ○ | **A real Windows run** | Still required. Nothing here has run on Windows. The step-by-step acceptance script is in [RUNBOOK.md § Windows acceptance](../RUNBOOK.md#windows-acceptance-script) |

## 10. The application

Unchanged by this work; see the application team's status. On an installed
system: 143 entities, all with tables; 11 scheduled jobs; UI sweep clean.

Final application status (2026-09-18, release 1.0.0): full suite **1372 tests,
OK** on a clean site; interface sweep **274 passed, 0 failed** on the final
demonstration site; browser journeys **8/8**; platform rules **6/6**. Measured
coverage: [`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md); story status:
[`EPICS.md`](EPICS.md).

---

## Bugs found by running it, and fixed

In `deploy/`, `winbench/`, `scripts/`:

1. **Offline install could not work at all.** `install.sh`/`install.ps1` ran
   `pip install --no-index frappe consilium`, which follows the framework's own
   metadata: two git URLs (pip fetches those even under `--no-index`) and
   `maxminddb-geolite2`, deliberately dropped from `requirements.txt` in the
   last commit. Now: the requirement set first, then the three wheels with
   `--no-deps`. The builder verifies both steps.
2. **Wrong Python gave a cryptic error.** A bundle is built for one Python
   version; the installer now reads it from the manifest, finds `pythonX.Y`,
   and refuses a platform/architecture mismatch before changing anything.
3. **The framework's assets were never imported on a wheel install.** winbench
   looked for `apps/<app>/<app>/public`, which a wheel install does not have
   ("skipping frappe: not installed in this bench"). It now resolves app paths
   from the imported package, as the framework does.
4. **The code editor never loaded on a wheel install.** The framework maps
   `<package>/../node_modules` to `/assets/<app>/node_modules` in a dict keyed
   by source; with every app in one site-packages only the last app got the
   libraries. winbench now serves them for every app.
5. **`winbench doctor` never said "(none needed on this platform)"** — HANDOVER's
   Phase 3 criterion. It force-installed the patches to list them, so Linux
   showed all eight "applied". It now reports none needed, and separately that
   they still install cleanly (to catch a framework upgrade that breaks one).
   It also checks the database with the site's own role when no superuser
   password is kept on disk.
6. **Every link and every PDF pointed at `https://<host>:8000`.** The framework
   appends `webserver_port` to `host_name` unless a production flag is set; the
   PDF engine then fetched stylesheets from a port nothing served ("network
   error: ConnectionRefused"). The kit sets `restart_systemd_on_update`.
7. **PDFs failed on minimal RHEL** (`which` missing) and **restores failed**
   (`file` missing): both are now prerequisites the installer checks.
8. **The scheduler was off on every installed site** (it is enabled by the
   setup wizard the product skips). The kit enables it.
9. **The smoke test could not use a session**; it sent the Guest cookie from
   its first request alongside the real one. Fixed, and `--sid` added so no
   password is needed.
10. **`ui_regression.py` needed a repository checkout**; it now reads the
    installed package.
11. **Upgrade pruned the previous release immediately**, leaving nothing to roll
    back to. Fixed.
12. **The bundle builder wrote into the checkout** (`winbench/build`, tracked in
    git) and used a literal `/tmp`. Fixed.
13. Existing database dropped by a re-install with a missing site directory —
    now refused.

## Needs the application team or a decision (not changed here)

1. ~~**`consilium.governance.reviews.overdue_reviews` is no longer scheduled**~~
   **Resolved.** The job was folded into the daily reminder run:
   `consilium_core.reminders.daily` (scheduled in `hooks.py`) calls
   `reviews.overdue_reviews` and sends the reminders, with `Reminder Log`
   de-duplication. The deleted job type is expected.
2. ~~**The application version never changes**~~ **Resolved.** The version is
   now `1.0.0`. Bump it per release; the kit still identifies a release by its
   bundle's manifest hash.
3. **Open. Pins that limit the platforms** (`requirements.txt`, owned outside
   this work): `hiredis==2.2.3` has no Python 3.12 wheels (blocks Ubuntu 24.04,
   whose only Python is 3.12); `psutil==5.9.8` has no aarch64 wheels. Until they
   are raised, **Python 3.11 on x86_64 is required**. `async-timeout` is
   missing for Python ≤ 3.11.2 (the builder compensates).
4. **Partly resolved.** `playwright`, `greenlet` and `pyee` moved to
   `requirements-dev.txt`, so neither they nor Playwright's Node.js driver reach
   the server. `duckdb` and `pyarrow` are still in the runtime set.

## What only the real server can confirm

- Real certificates from the organisation's CA, and the names people will use.
- The real identity provider (OIDC or LDAP), including redirect-URI
  registration and claims.
- Real SMTP: the kit tests the connection when it saves the mail account; it
  was left off here.
- Real hardware load numbers, with several web processes.
- The target's own PostgreSQL (and, if managed, the `provisioned` model).
- RHEL 8, RHEL 9 proper, Ubuntu 22.04 (only Rocky 9 was run), and the PDF
  engine's libraries from the target's own mirror.
- Rollback, exercised once.
- **The Windows workstation run** (acceptance script in RUNBOOK).
- The offline bundle rebuilt from the final commit (Python 3.11, x86_64), then
  installed and verified with `verify.sh`.

## Evidence

Everything above was produced by running it; the files are in
[`evidence/linux-rehearsal/`](evidence/linux-rehearsal/): the air-gap proof,
the install, upgrade, migration and restore logs, both readiness reports as
`verify.sh` wrote them, row counts, scheduler and worker logs, the SSO
exchange, the load results, and the rendered units with `systemd-analyze
verify` and `nginx -t` output.

The rehearsal harness is `tests/linux_harness/` (image definition, the filled
configuration, host preparation, the SSO driver). During iteration the latest
kit files were copied into the running rehearsal host rather than rebuilding
the bundle each time. Two last fixes were not re-run end to end: the release
pruning fix (unit-level reasoning only) and the builder building each wheel
from a copy of its source (verified for the launcher's wheel only). A fresh
bundle build from this tree is therefore the first step of the real
deployment, followed by the same install and `verify.sh`.
