# Project context for AI agents

This repository is a port of the **Frappe framework** to run natively on
**Windows** with **PostgreSQL** — no WSL, no Docker, no supervisor, no nginx,
no gunicorn. The project lives at the repository root.

Read [`HANDOVER.md`](HANDOVER.md) for the full picture and
[`docs/KNOWLEDGE-BASE.md`](docs/KNOWLEDGE-BASE.md) before changing anything.

## Goal

Stand up a Frappe-based governance platform (policy, escalation, committee
workflow — a ServiceNow alternative) that installs inside a restricted
enterprise network, on Windows laptops for development and Linux/AWS for
deployment.

## Hard invariants — do not break these

1. **Never fork or edit Frappe's source.** Frappe lives in `<bench>/apps/frappe`
   and must stay pristine so `git pull` keeps working. Windows fixes go in
   `winbench/winbench/compat.py` as runtime patches.
2. **Every compat patch must be a no-op on POSIX.** Start each with
   `if not IS_WINDOWS: return <original>`. This is what lets one codebase serve
   the Windows laptop and the Linux server.
3. **Every patch needs a test** in `tests/test_compat.py` that simulates Windows
   (set `compat.IS_WINDOWS = True` and remove the POSIX API being replaced).
4. **Never claim something works because an API returned 200.** We shipped a
   blank-page bug that way. Use `scripts/smoke_test.py`, which fetches every
   asset the Desk references.
5. **Do not add `PyPika` to `requirements.txt`.** PyPI's PyPika 0.48.9 is a
   different library from Frappe's fork of the same version, and it fails
   silently. See KNOWLEDGE-BASE §2.1.

## Layout

```
winbench/winbench/
  cli.py          the `winbench` command (init, new-site, serve, worker, ...)
  compat.py       the 8 runtime patches -- the heart of the port
  worker.py       fork-free RQ worker (Windows has no os.fork)
  procs.py        process supervisor using Windows Job Objects
  services.py     Postgres/Redis/node health checks
  layout.py       bench directory model
scripts/
  bootstrap.ps1             one-shot Windows setup
  check_availability.py     what the network allows
  smoke_test.py             end-to-end check against a running site
  audit_windows_compat.py   static AST audit for POSIX-only code
tests/test_compat.py        20 tests, run anywhere, need no services
```

## Verify before you claim anything works

```bash
python -m pytest tests/ -q                                   # expect 20 passed
python scripts/smoke_test.py --site <site> --port 8000       # expect 8 passed
python scripts/audit_windows_compat.py <bench>/apps/frappe/frappe --severity BLOCKER
python scripts/check_availability.py --target-windows        # ~25s
```

Expected baselines are tabulated in KNOWLEDGE-BASE §5. If a number differs from
the baseline, investigate before proceeding — do not update the baseline to
match.

## Things that will bite you

- `signal.SIGUSR1`, `os.fork`, `os.nice`, `preexec_fn`, `resource`, and literal
  `/tmp` paths do not exist on Windows. The audit script finds them.
- `pip --no-index` still fetches `git+https://` direct references.
- `pip download --platform` requires `--no-deps` with our flattened requirements.
- Frappe must be installed **editable**, or `winbench build` cannot find
  `package.json`.
- Run exactly one scheduler process, or every scheduled job fires twice.

## Style

Match the existing code: tabs for indentation in Python (Frappe's convention,
which `winbench` follows), docstrings that explain *why* a workaround exists and
what the trade-off is, not just what the code does. Comments in this codebase
carry the institutional memory — keep that standard.
