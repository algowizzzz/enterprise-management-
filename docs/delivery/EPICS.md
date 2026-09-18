# Consilium — Delivery Backlog

Epics and stories for the end-to-end build.

**How to read this.** Each epic states the outcome it delivers and why it sits
where it does in the order. Stories carry acceptance criteria written so that
they can be tested, and a trace back to the requirement identifiers they
satisfy. Size is relative: **S** is under a day, **M** is one to three days,
**L** is a week or more and should probably be split once it is better
understood.

**Requirement identifiers.** `G-*` governance forum, `P-*` policy, `E-*`
escalation. `D-*` refers to a recorded decision; `R-*` to a recommendation
adopted.

**Definition of done**, applied to every story without exception:

1. The behaviour works when exercised against a running system, not only in a
   unit test.
2. Automated tests cover the behaviour, including at least one failure path.
3. Permissions are enforced server-side, and verified by a test that attempts
   the action as a role that should not be allowed it.
4. Anything a user can change is captured in the audit trail.
5. No dependency added that needs a compiler, a package manager at build time,
   or a network fetch at run time.
6. Works identically on Windows and on Linux.
7. No client-identifying content anywhere in code, comments, fixtures or docs.

---

## Status at a glance

**Final measurement, 2026-09-18, release 1.0.0.** Measured against the final
working tree, the rebuilt demonstration site and the final full test run on a
clean site: **1372 tests, OK** (0 failures, 0 errors). Other runs:

- `pytest tests/`: 51 passed.
- Interface sweep: 274 passed, 0 failed.
- Browser journeys: 8/8.
- Platform rules: 6/6.
- Deployment kit on air-gapped Rocky Linux 9: `verify.sh` 14/14.

The build is finished: **no story is in progress.** Every story is Done,
Partial or Not started. Per-requirement evidence is in
[`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md).

**Status key.**

- ✅ **Done**: the behaviour exists, a user can reach it (portal screen, desk,
  configuration or scheduled job, as the story intends) and a passing test
  covers it.
- 🟡 **Partial**: an acceptance clause is unmet, or no test covers the story.
  The unmet part is in bold.
- ⬜ **Not started**.

**Evidence notes** give the screen or route, the function and the test. Tests
are cited as `module.file.Class` for a file in `<module>/tests/`; the module is
dropped where the epic makes it obvious.

**Notifications.** A story whose acceptance criteria say someone is notified is
judged on whether the event raises a notification through the shared engine,
which records a `Notification Dispatch`. Every notice now goes through an
administrator-editable `Notification Template` (49 events) and the e-mail
channel. The approval-step notices on a governing document and the disbandment
approval request were the last two to move onto templates. No caller sends
hard-coded text any more (see `REQUIREMENTS-COVERAGE.md` §4.4). Real SMTP needs
the target environment.

**Where the Partial stories cluster.** Of the 37 stories not done:

* **Deployment readiness** (E34, E25-S2, E25-S6, E25-S7): each needs the
  target environment or a Windows workstation, not more code.
* **Missing automated tests** for behaviour that exists: E1-S2, E2-S5, E3-S5,
  E5-S1, E20-S1, E20-S2, E20-S5, E23-S2…S5, E26.
* **Small product gaps:**
  - Campaign export and completion by population segment (E18-S4, S5).
  - Template recipients by role or group, in-app notices and a digest (E19).
  - Documented API endpoints (E21-S3).
  - Summarising a long record (E22-S2).
  - The violation's escalation link on `/policy` (E27-S8).
  - Time To First Action shown (E29-S4).
  - Escalation transitions configurable by type and severity (E33-S6).
  - Carrying out an approved disposal from a screen (E5-S5).
  - Lint, format and type checks (E1-S5).

| Epic | ✅ Done | 🟡 Partial | ⬜ Not started | Total |
|---|---|---|---|---|
| *Phase 1 — Foundation* | | | | |
| E1 Platform foundation | 3 | 2 | 0 | 5 |
| E2 Identity, roles and access | 4 | 1 | 0 | 5 |
| E3 Taxonomy and reference data | 4 | 1 | 0 | 5 |
| E4 Audit, evidence and history | 4 | 0 | 0 | 4 |
| E5 Document handling, versioning and retention | 3 | 2 | 0 | 5 |
| **Phase 1 total** | **18** | **6** | **0** | **24** |
| *Phase 2 — Governance forums* | | | | |
| E6 Forum inventory | 6 | 0 | 0 | 6 |
| E7 Committee formation | 6 | 0 | 0 | 6 |
| E8 Forum lifecycle | 5 | 0 | 0 | 5 |
| E9 Membership, delegation and quorum | 6 | 0 | 0 | 6 |
| E10 Voting and decisions | 4 | 0 | 0 | 4 |
| **Phase 2 total** | **27** | **0** | **0** | **27** |
| *Phase 3 — Policy* | | | | |
| E11 Policy repository | 5 | 0 | 0 | 5 |
| E12 Policy lifecycle | 6 | 0 | 0 | 6 |
| E13 Intake classification | 4 | 0 | 0 | 4 |
| E14 Horizon scanning | 3 | 0 | 0 | 3 |
| E15 Monitoring, violations and glossary | 5 | 0 | 0 | 5 |
| **Phase 3 total** | **23** | **0** | **0** | **23** |
| *Phase 4 — Escalation* | | | | |
| E16 Escalation intake and templates | 4 | 0 | 0 | 4 |
| E17 Routing and resolution | 5 | 0 | 0 | 5 |
| **Phase 4 total** | **9** | **0** | **0** | **9** |
| *Phase 5 — Cross-cutting engines* | | | | |
| E18 Attestation | 3 | 2 | 0 | 5 |
| E19 Notifications | 1 | 3 | 0 | 4 |
| E20 Reporting and dashboards | 2 | 3 | 0 | 5 |
| E21 Import and export | 3 | 1 | 0 | 4 |
| E22 AI assistance | 3 | 1 | 0 | 4 |
| **Phase 5 total** | **12** | **10** | **0** | **22** |
| *Phase 6 — Interface* | | | | |
| E23 Interface shell | 1 | 4 | 0 | 5 |
| E24 Screens | 5 | 0 | 0 | 5 |
| **Phase 6 total** | **6** | **4** | **0** | **10** |
| *Phase 7 — Deployment* | | | | |
| E25 Installation and operations | 4 | 3 | 0 | 7 |
| E26 Quality | 1 | 4 | 0 | 5 |
| **Phase 7 total** | **5** | **7** | **0** | **12** |
| *Phase 8 — Gaps not in the original backlog* | | | | |
| E27 Portal write paths | 11 | 1 | 0 | 12 |
| E28 Work queues and oversight screens | 4 | 0 | 0 | 4 |
| E29 Notification delivery, reminders and service levels | 5 | 1 | 0 | 6 |
| E30 Record integrity and handling | 6 | 0 | 0 | 6 |
| E31 Product identity, scope and help | 4 | 0 | 0 | 4 |
| E32 Verification and demonstration | 6 | 0 | 0 | 6 |
| E33 Other measured gaps | 7 | 1 | 0 | 8 |
| **Phase 8 total** | **43** | **3** | **0** | **46** |
| *Phase 9 — Deployment readiness* | | | | |
| E34 Deployment readiness | 0 | 6 | 1 | 7 |
| **Phase 9 total** | **0** | **6** | **1** | **7** |
| **Original backlog (E1–E26)** | **100** | **27** | **0** | **127** |
| **All stories** | **143** | **36** | **1** | **180** |

On 2026-09-18, before the final wave, the count was 76 done, 24 partial, 76
in progress and 4 not started.

---

## Ordering rationale

The governance forum module publishes the data the other two consume — a
policy needs an approving committee, an escalation needs a destination forum.
So forums come first, then policy, then escalation. Underneath all three sit
identity, taxonomy and the audit trail, which is why the foundation epics are
not optional groundwork but the first release.

Three engines are deliberately built once and reused rather than per module:
**attestation**, **notification** and **document versioning**. Each is required
by all three modules with slightly different wording in the source
requirements. Building them three times is the most likely way this programme
accumulates inconsistency.

---

# Phase 1 — Foundation

## E1 — Platform foundation
*Outcome: an application that installs, migrates and serves, with the house
conventions enforced by tooling rather than by review.*

| ID | Story | Size | Status |
|---|---|---|---|
| E1-S1 | As an engineer, I have an application skeleton with four modules so that code has an obvious home. **AC:** app installs into a site; modules are `Consilium Core`, `Governance`, `Policy`, `Escalation`; module names do not collide with framework-owned names. | S | ✅ Done. Four modules in `modules.txt`; the shared one is `Consilium Core` because the framework owns `Core`. Installs in CI and by `deploy/install.sh`. escalation.tests.test_entities.TestModuleShape (all 3) |
| E1-S2 | As an engineer, I generate DocTypes from short specs so that every entity follows the same conventions. **AC:** a spec file produces DocType JSON, a controller and a test; the generator rejects a spec that declares a framework-maintained field, names a link target that does not exist, or has a duplicate field name. | M | 🟡 Partial. `apps/consilium/scripts/make_doctype.py` writes JSON, controller and test and rejects framework fields, unknown link targets and duplicate names. **No test covers the generator** (nothing under `tests/` or the app suites imports it) |
| E1-S3 | As an engineer, I have vendored front-end libraries with recorded checksums so the application installs with no internet access. **AC:** no CDN reference anywhere in the served HTML; a checksum file covers every vendored file; a test fails if a served page references an external host. | S | ✅ Done. `public/vendor/`, `VENDOR.md`, `SHA256SUMS`. `scripts/check_platform_rules.py` (no-CDN and checksum rules, 6/6), the health check's "Nothing references an external host" and `verify.sh`'s no-CDN scan of every served page and asset fail on a reference |
| E1-S4 | As an engineer, the test suite runs against a real database so that tests exercise the schema rather than a mock. **AC:** one command runs the suite; the suite creates and tears down its own fixtures. | M | ✅ Done. `run-tests --app consilium` on a site of its own: 1372 tests, OK. Every suite class is a `FrappeTestCase`, which rolls its class back on teardown; after the full run `consilium-test.localhost` holds 0 escalation matters, 0 governing documents and 0 notification dispatches, and the demo site holds no test rows |
| E1-S5 | As an engineer, continuous checks run on every change so regressions surface immediately. **AC:** lint, format, type check and tests run in one command and in CI; the air-gap rule and the sanitization rule are enforced by automated checks, not by convention. | M | 🟡 Partial. `.github/workflows/ci.yml` runs platform rules, toolchain tests on Linux and Windows, app tests and the health check; the air-gap and sanitization rules are automated (`check_platform_rules.py`). **No lint, format or type-check step, and no configuration for one** |

## E2 — Identity, roles and access
*Outcome: people can sign in, and what they can see and do is governed by role.*
Trace: G-13, P-13, E-16, D-3.

| ID | Story | Size | Status |
|---|---|---|---|
| E2-S1 | As an administrator, I manage users in the application so the system works before any directory integration exists. **AC:** create, deactivate and reactivate users; deactivated users cannot sign in but remain linked to their historical records. | S | ✅ Done. The framework's own user screens on desk. Disabled users are never offered or assigned. governance.tests.test_regressions.TestRoleBasedAssignment (all 2), governance.tests.test_formation_portal.TestNamedPeople (all 2) |
| E2-S2 | As an administrator, I assign access roles so that permissions follow the role, not the person. **AC:** ~~the role set covers administrator, taxonomy administrator, forum owner, committee secretary, reviewer, approver, compliance reviewer, policy owner, escalation owner and read-only viewer; each is enforced server-side.~~ the role set covers administrator, taxonomy administrator, forum owner, committee secretary, reviewer, compliance reviewer, policy owner, escalation owner and read-only viewer, each enforced server-side; approval is assigned per route step, to a role or a named person (formation approval route, document approval route, Core Approval Decision). *Revised 2026-09-18: approval authority belongs to the route step, not to a standing role.* | M | ✅ Done. Roles: Consilium Administrator, Taxonomy Administrator, Forum Owner, Committee Secretary, Policy and Escalation Reviewer, Compliance Reviewer, Policy Owner, Escalation Owner, Governance Viewer, Consilium Audit (consilium_core.tests.test_entities.TestPermissions (all 5) and each module's refusal tests). Approval per route step: `Formation Approval Route`, `Approval Route`, Core `Approval Decision` (governance.tests.test_formation.TestApprovalRoute, consilium_core.tests.test_services.TestApprovals, policy.tests.test_lifecycle.TestApprovalRouting) |
| E2-S3 | As a security reviewer, I see that restricted records are visible only to authorised users. **AC:** a record marked restricted is excluded from list views, search, reports and the API for users without the right; a test asserts the API path, not only the UI. | M | ✅ Done. `permission_query_conditions` and `has_permission` in `hooks.py` for Escalation Matter and its children (`escalation/sensitivity.py`) and for Governing Document and Document Version (`policy/handling.py`), so list, search, report, count and REST paths all filter. Tests go through the API: escalation.tests.test_sensitivity.TestSensitiveMatters (all 7), policy.tests.test_handling.TestVisibility (all 8), TestVersionHooks (all 2) |
| E2-S4 | As an administrator, I can enable single sign-on later without re-mapping existing records. **AC:** ~~an identity provider can be configured for LDAP or OIDC/SAML; an existing user is matched to a directory identity without changing the record's key; the feature is off by default.~~ single sign-on via OIDC/OAuth (the framework's Social Login Key) or LDAP; existing users matched without changing the record key; off by default. *Revised 2026-09-18: SAML dropped; the framework does not support it.* | L | ✅ Done. OIDC through the framework's `Social Login Key`, set from `[sso]` in `consilium.conf` by `install.sh`; rehearsed end to end offline against `scripts/mock_oidc_provider.py`: the existing account signed in with the same user id and creation time, a stranger refused with sign-ups denied (`docs/delivery/evidence/linux-rehearsal/41-sso-oidc-demo.txt`). Off by default (demo site: no Social Login Key, LDAP disabled). tests/test_kit.py (test_sso_and_ai_are_off_by_default, test_oidc_needs_its_endpoints_and_a_secret, test_ldap_search_filter_must_take_the_sign_in_name). LDAP is configuration only, not exercised; the real directory is E34-S5 |
| E2-S5 | As an auditor, I can see who held which role and when. **AC:** role grants and revocations are recorded with actor and timestamp and survive the user being deactivated. | M | 🟡 Partial. `User` tracks changes (framework `user.json`, `track_changes: 1`), so `Has Role` grants and revocations reach the Version log with actor and time and outlive deactivation. **No test** |

## E3 — Taxonomy and reference data
*Outcome: the shared vocabulary every module tags against, maintained by an
administrator rather than by a developer.* Trace: G-3, P-3, E-3, D-12.

| ID | Story | Size | Status |
|---|---|---|---|
| E3-S1 | As a taxonomy administrator, I maintain each reference list in the application. **AC:** risk category, legal entity, organisation unit, jurisdiction, forum type, governing document type, escalation type and horizon scanning coverage area are all maintainable; each value has a stable code, a name, a description and an active flag. | M | ✅ Done. All eight lists and nine more, on the Consilium Administration workspace; code, name, description, `is_active`. consilium_core.tests.test_entities.TestTaxonomies (all 9) |
| E3-S2 | As a taxonomy administrator, I retire a value without breaking history. **AC:** an inactive value no longer appears in pickers for new records but still displays correctly on existing ones; a test covers a record created before retirement. | S | ✅ Done. Deactivation, never deletion. `standard_queries` in `hooks.py` sends every taxonomy picker through an active-only query (`consilium_core/taxonomy.py`); an existing record still shows its retired value. consilium_core.tests.test_taxonomy.TestActiveOnlySearch (all 6, incl. test_a_record_made_before_retirement_still_shows_the_value), escalation.tests.test_assignment_and_timing.TestRetiredValuesAreNotOffered (all 1) |
| E3-S3 | As a taxonomy administrator, I maintain hierarchical taxonomies as trees. **AC:** risk category, organisation unit and jurisdiction support parent/child; a tree view is available; a value cannot be its own ancestor. | M | ✅ Done. Six trees with the desk tree view; the framework's nested set refuses a loop. TestTaxonomies.test_the_hierarchical_taxonomies_are_trees, test_a_child_resolves_to_its_parent |
| E3-S4 | As a taxonomy administrator, I load values in bulk from a file. **AC:** CSV import creates and updates values, reports per-row errors without partially applying a failed file, and records who imported what and when. | M | ✅ Done. `/imports` (`importing.upload_batch`, review, commit); `Reject Batch` handling rejects the whole file with per-row errors; each `Import Batch` keeps file hash, actor and outcome. Tests import `Risk Type` values: consilium_core.tests.test_import_pipeline.TestImportPipeline (all 9), consilium_core.tests.test_imports_portal.TestUpload (all 5), TestReview (all 7). A taxonomy profile is set up by the administrator on desk; none ships |
| E3-S5 | As an engineer, taxonomy values are referenced consistently everywhere. **AC:** every tagging field across all three modules links to these DocTypes; no module defines its own copy of a shared list. | S | 🟡 Partial. Tagging fields across the modules link to the Core taxonomies (e.g. `Forum Risk Type`, `Document Risk Type`). **No test asserts that no module keeps its own list** |

## E4 — Audit, evidence and history
*Outcome: the record of who did what, which is the reason this system exists.*
Trace: G-9, P-9, E-12, D-4.

| ID | Story | Size | Status |
|---|---|---|---|
| E4-S1 | As an auditor, every change to a governed record is recorded with actor, timestamp and before/after values. **AC:** change history is on for all governed entities; it cannot be switched off per record; a test asserts a field change produces an entry. | S | ✅ Done. `track_changes` on every governed entity. consilium_core.tests.test_entities.TestEntityStructure.test_governed_entities_keep_their_change_history, escalation.tests.test_entities.TestModuleShape.test_every_entity_tracks_changes |
| E4-S2 | As an auditor, I can read a record's full history in one place, in plain language. **AC:** a history view shows field changes, workflow transitions, comments, attachments and notifications in one chronological list. | M | ✅ Done. `evidence.record_history` (GET) merges Version, Comment (workflow, comments, attachments), Notification Log, Email Queue and `Notification Dispatch` into one chronological list, read on `/forum` and `/escalation`. consilium_core.tests.test_core_controls_wave3.TestHistoryAndEvidencePack.test_the_history_lists_changes_comments_and_notifications_in_one_list, test_the_history_is_refused_to_someone_who_cannot_read_the_record. `/policy` has no merged panel; its history reaches readers through the evidence pack |
| E4-S3 | As a record owner, I can revert a record to a previous version. **AC:** reverting writes a **new** version rather than mutating history; the revert itself is recorded with actor, timestamp, source version and a required reason; a test asserts the prior versions still exist afterwards. | L | ✅ Done. Core engine writes a new version with a required reason; revert offered on `/policy` (`publication.revert_version`) and from the revision history on `/forum` and `/escalation` (`consilium_core/revision.py`). consilium_core.tests.test_versioning.TestVersioning (all 9), policy.tests.test_portal_actions.TestVersions (all 9), consilium_core.tests.test_revision.TestMatterRevision (all 13), TestForumRevision (all 5) |
| E4-S4 | As an auditor, I can export a record's evidence pack. **AC:** a single export contains the record, its history, its attachments and its approvals, in a form that can be handed to a reviewer. | M | ✅ Done. `evidence.export_pack` builds one ZIP: record, history, revision chain, approvals and exceptions, refusals, dispatches, readable attachments, and a `manifest.json` with each entry's SHA-256; linked from `/forum`, `/escalation` and `/policy`; limited to audit and administration roles, refusals audited. TestHistoryAndEvidencePack.test_the_pack_holds_the_record_its_history_and_a_verifiable_manifest, test_the_pack_is_refused_without_an_evidence_role_and_the_refusal_is_audited |

## E5 — Document handling, versioning and retention
*Outcome: documents are held, versioned and retained by us.* Trace: G-15, G-16,
P-17, P-18, E-11, D-2, D-9.

| ID | Story | Size | Status |
|---|---|---|---|
| E5-S1 | As a user, I attach documents to a record. **AC:** attach, replace and remove; file type and size are validated; every action is audited. | S | 🟡 Partial. The framework's attachments, logged in the timeline; attachments to restricted documents are forced private (`handling.guard_file_privacy`). **File type is not restricted** (System Settings `allowed_file_extensions` empty, no `max_file_size` in the site config) and **no test covers attach, replace or remove on the governed entities** |
| E5-S2 | As a policy owner, I upload a new version of a document and the prior version is preserved. **AC:** versions are ordered and immutable; each carries who uploaded it and when; the current version is unambiguous. | M | ✅ Done. `Document Version` chain, ordered and immutable; `/policy` uploads a new body (`publication.upload_new_version`) only while editable. consilium_core.tests.test_versioning.TestVersioning (all 9), policy.tests.test_lifecycle.TestVersioningAndPublication (all 7), policy.tests.test_portal_actions.TestVersions (all 9) |
| E5-S3 | As a compliance officer, retained records cannot be altered or deleted before their retention period expires. **AC:** a retention class sets the period; deletion and modification are refused with a clear reason while a record is under retention; the refusal is audited. | L | ✅ Done. `retention.guard_modification` and `guard_deletion` on every DocType; each refusal goes to `Governance Refusal Log`. Classes and assignments on desk. consilium_core.tests.test_retention.TestRetention (all 14) |
| E5-S4 | As a compliance officer, I can place and lift a legal hold that overrides scheduled disposal. **AC:** a held record is never disposed of regardless of its retention period; placing and lifting a hold requires authorisation and is audited. | M | ✅ Done. `Legal Hold` on desk, Records Manager only, change-tracked; a hold beats disposal. TestRetention.test_a_legal_hold_overrides_a_scheduled_disposal, consilium_core.tests.test_entities.TestPermissions.test_retention_is_the_records_manager_s_to_run |
| E5-S5 | As a compliance officer, records past their retention period are disposed of on a defined schedule, with a certificate of what was disposed. **AC:** ~~disposal runs on a schedule, skips held records, and writes a disposal record that survives the disposal.~~ records past retention are flagged on a daily schedule for a disposal a named person approves; held records are flagged as held and never disposed of; an executed disposal writes a record that survives it. *Revised 2026-09-18: disposal is never automatic (retention rule 3); the schedule flags, a named approver decides.* | L | 🟡 Partial. Daily `retention.flag_due_for_disposal` (hooks.py) schedules a `Disposition Event` for each archive past retention, held ones as held; nothing is deleted. consilium_core.tests.test_core_controls_wave3.TestScheduledDisposalReview (all 5), TestRetention.test_an_approved_disposal_executes. **`execute_disposition` has no caller: no endpoint, desk button or job, so an approved disposal cannot be carried out from any screen (`executed_on` is read-only on the desk form)** |

---

# Phase 2 — Governance forums

## E6 — Forum inventory
*Outcome: the single inventory that the whole platform depends on.* Trace: G-1,
G-2, G-3, G-4, G-19.

| ID | Story | Size | Status |
|---|---|---|---|
| E6-S1 | As a governance user, I maintain a forum record with its identifying and ownership details. **AC:** all specified fields are present; required fields are enforced; the record is searchable by name and code. | M | ✅ Done. `Governance Forum` on `/forums`, `/forum` and desk. governance.tests.test_entities.TestGovernanceEntities, test_inventory.TestSearchAndFilter.test_free_text_search_covers_identifier_name_and_mandate. |
| E6-S2 | As a governance user, I tag a forum against the shared taxonomies. **AC:** business unit, risk type, legal entity and jurisdiction accept **multiple** values; primary risk category and owning organisation accept one; a test covers both shapes. | M | ✅ Done. Four multi-valued child tables, two single links. TestGovernanceEntities.test_four_dimensions_are_multi_valued_and_two_are_not. |
| E6-S3 | As a governance user, I search and filter the inventory. **AC:** filter by any tagged dimension and by status; free-text search across name, code and mandate; results paginate, sort and respect permissions. | M | ✅ Done. `/forums` now filters by the four multi-valued dimensions too (`inventory.inventory_filters`, `tagged_forum_names`, intersecting, permission-checked, retired values marked), alongside type, status, cadence, category, group and standing. governance.tests.test_governance_gaps.TestInventoryReads, test_inventory.TestSearchAndFilter. |
| E6-S4 | As a governance user, I map a forum to related forums. **AC:** parent, sub-forum, upstream and downstream relationships; a forum cannot be its own ancestor; the inverse relationship is visible from the other side. | M | ✅ Done. `parent_forum`, `Forum Link`; both directions drawn on `/forum` and on the home map. governance.tests.test_inventory.TestRelationships, TestGovernanceEntities.test_a_forum_cannot_be_its_own_ancestor. |
| E6-S5 | As a governance user, I record that a forum is regulatory-required and cite the requirement. **AC:** a flag with dependent fields that become required when set. | S | ✅ Done. `Forum Regulatory Requirement` required under the flag. TestGovernanceEntities.test_regulatory_detail_becomes_required_when_the_flag_is_set. |
| E6-S6 | As a user of another module, I can select a forum from authoritative data. **AC:** policy and escalation records link to forums directly; no copy of forum data exists in those modules. | S | ✅ Done. `Governing Document.approving_forum`, `Escalation Forum Link` (active forums only). escalation.tests.test_routing.TestRouting.test_an_inactive_forum_cannot_be_a_destination. |

## E7 — Committee formation
*Outcome: a request to stand up a forum, evaluated and approved on the record.*
Trace: G-5, G-6, G-7, G-8, G-17, G-18, R-2.

| ID | Story | Size | Status |
|---|---|---|---|
| E7-S1 | As a requester, I submit an intake request to create, modify or retire a forum. **AC:** a single intake form covers all three intents; required fields are enforced before submission; the form warns the requester that compliance review is required before they begin. | M | ✅ Done. `/create-forum` warns of the compliance review; `formation.submit_request`. governance.tests.test_formation.TestIntake. |
| E7-S2 | As a governance office reviewer, I evaluate a request against the standard criteria. **AC:** coverage gap, duplication, escalation pathway clarity, framework alignment and resource feasibility are each recorded with a finding and a comment; the request cannot be approved until each is assessed. | M | ✅ Done. Findings on `/formation-request`. test_formation.TestEvaluation, test_formation_portal.TestFindings. |
| E7-S3 | As a governance office reviewer, I can return a request to its originator with questions. **AC:** returning is a workflow transition, not a comment; the originator is notified; the exchange is preserved on the record. | S | ✅ Done. `return_request_to_originator`, `respond_to_returned_request`; the notice goes through its template. test_formation.TestReturnToOriginator, test_formation_portal.TestReturnAndRespond, test_wave3_governance.TestTemplatedNotices.test_a_returned_request_is_told_through_its_template. |
| E7-S4 | As an approver, I approve or reject a request through a configurable multi-step workflow. **AC:** approval steps are configuration; steps can be role-based, sequential or parallel; no step can be bypassed without a recorded exception. | L | ✅ Done. Sequential order is now enforced in Core (`approvals.record_decision`, `is_turn`), and `/formation-request` offers a step only in its turn. Parallel and peer steps do not wait. Role-based steps form a queue. A bypass needs an `Exception Authorisation` and waives only its own step. consilium_core.tests.test_core_controls_wave3.TestSequentialApprovals, governance.tests.test_wave3_governance.TestFormationStepOrder, test_w3_guides.TestABypassWaivesOnlyItsOwnStep, TestARoleIsAQueue, test_formation.TestApprovalRoute. |
| E7-S5 | As a governance user, an approved request creates a forum in draft. **AC:** approval creates the forum record with the request's data carried across; the link between request and forum is navigable in both directions. | M | ✅ Done. `formation.approve_request` creates the forum in draft, linked both ways (CFR-2026-00001 → FRM-2026-00014). test_formation.TestApprovalCreatesTheForum. |
| E7-S6 | As a governance office reviewer, I resolve a disputed request through a defined exception path. **AC:** an exception state routes to the designated authority and requires a recorded rationale. | M | ✅ Done. Exception to the designated authority with a rationale. test_formation.TestExceptionRoute, test_formation_portal.TestExceptionThroughThePortal. |

## E8 — Forum lifecycle
*Outcome: a forum's compliance standing, kept current.* Trace: G-10, G-11, R-2.

| ID | Story | Size | Status |
|---|---|---|---|
| E8-S1 | As a compliance reviewer, I move a forum through its compliance states. **AC:** draft, pending, compliant, non-compliant and not-applicable; only compliance roles may set the outcome states; every transition is audited. | M | ✅ Done. `/forum-review`, `lifecycle.record_compliance_review`. A favourable decision is refused while a charter challenge is open. governance.tests.test_lifecycle.TestComplianceReview, test_formation_portal.TestComplianceReviewThroughThePortal, test_governance_gaps.TestStandingGate. |
| E8-S2 | As a compliance reviewer, I return a forum to its creator with comments. **AC:** as E7-S3, on the forum record. | S | ✅ Done. "Returned To Creator" with questions on `/forum-review` (FCR-2026-00012 on FRM-2026-00011). TestComplianceReview.test_returning_to_the_creator_is_a_transition_carrying_questions. |
| E8-S3 | As a compliance administrator, changes to designated fields send a forum back for review automatically. **AC:** the watched-field list is **configuration**, editable without a deployment; changing a watched field moves the forum to pending and notifies compliance; changing an unwatched field does not. | M | ✅ Done. `Watched Field Set` on desk; `watched_fields.on_update`; templated notice. governance.tests.test_lifecycle.TestWatchedFields, consilium_core.tests.test_core_controls_wave3.TestWatchedFieldEvent, test_wave3_governance.TestTemplatedNotices.test_compliance_is_told_of_a_review_through_its_template. |
| E8-S4 | As a forum owner, I complete the required annual review. **AC:** review is due on a schedule; both the owner and compliance must confirm; an incomplete review is visible as an exception. | M | ✅ Done. Annual review panel on `/forum-review#annual-review` (`reviews.start_forum_annual_review`, `record_forum_annual_review`). The owner answers and compliance counter-signs in `/tasks`. `next_review_on` makes it due; the daily `reminders.remind_forum_reviews` chases overdue reviews and missing signatures. FCR-2026-00015/16/17 on the demo. governance.tests.test_w3_guides.TestAnnualReviewFromTheForum, test_lifecycle.TestAnnualReview, consilium_core.tests.test_reminders.TestForumReviewReminders, test_inbox.TestSecondSignature. |
| E8-S5 | As an approver, I disband a forum through a controlled workflow. **AC:** disbandment requires the specified approvals; the forum becomes inactive rather than deleted; its history and documents remain and remain subject to retention. | M | ✅ Done. `/forum-disband`: raise, attach plan, approver or delegate decisions, execute (`lifecycle.execute_forum_disbandment` waits for every approval; the forum goes inactive, never deleted). Approvers are asked through the `governance.disbandment.approval_requested` template. FDIS-2026-00002 is live on the demo. governance.tests.test_governance_gaps.TestDisbandmentPortal, test_lifecycle.TestDisbandment. |

## E9 — Membership, delegation and quorum
*Outcome: who sits on a forum, with the history intact.* Trace: G-13, G-14,
E-7, D-3.

| ID | Story | Size | Status |
|---|---|---|---|
| E9-S1 | As an administrator, I maintain the list of membership roles. **AC:** roles are data, not code; each carries whether it counts toward quorum, whether it votes by default and whether it can attest. | S | ✅ Done. `Governance Forum Role` carries quorum, vote and attest flags (10 roles on the demo). consilium_core.tests.test_entities.TestTaxonomies.test_the_seeded_seat_roles_carry_their_behaviour. |
| E9-S2 | As a forum secretary, I add and remove members with effective dates. **AC:** membership is a record with a from-date and an optional to-date; removing a member ends the record rather than deleting it. | M | ✅ Done. `Forum Membership` with dates, closed not deleted (desk; secretary and governance office may write). governance.tests.test_membership.TestMembershipHistory. |
| E9-S3 | As an auditor, I can see who sat on a forum at any past date. **AC:** a query by date returns the membership as it stood then; a test covers a member who joined and left before the query date. | M | ✅ Done. "Membership as at" on `/forum`. TestMembershipHistory.test_who_sat_on_a_forum_at_a_past_date. |
| E9-S4 | As a forum secretary, I record a seat held by position rather than by a named person. **AC:** a seat can name a position; the occupant can change without the seat losing identity or history. | M | ✅ Done. Position seats that may stand vacant. governance.tests.test_membership.TestSeatShape. |
| E9-S5 | As a member, I delegate my seat for a period. **AC:** a delegation records who delegated, to whom and for how long; the delegate inherits voting rights only if the role permits; delegation is visible on the forum. | M | ✅ Done. Delegate with dates and vote flag; "Standing delegate" on `/forum`; a delegate may cast the seat's ballot on `/forum-motion` where the seat allows (FMEM-00031). governance.tests.test_membership.TestDelegation, test_voting.TestDelegatedVoting. |
| E9-S6 | As a forum secretary, quorum is calculated from current voting membership. **AC:** the quorum rule is configurable per forum as a count or a percentage; the system reports whether quorum is met for a given date. | M | ✅ Done. Count or percentage per forum (`membership.quorum_status`); the verdict is stored on each sitting and motion. governance.tests.test_membership.TestQuorum. |

## E10 — Voting and decisions
*Outcome: decisions with enough evidence to defend them later.* Trace: G-12,
PPTX target operating model, D-3.

| ID | Story | Size | Status |
|---|---|---|---|
| E10-S1 | As a forum secretary, I record a matter put to a forum for decision. **AC:** a decision record links to the forum, the date, the matter and any related policy or escalation. | M | ✅ Done. `/forum-motion` (`voting.propose_motion`, secretary only) and `Forum Motion` links forum, sitting, date and subject record. 24 motions on the demo. governance.tests.test_voting.TestRecordedDecisions, test_w3_guides.TestVotingScreen.test_only_the_secretary_puts_a_motion_or_records_its_outcome. |
| E10-S2 | As a forum secretary, I record votes against a decision. **AC:** who was entitled to vote at that date, who voted, how they voted and abstentions; entitlement is derived from membership as at the decision date, not as at today. | L | ✅ Done. Entitlement as at the decision date. Members (or seat delegates) cast their own ballots on `/forum-motion` (`voting.cast_my_vote`), and the tally shows for, against and abstentions. Known gap: there is no attendance entry, so presence for quorum is taken from ballots cast. test_voting.TestEntitlement, TestDelegatedVoting, test_w3_guides.TestVotingScreen. |
| E10-S3 | As an auditor, I can see whether quorum was met when a decision was taken. **AC:** quorum status is calculated and stored on the decision at the time it is recorded, so later membership changes do not rewrite history. | M | ✅ Done. Quorum is stored when the outcome is recorded; an inquorate sitting cannot record a standing decision (FMOT-2026-00018 recorded Inquorate). TestRecordedDecisions.test_a_later_membership_change_does_not_rewrite_a_past_quorum, test_w3_guides.TestVotingScreen.test_a_decision_does_not_stand_on_an_inquorate_sitting. |
| E10-S4 | As a governance user, I can see all decisions taken by a forum. **AC:** a decision list per forum, filterable by date and outcome, exportable. | S | ✅ Done. Motions table on `/forum` (Decisions tab); desk list export. TestRecordedDecisions.test_a_forum_s_decisions_are_listable_and_filterable. |

---

# Phase 3 — Policy

## E11 — Policy repository
*Outcome: one searchable home for governing documents.* Trace: P-1, P-2, P-3,
P-4, P-21.

| ID | Story | Size | Status |
|---|---|---|---|
| E11-S1 | As a policy user, I maintain a policy record with its full metadata. **AC:** all specified metadata fields; required fields enforced; document type drawn from the taxonomy. | M | ✅ Done. `Governing Document` on the desk, shown on `/policy`, with correction in place (`metadata.correct_metadata`). policy.test_repository.TestGoverningDocument, policy.test_wave3.TestMetadataCorrection |
| E11-S2 | As a policy user, I search and filter the repository. **AC:** filter by type, owner, status, risk category and organisation; full-text search across title and content; results respect permissions. | M | ✅ Done. `/policies` filters by type, phase, group, risk category, handling and owner (`repository.owners`), and does content search through `repository.search`, which covers the current version's text and respects handling. policy.test_wave3.TestSearch (all 4) |
| E11-S3 | As a policy user, I record relationships between documents. **AC:** parent, child and addendum lineage; navigable in both directions; circular lineage prevented. | M | ✅ Done. `lineage.lineage_of` drawn on `/policy`; a restricted child is not named. policy.test_repository.TestLineage, policy.test_wave3.TestLineageVisibility |
| E11-S4 | As a policy owner, I record where a policy applies. **AC:** applicability covers organisation units, legal entities, jurisdictions and roles, and records formal exemptions with their approvals. | M | ✅ Done. `Document Applicability` and `Applicability Exemption` on the desk, shown on `/policy`. test_repository.TestApplicability, policy.test_entities.TestExemptionLifecycle |
| E11-S5 | As an affected party, I am notified when a policy that applies to me is published, changed or retired. **AC:** notification derives from applicability rather than a manual list. | M | ✅ Done. Publication raises `policy.document.audience` (`publish_record` on `/policy`). A new version in force raises `policy.document.changed` and retirement `policy.document.retired` (`disposition.py`), each to `applicability.affected_parties`. policy.test_wave3.TestChangeAndRetirement, policy.test_wave3_policy.TestAudienceNotice |

## E12 — Policy lifecycle
*Outcome: a policy moves from request to retirement on a defined path.* Trace:
P-5, P-6, P-7, P-8, P-25.

| ID | Story | Size | Status |
|---|---|---|---|
| E12-S1 | As a business user, I request a new or amended policy. **AC:** an intake request captures the need, the proposed implementation date and who must be engaged. | M | ✅ Done. `Document Intake Request`, raised on `/policy-intake` (`intake.raise_request`) or on the desk. policy.test_intake.TestIntakeRequest, policy.test_portal_actions.TestIntake |
| E12-S2 | As a drafter, I move a policy through drafting, review, approval, publication, periodic review and retirement. **AC:** states and transitions are configuration; role-based; every transition audited; no state name is hard-coded in business logic. | L | ✅ Done. The *Governing Document Lifecycle* Workflow is driven from `/policy` (`lifecycle.document_actions` and `take_action`, POST only). A new state needs no schema change (`derive_phase_from_state`, opt-in). policy.test_lifecycle.TestLifecycleConfiguration, TestLifecycleTransitions, policy.test_portal_actions.TestLifecycleActions, policy.test_w3_state_phase.TestDerivedPhase. Known limit: the reviewer's "Return to Drafting" works on the portal, not the desk |
| E12-S3 | As an approver, approvals route by policy type, change type and risk level. **AC:** conditional routing is configuration; the resulting path is visible on the record before submission. | L | ✅ Done. `Approval Route` configuration. `/policy` shows the planned steps (`routing.approval_context`) before `raise_steps`. test_lifecycle.TestApprovalRouting, policy.test_portal_actions.TestApprovalChain |
| E12-S4 | As a policy owner, parent policy owners approve changes to child documents where required. **AC:** the requirement is derived from lineage; the parent owner's approval is a distinct step. | M | ✅ Done. The parent-owner step is derived from lineage (`routing.resolved_steps`) and raised from `/policy`. test_lifecycle.TestParentOwnerApproval. No demo relationship row sets `owner_approval_required` |
| E12-S5 | As a policy owner, I raise an exception or exemption request through a form and workflow. **AC:** exceptions are records with their own approval path and expiry. | M | ✅ Done. `Applicability Exemption` (desk form, authorisation and expiry, daily lapse). Gate exceptions are requested by the owner on `/policy` and approved by the policy office. policy.test_entities.TestExemptionLifecycle, policy.test_wave3.TestGateExceptions |
| E12-S6 | As a compliance officer, publication cannot occur without approval. **AC:** the transition to published is refused without a complete approval chain; bypass requires a recorded, authorised exception. | M | ✅ Done. Gates run on every route (`GoverningDocument.validate`), and the refusal names the gate on `/policy`. test_lifecycle.TestPublicationRefusal, policy.test_regressions.TestGatesOnEveryRoute, policy.test_w3_record_approval.TestRecordApprovalChecksTheChain |

## E13 — Intake classification
*Outcome: the major/minor decision, owned by the business and changeable
without a deployment.* Trace: P-16, D-19.

| ID | Story | Size | Status |
|---|---|---|---|
| E13-S1 | As an administrator, I define the classification questions. **AC:** questions, answer options and ordering are data; adding a question requires no code change. | M | ✅ Done. `Classification Question` and its options on the desk, rendered by `/policy-intake` (`intake.form_options`). test_intake.TestClassification.test_an_administrator_can_add_a_question_without_a_code_change |
| E13-S2 | As an administrator, I define the rules that turn answers into a classification. **AC:** rules are data; the rule set is versioned; the version used is stored on each classified request. | L | ✅ Done. Versioned `Classification Rule Set`, locked once used. consilium_core.test_classification.TestClassification, test_intake.TestClassification.test_the_rule_set_version_is_stored_on_the_assessment |
| E13-S3 | As a requester, my answers produce a classification I can see and that is explained. **AC:** the outcome shows which rule fired; the requester can challenge it and the challenge is recorded. | M | ✅ Done. `/policy-intake` classifies (`intake.classify_request`), shows the matched rule and trace, and records a challenge (`challenge_request`). policy.test_portal_actions.TestIntake, test_intake.TestClassification.test_the_outcome_is_explained_and_can_be_challenged |
| E13-S4 | As a policy owner, classification drives routing, approval steps and service levels. **AC:** classification selects the workflow path; a test covers both a major and a minor path. | M | ✅ Done. Classification on `/policy-intake` selects the Major or Minor route and starts POL-INTAKE-MAJOR or MINOR. test_intake.TestClassificationDrivesRoutingAndService |

## E14 — Horizon scanning
*Outcome: a periodic obligation on the policy owner, recorded and traceable.*
Trace: P-8 sub-requirement, deck annex.

| ID | Story | Size | Status |
|---|---|---|---|
| E14-S1 | As a policy owner, I record a horizon scan against a policy. **AC:** scan date, period covered, coverage areas, sources reviewed, findings and an impact assessment. | M | ✅ Done. `Horizon Scan` on the desk and on `/policy` (`horizon.record_scan`). policy.test_horizon.TestHorizonScanRecord, policy.test_portal_actions.TestReviewsAndScans |
| E14-S2 | As a policy owner, I am reminded when a scan is due. **AC:** due dates derive from the policy's review cadence; reminders escalate when overdue; completion is tracked. | M | ✅ Done. Daily `horizon.remind_due` goes to the owner, then the sponsor, and does not chase daily. test_horizon.TestScanCadence, policy.test_wave3_policy.TestHorizonReminderCadence |
| E14-S3 | As a policy owner, a scan finding can trigger a policy review. **AC:** an impact assessment of "review triggered" creates the downstream workflow and links it to the scan. | M | ✅ Done. A review-triggered scan opens a linked review cycle (PHSC-00002 → PRVC-00001). test_horizon.TestScanTriggersReview |

## E15 — Monitoring, violations and glossary
*Outcome: the policy office can see adherence and keep language consistent.*
Trace: P-11, P-22, P-23, P-24.

| ID | Story | Size | Status |
|---|---|---|---|
| E15-S1 | As a policy office user, I record monitoring activities against a policy. **AC:** activity, date, outcome and evidence. | M | ✅ Done. `Monitoring Activity` on the desk; results recorded on `/policy` (`monitoring.record_result`). policy.test_monitoring.TestMonitoring, policy.test_portal_actions.TestMonitoring |
| E15-S2 | As a policy office user, I record a violation and track it to resolution. **AC:** violation record with severity, owner, remediation and status; links to the policy and optionally to an escalation. | M | ✅ Done. Logged and moved on from `/policy` (`log_violation` and `update_violation`). The controller guards reopening and closure. The escalation link is set on the desk. test_monitoring.TestViolations, policy.test_wave3.TestViolationTransitions |
| E15-S3 | As a policy office user, I maintain a glossary of terms. **AC:** centrally maintained; versioned; changes audited. | M | ✅ Done. `Glossary Term` on the Core version chain. test_monitoring.TestGlossary |
| E15-S4 | As a policy author, glossary terms are surfaced in context. **AC:** defined terms are recognisable in a document view and show their definition. | M | ✅ Done. A definitions panel (`glossary.in_context`, with use counts and findings) on `/policy` and beside the body on `/document-view`. It is a panel, not inline highlighting. policy.test_wave3.TestGlossaryOnThePage, policy.test_naming_glossary.TestGlossaryEnforcement.test_in_context_counts_use_and_reports_findings |
| E15-S5 | As a policy office user, I can find records with missing required metadata. **AC:** a maintenance view lists incomplete records by field, and supports correcting them in place. | M | ✅ Done. `/reports` lists incomplete records with a "Correct in place" link, and `/policy` corrects a field with a reason (`metadata.correct_metadata`, which resolves open remediation tasks). policy.test_wave3.TestMetadataCorrection, test_monitoring.TestMetadataMaintenance |

---

# Phase 4 — Escalation

## E16 — Escalation intake and templates
*Outcome: consistent capture of matters that need to go up.* Trace: E-1 … E-6.

| ID | Story | Size | Status |
|---|---|---|---|
| E16-S1 | As an administrator, I configure templates per escalation type. **AC:** the escalation, action plan and risk acceptance templates each have a configurable required-field set; standard fields are shared across templates. | L | ✅ Done. `Escalation Template` in three scopes (ESC-INCIDENT, AP-INCIDENT, RA-LIMIT on the demo), administrator-owned on desk. escalation.tests.test_templates.TestTemplates (all 8). |
| E16-S2 | As an escalation owner, I raise an escalation using the right template. **AC:** selecting a type applies its template; required fields enforced; the matter is searchable immediately. | M | ✅ Done. `/raise-escalation` shows the type's required fields (`template_requirements`) and `raise_escalation` inserts through the controller; the matter is listed on `/escalations` at once. escalation.tests.test_templates.TestTemplates, escalation.tests.test_portal_actions.TestRaise (all 6). |
| E16-S3 | As an escalation owner, I record an action plan against an escalation. **AC:** start and end dates, accountable executive, owner and status; multiple action plans per escalation. | M | ✅ Done. `Action Plan`, several per matter, added and updated from `/escalation` (`add_action_plan`, `update_action_plan`). escalation.tests.test_entities.TestActionPlan (all 2), escalation.tests.test_portal_actions.TestActionPlans (all 4). |
| E16-S4 | As an escalation owner, I record a risk acceptance against an escalation. **AC:** rationale, accountable executive, period and status; a risk acceptance requires an explicit approval. | M | ✅ Done. Proposed from `/escalation` (`approvals.add_risk_acceptance`); takes effect only after an independent approver's decision or a forum motion (`request_risk_acceptance_approval`, `decide_risk_acceptance`). escalation.tests.test_resolution.TestRiskAcceptanceApproval (all 5), escalation.tests.test_portal_actions.TestRiskAcceptanceApproval (all 9). |

## E17 — Routing and resolution
*Outcome: matters reach the right forum and are closed with evidence.* Trace:
E-7 … E-15.

| ID | Story | Size | Status |
|---|---|---|---|
| E17-S1 | As an escalation owner, I select a governance forum as the escalation pathway. **AC:** the forum list comes from the forum inventory; only active forums are selectable; the forum's escalation protocol and threshold are shown. | M | ✅ Done. `Escalation Forum Link`; forums chosen on `/raise-escalation` and changed on `/escalation` (`routing.set_pathway`, active forums only); protocol and threshold shown. escalation.tests.test_routing.TestRouting.test_the_forums_protocol_and_threshold_are_shown, escalation.tests.test_portal_actions.TestPathway (all 4). |
| E17-S2 | As an administrator, I configure escalation pathways so routing is consistent. **AC:** pathways are data; a matter of a given type and severity proposes its destination automatically. | L | ✅ Done. `Escalation Matrix` rules on desk propose severity, pathway, queue and service level on save and on the intake form (`propose_pathway`). escalation.tests.test_routing.TestRouting (all 12). |
| E17-S3 | As an escalation owner, I move a matter through its states to closure. **AC:** ~~open, in progress, pending review and closed; closure requires a recorded outcome.~~ the configured set of states (Open, In Progress, Under Review, Pending Review, Closed, Closed — Tracked Externally), driven by semantic flags, not a fixed four; closure requires a recorded outcome. *Revised 2026-09-18: the states are configuration, and E-14 needs more than four.* | M | ✅ Done. Six configured states mapped to semantic flags; moved and closed on `/escalation` (`move_matter_status`, `record_matter_closure`, `close_matter`) behind the `Escalation Closure` gate. escalation.tests.test_resolution.TestStatesAndClosure (all 7), escalation.tests.test_portal_actions.TestStatus (all 4), TestClosure (all 4). |
| E17-S4 | As a manager, matters that breach their time thresholds are escalated automatically. **AC:** thresholds are configuration per type and severity; breach raises the matter and notifies; the breach is recorded. | M | ✅ Done. Daily `sla.sweep` and `resolution.sweep_breaches`; only the resolution threshold raises the matter; the notice reaches pathway forum participants. escalation.tests.test_resolution.TestServiceLevels (all 5), escalation.tests.test_regressions.TestBreachIsNotRepeated (all 2), escalation.tests.test_wave3_escalation.TestOnlyTheResolutionThresholdRaisesAMatter (all 2). |
| E17-S5 | As a risk manager, I can analyse escalation patterns. **AC:** volumes, durations, destinations and outcomes over time, filterable and exportable. | M | ✅ Done. `analysis.summary` and CSV `analysis.export` on `/reports`. escalation.tests.test_analysis.TestAnalysis (all 5). |

---

# Phase 5 — Cross-cutting engines

## E18 — Attestation
*Outcome: one engine, three campaigns.* Trace: G-10, P-8, deck slide 13.

| ID | Story | Size | Status |
|---|---|---|---|
| E18-S1 | As an administrator, I define an attestation campaign. **AC:** scope, population, period, opening and closing dates; three campaign types supported by one engine. | L | ✅ Done. `Attestation Campaign` (scope, population query, period, opening and closing dates) on desk; forum campaigns opened from `/attestation-campaigns`, policy campaigns from `/policy`; three types, one engine. consilium_core.tests.test_attestation.TestAttestation (all 13), policy.tests.test_wave3.TestAttestationCampaign (all 2) |
| E18-S2 | As a campaign owner, tasks are generated for the right people. **AC:** the population is derived from live data — forum membership or policy ownership — not a pasted list; regenerating is safe and does not duplicate open tasks. | M | ✅ Done. `/attestation-campaigns` calls `attestation.generate_campaign_tasks` (POST); population from live membership or ownership; regeneration adds, never duplicates. TestAttestation (all 13), TestUnconfiguredRecordsDoNotStopACampaign (all 3), consilium_core.tests.test_inbox.TestCampaignAdministration (all 5) |
| E18-S3 | As an attester, I complete my task with a recorded confirmation. **AC:** confirm or raise an exception; a comment is required on exception; the response is immutable once submitted. | M | ✅ Done. `/tasks` calls `attestation.respond_to_task`: a statement is required on an exception; an answered or lapsed task cannot be answered again; attesters have no desk write. consilium_core.tests.test_inbox.TestInboxAttestation (all 8), TestSecondSignature (all 3) |
| E18-S4 | As a campaign owner, I can see completion and chase what is outstanding. **AC:** live completion by population segment; reminders escalate as the close date approaches. | M | 🟡 Partial. `campaign_overview` on `/attestation-campaigns` shows each campaign's open, overdue, answered, lapsed and awaiting-signature counts; campaign reminders follow the campaign's `Attestation Reminder` schedule (consilium_core.tests.test_w3_guides_core.TestCampaignReminderSchedule (all 4)). **Completion is per campaign, not by population segment, and campaign reminders repeat to the same person rather than escalating** |
| E18-S5 | As an auditor, a closed campaign is evidence. **AC:** a campaign export shows who was asked, who responded, what they said and who did not respond. | M | 🟡 Partial. Only the generic desk export of `Attestation Task`. **No campaign export (who was asked, who answered, what, who did not), no test** |

## E19 — Notifications
*Outcome: the right people told, through a channel that can change.* Trace:
G-14, P-14, E-17.

| ID | Story | Size | Status |
|---|---|---|---|
| E19-S1 | As an administrator, I configure notification templates per event. **AC:** templates are data; recipients can be roles, groups or derived from the record. | M | 🟡 Partial. `Notification Template` rows per event and channel (49 on the demo site), rendered by `notification.notify`. consilium_core.tests.test_notification_templates.TestEventApi (all 10), TestSeeding (all 2). **Recipients are chosen by the calling code for each event; a template cannot name a role or a group** |
| E19-S2 | As a user, I receive notifications in the application. **AC:** in-app delivery with read state; a digest option. | M | 🟡 Partial. The `in_app` adapter writes the framework's Notification Log, which carries read state. **No event is templated on the in-app channel (all 49 templates are EMAIL), the portal has no notification list, the `WEEKLY_DIGEST` channel is a `record_only` placeholder, and no test exercises in-app delivery** |
| E19-S3 | As an engineer, delivery channels are pluggable. **AC:** channel is an interface with in-app and email implemented, and a third channel stubbed against a documented API so it can be added without touching callers. | M | 🟡 Partial. Adapter registry (`notification.register_adapter`, documented in the module docstring) with `record_only`, `in_app` and `email`; channels are `Notification Channel` rows with fallbacks. consilium_core.tests.test_notification.TestNotification (all 6). **No third channel is stubbed** (the chat channel is "not built" in `docs/product/04-architecture.md`) |
| E19-S4 | As an auditor, notification delivery is recorded. **AC:** what was sent, to whom, when, on which channel, and whether it succeeded. | S | ✅ Done. A `Notification Dispatch` row for every send, including failures, suppressions and fallbacks. consilium_core.tests.test_notification.TestNotification (all 6) |

## E20 — Reporting and dashboards
*Outcome: the numbers people ask for, without an export to a spreadsheet.*
Trace: G-12, P-12, E-15, deck optional items.

| ID | Story | Size | Status |
|---|---|---|---|
| E20-S1 | As a user, I build a report over any entity. **AC:** choose columns, filter, group, sort; save and share; export to CSV and Excel. | M | 🟡 Partial. The framework's report builder and export on desk. **No test in this application.** |
| E20-S2 | As a governance user, I see a dashboard of forum activity and compliance standing. **AC:** counts by category, status distribution, overdue reviews, recent changes. | M | 🟡 Partial. `/reports` forum section (awaiting review, overdue, regulatory-required, disbanded, by compliance status, by type) and home counts, each linking to the filtered inventory. **No test of any figure**; they are counted in the browser, and consilium_core.tests.test_portal_pages checks only that the page renders. |
| E20-S3 | As a governance user, I see where governance coverage has gaps. **AC:** coverage by risk category and organisation unit, highlighting combinations with no forum. | L | ✅ Done. Coverage matrix (risk category by owning group, empty cells highlighted, each cell opens the filtered inventory) on `/reports#coverage`. The same rule lists gaps on `/governance-gaps` (`ai.gaps.coverage_gaps`). consilium_core.tests.test_ai_features.TestGaps.test_forum_policy_regulatory_and_coverage_gaps_are_found. |
| E20-S4 | As a user, I see how forums connect to one another. **AC:** a navigable diagram of parent, sub-forum, upstream and downstream relationships. | L | ✅ Done. `inventory.interconnectivity` SVG on `/forum` and the enterprise map (`inventory.forum_map`) on `/`; nodes link to their forum. governance.tests.test_inventory.TestRelationships, test_governance_gaps.TestInventoryReads.test_the_map_draws_what_the_viewer_may_see. |
| E20-S5 | As a user, dashboards respect my permissions. **AC:** figures reflect only records the viewer may see; a test asserts two roles see different totals from the same dashboard. | M | 🟡 Partial. Every figure comes through permission-checked reads. Two-viewer tests exist for the escalation analysis (escalation.tests.test_analysis.TestAnalysis.test_the_analysis_shows_only_what_the_viewer_may_see), policy sections (policy.tests.test_wave3.TestReporting.test_sections_count_only_what_the_viewer_may_read), the forum map and the risk scores. **Forum figures on `/reports` are not tested for two viewers.** |

## E21 — Import and export
*Outcome: the replacement for the integrations that are out of scope.* Trace:
G-19, P-20, E-19, D-18.

| ID | Story | Size | Status |
|---|---|---|---|
| E21-S1 | As an administrator, I import records from a file. **AC:** a documented template per entity; validation before commit; per-row error reporting; no partial application of a failed file. | L | ✅ Done. `/imports`: upload against an `Import Profile`, whose required columns the page lists; validated before commit, per-row errors, `Reject Batch` refuses a failed file whole. consilium_core.tests.test_import_pipeline.TestImportPipeline (all 9), consilium_core.tests.test_imports_portal.TestUpload (all 5), escalation.tests.test_import_export.TestImportPath (all 4). Profiles ship for Escalation Matter and Regulatory Requirement; others are defined on desk |
| E21-S2 | As an administrator, an import is auditable and reversible. **AC:** ~~each import is a record with its file, actor and outcome; an import can be rolled back.~~ each import is a record with its file, actor and outcome; a batch is reviewed and can be discarded before commit; a committed import is corrected by a compensating import, never by deletion (audit and retention rules). *Revised 2026-09-18: rollback would delete audited and possibly retained records.* | M | ✅ Done. Each `Import Batch` keeps file hash, actor and outcome; rows reviewed, excluded, revalidated and the batch discarded before commit on `/imports`; a re-import of the same key updates. consilium_core.tests.test_imports_portal.TestReview (all 7), TestDiscard (all 1), TestImportPipeline.test_a_second_import_of_the_same_key_updates_rather_than_duplicates |
| E21-S3 | As an integrator, data can be extracted through the API. **AC:** documented read endpoints for every published entity, with permission enforcement and pagination. | M | 🟡 Partial. The framework's REST API enforces permissions and pages (escalation.tests.test_sensitivity.TestSensitiveMatters, policy.tests.test_handling.TestVisibility). **The read endpoints are not documented** (no `/api/resource` reference in `docs/`) |
| E21-S4 | As an engineer, an integration can be added later without reshaping the data. **AC:** an integration boundary exists with the file importer as its first implementation; adding an API-based source requires no change to the entities. | M | ✅ Done. Staged `Import Row`, `External System`, `External Reference`; the file importer is the first source; a module preparer hook runs before commit. TestImportPipeline (all 9), TestReview.test_a_module_preparer_runs_before_the_commit |

## E22 — AI assistance
~~*Outcome: the external AI platform made useful inside the workflow, with
provenance.*~~ *Outcome: an offline-first help assistant plus AI features
(O-6, O-7) on an optional, administrator-configured endpoint, off by default,
with every call audited and a non-AI result always available.* Trace: D-1, O-6,
O-7. *Revised 2026-09-18: the AI service is optional, not the centre of the
epic.*

| ID | Story | Size | Status |
|---|---|---|---|
| E22-S1 | As an engineer, the application can call the external AI service. **AC:** one adapter; endpoint and credentials are configuration; failure degrades gracefully and never blocks the user's work. | M | ✅ Done. `consilium_core/ai/client.py` is the one path for the help assistant and the analysis features; endpoint, model and key in `Assistant Settings`, off by default; timeout, error, refusal or unreachable endpoint falls back to the built-in result. consilium_core.tests.test_ai_features.TestClient (all 3), consilium_core.tests.test_assistant.TestAIMode (all 8), TestSettings (all 4). |
| E22-S2 | As a user, I can request a summary of a long record or document. **AC:** a summary is offered, clearly labelled as machine-generated, and never saved without a person accepting it. | M | 🟡 Partial. The help assistant describes the record on screen and the actions open on it (consilium_core.tests.test_assistant.TestRecordAwareness), and machine text elsewhere is labelled and never saved without acceptance. **No summary of a document body or long record is offered, with or without AI; there is no summarise action or endpoint.** |
| E22-S3 | As an auditor, I can tell which content originated from a suggestion. **AC:** accepted suggestions record the suggestion, who accepted it, when, and against which version. | M | ✅ Done. `ai.regulatory.decide` writes an immutable `AI Suggestion Acceptance` (suggested and accepted value, edited flag, who, when, `applied_to_version`) for accepts and rejects on `/regulatory-updates`. consilium_core.tests.test_ai_features.TestRegulatory (all 8), consilium_core.tests.test_services.TestProvenance (all 4). |
| E22-S4 | As a compliance officer, I control what may be sent to the external service. **AC:** a policy governs which fields and classifications may leave; restricted records are excluded; every outbound call is logged. | M | ✅ Done. `ai/guard.py`: data-sharing mode (tokens only by default), classification ceiling, Restricted and sensitive never sent, subject above the ceiling refused and recorded; every call an `AI Service Request`, every question an `Assistant Interaction`. consilium_core.tests.test_ai_features.TestGuard (all 4), TestImpact (all 11), consilium_core.tests.test_assistant.TestAuditAndLimits (all 4). |

---

# Phase 6 — Interface

## E23 — Interface shell
*Outcome: the look, feel and behaviour that stakeholders will judge.* Trace:
deck slide 15, stakeholder directives, R-1.

| ID | Story | Size | Status |
|---|---|---|---|
| E23-S1 | As a user, the application has a consistent shell with tabbed navigation. **AC:** home, forums, policies, escalations, reports and administration; breadcrumbs; current location always clear. | M | ✅ Done. `templates/base_portal.html`: Home, Forums, Policies, Escalations, Reports, Admin (each shown only to those who may read it), breadcrumbs, `aria-current`. consilium_core.tests.test_portal_pages.TestEveryRole (all 3); browser journeys `home-loads`, `non-admin-no-admin-nav` |
| E23-S2 | As a user, I switch between a light and a dark theme, and it is remembered. **AC:** switchable from the interface; applied before first paint; persists across sessions. | S | 🟡 Partial. `Consilium.theme` with a pre-paint bootstrap, stored per browser (`cns:theme`); dark tokens asserted in consilium_core.tests.test_branding.TestBrandStyle. **No automated test switches the theme or checks it persists** |
| E23-S3 | As a user, I change the font size on any page and it is remembered. **AC:** a visible control on every page; the whole page scales coherently; persists. | S | 🟡 Partial. `Consilium.fontSize` in the header of every page, stored per browser (`cns:fontsize`). **No automated test** |
| E23-S4 | As a user, every table paginates, sorts, searches and lets me set the page size. **AC:** one shared component; paging and sorting happen server-side so behaviour is correct on large datasets; page size persists. | L | 🟡 Partial. `consilium-table.js` pages, sorts and searches on the server and stores the page size; the `escalation-filters` browser journey checks filtering on it. **No automated test of server-side paging, sorting or the remembered page size** |
| E23-S5 | As a user, the interface is usable by keyboard and with a screen reader. **AC:** full keyboard navigation, visible focus, correct roles and labels, adequate contrast in both themes. | M | 🟡 Partial. Keyboard paths, focus and ARIA; the `help-assistant` journey checks `aria-expanded` and Escape. **Contrast is not measured in either theme** |

## E24 — Screens
*Outcome: the screens people actually use.* Trace: deck slide 15.

| ID | Story | Size | Status |
|---|---|---|---|
| E24-S1 | As a new user, the home page tells me how to use the system. **AC:** guidance on forum types and how to choose one, templates, decision authority and escalation protocols. | M | ✅ Done. `/` reads `Guide Article` (6 published: getting started, forum types, templates, decision authority, escalation protocol, policy lifecycle) and now also shows the forum map. consilium_core.tests.test_w3_guides_core.TestGuideArticlesAreFoundWhereTheAssistantPoints, test_portal_pages.TestAdministrator. |
| E24-S2 | As a governance user, the main table shows the inventory with the specified columns. **AC:** sortable, filterable, searchable, paginated; a row opens the record. | M | ✅ Done. `/forums` on the shared table, with tag filters. governance.tests.test_inventory.TestSearchAndFilter, test_governance_gaps.TestInventoryReads, consilium_core.tests.test_portal_pages. |
| E24-S3 | As a governance user, the forum detail page shows everything about a forum. **AC:** details, membership, linkages, documents, decisions, history; edit is available only with permission. | L | ✅ Done. `/forum` tabs: details, membership, linkages, documents (charter), decisions, escalations, history (revisions, record history). Edit only with write permission (`www/forum.py`). governance.tests.test_governance_gaps.TestPages, consilium_core.tests.test_portal_pages.TestAdministrator.test_record_pages_render_a_real_record, TestReaderWithoutAccess. |
| E24-S4 | As a requester, a guided form walks me through creating a forum. **AC:** explains the process and the review to expect, lists required fields, validates as I go, and saves a draft. | L | ✅ Done. `/create-forum` explains the review, marks required fields, saves a draft. governance.tests.test_formation_portal, test_formation.TestIntake. |
| E24-S5 | As an administrator, an administration area covers users, roles and reference data. **AC:** reachable from the shell; restricted to administrators. | M | ✅ Done. `/admin`, refused server-side to anyone but administrators (`www/admin.py`). consilium_core.tests.test_portal_pages.TestEveryRole.test_administration_pages_refuse_everyone_but_administrators. |

---

# Phase 7 — Deployment

## E25 — Installation and operations
*Outcome: a deployment team with no context can install and run this, offline.*
Trace: the phase 2 success criterion.

| ID | Story | Size | Status |
|---|---|---|---|
| E25-S1 | As a deployer, I install the whole system on an air-gapped server from staged artifacts. **AC:** a documented, scripted install with no network access at any point; the script verifies its own prerequisites and fails clearly when one is missing. | L | ✅ Done. `deploy/make_bundle.py`, `deploy/install.sh`: prerequisites checked before any change; air-gapped Rocky Linux 9 install in 2 min 23 s, health 17/17, 0 network lines in pip's log (DEPLOYMENT-READINESS §1–2; `evidence/linux-rehearsal/20-airgap-proof.txt`, `21-rocky-install.log`) |
| E25-S2 | As a deployer, I install on a managed corporate Windows workstation. **AC:** same scripted path; no compiler, no package manager, no administrator rights beyond what is documented. | M | 🟡 Partial. `deploy/install.ps1`, `scripts/bootstrap.ps1`; toolchain tests (`tests/test_compat.py`, Windows simulated) run on `windows-latest` in CI. **No install has been run on a managed Windows workstation** (E34-S6) |
| E25-S3 | As a deployer, I can confirm the installation is healthy. **AC:** one command checks database, cache, workers, scheduler, assets and permissions and reports pass or fail per check with a remedy for each failure. | M | ✅ Done. `deploy/verify.sh` (one command, 14 checks: every unit active, exactly one scheduler process, web answers, the 17-check `deploy/healthcheck.py` with a remedy per failure, smoke, workflow, PDF, no network, UI sweep with guest refusal per page, no-CDN, TLS, scheduler enabled) wrote READY 14/14 on Rocky 9, fresh and after upgrade (`evidence/linux-rehearsal/23-…`, `66-…`) |
| E25-S4 | As an operator, I can back up and restore. **AC:** documented, scripted, tested by an actual restore into an empty database, not only by taking a backup. | M | ✅ Done. `deploy/backup.sh` (SHA-256 manifest, mode 0600, retention) and `restore.sh`; restored in place (24 s, health 17/17) and into a new empty database on the air-gapped host with identical row counts (`evidence/linux-rehearsal/50-backup-restore.log`, `30-migration-rehearsal.log`, `31-counts-*.txt`) |
| E25-S5 | As an operator, I can upgrade without losing data. **AC:** a documented upgrade path; migrations are reversible or explicitly flagged as not; tested from the previous release. | L | ✅ Done. `deploy/upgrade.sh`, documented in `docs/OPERATIONS.md` and RUNBOOK Phase 3; migrations are explicitly flagged as not reversible (restore the pre-upgrade backup). Upgrade from the previous release (`c2c8a91`) to the working tree on Rocky 9: 1 min 29 s, no table lost a row, verify 14/14 after (`evidence/linux-rehearsal/63-upgrade-run.log`, `65-upgrade-counts-diff.txt`). Rollback printed, not exercised |
| E25-S6 | As a deployer, the database can be either self-installed or provisioned by a database team. **AC:** both paths documented; the provisioned path does not require superuser; both are tested. | M | 🟡 Partial. Both models in `deploy/install.sh` (`superuser`, and `provisioned` with `--no-setup-db` and no superuser on disk); `tests/test_kit.py::test_superuser_provisioning_needs_a_root_password_source`. **Only `superuser` was rehearsed; the provisioned path has never been run** |
| E25-S7 | As an operator, the system produces logs and metrics I can act on. **AC:** structured logs, error reporting, and a documented list of what to watch. | M | 🟡 Partial. `docs/OPERATIONS.md` says what to watch; logs are files and the journal. **No structured logs, nothing collects or alerts** (DEPLOYMENT-READINESS §6) |

## E26 — Quality
*Outcome: confidence that what is claimed to work, works.*

| ID | Story | Size | Status |
|---|---|---|---|
| E26-S1 | As an engineer, every entity has tests covering create, read, update, permissions and validation. **AC:** coverage reported; no entity without tests. | L | 🟡 Partial. 1372 tests; each of the 142 product DocTypes has a test file with shape tests (installed, fields reach the table, readable by someone), behaviour in the module suites. **Coverage is not reported**, and the working tree holds an untracked scratch DocType `consilium_core/doctype/abc` whose test file has no test |
| E26-S2 | As an engineer, every workflow has tests covering the happy path, each rejection path and each permission boundary. **AC:** a test attempts each transition as a role that should not be allowed it. | L | 🟡 Partial. Formation, compliance review, lifecycle, publication and closure refusals are tested by role (governance.tests.test_formation_portal.TestRoleRefusals (all 5), policy.tests.test_portal_actions.TestLifecycleActions (all 8), policy.tests.test_regressions.TestGatesOnEveryRoute (all 3)). **No test attempts every Workflow transition as a role that may not take it** |
| E26-S3 | As an engineer, the main journeys are covered end to end in a browser. **AC:** forum creation through to approval, policy drafting through to publication, escalation raising through to closure. | L | 🟡 Partial. `scripts/browser_journeys.py` drives Chrome through Playwright: 8/8 journeys pass. **The journeys only navigate and read ("It changes nothing"): none takes a forum from creation to approval, a policy from drafting to publication or an escalation from raising to closure in a browser**; those paths are covered server-side by the portal-action tests |
| E26-S4 | As an engineer, automated checks enforce the platform rules. **AC:** checks fail the build on a CDN reference, a network fetch at run time, a compiler-requiring dependency, or client-identifying content. | M | ✅ Done. `scripts/check_platform_rules.py`: no CDN, no package manager, vendored checksums, no client-identifying content, no state names in conditionals, every dependency a wheel; 6/6, first CI job; `verify.sh` also proves no network at install |
| E26-S5 | As an engineer, the system is exercised with realistic data volumes. **AC:** seeded with a volume representative of the real inventory; list, search and dashboard response times recorded. | M | 🟡 Partial. `scripts/load_test.py` recorded p50/p95/p99 for 11 portal pages and 5 API calls at 1–25 threads, 0 errors (DEPLOYMENT-READINESS §7). **The data is the demonstration set (14 forums, 15 documents, 15 matters), not a representative volume, and the host was an emulated laptop**; see E34-S3 |

---

# Phase 8 — Gaps not in the original backlog

Work that has been done, is being done, or measurably must be done, and that no
story above describes. Found by the requirements coverage measurement
(`REQUIREMENTS-COVERAGE.md`) and by loading realistic demonstration data.

**The final wave (2026-09-18)** built the workstreams WS1–WS7 and wave 3. That
covered:

- E7-S4 sequential approvals;
- E6-S3, E11-S2, E11-S5, E8-S5, E5-S5, E3-S2, E15-S5 and E4-S2;
- all of E33;
- the deployment-readiness rehearsal (E34).

Every story below is measured against the result. What is still missing is in
bold in its note.

## E27 — Portal write paths
*Outcome: the policy and escalation screens act, not only show. The backend
existed; until now every write happened on the desk, and some had no entry
point at all.* Trace: CS-6…CS-9, P-8, P-9, P-16, P-19, P-26, E-5, E-8, E-10.

| ID | Story | Size | Status |
|---|---|---|---|
| E27-S1 | As the governance office, I work formation requests and forum compliance reviews on the portal. **AC:** `/formation-requests`, `/formation-request` and `/forum-review` offer each formation and compliance action of E7 and E8 only to the role and stage that allow it; a refusal is audited. | M | ✅ Done. `formation.*` endpoints (including charter challenge and in-turn step decisions), `lifecycle.record_compliance_review`, and the annual review panel. governance.tests.test_formation_portal (all 10 classes, 34 tests, including TestRoleRefusals and TestStageRefusals), test_wave3_governance.TestCharterChallengeOnTheRequest. |
| E27-S2 | As a drafter or approver, I move a document through its lifecycle from `/policy`. **AC:** the buttons offered are the Workflow actions open to me in the current state; each goes through the gated route; a refusal names the failing gate. | M | ✅ Done. `lifecycle.document_actions` and `take_action` (POST only) on `/policy`. policy.test_portal_actions.TestLifecycleActions (all 8), policy.test_wave3_policy.TestTransitionIsPostOnly |
| E27-S3 | As a policy owner, I raise approval steps and approvers decide them from `/policy`. **AC:** steps come from the resolved route and are shown before submission; only the assignee or a delegate decides; bypass needs an exception authorisation. | M | ✅ Done. `routing.raise_steps`, `decide_step` and `bypass_step` on `/policy`; the planned steps are shown first; the sequential order is held back on screen; approvers and the owner are told through the `policy.approval.requested`, `decided` and `bypassed` templates. test_portal_actions.TestApprovalChain (all 15), policy.test_wave3_policy.TestDocumentStepOrder |
| E27-S4 | As a policy owner, I upload a new body version and revert to an earlier one from `/policy`. **AC:** upload only while editable; revert writes a new version with a required reason. | M | ✅ Done. `publication.upload_new_version` and `revert_version` on `/policy`. test_portal_actions.TestVersions (all 9), policy.test_wave3_policy.TestRevertLeavesTheLifecycleAlone |
| E27-S5 | As the policy office, I publish from `/policy`. **AC:** the audience is previewed first; publishing records the publication and notifies the audience; a publication can be withdrawn. | M | ✅ Done. `publication.audience_preview`, `publish_record` and `withdraw_publication` on `/policy`. test_portal_actions.TestPublication (all 7) |
| E27-S6 | As a policy owner, I open and conclude review cycles and record horizon scans from `/policy`. **AC:** a cycle opens and concludes with an outcome; a scan records its sources, areas and impact. | M | ✅ Done. `horizon.open_review`, `conclude_review` and `record_scan` on `/policy`. test_portal_actions.TestReviewsAndScans (all 7) |
| E27-S7 | As a requester, I raise a policy intake and see it classified on `/policy-intake`. **AC:** answers produce a classification showing the rule that fired; I can challenge it; the office can override with a justification and create the document. | L | ✅ Done. `/policy-intake`, linked from `/policies`: `intake.raise_request`, `classify_request`, `challenge_request`, `override_request`, `create_from_request` and `withdraw_request`. test_portal_actions.TestIntake (all 12), TestPages.test_the_intake_page_renders |
| E27-S8 | As the policy office, I record monitoring results and violations from `/policy`. **AC:** a result advances its activity; a violation links to the document and optionally an escalation. | S | 🟡 Partial. `monitoring.record_result` (which advances `next_due_on`), `log_violation` and `update_violation` work on `/policy`. test_portal_actions.TestMonitoring (all 8), policy.test_wave3.TestViolationTransitions. **The optional escalation link cannot be set from `/policy`:** `log_violation` takes no escalation argument, so it is set on the desk only. |
| E27-S9 | As an escalation owner, I raise a matter on `/raise-escalation`. **AC:** the type selects the template; required fields apply by template and severity; the matrix proposes the pathway. | M | ✅ Done. `/raise-escalation`; `templates.intake_options`, `template_requirements`, `routing.propose_pathway`, `raise_escalation` (POST). escalation.tests.test_portal_actions.TestRaise (all 6). |
| E27-S10 | As an escalation owner, I work a matter on `/escalation`. **AC:** status changes, action plans, review rounds and closure are offered only where the state and my role allow; closure criteria are enforced; a sensitive matter stays invisible to others. | L | ✅ Done. `/escalation` workbench from `resolution.get_matter_workbench`; `move_matter_status`, `add_action_plan`, `update_action_plan`, `record_review_round`, `record_matter_closure`, `close_matter` re-check stage and role on the server. escalation.tests.test_portal_actions.TestWorkbench (all 3), TestStatus (all 4), TestActionPlans (all 4), TestReviewRounds (all 5), TestClosure (all 4), TestSensitiveMatter (all 3). |
| E27-S11 | As an accountable executive, I request and decide a risk acceptance approval on the portal. **AC:** the acceptance takes effect only after an approving decision by the assignee. | M | ✅ Done. `approvals.request_risk_acceptance_approval` and `decide_risk_acceptance` from `/escalation`; four eyes, approver role, clearance for sensitive matters; decisions waiting also listed on `/escalations`. escalation.tests.test_portal_actions.TestRiskAcceptanceApproval (all 9). |
| E27-S12 | As an escalation owner, I accept or change the proposed pathway. **AC:** only active forums; each change recorded. | S | ✅ Done. `routing.propose_pathway`, `set_pathway` from `/escalation`; inactive forums refused; a matrix-routed forum cannot be removed; each save is versioned (`revision.snapshot`, change tracking). escalation.tests.test_portal_actions.TestPathway (all 4). |

## E28 — Work queues and oversight screens
*Outcome: people see what is waiting on them, and the office sees where
coverage and campaigns stand.* Trace: CS-10, CS-11, G-10, G-19, P-20, P-23, E-19, O-3.

| ID | Story | Size | Status |
|---|---|---|---|
| E28-S1 | As any user, I see and act on everything waiting on me in one inbox (CS-10). **AC:** attestations, second signatures, approval steps, remediation tasks and returned requests in one list, most urgent first, each read through permissions; respond and second-sign from the list. | L | ✅ Done. `/tasks`; `inbox.my_tasks` gathers attestations, second signatures, approval and formation steps, returned requests, remediation tasks and queue items, read through permissions; answer and second-sign in place. consilium_core.tests.test_inbox.TestInboxAttestation (all 8), TestSecondSignature (all 3), TestInboxApprovalsAndReadRules (all 3), TestCountAndAccess (all 3) |
| E28-S2 | As a campaign owner, I administer attestation campaigns. **AC:** open the annual forum campaigns, generate tasks, see completion, and see the records a campaign could not ask about. | M | ✅ Done. `/attestation-campaigns`; `reviews.open_forum_campaign`, `attestation.generate_campaign_tasks`, `campaign_overview`, unconfigured records named. consilium_core.tests.test_inbox.TestCampaignAdministration (all 5) |
| E28-S3 | As an administrator, I review an import batch before it commits (CS-11). **AC:** upload against a profile; rows with errors shown; exclude and revalidate; commit or discard; nothing is written before commit. | L | ✅ Done. `/imports`; `importing.upload_batch`, `get_batch_review`, `exclude_row`, `revalidate_batch`, `commit_reviewed_batch`, `discard_batch` (POST only). consilium_core.tests.test_imports_portal.TestUpload (all 5), TestReview (all 7), TestDiscard (all 1), TestMethods (all 1) |
| E28-S4 | As a governance user, I see where forum coverage has gaps (O-3). **AC:** risk category by organisation matrix with empty cells highlighted, counting only forums I may see. | M | ✅ Done. `/reports#coverage`: risk category by operating group, counted over the permission-checked REST list, empty cells highlighted; the same gaps listed on `/governance-gaps` (`ai/gaps.coverage_gaps`). consilium_core.tests.test_ai_features.TestGaps.test_forum_policy_regulatory_and_coverage_gaps_are_found (a gap shown or hidden by what the viewer may read). The in-browser matrix itself is checked only by the render sweep |

## E29 — Notification delivery, reminders and service levels
*Outcome: notifications reach people, reminders go out on time, and a clock
warns before it breaches.* Trace: G-14, P-6, P-7, P-10, P-11, P-14, E-7, E-9, E-11, E-13, E-17, O-4, O-7.

| ID | Story | Size | Status |
|---|---|---|---|
| E29-S1 | As a recipient, I receive notifications by email. **AC:** an email adapter over the framework's mail queue; the channel reports itself unavailable with no outgoing account; a refused recipient is recorded as suppressed; failures retry. | M | ✅ Done. `email` adapter over the framework mail queue; unavailable with no outgoing account (falls back to RECORD); opted-out or disabled recipients recorded as suppressed; hourly `notification.retry_failed`. consilium_core.tests.test_notification_templates.TestEventApi (all 10), TestEmailRetry (all 3). Real SMTP is unexercised (needs the target) |
| E29-S2 | As an administrator, I edit notification wording without a deployment. **AC:** a template per event and channel with record fields; a broken template is refused at save; callers raise events, not text. | M | ✅ Done. `Notification Template` per event and channel (49 seeded), Jinja with record fields; a template that does not parse or reaches for internals is refused at save; every caller raises an event through `notification.notify`, the policy approval-step and disbandment approval notices included. TestEventApi (all 10), TestTemplateFailures (all 5), TestTemplatePermissions (all 2), TestSeeding (all 2) |
| E29-S3 | As an owner, I am reminded before and when things fall due. **AC:** daily and hourly jobs remind document reviews (P-10), monitoring (P-11), risk-acceptance reassessment (E-9), periodic submissions (E-11), forum overdue reviews and action plans; each reminder is logged once per due date. | L | ✅ Done. `consilium_core/reminders.py` (`reminders.daily`, `reminders.hourly` in hooks.py): document reviews, review cycles, monitoring, risk-acceptance reassessment and end dates, periodic returns, forum annual reviews, action plans; `Reminder Log` unique key, escalation to approver or executive where defined. consilium_core.tests.test_reminders (TestDocumentReviewReminders (all 9), TestMonitoringReminders (all 2), TestEscalationReminders (all 6), TestForumReviewReminders (all 1), TestReminderLog (all 2)) |
| E29-S4 | As a manager, a clock warns me before it breaches and measures time in each state (P-7, E-13). **AC:** a warning at the configured percentage; time-in-state and time-to-first-action measures; clocks on policy lifecycle steps. | M | 🟡 Partial. `consilium_core/sla.py`: warning at `warning_threshold_pct`, time in state, clocks on governing-document lifecycle steps; time in each status shown on `/escalation` and `/reports`. consilium_core.tests.test_sla_measures (TestWarningsAndBreaches (all 7), TestTimeInState (all 8), TestGoverningDocumentSteps (all 1), TestTimeToFirstAction (all 1)). **Time To First Action is measured but not shown anywhere, and no SLA Definition on the demo site uses it** |
| E29-S5 | As a document or forum owner, I am told when a regulatory requirement I cite changes (P-6, O-7). **AC:** a change to a `Regulatory Requirement` notifies the owners of every document and forum citing it. | M | ✅ Done. The `Regulatory Requirement` controller notifies the owners of every in-force document and active forum citing it, on a substantive change. consilium_core.tests.test_regulatory_change.TestRegulatoryChangeFanOut (all 6), consilium_core.tests.test_ai_features.TestRegulatory.test_recording_a_change_saves_through_the_controller_and_its_fan_out |
| E29-S6 | As a committee secretary, I am told when an escalation names my forum on its pathway (E-7). **AC:** breach and material-entity notices reach the secretary, chair and attesting members of each pathway forum, from membership as at today. | S | ✅ Done. `routing.forum_participants` resolves chair, secretary and attesting seats (and live delegates) as at today; `resolution.breach_recipients` includes them and stamps `notified_on`; "Who a notice reaches" on `/escalation`. escalation.tests.test_participants.TestPathwayParticipants (all 5). |

## E30 — Record integrity and handling
*Outcome: history can be restored, restricted documents stay restricted, and
document language follows the rules.* Trace: G-9, E-12, P-1, P-13, P-15, P-19, P-24, P-25.

| ID | Story | Size | Status |
|---|---|---|---|
| E30-S1 | As a record owner, I revert a forum or an escalation to an earlier revision (G-9, E-12). **AC:** every save keeps a revision; revert writes a new revision with a required reason; offered from the history on `/forum` and `/escalation`. | M | ✅ Done. `consilium_core/revision.py` `snapshot` is registered as `on_update` for Governance Forum and Escalation Matter. `revision.history` and `revert` are called from the revision panels on `/forum` and `/escalation`. consilium_core.test_revision.TestMatterRevision, TestForumRevision (demo: FRM-2026-00010 reverted) |
| E30-S2 | As a security reviewer, confidential and restricted documents are enforced, not only flagged (P-1, P-13, P-19). **AC:** read, list, download, print and share are refused per the handling flags on every path, attachments included; tests go through the API. | L | ✅ Done. `policy/handling.py` is registered in `hooks.py` (`has_permission` and `permission_query_conditions` for Governing Document and Document Version; `File.before_insert`). policy.test_handling.TestVisibility, TestActions, TestHandlingChanges, TestVersionHooks |
| E30-S3 | As a reader, I view a document in the portal without downloading it. **AC:** the current version body renders in a view-only page; download and print are offered only where the flags allow. | M | ✅ Done. `/document-view` and `handling.version_body` (inline, `no-store`, watermark on Restricted), linked from the version table on `/policy`. test_handling.TestViewerPage, TestVersionBody |
| E30-S4 | As the policy office, document names follow the template's naming convention (P-15). **AC:** the name is checked against the pattern at save and at intake, with the expected form in the message. | S | ✅ Done. `policy/naming.py`. policy.test_naming_glossary.TestNamingPattern, TestNamingEnforcement |
| E30-S5 | As the policy office, only approved glossary terms are used (P-24). **AC:** text is checked against terms marked for enforcement and their synonyms; definitions are shown in context. | M | ✅ Done. The enforcement validator runs on save and on upload; `glossary.in_context` feeds `/policy` and `/document-view`. test_naming_glossary.TestGlossaryEnforcement, policy.test_wave3.TestGlossaryOnThePage |
| E30-S6 | As a compliance officer, no route publishes past a failing gate (P-25). **AC:** the desk Workflow menu, a direct write and the lifecycle action are all refused; a written exception still works. | S | ✅ Done. `GoverningDocument.validate` runs the gates on every phase change. policy.test_regressions.TestGatesOnEveryRoute |

## E31 — Product identity, scope and help
*Outcome: the portal carries the deploying organisation's brand, shows only
what is in scope, and explains itself.* Trace: stakeholder directives, O-1.

| ID | Story | Size | Status |
|---|---|---|---|
| E31-S1 | As a deploying organisation, I brand the portal as our own. **AC:** name, logo, colours, typeface and banner are data on one record and reach the portal and the framework's sign-in, workspace and browser tab; no brand is committed to the repository. | M | ✅ Done. `Portal Branding` and `consilium_core/branding.py` (after-migrate, template methods) carry name, logo, colours, typeface and banner to the portal and the framework's sign-in, workspace and tab. consilium_core.tests.test_branding.TestGetBrand (all 6), TestBrandStyle (all 5), TestFrameworkBranding (all 5), TestAssetUrl (all 3) |
| E31-S2 | As a user, I never see the underlying framework's name. **AC:** no framework name or logo on any page or on sign-in. | S | ✅ Done. `branding.apply_framework_branding` sets every framework fallback. consilium_core.tests.test_branding.TestFrameworkBranding (all 5); `scripts/ui_regression.py` framework-branding check (274 passed) |
| E31-S3 | As an everyday user, I see only what this platform is for. **AC:** out-of-scope framework modules, workspaces and website pages are hidden or redirected; the platform administrator keeps them. | M | ✅ Done. `consilium_core/scope.py` (workspaces by role, module profile that blocks out-of-scope modules for new everyday users) and `website_redirects` in `hooks.py`. consilium_core.tests.test_scope.TestWorkspaces (all 6), TestModuleProfile (all 5), TestWebsiteRedirects (all 4) |
| E31-S4 | As a user, I ask the portal how to do something here. **AC:** built-in offline answers per page and permission; never reveals a record I cannot read; every question logged append-only with an hourly limit; an optional AI endpoint, off by default, falls back to the built-in answer. | L | ✅ Done. `consilium_core/assistant/`: built-in offline answers per page and permission, append-only question log with an hourly limit, optional endpoint off by default with fallback. consilium_core.tests.test_assistant (TestBuiltInAnswers (all 12), TestRecordAwareness (all 6), TestAdminDocumentation (all 2), TestAuditAndLimits (all 4), TestSettings (all 4), TestAIMode (all 8)); browser journey `help-assistant` |

## E32 — Verification and demonstration
*Outcome: evidence that the product works on realistic data, and guides for
the people who use and run it.*

| ID | Story | Size | Status |
|---|---|---|---|
| E32-S1 | As an engineer, defects found by loading realistic data are fixed and pinned. **AC:** each defect has a test that failed before the fix. | M | ✅ Done. Defects fixed and pinned: governance, escalation and policy `test_regressions.py` (e.g. governance.tests.test_regressions.TestOverdueReviews, policy.tests.test_regressions.TestReopening), consilium_core.tests.test_attestation.TestUnconfiguredRecordsDoNotStopACampaign (all 3) |
| E32-S2 | As an engineer, tests run on a site that holds no demonstration data. **AC:** a separate site and database with tests allowed. | S | ✅ Done. `consilium-test.localhost` with its own database (`consilium_test`, `allow_tests`); the demo site holds no test rows |
| E32-S3 | As an engineer, a sweep catches a screen that no longer renders. **AC:** every portal page renders for an administrator and refuses a guest; links and assets resolve; every entity list reads; scripts parse; no framework branding. | M | ✅ Done. `scripts/ui_regression.py`: 274 passed, 0 failed on the final demo site; also run inside `verify.sh` |
| E32-S4 | As a demonstrator, the system is loaded with realistic, generic data. **AC:** an idempotent loader; every requirement has a demonstration record; generic personas only. | M | ✅ Done. `deploy/demo_data.py`, idempotent, generic `@demo.example` personas; 14 forums, 15 governing documents, 15 matters, 67 meetings on the demo site; `deploy/demo_logins.py` issues random per-run passwords into a file it refuses to write inside the repository; the platform-rules sanitization check |
| E32-S5 | As a user or administrator, I have a guide. **AC:** task-based guides for both audiences, matching the screens. | M | ✅ Done. `docs/USER-GUIDE.md`, `docs/ADMIN-GUIDE.md` and twelve task-based chapters in `docs/guides/` (getting started to troubleshooting, incl. configuring workflows), built to PDF and DOCX by `scripts/build_guides.sh` outside the repository; shipped to the help assistant by the bundle |
| E32-S6 | As an engineer, the suite tests every portal page. **AC:** a page-context test per `www` page: renders, shows its key sections, refuses a reader without access. | M | ✅ Done. consilium_core.tests.test_portal_pages: TestEveryPageIsCovered (all 1), TestAdministrator (all 3), TestSignedOutVisitor (all 2), TestEveryRole (all 3), TestReaderWithoutAccess (all 2), TestAddressValuesAreEscaped (all 1) — every `www` page renders its key sections and refuses a reader without access |

## E33 — Other measured gaps
*Outcome: the remaining gaps the coverage measurement found, with no story.*
Trace: `REQUIREMENTS-COVERAGE.md` §4.

| ID | Story | Size | Status |
|---|---|---|---|
| E33-S1 | As the governance office, an unresolved charter challenge blocks formation approval (G-7). **AC:** the challenge is recorded on `/formation-request` and is an approval blocker until cleared. | S | ✅ Done. `formation.approval_blockers` includes `charters.uncleared_challenges`. Recorded on `/formation-request` through `charters.record_charter_challenge` (office only). It also blocks a favourable compliance decision. CFR-2026-00002 is held by CHT-2026-00014. governance.tests.test_governance_gaps.TestFormationCharterGate, TestStandingGate, test_wave3_governance.TestCharterChallengeOnTheRequest. |
| E33-S2 | As a committee secretary, I take a new charter version from a screen (G-15). **AC:** as minutes: a new version with a change summary. | S | ✅ Done. `/forum` Documents tab, "Take a new version" (`charters.publish_charter_version`: summary and body required, only a file attached to that charter, reopens the challenge; readers refused and audited). governance.tests.test_governance_gaps.TestCharterPortal. |
| E33-S3 | As a forum member, the forum page lists the escalations on its pathway (O-5). **AC:** a section on `/forum`, ~~sensitive matters excluded~~ sensitive matters shown only to viewers cleared to read them and never counted for others. *Revised 2026-09-18: excluding them for everyone would hide from the forum's own cleared members a matter the forum is deciding.* | S | ✅ Done. Escalations tab on `/forum` (`inventory.forum_escalations`, read through the permitted list). FRM-2026-00006 lists 8 matters, including sensitive ESC-2026-00003/00004 for cleared readers. governance.tests.test_governance_gaps.TestForumEscalations. |
| E33-S4 | As a user, the home page shows the enterprise forum map (O-2). **AC:** the interconnectivity graph for all forums on `/`. | M | ✅ Done. `inventory.forum_map` drawn on `/` (links only where both ends are readable). governance.tests.test_governance_gaps.TestInventoryReads.test_the_map_draws_what_the_viewer_may_see, TestPages.test_the_pages_render_with_their_new_sections. |
| E33-S5 | As the policy office, `/reports` covers document families, monitoring outcomes, exceptions and violations, with export (P-4, P-12, P-22). **AC:** each section permission-filtered and exportable. | M | ✅ Done. `reporting.policy_sections` (families, monitoring, exceptions, violations and dispositions over `get_list`) and `reporting.export` (server-side CSV, formulas neutralised) on `/reports`. policy.test_wave3.TestReporting (all 3) |
| E33-S6 | As an escalation manager, matters are assigned by role or group through configurable transitions (E-5, E-8). **AC:** transitions and assignment rules are configuration per type and severity. | L | 🟡 Partial. Assignment is configuration per type and severity: the matrix rule's `route_to_role` and `route_to_group` queue the matter, the queue is told, and a member takes it on `/escalation` (`assignment.take_ownership`). escalation.tests.test_assignment_and_timing.TestAssignmentByGroup (all 10), TestAssignmentByRole (all 1). **Transitions are not configuration per type and severity: any open state may be reached from any other by the stage's role.** |
| E33-S7 | As a risk manager, systemic matters route to the head of enterprise risk and second-line challenge runs to a service level (E-9). **AC:** a routing rule or role for systemic matters; a clock started when a review round opens. | M | ✅ Done. Matrix rule on `systemic` (demo R05-SYSTEMIC to role Head of Risk Governance and the higher forums); Time In State definition on `requires_review` scoped to systemic matters starts when the matter goes to the second line and stamps the review round (demo SLAC-00020 on ESC-2026-00015). escalation.tests.test_assignment_and_timing.TestSystemicRoute (all 2), TestChallengeServiceLevel (all 3). |
| E33-S8 | As a drafter, a review ends in a recorded disposition and I am told (P-26). **AC:** a disposition record per review round, notifying the originator. | M | ✅ Done. `Document Disposition` is written from `on_update` ("Review Returned" or "Review Accepted"), and the originator is told through `policy.review.disposition`. PDSP-00001…12 are on the demo. policy.test_wave3.TestReviewerReturn (all 4). Known limit: the reviewer's return works on the portal, not the desk |

---

# Phase 9 — Deployment readiness

Non-feature work that stands between a working build and go-live. None of it
blocks building; all of it blocks going live.

## E34 — Deployment readiness
*Outcome: evidence, gathered on the target, that the system installs, upgrades,
performs and runs unattended.* Trace: the phase 2 success criterion;
`DEPLOYMENT-READINESS.md`.

| ID | Story | Size | Status |
|---|---|---|---|
| E34-S1 | As a deployer, I rehearse install and migration on a target server. **AC:** install and migrate on the target operating system and database server; the full suite and the health check pass; any database divergence is recorded and fixed. | L | 🟡 Partial. Rehearsed on a stand-in: air-gapped Rocky Linux 9 with PostgreSQL 16; install, health 17/17, verify 14/14; the demo site's backup restored and migrated with identical counts and a 239-page UI sweep (DEPLOYMENT-READINESS §2, §4). **Not run on the target operating system or its own database server; the full app suite was not run on the rehearsal host; RHEL 8 and Ubuntu 22.04 not rehearsed; the bundle must be rebuilt from the final commit and installed again** |
| E34-S2 | As an operator, I rehearse an upgrade from the previous release. **AC:** closes E25-S5. | M | 🟡 Partial. Upgrade from the previous release (`c2c8a91`) rehearsed on Rocky 9 with `upgrade.sh`: no table lost a row, verify 14/14 after (DEPLOYMENT-READINESS §5). **Stand-in only; rollback never exercised; the release upgraded to was the working tree of that moment, not the final commit** |
| E34-S3 | As an operator, I know how the system performs at representative volume. **AC:** list, search and dashboard response times recorded at a volume agreed with the business; closes E26-S5. | M | 🟡 Partial. `scripts/load_test.py`, indicative only: 16 requests at 1–25 threads, 0 errors, throughput flat from 5 threads on one process (DEPLOYMENT-READINESS §7). **Volume not agreed with the business; demonstration data on an emulated laptop; real numbers need the target with several web processes** |
| E34-S4 | As a deployer, certificates, ports and service accounts are decided and the services are defined. **AC:** documented decisions; systemd units and Windows service definitions that restart on failure. | M | 🟡 Partial. Decisions written in `docs/OPERATIONS.md` (certificates, ports, service accounts); systemd units in `deploy/service/systemd/` with `Restart` and hardening, `systemd-analyze verify` clean and run on Rocky 9; nginx and Caddy TLS templates; tests/test_kit.py unit and proxy template tests. **The organisation's CA, names and firewall decisions are open; `deploy/service/windows/register-services.ps1` has never been run** |
| E34-S5 | As an administrator, people sign in through the corporate directory. **AC:** the protocol is decided (LDAP and OIDC are configuration; SAML is a separate build); existing users matched without re-keying; closes E2-S4. | L | 🟡 Partial. OIDC proven end to end against a mock provider on the stand-in, existing user matched without re-keying (E2-S4); LDAP is configuration (`[sso] mode = ldap`, pure-Python `ldap3`), not exercised. **No corporate identity provider or directory connected; protocol choice, redirect-URI registration and claims need the target** |
| E34-S6 | As a deployer, the system runs on a managed Windows workstation. **AC:** the scripted install, the suite and the health check pass there; closes E25-S2. | M | ⬜ Not started. `deploy/install.ps1`, `register-services.ps1` and the RUNBOOK Windows acceptance script exist; Windows is only simulated (`tests/test_compat.py`, CI `windows-latest` toolchain job). **Nothing has been installed or run on a Windows workstation** |
| E34-S7 | As an operator, scheduled work runs on a real deployment. **AC:** exactly one scheduler process; every Consilium job shows a last execution; the SLA sweep, breach escalation and reminders observed once. | S | 🟡 Partial. On the Rocky 9 stand-in under systemd: one scheduler process; all 11 Consilium jobs (incl. `sla.sweep`, `resolution.sweep_breaches`, `reminders.daily`, `reminders.hourly`) made due and each run exactly once by two workers (`evidence/linux-rehearsal/24-scheduler-workers.txt`); `install.sh` enables the scheduler. **Not observed on a real deployment over a real day; the scheduler is still disabled on the demo site** |

---

# Status

The measured status of every story is in its table, and the counts are in
[Status at a glance](#status-at-a-glance) at the top. A story is **done** only
under the definition of done — which includes having been exercised against a
running system, not only unit tested.

**Acceptance criteria revised 2026-09-18.** Each revision keeps the original
wording struck through beside the new criterion, and the story was re-judged
against the new one:

- **E2-S2**: no "approver" role; approval is assigned per route step. ✅
- **E2-S4**: SAML dropped; OIDC/OAuth or LDAP. ✅. OIDC is proven end to end
  against a mock provider; the real directory is E34-S5.
- **E5-S5**: disposal is never automatic. The daily job flags records past
  retention for a named approver, and held records are flagged as held. 🟡:
  carrying out an approved disposal has no screen.
- **E17-S3**: the configured states, driven by semantic flags. ✅
- **E21-S2**: review and discard before commit; a compensating import instead
  of rollback. ✅
- **E22**: an offline-first assistant plus AI features on an optional
  endpoint. Three stories ✅; E22-S2 (summarise a long record) 🟡.
- **E33-S3**: sensitive matters on a forum's Escalations tab are shown to
  cleared readers and never counted for others, rather than excluded for
  everyone. ✅

**Known gaps still open at release 1.0.0:**

- A reviewer's "Return to Drafting" fails on the desk; the portal works.
- Voting has no attendance entry: presence for quorum is taken from ballots
  cast.
- Time To First Action is measured but not shown.
- No real Windows run.
- No RHEL 8 or Ubuntu 22.04 rehearsal.
- Python 3.11 on x86_64 is required: the framework's `hiredis` pin blocks
  3.12, and `psutil` blocks ARM.
- Real certificates, the identity provider, SMTP and load testing need the
  target environment.
- The offline bundle must be rebuilt from the final commit.
