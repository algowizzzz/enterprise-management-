# Hand-off — for the AI coding agent taking this platform in-house

You are taking over **Consilium**, a governance, risk and policy platform, from
the team that built it. Your job has two stages, in this order:

1. **Run it locally** on a developer workstation, load the demonstration data,
   and prove it works with the checks below.
2. **Deploy it** to the organisation's air-gapped Linux server with the offline
   deployment kit.

Do not skip stage 1. Every check in stage 2 has a local equivalent, and a
problem found on a laptop is cheaper than one found on the server.

Read [`CLAUDE.md`](CLAUDE.md) before you change anything. Its rules are binding
and several of them are not what a Frappe developer would assume. The ones
that matter most are in [§5](#5-rules-you-must-not-break). Then read
[`HANDOVER.md`](HANDOVER.md) and
[`docs/delivery/README.md`](docs/delivery/README.md).

---

## 1. What you are receiving

| | |
|---|---|
| Application | `apps/consilium/`, a Frappe app with three modules: governance forums (committees), policy lifecycle, escalations. A shared core supplies approvals, audit, SLAs, notifications, retention and attestation. |
| Framework | Frappe **v15.121.0**, never forked or edited, running on **PostgreSQL 16** and Redis. |
| Runtime | `winbench/`, a replacement for Frappe's `bench` tooling that runs natively on Linux and Windows with no Docker, supervisor, nginx-inside-the-app or gunicorn. |
| Front end | Portal pages in `apps/consilium/consilium/www/`, plain JavaScript, every library vendored. No npm, no build step, no CDN. The prebuilt framework assets are committed in `assets/`. |
| Deployment kit | `deploy/`. One config file, `install.sh`, `verify.sh`, `upgrade.sh`, `backup.sh`, `restore.sh`. Rehearsed air-gapped on Rocky Linux 9. |
| Version | 1.0.0 (`apps/consilium/consilium/__init__.py`) |
| Branding | White-label. The organisation's name, logo, colours and fonts are set in **Portal Branding** (desk → Portal Branding) after install. No code changes. |

Measured state at hand-off:

| Check | Result |
|---|---|
| App test suite, clean site | **1372 tests, OK** (about 21 min) |
| `pytest tests/` (runtime and kit) | 51 passed |
| Portal sweep (`scripts/ui_regression.py`) | 274 passed, 0 failed |
| Browser journeys (`scripts/browser_journeys.py`) | 8 / 8 |
| Platform rules (`scripts/check_platform_rules.py`) | 6 / 6 |
| Demo data on an empty site | about 30 s, 0 failed sections, idempotent |
| Air-gapped install and verify (Rocky 9) | `verify.sh` 14 / 14 |

What each requirement maps to, where it lives and how it is tested:
[`docs/delivery/REQUIREMENTS-COVERAGE.md`](docs/delivery/REQUIREMENTS-COVERAGE.md).
Story-level status: [`docs/delivery/EPICS.md`](docs/delivery/EPICS.md).

---

## 2. Stage 1 — run it locally

### 2.1 Prerequisites

- macOS or Linux, x86_64 or Apple silicon, with network access (only the
  workstation needs it).
- **Python 3.11** (3.12 also works locally. The server must be 3.11; see §4.4.)
- **PostgreSQL 16** and **Redis**. On macOS, `scripts/dev_setup.sh` installs
  both with Homebrew. On Linux, install them from the distribution first.
- Google Chrome, only if you want to run the browser journeys and screenshot
  tools.

### 2.2 Set up

```bash
git clone <this repository> consilium && cd consilium
git checkout consilium-delivery          # the branch this hand-off describes
./scripts/dev_setup.sh
```

The script creates `.venv/` and `.bench/`, the site `consilium.localhost`, and
loads the reference data (`deploy/seed.py`). It ends with the health check.

Watch for these:

- **Another PostgreSQL on 5432.** Start PostgreSQL 16 on a free port and run
  with `DB_PORT=5433 ./scripts/dev_setup.sh`. The script refuses a server that
  is not version 16.
- **The script prints the serve command at the end.** Use it exactly:
  `cd .bench && ../.venv/bin/winbench serve --site consilium.localhost --port 8000`.
  `--site` is required as soon as the bench holds more than one site.
- **Restart the server** after any change to `hooks.py` or a Python file. It
  does not reload.

### 2.3 Load the demonstration data and create logins

```bash
cd .bench/sites
export FRAPPE_BENCH_ROOT=$(cd .. && pwd)
../../.venv/bin/python ../../deploy/demo_data.py --site consilium.localhost
../../.venv/bin/python ../../deploy/demo_logins.py --site consilium.localhost \
    --url http://consilium.localhost:8000 --out ~/consilium-demo-logins.md --administrator
```

- `demo_data.py` builds a fictitious financial-services group:
  - 23 personas;
  - 14 forums with meetings and votes;
  - 15 policies at every lifecycle phase;
  - 15 escalations;
  - attestation campaigns.

  It goes through the platform's real functions, so every record carries a
  genuine audit trail. Running it again changes nothing.
- `demo_logins.py` gives every persona (and Administrator) a random password
  and writes them to the file you name. **It refuses to write inside the
  repository**, and the file must never be committed. The personas and their
  roles, without passwords, are in
  [`docs/delivery/DEMO-LOGINS.md`](docs/delivery/DEMO-LOGINS.md).
- `dev_setup.sh` creates the site with Administrator password `admin`. The
  `--administrator` flag above replaces it.

Open <http://consilium.localhost:8000> and sign in as a few personas: the
Chief Risk Officer, the Committee Secretary, the Enterprise Policy Office Lead
and the Internal Auditor. Each sees a different product. The desk, for
configuration, is at `/app` as Administrator.

### 2.4 Prove it — the stage 1 exit criteria

Run all of these from the repository root unless a command says otherwise. Do
not proceed to stage 2 until each matches.

```bash
.venv/bin/python -m pytest tests/ -q                                    # 51 passed
.venv/bin/python scripts/check_platform_rules.py                        # 6/6
.venv/bin/python apps/consilium/scripts/check_state_flags.py            # clean

cd .bench/sites && export FRAPPE_BENCH_ROOT=$(cd .. && pwd)
../../.venv/bin/python ../../deploy/healthcheck.py --site consilium.localhost      # 17/17, or 16/17 (see below)
../../.venv/bin/python ../../scripts/ui_regression.py --site consilium.localhost \
    --url http://consilium.localhost:8000                               # 0 failed
../../.venv/bin/python ../../scripts/smoke_test.py --site consilium.localhost --port 8000 \
    --password '<Administrator password from your logins file>'          # 8 passed
```

On a workstation the health check's **PDF engine** check fails unless
`wkhtmltopdf` 0.12.6 is installed. That is expected: only PDF downloads need
it, and the server bundle installs it. Everything else must pass. The smoke
test signs in as Administrator, so it needs the password `demo_logins.py`
wrote. It can also take an existing session with `--sid`.

The full app suite must run on a **separate test site**, never the demo site:
tests create and roll back data, and some deliberately provoke refusals.

```bash
cd .bench/sites
../../.venv/bin/python -m frappe.utils.bench_helper frappe new-site consilium-test.localhost \
    --db-type postgres --db-host 127.0.0.1 --db-port <port> --db-name consilium_test \
    --db-root-username <postgres superuser> --db-root-password <its password> --admin-password <any>
../../.venv/bin/python -m frappe.utils.bench_helper frappe --site consilium-test.localhost install-app consilium
../../.venv/bin/python -m frappe.utils.bench_helper frappe --site consilium-test.localhost set-config allow_tests 1 -p
../../.venv/bin/python -m frappe.utils.bench_helper frappe --site consilium-test.localhost set-config throttle_user_limit 100000 -p
../../.venv/bin/python -m frappe.utils.bench_helper frappe --site consilium-test.localhost run-tests --app consilium
# expect: Ran 1372 tests ... OK
```

Optional, needs Chrome and `pip install -r requirements-dev.txt`:
`scripts/browser_journeys.py --site consilium.localhost --url http://consilium.localhost:8000`
(8/8). It signs in with server-side sessions and never types a password.

The known expected messages are listed in §6.

---

## 3. Stage 2 — deploy inside the organisation

The full procedure, with every command, is **[`docs/RUNBOOK.md`](docs/RUNBOOK.md),
Phase 3**. The evidence that it works is
[`docs/delivery/DEPLOYMENT-READINESS.md`](docs/delivery/DEPLOYMENT-READINESS.md)
and [`docs/delivery/evidence/linux-rehearsal/`](docs/delivery/evidence/linux-rehearsal/).
In short:

1. **Build the offline bundle** on a connected build machine (your stage 1
   workstation is fine), **from the exact commit you will deploy**:
   ```bash
   python deploy/make_bundle.py --frappe-src <framework source tree> --out dist/ \
       --target-platform linux_x86_64 --target-python 3.11 \
       --name consilium-bundle-linux-x86_64-py311
   ```
   It refuses to write a bundle that cannot install offline. Carry the single
   `.tar.gz` across, through the organisation's approved transfer route.
2. **On the server:**
   - install the prerequisites from the distribution's repositories (RUNBOOK
     3b: Python 3.11, the PostgreSQL 16 client, a reachable PostgreSQL 16 and
     Redis, nginx or Caddy, the PDF engine libraries);
   - obtain a TLS certificate from the organisation's CA.
3. **Fill in `/etc/consilium/consilium.conf`.** Copy it from
   `consilium.conf.example`; it is the only file anyone edits. Secrets go in
   root-only files named by `*_file` keys, never in the config. Check it with
   `python3 consilium-bundle/install/kit.py check-config --config /etc/consilium/consilium.conf`.
4. **Install:** `sudo consilium-bundle/install/install.sh --config /etc/consilium/consilium.conf --bundle consilium-bundle`
5. **Verify:** `sudo /opt/consilium/deploy/verify.sh --config /etc/consilium/consilium.conf`.
   It must end with **"All 14 checks passed"** and a readiness report marked
   **READY**. Keep that report with the change record.
6. **Configure the organisation** (§4), then hand the first administrators the
   [configuration guide](docs/guides/README.md).

After go-live, each of these is one command (see RUNBOOK and
[`docs/OPERATIONS.md`](docs/OPERATIONS.md)):

- `upgrade.sh` takes a backup first and prints rollback commands if anything
  fails;
- `backup.sh`;
- `restore.sh`.

**Do not load demonstration data on the production server.** Load it on a
separate training site if you need one; `demo_logins.py` refuses a site that
holds real users unless forced.

### Milestone 1 acceptance (the first delivery milestone)

The platform is accepted into the organisation when all of the following are
true:

- `verify.sh` passes 14/14 on the target server, with no network access during
  install.
- No page loads anything from another host. This is part of `verify.sh`.
- Every portal page renders for every role, the portal sweep reports 0 failed,
  and the app suite is green on a test site built from the deployed commit.
- The organisation's brand is applied through Portal Branding, and no
  framework branding is visible to end users.
- Sign-in works through the organisation's identity provider, if SSO is in
  scope, and mail is delivered through its relay.
- A backup has been taken and restored once on the server (`backup.sh`, then
  `restore.sh` onto a scratch site), with row counts matching.
- The first administrators have completed the configuration guide's exercises:
  add a workflow state, add a routing rule, add a notification template.

---

## 4. Decisions the organisation must make

None of these is a code change. Each is configuration, and each has a safe
default.

1. **Branding.** Portal Branding: name, logo, favicon, colours, fonts, footer.
   Default: a neutral "Governance Portal".
2. **Identity.** OIDC single sign-on and LDAP are configured in
   `consilium.conf`. OIDC was rehearsed against a mock provider; LDAP is
   configured but untested against a real directory. Default: off, with local
   accounts.
3. **Mail.** SMTP relay in `consilium.conf`. Notifications are recorded
   in-platform regardless; email is an extra channel. Default: off.
4. **Python and CPU architecture.** The server must be **x86_64 with Python
   3.11**:
   - Frappe pins `hiredis==2.2.3`, which has no Python 3.12 wheels. That rules
     out Ubuntu 24.04's only Python.
   - It also pins `psutil==5.9.8`, which blocks ARM servers.
   - RHEL, Rocky or Alma 9 (`python3.11`) fits. Ubuntu 22.04 needs Python 3.11
     from an approved repository.
5. **AI (optional, off by default).** Every analysis works without AI:
   - impact of a policy change;
   - governance gaps;
   - emerging risks;
   - risk scores;
   - regulatory updates.
   An administrator can add AI commentary in **Assistant Settings**: the
   endpoint, model and API key, then "Use the AI Endpoint for Analysis
   Features". Decide:
   - which service is approved;
   - the **classification ceiling**: nothing above it is ever sent;
   - whether to allow "Include visible record summary". The default,
     "guidance only", sends counts and category names, never record text.

   Every call is logged in *AI Service Request* with exactly what was sent. The
   API key belongs in the settings' password field and nowhere else.
6. **Reference data.**
   - `deploy/seed.py` loads a generic starting taxonomy: risk types,
     organisational levels, retention classes, jurisdictions. Replace it with
     the organisation's own, by import (`/imports`) or in the desk.
   - Retired values stay on old records but are no longer offered for new ones.
7. **Retention periods and legal holds** (Retention Class, Legal Hold).
   Nothing is ever deleted by the platform. Records past retention are flagged
   for a disposal decision.
8. **Workflow states.** To add a policy lifecycle state without a schema
   change, run once per site:
   `bench --site <site> execute consilium.policy.lifecycle.derive_phase_from_state`.
   Then follow the configuration guide, chapter 11.

---

## 5. Rules you must not break

From [`CLAUDE.md`](CLAUDE.md), the ones an agent is most likely to break:

- **No CDN, no npm or yarn, no compiler, no internet at install time.** Every
  front-end library is vendored under `apps/consilium/consilium/public/vendor/`,
  recorded in `VENDOR.md` and hashed in `SHA256SUMS`.
- **Never edit Frappe's source.** Platform fixes go in `winbench/winbench/compat.py`,
  each a no-op on POSIX, each with a test in `tests/test_compat.py`.
- **PostgreSQL only.**
  - `["is", "not set"]` on a date column fails there: use `frappe.qb` with
    `.isnull()`.
  - Test anything that touches SQL on PostgreSQL, not SQLite or MariaDB.
- **Never compare workflow state names in code.** Every rule reads the semantic
  *Workflow State Flag* map, so administrators can rename and add states freely.
  `scripts/check_platform_rules.py` and `apps/consilium/scripts/check_state_flags.py`
  enforce this.
- **Nothing is deleted, and every refusal is logged.**
  - Refusals go through `consilium_core.audit.refuse`. The refusal log survives
    a rollback because it is written on its own connection.
  - Tests that provoke refusals must call `purge_on_teardown`.
- **DocTypes are generated from specs.**
  - Edit `apps/consilium/specs/<module>/<doctype>.json`, then regenerate with
    `apps/consilium/scripts/make_doctype.py`.
  - After any DocType JSON edit, bump its top-level `"modified"` to the current
    UTC time, or `migrate` ignores it.
- **Jinja does not autoescape.** Escape every value printed into a portal page
  with `| e`. The portal sweep sends a script payload in every address
  parameter and fails if one comes back.
- **No client-identifying content, ever.** No organisation, customer or
  personal names, internal hostnames or codenames in code, data, docs or
  commits. The platform is white-label; the organisation's identity lives only
  in its own Portal Branding record and its own server's config.
- **Passwords never go in git.** That includes demo passwords.

---

## 6. Known issues and expected messages

| You will see | Meaning |
|---|---|
| `Note: PostgreSQL support is limited to Frappe v16 and above` | The framework's generic warning. This build runs v15 on PostgreSQL through winbench's patches; the tests and rehearsal prove it. |
| `duplicate key value violates unique constraint …` scrolling past during the test suite | Tests that deliberately provoke a constraint. Only the final `OK` or `FAILED` counts. |
| `wkhtmltopdf: not on PATH` from `check_availability.py`, or "PDF engine present" failing in the health check, on a workstation | Only PDF print formats need it. The server bundle carries the official packages, and `verify.sh` produces a real PDF. |
| A reviewer pressing "Return to Drafting" **in the desk** gets a permission error | Known gap. Returning from the portal's policy page works and is the supported path. |
| The voting screen has no attendance entry | Quorum is counted from the seats that voted. |
| `bench` not found | There is no `bench`. Use `.venv/bin/winbench` (serve, migrate, backup, doctor), or `python -m frappe.utils.bench_helper frappe --site <site> <command>` for framework commands. |

Not yet proven. Each is on the organisation's side:

- a real Windows workstation run (the acceptance script is in RUNBOOK);
- RHEL 8 and Ubuntu 22.04;
- real certificates, identity provider and SMTP;
- load figures on production hardware (the rehearsal's numbers were taken
  under CPU emulation, so they are indicative only);
- an exercised rollback.

---

## 7. Where everything is

| Need | Go to |
|---|---|
| Requirement → where it lives → test | `docs/delivery/REQUIREMENTS-COVERAGE.md` |
| Epics and stories, with status | `docs/delivery/EPICS.md` |
| Deployment evidence | `docs/delivery/DEPLOYMENT-READINESS.md`, `docs/delivery/evidence/` |
| Install, upgrade, backup, restore | `docs/RUNBOOK.md`, `docs/OPERATIONS.md` |
| Troubleshooting | `docs/TROUBLESHOOTING.md`, `docs/KNOWLEDGE-BASE.md` |
| User and configuration guides (illustrated) | `docs/guides/` (12 chapters) |
| Short user and admin guides | `docs/USER-GUIDE.md`, `docs/ADMIN-GUIDE.md` |
| Demo personas and roles | `docs/delivery/DEMO-LOGINS.md` |
| Architecture and history | `HANDOVER.md`, `docs/delivery/SESSION-SUMMARY.md` |
| Refresh guide screenshots | `scripts/capture_screenshots.py`, then `scripts/build_guides.sh` |
