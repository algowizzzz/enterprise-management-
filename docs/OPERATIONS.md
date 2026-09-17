# Operations

For the team running Consilium once it is installed. Every procedure here has
been run, not just written.

Paths assume an installation at `/opt/consilium` on Linux or `C:\consilium` on
Windows, with the site named `consilium.local`. Substitute your own.

Throughout, `PY` is the installation's own interpreter — `/opt/consilium/env/bin/python`
or `C:\consilium\env\Scripts\python.exe`. Use it rather than the system Python,
or you will be running against the wrong set of packages.

---

## Starting and stopping

The system is three processes:

| Process | What it does | Without it |
|---|---|---|
| Web server | Serves the interface and the API | Nothing responds |
| Background worker | Runs queued jobs | Notifications, imports and exports queue up and never run |
| Scheduler | Triggers timed jobs | Reviews never fall due, attestation reminders never send, retention never disposes |

All three are needed. A system with only the web server looks healthy and
quietly stops doing anything on a timer, which is the kind of failure nobody
notices until an attestation deadline passes.

```
cd /opt/consilium/sites
export FRAPPE_BENCH_ROOT=/opt/consilium

$PY -m frappe.utils.bench_helper frappe --site consilium.local serve --port 8000
$PY -m winbench.cli worker
$PY -m winbench.cli scheduler
```

For a long-running deployment, run each under the platform's service manager —
systemd on Linux, a Windows service on Windows — so they restart on failure and
start at boot. `winbench start` runs all three under one supervisor for
development and for a single-machine deployment where a service manager is not
available.

---

## Backup

```
cd /opt/consilium/sites
FRAPPE_BENCH_ROOT=/opt/consilium $PY -m frappe.utils.bench_helper frappe \
    --site consilium.local backup --with-files
```

Writes four files to `sites/consilium.local/private/backups/`: the database, the
public files, the private files, and the site configuration. `--with-files` is
not optional in practice — the database holds the records, the file archives
hold every document attached to them, and a restore without them produces a
system full of records pointing at documents that are not there.

Copy all four off the machine. A backup that only exists on the machine it
protects is not a backup.

**Schedule this.** Nothing in the product does it for you.

## Restore

**An untested backup is not a backup.** This procedure has been rehearsed: a
backup was taken, restored into an empty database on a different site, and the
result verified by row count and by the health check.

```
# 1. Create an empty database and a site pointing at it.
createdb -h <host> -p <port> -U postgres consilium_restored

# 2. Point a site configuration at that database. Copy the existing site
#    directory and edit site_config.json so db_name is the new database.

# 3. Restore.
cd /opt/consilium/sites
FRAPPE_BENCH_ROOT=/opt/consilium $PY -m frappe.utils.bench_helper frappe \
    --site restored.local restore <path-to>-database.sql.gz \
    --db-root-username postgres --db-root-password <password>

# 4. Verify. Do not skip this — a restore that reports success and produces an
#    incomplete database is the failure this step exists to catch.
FRAPPE_BENCH_ROOT=/opt/consilium $PY ../deploy/healthcheck.py --site restored.local
```

Restore into a **new** database, never over the live one. If the restore is
wrong you still have the original, and comparing the two is the fastest way to
find out.

**Rehearse this quarterly**, against a real backup, into a real empty database.
The rehearsal is the only thing that tells you the backups work.

---

## Upgrading

```
# 1. Back up, and verify the backup restores. Not optional.
# 2. Stop the worker and the scheduler. Leave the web server for last.
# 3. Install the new bundle over the same target.
# 4. Migrate:
cd /opt/consilium/sites
FRAPPE_BENCH_ROOT=/opt/consilium $PY -m frappe.utils.bench_helper frappe \
    --site consilium.local migrate
# 5. Health check, then restart all three processes.
```

Migrations are not automatically reversible. If one fails part-way, restore from
the backup rather than trying to repair the schema by hand.

---

## Health

```
cd /opt/consilium/sites
FRAPPE_BENCH_ROOT=/opt/consilium $PY ../deploy/healthcheck.py --site consilium.local
```

Fifteen checks, each naming its own remedy. Run it after any install, upgrade,
restore or configuration change. It is quick and it catches the failures that do
not announce themselves — a stale asset copy, a dangling asset link, a cache
that accepts writes but returns nothing.

## What to watch

Nothing here is automated yet. Until it is, watch:

- **All three processes alive.** The scheduler failing is silent and expensive.
- **Queue depth.** A worker that has died leaves jobs accumulating.
- **Database size and connection count.**
- **Disk on the backup destination.**
- **Failed scheduled jobs**, visible in the interface under the scheduled job log.

---

## Known gaps

Stated plainly so nobody assumes otherwise:

- **No service definitions ship yet.** systemd units and Windows service
  wrappers are still to be written; today the processes are started manually or
  under `winbench start`.
- **No log shipping or metrics.** Logs are files on disk.
- **No automated backup schedule.** You must schedule it.
- **Certificates, ports and service accounts are undecided** and must be settled
  before go-live.
