# Knowledge base

Why things are the way they are. Read §2 (Landmines) before you change anything —
each item there cost real debugging time and three of them **fail silently**.

---

## 1. Glossary — Frappe's vocabulary

Frappe names things unusually. You need these five to read anything else:

| Term | Meaning |
|---|---|
| **bench** | A *directory*, not a program: `apps/`, `sites/`, `env/`. Confusingly, upstream's CLI is also called `bench`. When we say "a bench" we mean the directory. |
| **site** | One tenant: one database + one folder under `sites/`. A bench can host several. Sites are addressed by hostname, which is why you need a `hosts` entry. |
| **app** | A Python package under `apps/` that adds DocTypes and logic. `frappe` is itself an app. Consilium is such an app. |
| **DocType** | A model definition — table, form, permissions and validation in one. Created through the UI; Frappe generates the table. This is the core idea of the framework. |
| **Desk** | The admin SPA at `/app`. What users log into. |

Others you'll meet: **docstatus** (0 draft / 1 submitted / 2 cancelled),
**workspace** (a Desk landing page), **fixture** (exported records kept in git),
**patch** (a data migration, unrelated to our compat patches).

---

## 2. Landmines

### 2.1 🔴 PyPI's PyPika is not Frappe's PyPika — and it fails silently

Frappe pins `PyPika @ git+https://github.com/frappe/pypika@2c50e61...`. PyPI also
has a `PyPika 0.48.9`. **They are different libraries with the same version
number.** The fork rewrites ~850 lines across `terms.py`, `queries.py`,
`dialects.py` and `functions.py` — exactly the modules Frappe imports most (10
imports of `pypika.terms` alone).

Install the wrong one and nothing errors. Basic queries return correct results.
You would find out much later, from wrong data.

**Therefore:** `requirements.txt` deliberately **omits PyPika**, so a mirror
cannot hand you the wrong one. It lives in `requirements-github.txt`. To put the
fork in a wheelhouse:

```bash
pip wheel --no-deps -w wheelhouse \
  "PyPika @ git+https://github.com/frappe/pypika@2c50e6142b2d61d2d243e466fdd5dc03b3d918f2"
rm -f wheelhouse/PyPika-*.tar.gz     # pip also pulls the upstream sdist
```

Verify what you actually got:
```python
# fork has ~850 lines changed in terms.py vs upstream
import pypika, hashlib, inspect, pathlib
p = pathlib.Path(inspect.getfile(pypika)).parent / "terms.py"
print(hashlib.sha256(p.read_bytes()).hexdigest()[:16])   # fork: a9764727b433119d
```

### 2.2 🔴 `pip --no-index` still phones GitHub

A direct reference (`pkg @ git+https://...`) is honoured by pip **even under
`--no-index`**. So the obvious "offline" install silently clones from GitHub.

**Therefore:** install the dependency set from the wheelhouse *first*, then
Frappe with `--no-deps`, so pip never sees the direct references.
`winbench init --find-links` does this. Verify with:
```bash
grep -icE "git\+|github\.com|Cloning" install.log     # must be 0
```

### 2.3 🔴 `pip download --platform` needs `--no-deps`

`requirements.txt` is a complete flattened set from a freeze. Without
`--no-deps`, pip chases transitive dependencies, and under
`--only-binary=:all:` it fails on a sdist-only package (`docopt`) pulled in by
another package (`num2words`) — *even if you exclude `docopt` from the file*.

Our first checker ran 16 minutes and then wrongly reported the network as
blocking. With `--no-deps` it passes in 21 seconds.

### 2.4 🟠 No nginx means *something* must serve `/assets`

We removed nginx. Nothing replaced it at first, so `/app` returned 200 HTML and
then every JS/CSS bundle 404'd — **a blank white page while every API check
passed**. `winbench serve` now uses Frappe's own `application_with_statics()`.

`scripts/smoke_test.py` guards this by fetching every asset the page references.
Never treat "the API returns 200" as evidence the UI works.

### 2.5 🟠 Windows background workers have no crash isolation

`rq.Worker` forks a work-horse per job so a hung or crashing job can be killed
without taking the worker down. Windows has no `fork`. We use
`rq.SimpleWorker` + `rq.timeouts.TimerDeathPenalty` (a thread timer instead of
`SIGALRM`).

**The trade-off is real:** a job that segfaults the interpreter, or blocks in a C
call where the timer's exception cannot be delivered, takes its worker down.
Mitigation: run several supervised workers (`winbench start --background-workers 4`).
**Linux and AWS are unaffected** — they keep the fork-based worker.

### 2.6 🟠 PostgreSQL support in v15 is second-class

Frappe prints this on every `new-site`:

> *Note: PostgreSQL support is limited to Frappe v16 and above. Fixes for earlier
> versions will not be added.*

The one genuine failure in Frappe's own `test_db` suite is exactly this: `test_is`
expects `coalesce("name", ...)` in generated SQL and Postgres doesn't emit it.
Harmless alone, but it signals that Postgres paths in v15 get no upstream fixes.

**Recommendation: rebase onto v16 (`develop`) before building modules.** Nothing
in this port is version-specific.

### 2.7 🟠 Run exactly one scheduler

Frappe's scheduler does not elect a leader. Two scheduler processes means every
scheduled job fires twice — every escalation, every SLA notification. On AWS run
it as a single-replica task and start everything else with `--no-scheduler`.

### 2.8 🟠 `sites/assets/<app>` is a symlink — never hand-copy it between machines

The built bytes live in `apps/<app>/<app>/public/dist/`. `sites/assets/<app>` is
only a link to it. So copying `sites/assets/` to another machine — or tarring it
without dereferencing — produces a bundle that points at a path which does not
exist on the target. It looks like it worked and serves nothing.

`winbench assets --export` tars with `dereference=True` and carries the real
`dist/` directories; `--import` unpacks them and recreates the links locally.
Use `--copy` on Windows so assets are copied rather than linked, which needs no
Developer Mode.

This is also the **yarn escape hatch**: node and yarn are needed only to compile
assets, never at runtime. Verified end to end with `node_modules` absent and node
removed from `PATH` — full Desk, 8/8 smoke checks.

### 2.9 🟡 A non-editable install breaks `winbench build`

`pip install ./frappe` copies the package into `site-packages`, which has no
`package.json`, so esbuild can't find its config. Always install **editable**
(`pip install -e apps/frappe`). `winbench init` does this.

### 2.10 🟡 A `.git`-less install loses branch/commit display

`frappe.utils.change_log` shells out to `git` for the About dialog. Install from
a zip and branch/commit show as empty strings. The version number is still
correct and nothing raises. Cosmetic only.

---

## 3. The 8 compatibility patches

In `winbench/winbench/compat.py`, applied by `install()` **before
`import frappe`**. Each is a no-op on POSIX. `winbench doctor` lists what is live.

| # | Patch | Problem it solves |
|---|---|---|
| 1 | `frappe._register_fault_handler` | **The critical one.** `signal.SIGUSR1` doesn't exist on Windows, and this is reached from `frappe.init()` — so it fires on every request, job and CLI command. Registers on `SIGBREAK` instead. |
| 2 | `frappe.commands.popen` | `preexec_fn` is rejected outright by `Popen` on Windows. Sets child priority from the parent instead. |
| 3 | `frappe.utils.execute_in_shell` | Hard-codes `/bin/bash` and `os.nice`. Uses the platform shell and a priority class. |
| 4 | `frappe.utils.background_jobs.set_niceness` | `os.nice` is POSIX-only → `BELOW_NORMAL_PRIORITY_CLASS`. |
| 5 | `frappe.build.symlink` | `os.symlink` needs Developer Mode or admin. Uses **directory junctions**, falls back to copying. |
| 6 | `frappe.utils.pdf` | Writes to a literal `/tmp` → `tempfile.gettempdir()`. |
| 7 | `frappe.utils.get_bench_id` | `C:\frappe` leaks `\` and `:` into Redis keys and RQ queue names. |
| 8 | `frappe.installer.extract_files` | `tar --strip 2`; Windows' `tar.exe` (bsdtar) rejects `--strip`. Uses stdlib `tarfile`, with a path-traversal check. |

Plus one **substitution**, not a patch: `resource` is POSIX-only and Frappe
imports it at module scope, so a psutil-backed stub is registered in
`sys.modules` (it returns a real peak-RSS, not zero).

### Adding a patch

1. Write `_patch_<name>()` in `compat.py`. It **must** start with
   `if not IS_WINDOWS: return <original>`.
2. Add it to the `PATCHES` tuple.
3. Add a test in `tests/test_compat.py` that simulates Windows by setting
   `compat.IS_WINDOWS = True` and removing the POSIX API being replaced.
4. `python -m pytest tests/ -q`

**Do not fork Frappe.** A fork means owning security patches forever.

---

## 4. Architecture decisions, and why

| Decision | Reason | Alternative rejected |
|---|---|---|
| Replace `bench`, not fork Frappe | `bench` is orchestration; the framework barely cares about the OS. Only 10 blockers in all of `frappe/` | Forking Frappe — unmaintainable |
| Runtime patches over source patches | Survives `git pull`; each is self-contained and testable | A patch series — brittle, needs reapplying |
| waitress over gunicorn | Pure Python, Windows-native, and Frappe is a plain WSGI app. Gunicorn's pre-fork model is a *scaling* choice | Uvicorn (ASGI, wrong shape), IIS+FastCGI (heavy) |
| `SimpleWorker` over a custom pool | RQ already ships the fork-free pieces | Celery — a second queue system to run |
| Job Objects for process cleanup | Only reliable way to kill a tree on Windows; orphaned workers hold DB connections and break the next start | `taskkill /T` — races |
| PostgreSQL | Already first-class in Frappe; it's a config switch, not a port | Keeping MariaDB — against our standard |
| Serve statics in-process | No nginx to configure; `--no-statics` available when a real proxy exists | Requiring nginx on Windows |

---

## 5. Verification commands

Run these after any change. All were passing at handover.

```bash
# 1. compat layer unit tests -- 20 tests, runs anywhere, no services needed
python -m pytest tests/ -q

# 2. static audit of frappe -- expect 10 blockers, 6 of them in test code
python scripts/audit_windows_compat.py <bench>/apps/frappe/frappe --severity BLOCKER

# 3. dependency availability -- ~25s
python scripts/check_availability.py --target-windows

# 4. end-to-end against a running site -- 8 checks
python scripts/smoke_test.py --site <site> --port 8000

# 5. frappe's own tests against postgres (a sample)
cd <bench>/sites && ../env/bin/python -m frappe.utils.bench_helper frappe \
    --site <site> run-tests --module frappe.tests.test_document
```

Expected results at handover:

| Check | Result |
|---|---|
| `pytest tests/` | 51 passed |
| audit | 18 findings: 10 blocker, 4 warning, 4 note |
| availability (`--target-windows`) | 139 wheels + 6 pure-Python sdists (145 packages; dev-only tools are in `requirements-dev.txt`) |
| smoke test | 8 passed, 0 failed |
| `frappe.tests.test_document` | 36 run, OK |
| `frappe.tests.test_permissions` | 34 run, OK |
| `workflow.doctype.workflow.test_workflow` | 12 run, OK |
| `frappe.tests.test_db` | 54 run, 1 failure (pre-existing Postgres quirk, §2.6) |
