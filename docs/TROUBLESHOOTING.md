# Troubleshooting

Symptom → cause → fix. Most of these were hit for real during the port.

**Start every investigation with:**
```bash
winbench doctor
```
It checks Postgres, both Redis instances, node and wkhtmltopdf, and prints which
compatibility patches are live. Most problems show up here.

---

## Install and setup

### `No bench found at or above <path>`
You are not inside a bench directory. `cd` into it, or set `FRAPPE_BENCH_ROOT`.

### `Cannot import 'flit_core.buildapi'`
Frappe builds with flit and `flit_core` isn't installed. Offline installs need it
in the wheelhouse:
```bash
pip install flit_core          # or: pip download flit_core -d wheelhouse
```

### `pip install frappe` gives you version 0.0.1
That's the PyPI **placeholder**, not the framework — Frappe is not published to
PyPI. Use a GitHub archive (`requirements-github.txt`) or `git clone`.

### The "offline" install still contacts GitHub
Expected if you let pip resolve Frappe's dependencies: `PyPika` and `gunicorn`
are pinned to `git+https://` URLs, and pip honours a direct reference **even
under `--no-index`**. Install dependencies first, then Frappe with `--no-deps` —
`winbench init --find-links` does this. Confirm:
```bash
grep -icE "git\+|github\.com|Cloning" install.log     # must be 0
```

### `pip download --platform win_amd64` fails on `docopt` / `cairocffi`
You omitted `--no-deps`. Without it pip chases transitive dependencies and hits
sdist-only packages under `--only-binary=:all:`. See KNOWLEDGE-BASE §2.3.

### `Could not find a version that satisfies the requirement cairocffi==1.5.1`
Same cause, or you used `--only-binary=:all:` on the seven sdist-only packages.
They are pure Python — download them without the platform flags.

### Site creation: `Postgres super user password:` prompt then `Aborted!`
An empty password isn't accepted. Set one on the Postgres role and pass
`--db-root-password`.

---

## Runtime

### The Desk is a blank white page (but `/api/method/ping` returns 200)
`/assets` isn't being served. On Linux that's nginx's job; here the app must do
it. You are probably running with `--no-statics`, or serving
`frappe.app.application` directly instead of `application_with_statics()`.
```bash
winbench serve --site <site>          # statics on by default
python scripts/smoke_test.py --site <site>   # will show the 404s
```

### `AttributeError: module 'signal' has no attribute 'SIGUSR1'`
The compatibility layer wasn't installed before `import frappe`. Any entry point
must call `winbench.compat.install()` **first**. Use the `winbench` commands
rather than invoking Frappe directly.

### `ModuleNotFoundError: No module named 'resource'`
Same cause — the `resource` stub is registered by `compat.install()`.

### `ValueError: preexec_fn is not supported on Windows`
Same cause. Patch #2.

### `OSError: [Errno 98] Address already in use`
A previous server is still running. On Windows this usually means an orphaned
process tree — `winbench start` puts children in a Job Object specifically to
prevent it, but a hard kill can still leak.
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

### Background jobs never run
1. Is a worker running? `winbench worker --site <site>`
2. Is the queue Redis up? `winbench doctor`
3. Queue names are namespaced by bench path — a worker started from a different
   bench root listens on different queues. Check `FRAPPE_BENCH_ROOT` matches.

### A worker dies and takes its job with it
Expected on Windows: no `fork`, so there's no work-horse isolation
(KNOWLEDGE-BASE §2.5). Run more workers: `winbench start --background-workers 4`.
If one specific job kills workers repeatedly, that job has a real bug — Linux
would have masked it.

### Scheduled jobs run twice
More than one scheduler process. Frappe's scheduler does not elect a leader. Run
exactly one, and start everything else with `--no-scheduler`.

### `winbench serve` can't import frappe
`winbench` and `frappe` must be in the **same** virtualenv — `serve` imports
Frappe in-process. `winbench init` installs winbench into the bench venv; if you
assembled the bench by hand:
```bash
<bench>/env/bin/pip install -e <repo>/winbench
```

---

## Build

### `Couldn't find a package.json file in .../site-packages`
Frappe was installed non-editable. Reinstall editable:
```bash
pip uninstall -y frappe
pip install -e <bench>/apps/frappe --no-deps --no-build-isolation
```

### `Cannot find module 'fast-glob'` (or any node module)
`yarn install` didn't complete. Re-run it in `apps/frappe`. If it fails fetching
`air-datepicker` from GitHub, that's the one npm package not on the registry —
build assets on a connected machine and copy `sites/assets/` over.

### `os.symlink` / "A required privilege is not held by the client"
Windows needs Developer Mode or admin for symlinks. Patch #5 uses directory
junctions and falls back to copying, so this should not surface. If it does, the
compat layer wasn't installed.

---

## Database

### `PostgreSQL support is limited to Frappe v16 and above`
A warning, not an error — it prints on every `new-site`. It is a real signal
though: see KNOWLEDGE-BASE §2.6 and the v15-vs-v16 decision.

### `test_is` fails in `frappe.tests.test_db`
Known and pre-existing: it expects `coalesce("name", ...)` in generated SQL and
Postgres doesn't emit it. Not caused by this port.

### `permission denied to create database`
Site creation needs `CREATE DATABASE`. On RDS use the master user for
`winbench new-site`, then switch the site to a restricted role.

### Tests refuse to run: `Testing is disabled for the site!`
```bash
winbench migrate   # not needed, just be in the bench
cd <bench>/sites && ../env/bin/python -m frappe.utils.bench_helper frappe \
    --site <site> set-config allow_tests true
```

### `ModuleNotFoundError: No module named 'faker'`
A Frappe **test-only** dependency, not in `requirements.txt`. `pip install faker`
if you want to run those suites.

---

## PDF

### `OSError: No wkhtmltopdf executable found`
Install the **patched-qt** Windows build and put it on `PATH`. Frappe v15's
`get_pdf` requires this binary; there is no automatic fallback. (WeasyPrint
exists but only for Print Format *Builder* formats, and needs the GTK3 runtime
on Windows.)

---

## When you are stuck

1. `winbench doctor` — services and active patches
2. `python scripts/smoke_test.py --site <site>` — where the request path breaks
3. `python -m pytest tests/ -q` — is the compat layer itself intact (20 tests)
4. `python scripts/audit_windows_compat.py <path-to-app>` — POSIX-only code in an
   app you are porting

If it is a *new* Windows incompatibility in Frappe, the fix belongs in
`winbench/winbench/compat.py` with a test — **not** in a fork of Frappe.
