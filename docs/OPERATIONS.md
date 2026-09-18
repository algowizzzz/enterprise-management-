# Operations

For the team running Consilium once it is installed. Every procedure here has
been run, not just written: the evidence is in
[`delivery/DEPLOYMENT-READINESS.md`](delivery/DEPLOYMENT-READINESS.md).

Paths assume the deployment kit's defaults: installation in `/opt/consilium`,
configuration in `/etc/consilium/consilium.conf`, backups in
`/var/backups/consilium`, service account `consilium`. Substitute your own
from the configuration file. On Windows see the last section.

Every operation below is one command, driven by the one configuration file.
The commands live in `/opt/consilium/deploy/` after installation and need
root (they switch to the service account for everything the application does).

---

## Starting and stopping

The system is three kinds of process, each a systemd unit:

| Unit | What it does | Without it |
|---|---|---|
| `consilium-web.service` | Serves the interface and the API, on 127.0.0.1 only; the reverse proxy is the way in | Nothing responds |
| `consilium-worker@1.service`, `@2`, … | Run queued jobs (one unit per worker; the count is `[web] background_workers`) | Notifications, imports and exports queue up and never run |
| `consilium-scheduler.service` | Triggers timed jobs | Reviews never fall due, reminders never send, retention never disposes, SLA breaches are never raised |

All three are needed. A system with only the web server looks healthy and
quietly stops doing anything on a timer, which is the kind of failure nobody
notices until an attestation deadline passes.

```bash
sudo systemctl start   consilium.target 'consilium-worker@*'
sudo systemctl stop    consilium.target 'consilium-worker@*'
sudo systemctl restart consilium.target 'consilium-worker@*'
systemctl list-units 'consilium*'
journalctl -u consilium-web -u 'consilium-worker@*' -u consilium-scheduler --since today
```

**Run exactly one scheduler across the whole deployment.** The framework's
scheduler does not elect a leader; a second one makes every scheduled job run
twice. On a second application server, disable `consilium-scheduler` there.
`verify.sh` counts scheduler processes on the host.

`consilium-socketio.service` is installed but inert: it needs Node.js and the
framework's realtime libraries, which the bundle does not carry. The product
works without it; pages refresh on navigation rather than live.

The units run as the service account with no new privileges, a private
`/tmp`, the operating system read-only, home directories hidden, and write
access only to the installation. They restart on failure and start at boot.

## Health and acceptance

```bash
sudo /opt/consilium/deploy/verify.sh --config /etc/consilium/consilium.conf
```

The full acceptance run — services, health check, sign-in, smoke test, the
workflow primitives, a PDF, the air-gap evidence, the interface sweep, no
external fetches, TLS, the scheduler — about a minute. It writes
`/opt/consilium/logs/readiness-<timestamp>.md` (and `.json`). Run it after any
install, upgrade, restore or configuration change.

The health check alone (17 checks, each naming its own remedy):

```bash
cd /opt/consilium/sites
sudo -u consilium ../env/bin/python ../deploy/healthcheck.py --site <site>
```

## Backup

```bash
sudo /opt/consilium/deploy/backup.sh --config /etc/consilium/consilium.conf --label before-change
```

Writes one directory per backup under `[backup] dir`: the database, the public
and private files, the site configuration — **which holds the encryption key;
without it every stored password and secret in the backup is unreadable** —
and `BACKUP.json` with the size and SHA-256 of each file. Files are mode 0600,
owned by the service account. Backups older than `retention_days` are removed,
never the newest.

`consilium-backup.timer` runs this nightly (`[backup] schedule`, default
02:30). Check it with `systemctl list-timers consilium-backup.timer`.

**Copy backups off the machine.** A backup that only exists on the machine it
protects is not a backup. Nothing in the product does this for you.

## Restore

```bash
# into a NEW site beside the live one -- the rehearsal, and the safe first step
sudo /opt/consilium/deploy/restore.sh --config /etc/consilium/consilium.conf \
    --from /var/backups/consilium/<set> --as-site restored.example.internal --db-name consilium_restored

# over the live site (asks for --yes; stops the services first)
sudo /opt/consilium/deploy/restore.sh --config /etc/consilium/consilium.conf \
    --from /var/backups/consilium/<set> --yes
```

It checks every file against `BACKUP.json`, sets the site's encryption key to
the backup's, restores the database and files, migrates (so a backup from an
older release comes up to this one's schema), re-imports the assets and runs
the health check. It also accepts a backup the framework took itself
(`backup --with-files`) from another installation; there are then no recorded
checksums to verify.

Restoring needs the database superuser login (`[database] provisioning =
superuser`): the framework drops and recreates the database. With a
provisioned database, the database team restores the dump into an empty
database, then run `upgrade.sh --force` with the installed bundle to migrate.

Rehearsed: 24 s in place; 56 s for a copy of the demonstration site into a new
site, with every row count identical. **Rehearse it quarterly**, against a real
backup, into a new site.

## Upgrading

```bash
sudo /opt/consilium/deploy/upgrade.sh --config /etc/consilium/consilium.conf --bundle consilium-bundle-<new>.tar.gz
```

In order: verify the new bundle; **back up**; install the new release's Python
environment beside the current one (from the bundle, no network); maintenance
mode on and services stopped; switch `/opt/consilium/env` to the new release;
**migrate**; re-import assets, reference data and settings; maintenance mode
off; start; health check. Rehearsed from the previous release: 1 min 29 s, of
which migrate 27 s, with no table losing a row.

If any step fails it prints the rollback, which is two things — the code and
the database both go back:

```bash
sudo systemctl stop consilium.target 'consilium-worker@*'
sudo ln -sfn /opt/consilium/releases/<previous>/env /opt/consilium/env
sudo /opt/consilium/deploy/restore.sh --config /etc/consilium/consilium.conf --from <the pre-upgrade backup> --yes
sudo systemctl start consilium.target 'consilium-worker@*'
```

The current and the previous release are kept under `/opt/consilium/releases/`;
older ones are removed. Migrations are not reversible: never repair a
half-migrated schema by hand — restore the backup.

## Changing the configuration

Edit `/etc/consilium/consilium.conf`, check it, and run the installer again:

```bash
python3 /opt/consilium/deploy/kit.py check-config --config /etc/consilium/consilium.conf
sudo /opt/consilium/deploy/install.sh --config /etc/consilium/consilium.conf --bundle <the installed bundle>
```

It recreates nothing that exists; it re-applies the site settings (time zone,
mail, SSO, AI endpoint), re-renders the units (worker count, ports) and the
proxy configuration, and restarts the services — so run it in a quiet period.

### Single sign-on

Off by default (`[sso] mode = none`).

- **OpenID Connect** (`mode = oidc`): register the redirect URI
  `https://<hostname>/api/method/frappe.integrations.oauth2_logins.custom/<provider id>`
  with the identity provider (the provider id is the lower-cased provider name
  with underscores, `corporate_sso` for "Corporate SSO"), fill in the
  `oidc_*` keys and the client-secret file, re-run the installer. The sign-in
  page gains the provider's button. People are matched to existing accounts by
  email; with `allow_signup = no` (the default) nobody else can get in.
  Rehearsed end to end against a local test provider.
- **LDAP / Active Directory** (`mode = ldap`): fill in the `ldap_*` keys, the
  bind-password file and the CA file. The installer saves the framework's LDAP
  Settings, which binds to the directory to check them. Uses `ldap3`, a
  pure-Python wheel already in the bundle. Not rehearsed against a directory.

### Email

Off by default. Two routes, one at a time for notifications:

- **SMTP** (`[email] enabled = yes`): the installer saves an outgoing Email
  Account, which connects to the mail server to check the settings. Notifications
  go through the framework's mail queue.
- **Microsoft Graph** (`[email] graph_enabled = yes`), for an organisation that
  allows no SMTP from servers. Notifications are sent through the Graph API as
  the sender mailbox. The directory administrator provides:
  - an **app registration**, with its directory (tenant) ID and application
    (client) ID — no redirect URL, because the server signs in as the
    application (client credentials), never as a person;
  - a **client secret** for it, put in a file readable by root only and named
    by `graph_client_secret_file` (or an environment variable named by
    `graph_client_secret_env`);
  - the **`Mail.Send` application permission**, with admin consent, **limited to
    the sender mailbox by an application access policy**;
  - the **sender mailbox** (`graph_sender`, its user principal name or object ID).

  `graph_authority_url` and `graph_api_url` are for a national cloud only; the
  defaults are the global service. The server needs outbound HTTPS to both
  (the standard `HTTPS_PROXY` settings apply).

Either route can also be set in the portal, under **Admin → Integrations →
Email**, which shows the current route and its status, the SMTP account's
settings (read-only, with a link to edit them), and the Graph settings (the
secret is write-only). **Send a test email to me** sends one message now,
through the saved route, and records it like any notification.

How Graph mail behaves, so an alert can be read correctly:

- Every notification is a **Notification Dispatch** row, sent or not, on either
  route. A failed one stays open and the hourly job retries it, up to three times.
- A token is obtained with the client secret and reused until shortly before it
  expires. A **401** from Graph drops it and gets a new one, once.
- **429 / 503 / 504** (throttling) are waited out, honouring `Retry-After` up
  to 30 seconds, up to three times, within the same attempt.
- A **timeout** is recorded on the dispatch and left for the hourly retry, not
  resent at once: Graph may have accepted a message whose answer was lost.
- Inside a person's request the send is handed to a background worker, so
  nobody's page waits on Graph; the dispatch then fails and reopens if the
  worker's send fails. Workers must be running (see *Starting and stopping*).
- The framework's own mail (password resets) always uses the SMTP account.

Rotating the secret: write the new value to the secret file and re-run the
installer, or paste it in Admin → Integrations → Email. The cached token is
dropped when the settings are saved.

### AI endpoint for the help assistant

Off by default. `[assistant] ai_enabled = yes` with the endpoint URL and model
turns it on; an administrator then enters the API key in **Admin →
Integrations** (or Assistant Settings in the workspace), switches on the help
assistant and the analysis features, saves, and uses **Test connection**, which
sends one short request through the audited client and reports the answer's
latency or the error. The key is never in the configuration file and never
shown again once saved.

### Doc AI and horizon scanning

Two buttons that send a person to another tool the organisation runs, set in
**Admin → Integrations**. Both show from the start and explain "not connected
yet" until an address is saved; either can be switched off. Only http(s)
addresses are accepted, and a refused address is audited.

- **Doc AI** (a rich document editor): an address template with
  `{document}`, `{version}`, `{version_label}`, `{title}` and `{document_url}`,
  each URL-encoded. The file never leaves: only those identifiers, in the
  address the person's browser opens. Each hand-off is in the Access Log
  (method "Doc AI hand-off"). The button can be limited to roles; a person must
  always be able to read the document.
- **Horizon scanning**: one address, opened as saved. `/horizon-scanning`
  forwards to it.

---

## Certificates, ports and service accounts

### Ports

| Port | Listens on | Who connects | Open in the firewall? |
|---|---|---|---|
| 443 (`[tls] https_port`) | all interfaces, the reverse proxy | users' browsers | yes, from user networks |
| 80 (`[tls] http_port`) | all interfaces, the reverse proxy | browsers that typed `http://`; answered with a redirect only | optional |
| 8000 (`[web] port`) | **127.0.0.1 only**, the application server | the reverse proxy on the same host | no |
| 5432 | the database server | this host | from this host only |
| 6379 | the Redis server | this host | from this host only |
| 9000 | not used (realtime server not shipped) | — | no |

Outbound: none. The application needs no internet access; if outgoing mail,
SSO or an AI endpoint is configured, allow exactly those internal hosts. With
the Microsoft Graph mail route, allow HTTPS to the sign-in service and to Graph
(or their national-cloud equivalents). Doc AI and horizon scanning need nothing
from the server: people's browsers go there.

### Service accounts (least privilege)

| Account | Created by | Can | Cannot |
|---|---|---|---|
| `consilium` (OS) | the installer: system account, no password, no login shell, home `/opt/consilium` | read the code; write `sites/`, `logs/`, `config/` and the backup directory; run the three units | log in; write the code (`/opt/consilium/releases` is root-owned); read `/etc/consilium/secrets` |
| `root` (OS) | — | run `install.sh`, `upgrade.sh`, `restore.sh`, `verify.sh`; read the secrets | — |
| Database role, named as the database (`[database] name`) | the installer (`superuser`) or the database team (`provisioned`) | own and use its one database | anything else on the server; it is not a superuser |
| Database superuser (`root_user`) | the database team | create the database and role; restore | — **used only by install and restore**; with `provisioned` the kit never needs it |
| Redis | — | — | Use `rediss://user:password@host` URLs if the Redis server enforces authentication |
| Administrator (application) | the installer; password from `[site] admin_password_file` or generated into it (mode 0600) | everything in the application | — change its password after first sign-in, and give people their own accounts rather than sharing it |

Secrets live in `/etc/consilium/secrets/` (mode 0750 directory, 0600 files,
owned by root). The installer reads them as root and hands them to the
processes that need them through the environment, never through a command line
or a temporary file. The database role's password also ends up in the site's
`site_config.json` (mode 0640, service account), because the framework reads
it from there.

### Certificates

The reverse proxy terminates TLS with `[tls] cert_file` and `key_file`
(PEM). The rehearsal used a throwaway CA; production needs a certificate from
the organisation's CA:

1. **Request.** Generate the key on the server and a request for the public
   hostname (the subject alternative name must be `[site] hostname`):
   ```bash
   sudo openssl req -new -newkey rsa:3072 -nodes \
       -keyout /etc/pki/tls/private/<hostname>.key -out /tmp/<hostname>.csr \
       -subj "/CN=<hostname>" -addext "subjectAltName=DNS:<hostname>"
   sudo chmod 600 /etc/pki/tls/private/<hostname>.key
   ```
   Send the `.csr` to the CA. The key never leaves the server.
2. **Install.** Put the issued certificate followed by any intermediates in
   `cert_file`. Trust the organisation's root CA system-wide (RHEL:
   `/etc/pki/ca-trust/source/anchors/` + `update-ca-trust`; Ubuntu:
   `/usr/local/share/ca-certificates/` + `update-ca-certificates`): the PDF
   engine fetches the application's stylesheets through the proxy, and the
   rehearsal trusted its CA this way (an untrusted chain was not tested).
3. **Apply.** Re-run the installer (it tests the proxy configuration before
   reloading), then `verify.sh`: the TLS check verifies the chain against the
   system trust store for the hostname and reports the expiry date.
4. **Renew** before `notAfter` — the readiness report records it. Replace the
   two files and `sudo systemctl reload nginx` (or Caddy). No application
   restart is needed. Put the expiry date in the team's calendar; nothing in
   the product alerts on it.

Only TLS 1.2 and 1.3 are offered, with HSTS. Caddy is configured with the
certificate files explicitly, so it never tries to obtain one from a public
CA.

---

## What to watch

Nothing here is automated yet. Until it is, watch:

- **All units active**: `systemctl list-units 'consilium*'`; exactly one
  scheduler.
- **Queue depth.** A worker that has died leaves jobs accumulating.
- **Failed scheduled jobs**: Scheduled Job Log in the interface.
- **Database size and connection count.**
- **Disk** on the installation and on the backup destination.
- **Certificate expiry** (in every readiness report).
- **The nightly backup ran**: a new directory under the backup directory each
  morning.

## Windows

`deploy/install.ps1` installs from a Windows bundle; there is no configuration
file on Windows. `deploy/service/windows/register-services.ps1` registers three
Task Scheduler tasks (web, workers, scheduler) that start at boot under a
service account and run winbench's own supervisor. Backup and restore use the
framework's commands (`python -m winbench.cli backup`, the framework's
`restore`). None of this has run on Windows yet; see the acceptance script in
[`RUNBOOK.md`](RUNBOOK.md#windows-acceptance-script).

## Known gaps

Stated plainly so nobody assumes otherwise:

- **No log shipping or metrics.** Logs are files under `/opt/consilium/logs`
  and the systemd journal.
- **Backups are not copied off the host** by anything in the product.
- **The realtime server is not shipped** (needs Node.js).
- **Rollback has not been exercised** end to end; the steps are above.
- **Windows** is unrun.


---

# Appendix: platform-team reference

The business guides (`docs/guides/`, and the short `USER-GUIDE.md` and
`ADMIN-GUIDE.md`) are written for business users and business administrators.
Everything technical that used to sit in them is kept here: commands, record
type and field names, configuration syntax and the tooling behind the guides.
Where the business guides say "ask your platform team", this is what the
platform team does.

## A. Administration internals (moved from the administrator guide)

### 1. How it fits together

| Piece | What it is | Where to change it |
|---|---|---|
| **Portal** | The screens most people use: `/`, `/forums`, `/policies`, `/escalations`, `/reports`, `/admin`, the guided forms. | Page templates in `apps/consilium/consilium/www/`. Look and feel from **Portal Branding**. |
| **Workspace** | The full record screens at `/app`, with four workspaces: Governance, Policy, Escalation, Consilium Administration. | Records, roles and settings, through the interface. |
| **Record types** | About 140 entities across Core, Governance, Policy and Escalation. | Generated from `apps/consilium/specs/`; see `DEVELOPING.md`. |
| **Reference data** | The lists every form chooses from. | `/admin`, or CSV import. The starting set is in `deploy/reference/`. |
| **Rules as data** | Workflow state flags, watched fields, approval routes, lifecycle gates, escalation matrix, service levels. | Records in the workspace. None of these need a release. |

Three design rules explain most of how the system behaves. Knowing them saves
support calls.

1. **Nothing is deleted.** Seats are ended, forums are disbanded, documents are
   retired, and reference values are made inactive. History can always be read
   back as it stood on any date.
2. **States are configuration, flags are logic.** A state's name (for example
   "Under Review") means nothing to the code. The code reads semantic flags
   (`is_editable`, `is_active`, `requires_review`, `is_open`, `is_committable`,
   `requires_statement`, `is_affirmative`), and a state's flags come from its
   **Workflow State Flag** row. Renaming a state, or adding one, is
   configuration.
3. **Every refusal is recorded.** When a control stops an action, the reason
   is written to the **Governance Refusal Log**, even if the action is rolled
   back.

---

### 2. First-run checklist

After installation, in this order. A system without these steps works, but
people will hit empty dropdowns and unassigned steps.

1. **Reference data.** `deploy/seed.py` loads a generic starting set:
   - forum types and roles;
   - risk categories and a two-tier risk type taxonomy;
   - organisation units and organisational levels;
   - legal entity, jurisdictions, document types, escalation types, lines of
     defence.

   Replace it with your own taxonomy (§4). It is only there so the system
   works out of the box.
2. **Time zone.** In **System Settings**, set the zone your organisation works
   in. Dates the server stamps, such as "decided on", use it. The installer
   leaves it at UTC.
3. **Branding.** Set the portal's name, logo, colours and home page (§5).
4. **People and roles** (§3). At least one active person must hold each of:
   - **Risk Governance Office.** Raising approval steps on a formation request
     fails with *Step Unassigned* without one.
   - **Head of Risk Governance.** Approval exceptions and bypasses need one.
   - **Compliance Reviewer.** Forums cannot leave draft without one.
   - **Enterprise Policy Office**, **Policy Owner** and **Policy Reviewer**, for
     the document lifecycle.
   - **Escalation Owner** and **Escalation Reviewer.**
5. **Formation approval route.** A standard route is created automatically.
   Review its steps under *Governance → Formation Approval Route* and adjust
   them to your delegations.
6. **Escalation configuration.** Create at least one **Escalation Matrix**, the
   **SLA Definitions** for the time limits you hold yourselves to, and a
   **Business Calendar** if limits count working hours only. Without these,
   severity is always manual and no clock runs.
7. **Home page guidance.** Write **Guide Articles** (Admin → *The home-page
   guide*). Each article replaces one section of the built-in wording on the
   home page.
8. **Notification channels.** Point **Notification Channels** at your mail
   system. To show your logo in outgoing mail, set **Brand Logo** on the
   outgoing **Email Account**.
9. **Retention.** Define **Retention Classes** and assign them, before records
   accumulate.
10. **Check it.** Run the health check (§8). It should report every check
    passed.

---

### 3. People and access

**Add a person.** *Admin → Users*, or `/app/user/new`. Use the **System User**
type for anyone who works in the portal or the workspace. Assign roles on the
user's **Roles** tab. For people who share a job, a **Role Profile** (*Admin →
Role profiles*) gives the right set in one step.

**Limit someone to part of the organisation.** *Admin → Record-level
restrictions* (User Permissions). For example, restrict a user to one
organisation unit or legal entity. The restriction applies everywhere:
lists, counts, reports, search and the API.

**Sensitive escalations.** A matter marked *sensitive* is invisible to anyone
without the **Sensitive Escalation Access** role, on every read path. Grant
that role sparingly, and review who holds it as part of your access reviews.

**See what a user sees.** Open the user in the workspace and use
**Impersonate** (System Manager only). (In this framework version the button is shown only when you are signed in as
the **Administrator** account; see [the administration chapter](guides/09-administration.md).) The session is logged. This is the
right way to reproduce "I can't see X", and it involves no password.

**Remove access.** Disable the user; do not delete them. Their name stays on
everything they did.

The role table in the user guide (§8) says what each role can do. The exact
permissions are on each record type (*Admin → Permission rules*). Change them
there if your operating model differs, and record why.

---

### 4. Reference data

`/admin` lists every reference list with its purpose, its module and how many
values it holds. **Add a value** opens a new entry. **Refresh counts** re-reads
the numbers.

- **Never delete a value that records use.** Untick **Active** instead. The
  value stays on historical records and is no longer offered for new ones.
- **Codes are permanent.** Integrations and imports match on the code. Rename
  the display name freely, but do not reuse a retired code.
- **Bulk changes:** every list accepts CSV import (*workspace → the list →
  Menu → Import*). **Import Profiles** save a mapping you use regularly.
- **Risk types have two tiers.** A tier 1 type has no parent; a tier 2 type
  must have one.
- **Organisation units are one tree:** operating groups, corporate support,
  lines of business and business units.

---

### 5. Making it look like your organisation

*Consilium Administration → Portal Branding* (`/app/portal-branding`). One
record controls:

| Section | Fields | Where it shows |
|---|---|---|
| Identity | Portal name, organisation name, logo, browser-tab icon | Portal header and footer, the browser tab, the sign-in page, the workspace header and loading screen. |
| Colours | Primary colour, accent colour, header style (glass, primary colour or white) | Every portal page. Shades are derived from the primary colour, and the dark theme is adjusted to keep contrast. |
| Typeface | Font family name, regular and bold font files | Every portal page. |
| Home page banner | Heading, text, image, two buttons and their links | The top of the home page. |
| Footer | A line of text | Every portal page. |

Save, then reload the portal. There is no deployment step.

**Brand assets are uploaded, not committed.** Logos, photographs and font files
are stored as site files and served from your own server, so the code
repository never holds anyone's brand. Upload only assets your organisation is
licensed to use in this way, particularly fonts. Many commercial fonts are
licensed per domain or per server.

**Practical advice:**

- **Logo:** use SVG where you can, wide rather than square. If your logo is
  drawn for a white background, set **Header style** to *White*.
- **Banner image:** at least 1600 pixels wide, with the subject on the right.
  The heading sits on the left over a gradient.
- **Colours:** the system picks white or dark text for readability
  automatically. Check the home page in both themes after a change.

Saving the record also updates the framework's own settings: the website and
system application name, logo, favicon, splash image and footer. It also hides
the framework's help and app-switcher entries. The same step re-runs on every
migration, so an upgrade does not bring them back.

---

### 6. Configuring behaviour

All of these are records. Change them in the workspace; none needs a release.

| To change | Edit | Notes |
|---|---|---|
| The steps a formation request goes through | **Formation Approval Route** (and its steps) | Steps are role-based, in sequence or in parallel. The most specific active route wins. A role-based step goes to the first enabled holder of the role, alphabetically. |
| The criteria a request is evaluated on | Seeded on each new request as rows | The five standard criteria are always present. |
| Document approval routing | **Approval Route** | Conditional routing for governing documents. |
| What must be true before a document changes phase | **Document Lifecycle Gate** | For example, no publication without a complete approval chain. |
| The document lifecycle itself | *Workflow → Governing Document Lifecycle* | Add a state here **and** its **Workflow State Flag** row (below). |
| What a state means | **Workflow State Flag** | One row per state, per record type. A state with no row is refused rather than guessed. |
| Changes that send a record back for review | **Watched Field Set** | For example, changing a forum's mandate sends it back for a compliance review. |
| Escalation severity and routing | **Escalation Matrix** (rules, routes, notifications) | Used when a matter's severity source is *Matrix*. |
| Required fields per escalation type and severity | **Escalation Template** | Separate templates for the escalation, its action plans and its risk acceptances. |
| Time limits | **SLA Definition**, **Business Calendar** | Clocks start and stop automatically; breaches are recorded and notified. |
| Periodic attestations | **Attestation Campaign** | Generates a task for each person in the population. |

**Adding a workflow state (worked example).** To add "Legal Review" between
Review and Approved:

1. Add the state and its transitions to the workflow.
2. Add a **Workflow State Flag** row: target type *Governing Document*, state
   field `lifecycle_phase`, state *Legal Review*, and the flags it should carry
   (editable? active? requires review? open?).
3. Test by moving a document through it.

Without step 2 the system refuses to enter the state rather than leaving stale
flags. That is deliberate: a missing row shows up at once, instead of quietly
removing a permission weeks later.

> The supported procedure, including the one-time switch that lets states
> and phases differ, is in *Custom lifecycle steps* below.

---

### 7. The workspace

The four Consilium workspaces are part of the application and sit first in the
sidebar. The framework's own workspaces (Users, Website, Tools, Integrations,
Build) come after them. Administrators can add shortcuts or cards to a
workspace with **Edit**. Users can hide workspaces they do not need from their
own sidebar.

---

### 8. Keeping it healthy

| Check | Command (from `<bench>/sites`, with `FRAPPE_BENCH_ROOT=<bench>`) | Expect |
|---|---|---|
| Health check | `python <repo>/deploy/healthcheck.py --site <site>` | Every check passed, including *libraries loaded on demand*. |
| Full verification | `<repo>/scripts/verify.sh --bench <bench> --site <site>` | Platform rules, toolchain tests, migration, application tests, health. |
| Interface sweep | `python <repo>/scripts/ui_regression.py --site <site> --url <address>` | Every portal page renders, signed in and out; no dead links or missing assets; no framework branding visible. |

Run the health check after every change to the installation, and the full
verification after every upgrade.

**Where to look when something fails:**

- **Error Log** (Admin → *Error log*): server errors, with their traceback.
- **Governance Refusal Log**: every action a control refused, and why.
- **Scheduled jobs** (Admin → *Scheduled jobs*): background work and when it
  last ran. Run **exactly one** scheduler process across the deployment, or
  every scheduled job fires twice.

**Upgrading:** follow [`OPERATIONS.md`](OPERATIONS.md). In short: back up,
update the code, re-import the asset bundle with
`winbench assets --import <bundle> --copy`, migrate, then run the health
check. Browsers pick up new stylesheets and scripts automatically, because
asset addresses carry a fingerprint of the files.

---

### 9. Demonstration data

`deploy/demo_data.py` loads a realistic demonstration organisation:

- about twenty role-based personas (all `@demo.example`);
- a forum hierarchy with membership, meetings, motions and votes;
- governing documents in every lifecycle phase;
- escalations in every state, with action plans, risk acceptances and
  closures;
- configuration: escalation matrix, time limits, approval route, attestation
  campaign, guide articles.

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> python <repo>/deploy/demo_data.py --site <site>
```

It is safe to run twice. **Do not load it into production.** The script's
header describes how to remove it. The demonstration users have no passwords;
use **Impersonate** to see the system as one of them.

---

### 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A dropdown on a form is empty | The reference list has no active values | Add values at `/admin`, or re-run `seed.py`. |
| "Step Unassigned" when raising approval steps | Nobody active holds the step's role | Give the role to an active person (§2, step 4). |
| A JSON or code field shows no editor | The runtime libraries are missing from the asset bundle | Re-import the bundle; the health check names what is missing. |
| The workspace opens on a blank setup wizard | First-run setup not marked complete | Run `seed.py`; it completes setup and resets the landing page. |
| The portal looks unstyled or out of date | Assets not linked after an upgrade | `winbench assets --import <bundle> --copy`, then reload. |
| A user sees less than expected | A role or record-level restriction | Impersonate them (§3) and check *Record-level restrictions*. |
| A refusal message on save | A control or gate refused it | The message names the rule; the Governance Refusal Log has the detail. |
| Scheduled notices arrive twice | Two scheduler processes | Stop one. |

---

### 11. Help assistant

The **Help** button on every portal page answers questions about that page.
It needs no configuration and no network: out of the box it answers from the
user guide, this guide (administrators only), the glossary, published **Guide
Articles**, published enterprise-scope **Glossary Terms**, and a built-in
description of every portal page. Answers take the asker's roles and
permissions into account, and it never describes a record the asker cannot
read.

**Where the guides come from.** In a development checkout the assistant finds
the repository's `docs/` folder itself. An installation from the bundle
carries the application but not `docs/`; copy the folder onto the server and
set its path in the site configuration:

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> python -m frappe.utils.bench_helper frappe \
    --site <site> set-config assistant_docs_path /path/to/docs
```

Without it the assistant still answers from the page descriptions, the
glossary records and the guide articles. Edited guides are picked up on the
next question; there is nothing to rebuild.

**Settings.** In the portal, **Admin → Integrations** (`/integrations`): paste
the API key, switch on *Use for the Help assistant* and *Use for analysis
features*, save, then **Test connection**. The same settings are in the
workspace under *Consilium Administration → Assistant Settings*
(`/app/assistant-settings`):

| Setting | What it does |
|---|---|
| Questions Per Person Per Hour | The limit on each person (default 30). It protects a paid AI service and the server alike. |
| Use an AI Endpoint | Off by default. When on, an AI service phrases the answer; when off, or when the service fails or is slow, the built-in answer is shown. |
| Request Format | *Anthropic Messages API*, or *OpenAI-compatible API* for a hosted provider or a gateway your organisation runs in front of a model that speaks the chat-completions format. |
| Endpoint Base URL | The service's base address, reachable **from the server**. Browsers never contact it. |
| Model | The model identifier the endpoint expects. |
| API Key | Stored encrypted. Leave blank for a gateway that authenticates the server another way. |
| Timeout, Maximum Answer Length | After the timeout the built-in answer is shown. |
| What Leaves the Platform | See below. |

**What leaves the platform** when an AI endpoint is on:

- *Guidance only* (the default): the question, the guide sections that match
  it, the kind of page and its address (never a record's title or reference),
  the asker's role names, and what the built-in answer worked out about their
  access. No record contents, and not the asker's name or email.
- *Include visible record summary*: also a few fields of the record on screen
  that the asker may read, and the actions open to them on it. Never for a
  sensitive escalation, or a confidential or restricted document (or a request
  about one).

Every request to the endpoint is recorded as an **AI Service Request** with
exactly what was sent (less the key) and what came back, including failures
and timeouts.

**The log.** Every question is an **Assistant Interaction**: who asked, on
which page, the answer, whether an AI answer was shown and, if not, why, and
how long it took. Administrators and Consilium Audit can read it; nobody can
edit it. A restricted record is never named in it.

### 12. Integrations

**Admin → Integrations** (`/integrations`, administrators only) has one card per
connection to a service outside the platform. Each card says what the
connection is for, **what leaves the platform** when it is on, and its status:
*Connected*, *Not connected* (on, but its address or credentials are missing)
or *Off*. Keys and secrets can be pasted and removed, never read back: a card
says only "A key is saved" or "No key saved".

| Card | What you set | Notes |
|---|---|---|
| AI assistant and analysis | API key, the two switches, request format, endpoint, model, lengths, what may be shared, the classification limit, the analysis features | **Test connection** sends one short request with the saved settings and shows the latency or the error. It is recorded as an AI Service Request. A warning shows while a switch is on with no key saved. |
| Doc AI | Button label, address template, new tab, which roles see it | Shows "Open in Doc AI" on every governing document, each version and the viewer. Only identifiers go in the address (see the card); each hand-off is in the Access Log. Until an address is set the button explains that Doc AI isn't connected yet. |
| Horizon scanning | Label, address, new tab | Shows a button on the policy inventory and on regulatory updates; `/horizon-scanning` forwards to the address. |
| Email | Route (SMTP or Microsoft Graph), the Graph registration | The SMTP account's settings are shown read-only, with a link to edit them. **Send a test email to me** sends one now, through the saved route. See the Operations guide, *Email*, for what a Graph route needs. |
| Single sign-on | Nothing: read-only | Shows each provider, whether it is on, and the exact redirect address to register with the identity provider, with a copy button. Switching SSO on or off is done in the deployment configuration, because a mistake would lock everyone out. |

Only http:// and https:// addresses are accepted anywhere on this page; any
other kind (a `javascript:` address, for example) is refused, and the refusal
is recorded in the Governance Refusal Log.


## B. Custom lifecycle steps (states and phases)

The business guide ([chapter 9](guides/09-administration.md), *Adding a step to
a workflow*) tells business administrators how to add a step such as *Legal
Review* to the policy lifecycle. That needs the lifecycle to run on the
document's workflow state, with its business-facing **phase** derived from it.
A newly installed site runs the lifecycle directly on the phase field. The
platform team switches it once per site:

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> python -m frappe.utils.bench_helper frappe \
    --site <site> execute consilium.policy.lifecycle.derive_phase_from_state
```

In one transaction it:

1. sets every Governing Document's `workflow_state` to its current
   `lifecycle_phase`, so no document moves;
2. copies each Workflow State Flag row keyed on `lifecycle_phase` onto
   `workflow_state`, with the same flags, each naming itself as its phase;
3. sets the *Governing Document Lifecycle* workflow's state field to
   `workflow_state`.

It answers `{"switched": true, "flag_rows": 6}`; a second run answers
`{"switched": false, "reason": "already derived"}`. Only a System Manager (or
Administrator) may run it. Gates, service levels, reports and lists keep
reading `lifecycle_phase`, which the controller writes from the state on save
(`lifecycle.sync_phase`). A phase written directly, disagreeing with the state,
is refused and logged.

After the switch a new state is: a **Workflow State** and **Workflow Action
Master** for its names, rows in the workflow's states and transitions, and a
**Workflow State Flag** row with `state_field = workflow_state` and **Phase**
set to one of Draft, Review, Approved, Published, Implemented, Retired. No
Customize Form, Property Setter or schema change. Gates are configured per
phase (`lifecycle.gate_key`): a state is gated as the phase it belongs to.

Refusals an administrator may report:

| Message | Cause |
|---|---|
| "Workflow state … names no phase. Set Phase on its Workflow State Flag row …" | No flag row on `workflow_state`, or its Phase is empty |
| A Workflow State Flag row refused on save, listing the phases | The Phase is not one of the six phases (a misspelling is now refused where it is typed) |

**Verified** on the demonstration site on 18 September 2026 (switch, Legal
Review with Phase *Review*, a gate on the Review phase, approval, and a rename
to Legal Clearance), then restored exactly from a snapshot, including undoing
the switch (workflow state field, states, transitions, flag rows, gates, every
document's workflow state, the refusal log).

**Renaming a state** is add-move-retire: add the new name with the same flags
and phase, point incoming transitions at it and copy its outgoing ones, add a
temporary "Move to …" transition, move each document, then remove the old
state and its transitions. Only the governing document lifecycle can be
renamed this way; other record types' state names are written by the
platform's own code.

**Do not add a workflow to a record type the platform moves itself** (formation
requests, forums, compliance reviews, document requests, escalations, action
plans, risk acceptances, attestation campaigns and tasks, approval decisions,
imports, notifications, SLA clocks). A workflow allows state changes only
through its own transitions and roles, so the platform's actions would be
refused. Verified with a test workflow on Attestation Task inside a rolled-back
transaction. A workflow is right for a type people move by hand, such as
Policy Violation (`violation_status`).

## C. Rule syntax behind the configuration screens

**Escalation matrix conditions** are JSON objects over these facts:
`escalation_type`, `tier_1_risk_type`, `tier_2_risk_type`,
`organizational_level`, `material_entity_impact`, `risk_appetite_breach`,
`systemic`, `severity`. Values are reference-list codes; a list means "any of
these"; a fact left out matches anything; `{}` is a catch-all.

```json
{"tier_1_risk_type": "TECHNOLOGY", "organizational_level": "ENTERPRISE"}
{"risk_appetite_breach": true}
{"systemic": true}
{}
```

Only active matrices in force today are considered; a matrix whose scope
excludes the matter is skipped; rules are tried in ascending priority and the
first match wins. Rule destinations and notifications are joined to a rule by
its code. An unknown fact is refused ("… is not a routable attribute").

**SLA definition "Applies When"** is a JSON filter on the record, for example
`{"systemic": 1}`. *Time In State* needs `state_field` and `state_value`.

**Business calendar holidays** are a JSON list of ISO dates, for example
`["2026-12-25", "2026-12-26"]`.

**Classification rule conditions** group tests with `all`, `any` or `none`. A
test names a `question` and an operator: `equals`, `not_equals`, `in`,
`not_in`, `includes`, `greater_than`, `less_than`, `is_set`, `is_not_set`.

```json
{"any": [{"question": "q_scope", "equals": "enterprise"},
         {"question": "q_obligation", "equals": "yes"}]}
```

A rule set that has classified a request is sealed; a duplicate inherits the
seal and accepts one save only, so every change goes in before the first save.

**Attestation campaign population** is a JSON filter (`population_filter`), for
example `{"is_active": 1}`; `participant_field` names the field holding the
person asked, `second_signatory_field` the counter-signer.

**Notification templates** are Jinja: `{{ doc.<field> }}`, `{{ recipient_name }}`,
`{{ link }}`, `{{ today }}`, `{{ subject_name }}`, plus each event's own context
(shown on the template). A template with a syntax error is refused; one that
fails at send time falls back to the built-in wording and is logged.

## D. Demonstration logins

`deploy/demo_logins.py` gives every `@demo.example` persona a random password
and writes the list (roles, and where each persona starts) to a Markdown file,
which must be outside the repository:

```bash
cd .bench/sites
FRAPPE_BENCH_ROOT=<bench> ../../.venv/bin/python ../../deploy/demo_logins.py \
    --site <site> --url http://<site>:8000 --out ~/demo-logins.md [--administrator]
```

Running it again issues new passwords. It refuses a site with non-demo users
unless `--force`. Nothing is emailed; no password is ever committed.

## E. Regenerating the guides' pictures and the PDF and Word files

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> <repo>/.venv/bin/python <repo>/scripts/capture_screenshots.py \
    --site consilium.localhost --url http://consilium.localhost:8000
# then only what failed, or one area / pattern
... capture_screenshots.py --failed
... capture_screenshots.py --area governance --only 'forum-*'
# the chapter-9 walkthrough pictures, while that example is set up
... capture_screenshots.py --area verification
bash <repo>/scripts/build_guides.sh            # into ~/Desktop/Consilium-deliverables/
```

The capture script signs each demonstration persona in with a server-side
session (no password), finds each demonstration record by its characteristics
rather than its number, draws the numbered callouts as a temporary overlay in
the page just before each picture, and writes `docs/guides/images/manifest.json`.
The build script needs pandoc, and Google Chrome (through the repository's
Playwright) or LibreOffice.

## F. Rebuilding the leadership briefing (slide deck)

One command, from the repository root:

```bash
.venv/bin/python scripts/deck/build_deck.py
# writes ~/Desktop/Consilium-deliverables/Consilium-Leadership-Briefing.pptx
.venv/bin/python scripts/deck/build_deck.py --out deliverables/Consilium-Leadership-Briefing.pptx
# refreshes the copy committed with the release
```

It needs python-pptx from `requirements-dev.txt`, a pure-Python wheel; its
lxml and Pillow dependencies are wheels already in `requirements.txt`. It uses
no network, no Node.js and no npm. The sources are in `scripts/deck/`:

- `facts.json` holds every number and status: tests, checks, entities,
  demonstration counts, the backlog and the coverage class of every
  requirement.
- `slides.py` holds the slides in order, with their text, layout and speaker
  notes.
- `deckkit.py` holds the drawing primitives.

The screenshots come from `docs/guides/images/`, the same set the onboarding
guide uses. Re-capture them first (§E) if the interface has changed.

**After a re-grade, edit only `facts.json["coverage"]`.** The coverage chart,
the heatmap and its title, the "still open" list, the roadmap's first phase
and the appendix trace table are all computed from it. Slide text names
numbers as `<<name>>` placeholders, resolved from `facts.json` by
`build_deck.compute_values`. An unknown name stops the build rather than
leaving a gap.

The script exits with status 2 if a screenshot is missing; it draws a
labelled placeholder on the slide in its place. Check the result visually
before it goes out:

```bash
soffice --headless --convert-to pdf Consilium-Leadership-Briefing.pptx
pdftoppm -r 60 -jpeg Consilium-Leadership-Briefing.pdf slide
```
