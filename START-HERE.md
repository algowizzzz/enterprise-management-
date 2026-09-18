# Start here

You are picking up a build that is already substantially done. Read this whole
file before touching anything — most of what looks like a missing piece is a
decision that was already made, and re-deciding it costs more than reading.

## What this is

**Consilium** — an enterprise Governance, Risk & Policy platform. Three business
modules over a shared core, built on the Frappe Framework v15 with PostgreSQL,
designed to install on a server with **no internet access**.

It is real and it works: 136 entities across 371 tables, 724 automated tests
passing against a real database, five screens exercised in a browser, and an
offline installation proven by installing it into a clean target with every
proxy variable pointed at a dead port.

## Two sources of truth, and they are different

**The repository** holds the product: code, tests, and the sanitized product
documentation. It is **public**, and nothing identifying the client may ever be
committed to it. An automated check (`scripts/check_platform_rules.py`) fails the
build if anything slips through. That check is not advisory.

**`docs/context/`** holds *why*: the decisions, the stakeholder's answers, the
open questions, and reproductions of the six source documents the requirements
came from. It has been sanitized — the client, its people and the commercial
products it uses are described by role rather than named, so it is safe in a
public repository. What that costs you: a source document reproduction is no
longer traceable to its original by name, and "the sponsor confirmed X" does not
tell you who. Ask if that matters for a particular decision.

## Read in this order

1. `docs/context/README-FIRST.md` — the settled positions, one page.
2. `docs/context/DECISIONS.md` — the binding directives, D-1 to D-12. **These
   override the source documents wherever they disagree.**
3. `docs/context/ANSWERS-ROUND-1.md` — two further rounds of answers. These override
   too, and they moved scope: retention came in-house, integrations went out,
   the deck's Optional items came in.
4. `HANDOVER.md` in the repository.
5. `docs/product/05-glossary.md`, then `02-data-model.md`.
6. `docs/delivery/SESSION-SUMMARY.md` — what is done, what is not, what still
   needs a person.
7. `docs/product/07-assumptions-and-gaps.md` — **this exists to be argued with.**
   It names the most consequential inference in the model. If a reviewer is
   going to push back anywhere, it is there.

The commit messages carry reasoning, not just description. `git log` is worth
reading when something looks odd — the answer to "why is it like that" is
usually in the commit that made it so.

## Rules that are enforced, not merely encouraged

These are not style preferences. Each one has already cost real debugging time.

- **Nothing branches on a workflow state name.** Logic reads semantic flags a
  configuration table sets. A checker enforces this across 82 state names and
  fails the build. It is what makes a state rename configuration rather than a
  code change. When you add a state, add its row to
  `consilium_core/setup/state_flag_seed.py` — otherwise saving that record
  throws, deliberately.
- **Entities are generated from specs**, never hand-written. Write
  `specs/<module>/<name>.json`, run `scripts/make_doctype.py`. The generator
  refuses the mistakes that migrate cleanly and fail weeks later.
- **No CDN, no package manager in the build, no compiler-requiring dependency.**
  The target has no internet. A CDN link works on your machine and fails only
  there, which is the worst place to find out.
- **Nothing identifying the client**, anywhere, including commit messages.
- **Use the Core engines.** Versioning and revert, attestation, retention, the
  classification rules engine, notifications, imports, SLA timing — all exist
  once in `consilium_core/`. Do not write a second one.

## Running it locally

```bash
./scripts/dev_setup.sh
cd .bench && ../.venv/bin/winbench serve --port 8000
```

`http://localhost:8000`, Administrator / `admin`.

**This script has never been run on macOS.** Its syntax is checked and its Linux
path is exercised; that is all. Verify rather than trust — the likely trip
points are a Homebrew path or a `psql` default. Fixing it and committing the fix
is a genuinely useful first contribution.

Your local database starts with seeded reference data and no forums. The demo
data in the screenshots was created in the cloud environment and is not in the
repository.

## What is not done

1. **No migration rehearsal on a target server.** Frappe describes its own
   PostgreSQL support as second-class in v15. Four divergences between the two
   database backends were found and fixed during this build, and there is no
   basis for assuming that list is complete. **This is the largest unknown and it
   can only be closed on the target.**
2. No upgrade rehearsal from a previous release.
3. No load numbers. Paging and search happen in the database rather than the
   browser, so the design is sound, but nothing is measured.
4. Contrast ratios are eyeballed, not audited.
5. Certificates, ports and service accounts undecided; no systemd or Windows
   service definitions.
6. Single sign-on not enabled. LDAP and OIDC are configuration — **SAML is not
   implemented in the framework at all**, verified in source. If SAML is
   mandated it is a separate build.

## The known defect worth fixing first

The forum inventory renders 27 columns, making the table about 4400px wide and
squeezing forum names onto four lines. It was flagged by the engineer who built
it, who could not fix it without adding a column chooser to the shared table
component and had been told not to modify shared components unilaterally.

You can. A sensible default column set plus a chooser, in
`consilium/public/js/consilium-table.js` and the inventory screen. Keep the
component's declarative configuration style.

## How to behave here

Verify by running, not by reasoning. Every claim in the repository's
documentation was executed before it was written, and where something could not
be verified it says so. Hold that line — a health check that passes on an
installation nobody opened is worth nothing, and this project has already been
bitten once by a site that returned HTTP 200 for every request while serving a
blank page.

When you find something wrong with a decision recorded in `DECISIONS.md`, say so
plainly rather than working around it. Several of those decisions were made on
incomplete information and the person who made them would rather hear it.
