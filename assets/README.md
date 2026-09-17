# Prebuilt assets

`frappe-assets-v15.121.0.tar.gz` — compiled JS/CSS for **Frappe v15.121.0**.

## Why this is committed

Compiling assets needs node and yarn, which pull ~517 packages from the npm
registry. On a locked-down network that is usually the first thing to fail. It
is also the *only* step that needs node — **the runtime never does**.

So the build output is committed here. Drop it in and skip the build entirely:

```powershell
winbench assets --import assets/frappe-assets-v15.121.0.tar.gz --copy
```

`--copy` copies rather than symlinks, so Windows needs no Developer Mode or
admin rights.

Verified on a bench with `node_modules` absent and node removed from `PATH`
entirely: full Desk, 8/8 smoke checks.

## Version must match

The bundle targets **v15.121.0** — the tag pinned in `requirements-github.txt`.
Check before importing:

```powershell
python -c "import frappe; print(frappe.__version__)"
```

If it differs, regenerate on any machine with working node rather than importing
this one:

```bash
winbench build --production
winbench assets --export assets/frappe-assets-<version>.tar.gz
```

## What is in it

- `apps/frappe/dist/` — the compiled bundles (the real bytes)
- `sites/assets.json`, `assets-rtl.json`, `css/`, `js/`, `locale/` — manifests
  and shared trees

Source maps are **excluded**: they were ~75% of the bytes and are only ever
fetched by browser devtools. Pass `--with-sourcemaps` to `--export` if you want
them for front-end debugging.

Note `sites/assets/<app>` in a live bench is a *symlink* into
`apps/<app>/<app>/public`. That is why you must use `--import` rather than
copying a `sites/assets/` folder between machines — a plain copy arrives
dangling, and serves a blank Desk while returning HTTP 200.
