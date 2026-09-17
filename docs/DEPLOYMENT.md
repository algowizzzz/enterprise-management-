# Deployment & dependency review

A generic deployment guide for three targets: a **managed corporate Windows
workstation** (development, and small single-machine deployments), an
**air-gapped Linux server** (staging/production), and **managed cloud
infrastructure** (optional). Plus everything a security review will ask for.

---

## 1. Does the same application run on Linux?

**Yes — and that is not a claim, it's how it was built.** Every result in
`REPORT.md` was produced *on Linux*. Same `winbench` commands, same code path.

There is no Windows build and no Linux build. `winbench` is one cross-platform
package:

- All 8 compatibility patches are **no-ops on POSIX** — each one starts with
  `if not IS_WINDOWS: return <the original function>`. On Linux you are running
  stock Frappe.
- Worker: Linux gets `rq.Worker` (fork-per-job, upstream semantics). Windows
  gets `SimpleWorker`. Same command, chosen at runtime.
- Supervisor: Windows uses Job Objects + `CTRL_BREAK_EVENT`; Linux uses process
  groups + `SIGTERM`.

`winbench doctor` prints which patches are live. On Linux it prints
`(none needed on this platform)`.

**So: develop on the Windows workstation, deploy the identical tree to Linux.**
That was the design goal, and it is the part that most de-risks an enterprise
rollout — you are not maintaining a Windows fork.

One caveat worth stating: the reverse is also true of the *limitations*. The
worker downgrade is Windows-only. On a Linux server, and in the cloud, you get
the full fork-based worker with hard job timeouts.

---

## 2. Viewing the UI

The instance a developer runs binds to `127.0.0.1`; there is no shared demo
environment. To bring one up yourself, that is what `scripts/bootstrap.ps1`
(Windows) and `winbench init` (Linux) are for. Open
<http://127.0.0.1:8000> and log in as `Administrator`.

> **Look at the UI with your own eyes, not just the API.** An early bug had
> `winbench serve` handing waitress the bare WSGI app, so the Desk loaded its
> HTML and then 404'd on every JS/CSS bundle — a blank white page. On a normal
> bench, nginx serves `/assets`; with nginx removed, nothing did. Fixed by using
> Frappe's own `application_with_statics()`. This is exactly the class of bug an
> API smoke test misses and a browser catches, which is why
> `scripts/smoke_test.py` now fetches every referenced asset.

---

## 3. The dependency list

**Take `requirements.txt` to the target network and run:**

```bash
# does this network have everything?          (nothing is installed)
python scripts/check_availability.py --target-windows      # ~25 seconds

# or just the pip half, by hand -- note --no-deps:
pip download --no-deps -r requirements.txt -d wheelhouse \
    --platform win_amd64 --python-version 3.11 --only-binary=:all:
pip download --no-deps -d wheelhouse \
    cairocffi==1.5.1 docopt==0.6.2 maxminddb-geolite2==2018.703 \
    PyQRCode==1.2.1 rauth==0.7.3 traceback-with-variables==2.0.4 zxcvbn==4.4.28
```

`--no-deps` is required, not an optimisation: `requirements.txt` is already a
complete flattened set, and without it pip chases transitive dependencies — so
`--only-binary=:all:` fails on `docopt` (pulled in by `num2words`) even when
`docopt` is excluded from the file.

**Verified:** all 150 resolve for `win_amd64` / cp311 — 143 wheels plus the 7
pure-Python sdists.

`check_availability.py` uses whatever index pip is configured with, so an
internal package mirror is exercised exactly as a real install would be. It then
checks the GitHub artifacts and the external programs, and prints a specific
blocked-item list. Exit 1 if anything required is missing.

| File | Contents |
|---|---|
| `requirements.txt` | **150 packages**, pinned, all resolvable from PyPI — the file to test |
| `requirements-github.txt` | The 3 artifacts that cannot come from PyPI, with direct archive URLs |
| `requirements/frappe-full.txt` | The raw freeze, including the entries above annotated in place |
| `requirements/winbench.txt` | The 6 winbench adds (`waitress`, `psycopg2-binary`, `rq`, `redis`, `click`, `psutil`) |
| `requirements/excluded.txt` | What we deliberately do **not** install, and why |

Note `requirements.txt` deliberately **omits PyPika**: PyPI's PyPika 0.48.9 is a
different library from frappe's fork of the same version number, so listing it
would let a well-meaning mirror hand you the wrong one. It lives in
`requirements-github.txt` instead.

### Windows installability — all 151 checked against PyPI

| Result | Count |
|---|---|
| Pure-Python wheel (`py3-none-any`) | 126 |
| Has a `win_amd64` wheel | 17 |
| Source-only (`sdist`) | 7 |

All 7 sdists were inspected for C extensions (`ext_modules`, `cffi_modules`,
`.c` files). **All 7 are pure Python** — pip builds a wheel locally with no
compiler:

```
cairocffi, docopt, maxminddb-geolite2, PyQRCode, rauth,
traceback-with-variables, zxcvbn
```

(`rauth` publishes only a `py2-none-any` wheel, which pip correctly rejects for
Python 3.11, so it resolves as a source distribution.)

**No package in the stack requires a C compiler on Windows.** `cairocffi` uses
cffi in ABI mode — it installs cleanly, but needs the cairo/GTK3 DLLs *at
runtime*, and only if you use WeasyPrint for PDFs. Skip WeasyPrint and it never
loads them.

---

## 4. ⚠️ The finding that matters most

**You cannot get Frappe from PyPI:**

```
pypi.org/project/frappe  ->  version 0.0.1, "Frappe placeholder package"
```

The real framework is **not published to PyPI**. It is distributed only as a Git
repository. So if an internal mirror proxies PyPI, `pip install frappe` gets you
a stub, not the framework.

There are exactly **three** things that must come from GitHub:

| What | Source | Needed? |
|---|---|---|
| `frappe` framework itself | `github.com/frappe/frappe` | **Yes** — no alternative |
| `PyPika` (frappe's fork) | `git+https://github.com/frappe/pypika@2c50e61` | **Yes** — 27 imports; the PyPI PyPika (0.51.1) is upstream, not the fork |
| `gunicorn` (frappe's fork) | `git+https://github.com/frappe/gunicorn@bb55405` | **No — dropped** |
| `air-datepicker` (npm) | `codeload.github.com/frappe/air-datepicker` | Yes, for Frappe's asset build only |

All of these can be fetched as **archive downloads** rather than git clones — see
below.

**One of them is already gone.** `grep -rn "import gunicorn" frappe/` returns
nothing — it is a deploy-only dependency, replaced here with waitress. That cuts
the GitHub surface from 3 to 2 (plus 1 npm, needed only if you rebuild assets).

### Yes — you can download it from a GitHub URL. Verified.

`git clone` is not required. Frappe builds with **flit**, which reads its version
from `frappe/__init__.py` rather than from git metadata, so a plain source
archive installs and runs normally:

```
https://github.com/frappe/frappe/archive/refs/heads/version-15.zip     <- "Download ZIP"
https://github.com/frappe/frappe/archive/refs/tags/v15.x.x.tar.gz      <- a pinned release
```

In many locked-down enterprises a browser download through the corporate proxy is
allowed where the git CLI is not, which usually makes this the practical path.
`winbench` supports it directly:

```powershell
winbench init C:\frappe --from-archive C:\Downloads\frappe-version-15.zip
```

It strips GitHub's wrapper directory, validates the tree really is frappe, and
installs it **editable** (a copied install puts the package in `site-packages`
without `package.json`, and `winbench build` then can't find the esbuild config).

**Verified end to end:** a bench built from a 40 MB zip with **no `.git` anywhere**
created a Postgres site, built assets, served the Desk, and passed all 8 smoke
checks.

**The only thing you lose** is cosmetic: `frappe.utils.change_log` shells out to
`git` for the About dialog, so branch and commit show as empty strings. The
version number is still correct (15.121.0) and nothing raises.

### Fully offline install — verified, and with one trap

```bash
# --- on a connected machine, once ---
pip download -r requirements/frappe-full.txt -d wheelhouse

# frappe's PyPika FORK must be built into the wheelhouse explicitly:
pip wheel --no-deps -w wheelhouse \
  'PyPika @ git+https://github.com/frappe/pypika@2c50e6142b2d61d2d243e466fdd5dc03b3d918f2'
rm -f wheelhouse/PyPika-*.tar.gz     # delete the upstream sdist pip also pulls

# --- transfer wheelhouse/ + the zip, then on the restricted machine ---
winbench init C:\frappe --from-archive frappe-version-15.zip --find-links wheelhouse
```

Verified: `init` completes with **zero** GitHub contacts, the fork lands, and the
resulting bench serves the Desk and passes all 8 smoke checks. This is the path
for an air-gapped server: the transfer bundle is `wheelhouse/`, the Frappe
archive, and this repository.

#### ⚠️ The trap: PyPika

`pip install frappe` resolves `PyPika @ git+https://github.com/frappe/pypika@...`
— a **direct reference**, which pip honours *even under `--no-index`*. So a naive
wheelhouse install silently phones GitHub and the "offline" install isn't.

Worse, if you let it resolve from PyPI instead, you get a **different library
with the same version number**. Both call themselves `0.48.9`, but frappe's fork
rewrites roughly **850 lines** across `terms.py`, `queries.py`, `dialects.py` and
`functions.py` — precisely the modules frappe imports most (10 imports of
`pypika.terms` alone). It does not fail loudly: basic queries still run. You just
get a quietly different query builder.

`winbench init --find-links` handles this: it installs the dependency set from
the wheelhouse first, then frappe with `--no-deps`, so pip never sees the direct
references. `requirements/frappe-full.txt` carries the warning inline.

For npm: Frappe's own build pulls 415 packages, **exactly one**
(`air-datepicker`) from GitHub. It is needed only for `winbench build`. Build
assets once on a connected box and ship `sites/assets/` — or just use the bundle
committed in `assets/`. The runtime never needs npm or node, and the Consilium
app has no front-end build step at all.

---

## 5. Non-pip components

| Component | Managed Windows workstation | Linux server / cloud | Required? |
|---|---|---|---|
| Python 3.11 | winget / MSI | distro or pyenv | **Yes** |
| PostgreSQL 16 | EDB installer | distro package, or a managed service | **Yes** |
| Redis | **Memurai** (no official Windows Redis) | redis-server, or a managed service | **Yes** |
| Node 22 + yarn | winget | distro | Build only — not at runtime |
| wkhtmltopdf | official Windows build | distro | Only for PDF print formats |
| GTK3 runtime | separate installer | usually present | Only for WeasyPrint PDFs |

Note Redis: Frappe wants two logical instances (cache 13000, queue 11000). One
works, but flushing the cache would also drop queued jobs.

---

## 6. The three targets

### Managed corporate Windows workstation — development
The intended development path. `bootstrap.ps1` does it in one command.

**Watch for:** corporate AV scanning `node_modules` makes asset builds slow (use
the committed bundle and skip them); keep the bench off any file-sync client
such as OneDrive (file-locking sync corrupts builds); a Redis-compatible service
such as Memurai may need a software request; the fork-free worker is a real
downgrade (see `REPORT.md`). Everything installs per-user — no admin rights
needed except for the PostgreSQL and Redis-compatible services.

### Air-gapped Linux server — staging/production
Stock Frappe territory; the compat layer is inert. Install from the offline
transfer bundle described in §4. You have a genuine choice of launcher:

- **Use `winbench`** for one toolchain across both environments, no supervisor,
  no nginx config generation. Simple, and the recommended option for a first
  rollout.
- **Use upstream `bench`** for the battle-tested production topology
  (supervisor + nginx + gunicorn). The sites directory `winbench` creates is
  byte-compatible with `bench` — it's the same layout — so you can switch later
  without migrating anything.

Put a reverse proxy in front for TLS if the server is reachable by more than
localhost.

### Managed cloud infrastructure — optional
Nothing here is cloud-hostile. Using AWS names as an example:

- **Managed PostgreSQL (e.g. RDS)** — it's a plain TCP connection; set `db_host`
  in `common_site_config.json`. Frappe needs the `CREATE DATABASE` privilege at
  site-creation time, so use the master user for `winbench new-site`, then a
  restricted role afterwards.
- **Managed Redis (e.g. ElastiCache)** — set `redis_cache` / `redis_queue` URLs.
  If you enable TLS or auth, use `rediss://` and pass credentials in the URL.
- **A load balancer or CDN in front** — run `winbench serve --proxy
  --no-statics`. `--proxy` trusts `X-Forwarded-*` so Frappe builds correct URLs;
  `--no-statics` hands `/assets` to the CDN or object store instead of the app
  process.
- **Containers or VMs** — containerise or run under systemd. `winbench start`
  works under both; prefer one process type per task and let the scheduler run
  as its own task so you don't get duplicate scheduled jobs across replicas.

**Run exactly one scheduler process** across the whole deployment. Frappe's
scheduler does not elect a leader; two schedulers means every scheduled job
fires twice.

---

## 7. Summary for a security review

- 151 Python packages, all pinned, all from PyPI, none needing a compiler.
- 4 artifacts must come from GitHub: `frappe`, the PyPika fork, and (npm)
  `air-datepicker`; the `gunicorn` fork has been dropped. All are archive
  downloads, and the offline path needs none of them at install time.
- Offline install from a wheelhouse is verified working, with zero network
  contacts.
- All front-end assets used by the application are vendored in-repo and
  checksummed; nothing is fetched from a CDN at build or run time.
- Runtime services: PostgreSQL and Redis. Nothing else listens on a port.
- No `sudo`, no system-wide install, no kernel modules, no WSL, no Docker.
