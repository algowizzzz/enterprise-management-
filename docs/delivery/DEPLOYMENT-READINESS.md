# Deployment readiness

The deploying team installs and operates this system. They do not build it, and
they should not have to work anything out. So "ready" means: every step is
written down, every step has been run, and every failure a step can produce has
a stated remedy.

This document is the checklist. It is honest about what is not done yet.

Status: **✅ done and verified** · **◑ partial** · **○ not started**

---

## 1. Getting the software there

| | Item | Notes |
|---|---|---|
| ✅ | A single artifact carries everything | One archive: every Python dependency as a built wheel, the framework, the application, prebuilt front-end assets, the installation tooling. 153 wheels, ~265 MB. |
| ✅ | No network access needed at install time | Proven by installing with every proxy variable pointed at a dead port. |
| ✅ | No compiler needed | Dependencies that publish no wheel for their pinned version are built into wheels when the bundle is made, on a machine that has a network. |
| ✅ | No package manager needed | No npm, no yarn, at build or run time. Front-end assets ship prebuilt; front-end libraries are vendored. |
| ✅ | The bundle verifies itself | A checksum for every file, checked before installation begins. |
| ✅ | The bundle is proven before it ships | The builder resolves the requirement set with `--no-index` and refuses to write a bundle that cannot install offline. |
| ✅ | The correct dependency fork is included | The framework needs its own fork of one library that reports the same version as an unrelated package of the same name. The wrong one installs cleanly and fails silently much later. Verified by content, not by version string. |

## 2. Installing

| | Item | Notes |
|---|---|---|
| ✅ | Scripted install for Linux | `deploy/install.sh` |
| ✅ | Scripted install for Windows | `deploy/install.ps1` |
| ✅ | Prerequisites checked before anything is changed | Python version, database reachable, cache reachable. Each failure says what to do. |
| ✅ | Both database provisioning models supported | Self-installed with a superuser login, or a database and role provisioned by a database team with no superuser available. |
| ✅ | First-run setup completed automatically | Otherwise the first person to open the system is trapped in a setup wizard asking for details this product does not use. |
| ✅ | Reference data loaded | A generic starting taxonomy, so the system is usable rather than empty. Idempotent. |
| ✅ | Windows-specific hazards checked | Install target inside a syncing folder, non-ASCII characters in the path. |
| ◑ | Upgrade path | Migrations run, but an upgrade from a previous release has not been rehearsed. Needs doing before the second release, not the first. |

## 3. Knowing it works

| | Item | Notes |
|---|---|---|
| ✅ | One command reports health | `deploy/healthcheck.py`, 15 checks, each with a remedy. |
| ✅ | Checks look for evidence, not absence of error | The cache is written to and read back. Asset links are followed. Vendored files are re-hashed. |
| ✅ | The blank-interface failure is caught | A dangling asset link serves an empty interface while returning HTTP 200 for everything. Explicitly detected. |
| ✅ | Stale served assets are caught | A copied asset directory goes stale silently. The check compares served bytes against source bytes. |
| ✅ | Continuous integration | Platform rules, toolchain tests on Linux and Windows, application tests against a real database, then the health check. |
| ○ | Load rehearsal at realistic volume | Response times under a representative inventory are unmeasured. |
| ○ | Migration rehearsal on the target | The framework's support for this database is second-class in this major version, and three divergences are already known. A rehearsal on the target is the only thing that settles whether there are more. |

## 4. Running it

| | Item | Notes |
|---|---|---|
| ◑ | Long-running service configuration | Documented, not scripted. A service wrapper for each platform is still to do. |
| ◑ | Backup and restore | The framework's own commands work; a restore into an empty database has not been rehearsed end to end. **Taking a backup is not evidence; restoring one is.** |
| ○ | Log and metric guidance | No stated list of what to watch. |
| ○ | Certificate, port and service-account guidance | Deferred by direction. Must be closed before go-live. |

## 5. Understanding it

| | Item | Notes |
|---|---|---|
| ✅ | What the product is and does | `README.md`, `docs/product/` |
| ✅ | The data model and physical schema | `docs/product/02` and `03` |
| ✅ | Architecture and boundaries | `docs/product/04` |
| ✅ | What is assumed or unresolved | `docs/product/07` |
| ✅ | Delivery plan | `docs/delivery/EPICS.md` |
| ✅ | Repository rules, enforced automatically | `CLAUDE.md`, `scripts/check_platform_rules.py` |

---

## What would stop a deployment today

1. **No migration rehearsal on the target database.** Three divergences between
   the two database backends are already known, and the framework itself
   describes its support for this one as second-class in this major version.
   There is no basis for assuming the known list is complete. This is the single
   largest unknown and it can only be closed on the target.

2. **Restore has not been rehearsed.** Backups are taken. Whether they restore
   is a different question and an untested backup is not a backup.

3. **Certificates, ports and service accounts are undecided.** Deferred by
   direction, and correctly so at this stage — but nothing can go live until
   they are settled.

4. **No load rehearsal.** The interface pages and searches from the database
   rather than fetching everything, so the design is sound, but no numbers
   exist.

None of these block building. All of them block going live.
