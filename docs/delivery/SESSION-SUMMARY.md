# Where this got to

Written at the end of the build, release **1.0.0** (2026-09-18), for whoever
picks it up next. The index of every delivery document is
[`README.md`](README.md).

## What exists

**A finished product.** Four modules run on one platform: **142 entities over
378 PostgreSQL tables** and 11 scheduled jobs. Every figure below was measured
on the final build, not asserted.

| Measure | Result |
|---|---|
| Application tests, clean site | **1372 tests, OK**: 0 failures, 0 errors, 1248 s |
| Toolchain tests, `pytest tests/` | 51 passed (22 of them simulate Windows) |
| Interface sweep, final demo site | 274 passed, 0 failed |
| Browser journeys | 8/8 |
| Platform rules | 6/6 |
| Deployment kit, air-gapped Rocky Linux 9 | `verify.sh` 14/14, fresh and after upgrade |

| | |
|---|---|
| Consilium Core | 62 entities. Taxonomy, identity and delegation. The shared engines: versioning and revert, attestation, retention and legal hold, the classification rules engine, notification templates and delivery, reminders, service levels, imports, evidence packs, the help assistant, and the audited AI client |
| Governance | 24 entities. Forum inventory and map; committee formation with sequential approval and charter challenge; the compliance lifecycle and annual review; membership with history; meetings, motions and voting; disbandment |
| Policy | 38 entities. Repository and full-text search; lineage; applicability; lifecycle and approval routing; confidential and restricted handling; intake classification; publication; horizon scanning; monitoring; violations; glossary; dispositions; regulatory-change import |
| Escalation | 18 entities. Matters with three templates; matrix routing; role and group queues; action plans; risk acceptances; time in each status; closure |

**Screens for the work, not only for reading.** Forums, policies and escalations
are all acted on from the portal: formation requests, compliance and annual
reviews, disbandment, voting, policy lifecycle actions, approvals, versions,
publication, intake, raising and working escalations. A task inbox (`/tasks`),
attestation campaigns and import review (`/imports`) exist, and every portal
page has a page-context test.

**Measured coverage.** Of 64 mandatory requirements:

- **49** are fully reachable: 43 through a portal screen, 6 through the desk or
  a job by design.
- **9** are partly reachable.
- **6** each miss one mandatory clause.

On 2026-09-17 the figures were 22, 24 and 18. Of 180 backlog stories, 143 are
done, 36 partial and 1 not started; none is in progress. See
[`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md) and
[`EPICS.md`](EPICS.md).

**A realistic demonstration organisation.** `deploy/demo_data.py` rebuilds it
from scratch in about 27 s, idempotently, with no failed section. It holds:

- 14 forums, 67 meetings, 24 motions and 137 votes;
- 15 governing documents and 157 versions;
- 15 escalations;
- 92 attestation tasks;
- 23 personas.

Personas have no password until `deploy/demo_logins.py` issues random ones
into a file outside the repository. [`DEMO-LOGINS.md`](DEMO-LOGINS.md) lists
the personas and explains why no password is ever committed.

**A rehearsed deployment path.** One bundle carries every dependency. The
runtime set is now 139 wheels + 6 pure-Python sdists, with Playwright, greenlet
and pyee moved to `requirements-dev.txt`. All of this was rehearsed air-gapped
on Rocky Linux 9:

- install, with 0 network lines in pip's log;
- migration of the demonstration site, with identical row counts;
- upgrade from the previous release, with no table losing a row;
- backup and restore;
- systemd units and a TLS proxy;
- one scheduler, which ran every job exactly once;
- OIDC sign-in against a mock provider.

See [`DEPLOYMENT-READINESS.md`](DEPLOYMENT-READINESS.md) and
[`../RUNBOOK.md`](../RUNBOOK.md).

**Documentation** exists for three audiences:

- The stakeholder: data model, schema, architecture, requirements coverage and
  the backlog.
- The people who use and configure it: twelve illustrated chapters in
  `docs/guides/`, built to PDF and Word outside the repository.
- The deploying team: the runbook, operations and readiness documents.

There is also a 47-slide leadership briefing.

## The decisions that shaped it

- **Nothing branches on a workflow state name.** Logic reads semantic flags that
  a configuration table sets, and a checker fails the build if code breaks
  this. A new state needs no schema change either: `derive_phase_from_state`
  and the phase column on Workflow State Flag, opt-in per site. So a renamed
  state or an inserted approval step is configuration, not a code change.
- **Entities are generated from short specs**, so the same conventions hold
  across all of them rather than being reapplied by hand.
- **The engines are built once**, in Core. Attestation, retention, versioning,
  notification and service levels are each shared by all three modules.
- **Everything is vendored and checksummed.** There is no CDN, no package
  manager and no dependency that needs a compiler. An automated check enforces
  this, because the target has no internet access.
- **AI is optional and never required.** Every analysis feature is rule-based
  first. AI commentary goes through one audited client with a classification
  ceiling. It is guidance-only by default, and stays off until an administrator
  adds an endpoint and key.

## What is not done

Product gaps, each a single clause
([`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md) §4):

1. The formation approval route cannot vary by forum type or materiality (G-8).
2. Nothing enforces a first-quarter annual inventory attestation (G-10).
3. There are no notices for meeting schedules or charter reviews (G-14). Every
   other notice, the policy approval-step and disbandment approval notices
   included, goes through an editable template.
4. Pending policy approval steps get no reminders, and steps cannot be routed
   to a group (P-8).
5. Escalation transitions are not configurable by type and severity (E-8).
6. A risk acceptance has no configurable approval chain (E-9).
7. An approved disposal cannot be carried out from a screen (G-16, P-18,
   E-18).
8. Outbound export has no screen (G-19, P-20, E-19).

Known limitations:

- On the desk, a reviewer cannot return a document to drafting. The portal can.
- Voting has no attendance entry: presence for quorum is taken from ballots
  cast.
- Time To First Action is measured but not shown.

Deployment work, which can only close on the target:

- No real Windows run.
- No RHEL 8 or Ubuntu 22.04 rehearsal.
- **Python 3.11 on x86_64 is required.** The framework's `hiredis` pin blocks
  3.12, and `psutil` blocks ARM.
- Real certificates, the identity provider, SMTP and load testing need the
  target environment.
- **The offline bundle must be rebuilt from the final commit.** First remove
  the untracked scratch DocType `ABC`, in
  `apps/consilium/consilium/consilium_core/doctype/abc/`, which is also
  installed on the demonstration site.

None of this blocks a demonstration. The deployment items block going live.

## Questions that still need a person

- **Which sign-on protocol.** OIDC is proven against a mock provider and LDAP is
  configuration. SAML is not in the framework at all, so it would be a separate
  build.
- **Which taxonomy values are real.** The seeded set is a generic starting
  point, meant to be replaced.
- **The classification rules** for major versus minor policy change. The engine
  is built; the rules must come from the business.
- **Whether AI is switched on**, which endpoint it uses, and under which
  data-boundary policy.
- **Whether the assumptions in `docs/product/07-assumptions-and-gaps.md`
  hold.** That document exists to be argued with.
