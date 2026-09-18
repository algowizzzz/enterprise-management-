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

### AI endpoint for the help assistant

Off by default. `[assistant] ai_enabled = yes` with the endpoint URL and model
turns it on; an administrator then enters the API key in Assistant Settings.
The key is never in the configuration file.

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
SSO or an AI endpoint is configured, allow exactly those internal hosts.

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
