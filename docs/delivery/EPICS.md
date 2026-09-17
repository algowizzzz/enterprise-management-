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

| ID | Story | Size |
|---|---|---|
| E1-S1 | As an engineer, I have an application skeleton with four modules so that code has an obvious home. **AC:** app installs into a site; modules are `Consilium Core`, `Governance`, `Policy`, `Escalation`; module names do not collide with framework-owned names. | S |
| E1-S2 | As an engineer, I generate DocTypes from short specs so that every entity follows the same conventions. **AC:** a spec file produces DocType JSON, a controller and a test; the generator rejects a spec that declares a framework-maintained field, names a link target that does not exist, or has a duplicate field name. | M |
| E1-S3 | As an engineer, I have vendored front-end libraries with recorded checksums so the application installs with no internet access. **AC:** no CDN reference anywhere in the served HTML; a checksum file covers every vendored file; a test fails if a served page references an external host. | S |
| E1-S4 | As an engineer, the test suite runs against a real database so that tests exercise the schema rather than a mock. **AC:** one command runs the suite; the suite creates and tears down its own fixtures. | M |
| E1-S5 | As an engineer, continuous checks run on every change so regressions surface immediately. **AC:** lint, format, type check and tests run in one command and in CI; the air-gap rule and the sanitization rule are enforced by automated checks, not by convention. | M |

## E2 — Identity, roles and access
*Outcome: people can sign in, and what they can see and do is governed by role.*
Trace: G-13, P-13, E-16, D-3.

| ID | Story | Size |
|---|---|---|
| E2-S1 | As an administrator, I manage users in the application so the system works before any directory integration exists. **AC:** create, deactivate and reactivate users; deactivated users cannot sign in but remain linked to their historical records. | S |
| E2-S2 | As an administrator, I assign access roles so that permissions follow the role, not the person. **AC:** the role set covers administrator, taxonomy administrator, forum owner, committee secretary, reviewer, approver, compliance reviewer, policy owner, escalation owner and read-only viewer; each is enforced server-side. | M |
| E2-S3 | As a security reviewer, I see that restricted records are visible only to authorised users. **AC:** a record marked restricted is excluded from list views, search, reports and the API for users without the right; a test asserts the API path, not only the UI. | M |
| E2-S4 | As an administrator, I can enable single sign-on later without re-mapping existing records. **AC:** an identity provider can be configured for LDAP or OIDC/SAML; an existing user is matched to a directory identity without changing the record's key; the feature is off by default. | L |
| E2-S5 | As an auditor, I can see who held which role and when. **AC:** role grants and revocations are recorded with actor and timestamp and survive the user being deactivated. | M |

## E3 — Taxonomy and reference data
*Outcome: the shared vocabulary every module tags against, maintained by an
administrator rather than by a developer.* Trace: G-3, P-3, E-3, D-12.

| ID | Story | Size |
|---|---|---|
| E3-S1 | As a taxonomy administrator, I maintain each reference list in the application. **AC:** risk category, legal entity, organisation unit, jurisdiction, forum type, governing document type, escalation type and horizon scanning coverage area are all maintainable; each value has a stable code, a name, a description and an active flag. | M |
| E3-S2 | As a taxonomy administrator, I retire a value without breaking history. **AC:** an inactive value no longer appears in pickers for new records but still displays correctly on existing ones; a test covers a record created before retirement. | S |
| E3-S3 | As a taxonomy administrator, I maintain hierarchical taxonomies as trees. **AC:** risk category, organisation unit and jurisdiction support parent/child; a tree view is available; a value cannot be its own ancestor. | M |
| E3-S4 | As a taxonomy administrator, I load values in bulk from a file. **AC:** CSV import creates and updates values, reports per-row errors without partially applying a failed file, and records who imported what and when. | M |
| E3-S5 | As an engineer, taxonomy values are referenced consistently everywhere. **AC:** every tagging field across all three modules links to these DocTypes; no module defines its own copy of a shared list. | S |

## E4 — Audit, evidence and history
*Outcome: the record of who did what, which is the reason this system exists.*
Trace: G-9, P-9, E-12, D-4.

| ID | Story | Size |
|---|---|---|
| E4-S1 | As an auditor, every change to a governed record is recorded with actor, timestamp and before/after values. **AC:** change history is on for all governed entities; it cannot be switched off per record; a test asserts a field change produces an entry. | S |
| E4-S2 | As an auditor, I can read a record's full history in one place, in plain language. **AC:** a history view shows field changes, workflow transitions, comments, attachments and notifications in one chronological list. | M |
| E4-S3 | As a record owner, I can revert a record to a previous version. **AC:** reverting writes a **new** version rather than mutating history; the revert itself is recorded with actor, timestamp, source version and a required reason; a test asserts the prior versions still exist afterwards. | L |
| E4-S4 | As an auditor, I can export a record's evidence pack. **AC:** a single export contains the record, its history, its attachments and its approvals, in a form that can be handed to a reviewer. | M |

## E5 — Document handling, versioning and retention
*Outcome: documents are held, versioned and retained by us.* Trace: G-15, G-16,
P-17, P-18, E-11, D-2, D-9.

| ID | Story | Size |
|---|---|---|
| E5-S1 | As a user, I attach documents to a record. **AC:** attach, replace and remove; file type and size are validated; every action is audited. | S |
| E5-S2 | As a policy owner, I upload a new version of a document and the prior version is preserved. **AC:** versions are ordered and immutable; each carries who uploaded it and when; the current version is unambiguous. | M |
| E5-S3 | As a compliance officer, retained records cannot be altered or deleted before their retention period expires. **AC:** a retention class sets the period; deletion and modification are refused with a clear reason while a record is under retention; the refusal is audited. | L |
| E5-S4 | As a compliance officer, I can place and lift a legal hold that overrides scheduled disposal. **AC:** a held record is never disposed of regardless of its retention period; placing and lifting a hold requires authorisation and is audited. | M |
| E5-S5 | As a compliance officer, records past their retention period are disposed of on a defined schedule, with a certificate of what was disposed. **AC:** disposal runs on a schedule, skips held records, and writes a disposal record that survives the disposal. | L |

---

# Phase 2 — Governance forums

## E6 — Forum inventory
*Outcome: the single inventory that the whole platform depends on.* Trace: G-1,
G-2, G-3, G-4, G-19.

| ID | Story | Size |
|---|---|---|
| E6-S1 | As a governance user, I maintain a forum record with its identifying and ownership details. **AC:** all specified fields are present; required fields are enforced; the record is searchable by name and code. | M |
| E6-S2 | As a governance user, I tag a forum against the shared taxonomies. **AC:** business unit, risk type, legal entity and jurisdiction accept **multiple** values; primary risk category and owning organisation accept one; a test covers both shapes. | M |
| E6-S3 | As a governance user, I search and filter the inventory. **AC:** filter by any tagged dimension and by status; free-text search across name, code and mandate; results paginate, sort and respect permissions. | M |
| E6-S4 | As a governance user, I map a forum to related forums. **AC:** parent, sub-forum, upstream and downstream relationships; a forum cannot be its own ancestor; the inverse relationship is visible from the other side. | M |
| E6-S5 | As a governance user, I record that a forum is regulatory-required and cite the requirement. **AC:** a flag with dependent fields that become required when set. | S |
| E6-S6 | As a user of another module, I can select a forum from authoritative data. **AC:** policy and escalation records link to forums directly; no copy of forum data exists in those modules. | S |

## E7 — Committee formation
*Outcome: a request to stand up a forum, evaluated and approved on the record.*
Trace: G-5, G-6, G-7, G-8, G-17, G-18, R-2.

| ID | Story | Size |
|---|---|---|
| E7-S1 | As a requester, I submit an intake request to create, modify or retire a forum. **AC:** a single intake form covers all three intents; required fields are enforced before submission; the form warns the requester that compliance review is required before they begin. | M |
| E7-S2 | As a governance office reviewer, I evaluate a request against the standard criteria. **AC:** coverage gap, duplication, escalation pathway clarity, framework alignment and resource feasibility are each recorded with a finding and a comment; the request cannot be approved until each is assessed. | M |
| E7-S3 | As a governance office reviewer, I can return a request to its originator with questions. **AC:** returning is a workflow transition, not a comment; the originator is notified; the exchange is preserved on the record. | S |
| E7-S4 | As an approver, I approve or reject a request through a configurable multi-step workflow. **AC:** approval steps are configuration; steps can be role-based, sequential or parallel; no step can be bypassed without a recorded exception. | L |
| E7-S5 | As a governance user, an approved request creates a forum in draft. **AC:** approval creates the forum record with the request's data carried across; the link between request and forum is navigable in both directions. | M |
| E7-S6 | As a governance office reviewer, I resolve a disputed request through a defined exception path. **AC:** an exception state routes to the designated authority and requires a recorded rationale. | M |

## E8 — Forum lifecycle
*Outcome: a forum's compliance standing, kept current.* Trace: G-10, G-11, R-2.

| ID | Story | Size |
|---|---|---|
| E8-S1 | As a compliance reviewer, I move a forum through its compliance states. **AC:** draft, pending, compliant, non-compliant and not-applicable; only compliance roles may set the outcome states; every transition is audited. | M |
| E8-S2 | As a compliance reviewer, I return a forum to its creator with comments. **AC:** as E7-S3, on the forum record. | S |
| E8-S3 | As a compliance administrator, changes to designated fields send a forum back for review automatically. **AC:** the watched-field list is **configuration**, editable without a deployment; changing a watched field moves the forum to pending and notifies compliance; changing an unwatched field does not. | M |
| E8-S4 | As a forum owner, I complete the required annual review. **AC:** review is due on a schedule; both the owner and compliance must confirm; an incomplete review is visible as an exception. | M |
| E8-S5 | As an approver, I disband a forum through a controlled workflow. **AC:** disbandment requires the specified approvals; the forum becomes inactive rather than deleted; its history and documents remain and remain subject to retention. | M |

## E9 — Membership, delegation and quorum
*Outcome: who sits on a forum, with the history intact.* Trace: G-13, G-14,
E-7, D-3.

| ID | Story | Size |
|---|---|---|
| E9-S1 | As an administrator, I maintain the list of membership roles. **AC:** roles are data, not code; each carries whether it counts toward quorum, whether it votes by default and whether it can attest. | S |
| E9-S2 | As a forum secretary, I add and remove members with effective dates. **AC:** membership is a record with a from-date and an optional to-date; removing a member ends the record rather than deleting it. | M |
| E9-S3 | As an auditor, I can see who sat on a forum at any past date. **AC:** a query by date returns the membership as it stood then; a test covers a member who joined and left before the query date. | M |
| E9-S4 | As a forum secretary, I record a seat held by position rather than by a named person. **AC:** a seat can name a position; the occupant can change without the seat losing identity or history. | M |
| E9-S5 | As a member, I delegate my seat for a period. **AC:** a delegation records who delegated, to whom and for how long; the delegate inherits voting rights only if the role permits; delegation is visible on the forum. | M |
| E9-S6 | As a forum secretary, quorum is calculated from current voting membership. **AC:** the quorum rule is configurable per forum as a count or a percentage; the system reports whether quorum is met for a given date. | M |

## E10 — Voting and decisions
*Outcome: decisions with enough evidence to defend them later.* Trace: G-12,
PPTX target operating model, D-3.

| ID | Story | Size |
|---|---|---|
| E10-S1 | As a forum secretary, I record a matter put to a forum for decision. **AC:** a decision record links to the forum, the date, the matter and any related policy or escalation. | M |
| E10-S2 | As a forum secretary, I record votes against a decision. **AC:** who was entitled to vote at that date, who voted, how they voted and abstentions; entitlement is derived from membership as at the decision date, not as at today. | L |
| E10-S3 | As an auditor, I can see whether quorum was met when a decision was taken. **AC:** quorum status is calculated and stored on the decision at the time it is recorded, so later membership changes do not rewrite history. | M |
| E10-S4 | As a governance user, I can see all decisions taken by a forum. **AC:** a decision list per forum, filterable by date and outcome, exportable. | S |

---

# Phase 3 — Policy

## E11 — Policy repository
*Outcome: one searchable home for governing documents.* Trace: P-1, P-2, P-3,
P-4, P-21.

| ID | Story | Size |
|---|---|---|
| E11-S1 | As a policy user, I maintain a policy record with its full metadata. **AC:** all specified metadata fields; required fields enforced; document type drawn from the taxonomy. | M |
| E11-S2 | As a policy user, I search and filter the repository. **AC:** filter by type, owner, status, risk category and organisation; full-text search across title and content; results respect permissions. | M |
| E11-S3 | As a policy user, I record relationships between documents. **AC:** parent, child and addendum lineage; navigable in both directions; circular lineage prevented. | M |
| E11-S4 | As a policy owner, I record where a policy applies. **AC:** applicability covers organisation units, legal entities, jurisdictions and roles, and records formal exemptions with their approvals. | M |
| E11-S5 | As an affected party, I am notified when a policy that applies to me is published, changed or retired. **AC:** notification derives from applicability rather than a manual list. | M |

## E12 — Policy lifecycle
*Outcome: a policy moves from request to retirement on a defined path.* Trace:
P-5, P-6, P-7, P-8, P-25.

| ID | Story | Size |
|---|---|---|
| E12-S1 | As a business user, I request a new or amended policy. **AC:** an intake request captures the need, the proposed implementation date and who must be engaged. | M |
| E12-S2 | As a drafter, I move a policy through drafting, review, approval, publication, periodic review and retirement. **AC:** states and transitions are configuration; role-based; every transition audited; no state name is hard-coded in business logic. | L |
| E12-S3 | As an approver, approvals route by policy type, change type and risk level. **AC:** conditional routing is configuration; the resulting path is visible on the record before submission. | L |
| E12-S4 | As a policy owner, parent policy owners approve changes to child documents where required. **AC:** the requirement is derived from lineage; the parent owner's approval is a distinct step. | M |
| E12-S5 | As a policy owner, I raise an exception or exemption request through a form and workflow. **AC:** exceptions are records with their own approval path and expiry. | M |
| E12-S6 | As a compliance officer, publication cannot occur without approval. **AC:** the transition to published is refused without a complete approval chain; bypass requires a recorded, authorised exception. | M |

## E13 — Intake classification
*Outcome: the major/minor decision, owned by the business and changeable
without a deployment.* Trace: P-16, D-19.

| ID | Story | Size |
|---|---|---|
| E13-S1 | As an administrator, I define the classification questions. **AC:** questions, answer options and ordering are data; adding a question requires no code change. | M |
| E13-S2 | As an administrator, I define the rules that turn answers into a classification. **AC:** rules are data; the rule set is versioned; the version used is stored on each classified request. | L |
| E13-S3 | As a requester, my answers produce a classification I can see and that is explained. **AC:** the outcome shows which rule fired; the requester can challenge it and the challenge is recorded. | M |
| E13-S4 | As a policy owner, classification drives routing, approval steps and service levels. **AC:** classification selects the workflow path; a test covers both a major and a minor path. | M |

## E14 — Horizon scanning
*Outcome: a periodic obligation on the policy owner, recorded and traceable.*
Trace: P-8 sub-requirement, deck annex.

| ID | Story | Size |
|---|---|---|
| E14-S1 | As a policy owner, I record a horizon scan against a policy. **AC:** scan date, period covered, coverage areas, sources reviewed, findings and an impact assessment. | M |
| E14-S2 | As a policy owner, I am reminded when a scan is due. **AC:** due dates derive from the policy's review cadence; reminders escalate when overdue; completion is tracked. | M |
| E14-S3 | As a policy owner, a scan finding can trigger a policy review. **AC:** an impact assessment of "review triggered" creates the downstream workflow and links it to the scan. | M |

## E15 — Monitoring, violations and glossary
*Outcome: the policy office can see adherence and keep language consistent.*
Trace: P-11, P-22, P-23, P-24.

| ID | Story | Size |
|---|---|---|
| E15-S1 | As a policy office user, I record monitoring activities against a policy. **AC:** activity, date, outcome and evidence. | M |
| E15-S2 | As a policy office user, I record a violation and track it to resolution. **AC:** violation record with severity, owner, remediation and status; links to the policy and optionally to an escalation. | M |
| E15-S3 | As a policy office user, I maintain a glossary of terms. **AC:** centrally maintained; versioned; changes audited. | M |
| E15-S4 | As a policy author, glossary terms are surfaced in context. **AC:** defined terms are recognisable in a document view and show their definition. | M |
| E15-S5 | As a policy office user, I can find records with missing required metadata. **AC:** a maintenance view lists incomplete records by field, and supports correcting them in place. | M |

---

# Phase 4 — Escalation

## E16 — Escalation intake and templates
*Outcome: consistent capture of matters that need to go up.* Trace: E-1 … E-6.

| ID | Story | Size |
|---|---|---|
| E16-S1 | As an administrator, I configure templates per escalation type. **AC:** the escalation, action plan and risk acceptance templates each have a configurable required-field set; standard fields are shared across templates. | L |
| E16-S2 | As an escalation owner, I raise an escalation using the right template. **AC:** selecting a type applies its template; required fields enforced; the matter is searchable immediately. | M |
| E16-S3 | As an escalation owner, I record an action plan against an escalation. **AC:** start and end dates, accountable executive, owner and status; multiple action plans per escalation. | M |
| E16-S4 | As an escalation owner, I record a risk acceptance against an escalation. **AC:** rationale, accountable executive, period and status; a risk acceptance requires an explicit approval. | M |

## E17 — Routing and resolution
*Outcome: matters reach the right forum and are closed with evidence.* Trace:
E-7 … E-15.

| ID | Story | Size |
|---|---|---|
| E17-S1 | As an escalation owner, I select a governance forum as the escalation pathway. **AC:** the forum list comes from the forum inventory; only active forums are selectable; the forum's escalation protocol and threshold are shown. | M |
| E17-S2 | As an administrator, I configure escalation pathways so routing is consistent. **AC:** pathways are data; a matter of a given type and severity proposes its destination automatically. | L |
| E17-S3 | As an escalation owner, I move a matter through its states to closure. **AC:** open, in progress, pending review and closed; closure requires a recorded outcome. | M |
| E17-S4 | As a manager, matters that breach their time thresholds are escalated automatically. **AC:** thresholds are configuration per type and severity; breach raises the matter and notifies; the breach is recorded. | M |
| E17-S5 | As a risk manager, I can analyse escalation patterns. **AC:** volumes, durations, destinations and outcomes over time, filterable and exportable. | M |

---

# Phase 5 — Cross-cutting engines

## E18 — Attestation
*Outcome: one engine, three campaigns.* Trace: G-10, P-8, deck slide 13.

| ID | Story | Size |
|---|---|---|
| E18-S1 | As an administrator, I define an attestation campaign. **AC:** scope, population, period, opening and closing dates; three campaign types supported by one engine. | L |
| E18-S2 | As a campaign owner, tasks are generated for the right people. **AC:** the population is derived from live data — forum membership or policy ownership — not a pasted list; regenerating is safe and does not duplicate open tasks. | M |
| E18-S3 | As an attester, I complete my task with a recorded confirmation. **AC:** confirm or raise an exception; a comment is required on exception; the response is immutable once submitted. | M |
| E18-S4 | As a campaign owner, I can see completion and chase what is outstanding. **AC:** live completion by population segment; reminders escalate as the close date approaches. | M |
| E18-S5 | As an auditor, a closed campaign is evidence. **AC:** a campaign export shows who was asked, who responded, what they said and who did not respond. | M |

## E19 — Notifications
*Outcome: the right people told, through a channel that can change.* Trace:
G-14, P-14, E-17.

| ID | Story | Size |
|---|---|---|
| E19-S1 | As an administrator, I configure notification templates per event. **AC:** templates are data; recipients can be roles, groups or derived from the record. | M |
| E19-S2 | As a user, I receive notifications in the application. **AC:** in-app delivery with read state; a digest option. | M |
| E19-S3 | As an engineer, delivery channels are pluggable. **AC:** channel is an interface with in-app and email implemented, and a third channel stubbed against a documented API so it can be added without touching callers. | M |
| E19-S4 | As an auditor, notification delivery is recorded. **AC:** what was sent, to whom, when, on which channel, and whether it succeeded. | S |

## E20 — Reporting and dashboards
*Outcome: the numbers people ask for, without an export to a spreadsheet.*
Trace: G-12, P-12, E-15, deck optional items.

| ID | Story | Size |
|---|---|---|
| E20-S1 | As a user, I build a report over any entity. **AC:** choose columns, filter, group, sort; save and share; export to CSV and Excel. | M |
| E20-S2 | As a governance user, I see a dashboard of forum activity and compliance standing. **AC:** counts by category, status distribution, overdue reviews, recent changes. | M |
| E20-S3 | As a governance user, I see where governance coverage has gaps. **AC:** coverage by risk category and organisation unit, highlighting combinations with no forum. | L |
| E20-S4 | As a user, I see how forums connect to one another. **AC:** a navigable diagram of parent, sub-forum, upstream and downstream relationships. | L |
| E20-S5 | As a user, dashboards respect my permissions. **AC:** figures reflect only records the viewer may see; a test asserts two roles see different totals from the same dashboard. | M |

## E21 — Import and export
*Outcome: the replacement for the integrations that are out of scope.* Trace:
G-19, P-20, E-19, D-18.

| ID | Story | Size |
|---|---|---|
| E21-S1 | As an administrator, I import records from a file. **AC:** a documented template per entity; validation before commit; per-row error reporting; no partial application of a failed file. | L |
| E21-S2 | As an administrator, an import is auditable and reversible. **AC:** each import is a record with its file, actor and outcome; an import can be rolled back. | M |
| E21-S3 | As an integrator, data can be extracted through the API. **AC:** documented read endpoints for every published entity, with permission enforcement and pagination. | M |
| E21-S4 | As an engineer, an integration can be added later without reshaping the data. **AC:** an integration boundary exists with the file importer as its first implementation; adding an API-based source requires no change to the entities. | M |

## E22 — AI assistance
*Outcome: the external AI platform made useful inside the workflow, with
provenance.* Trace: D-1.

| ID | Story | Size |
|---|---|---|
| E22-S1 | As an engineer, the application can call the external AI service. **AC:** one adapter; endpoint and credentials are configuration; failure degrades gracefully and never blocks the user's work. | M |
| E22-S2 | As a user, I can request a summary of a long record or document. **AC:** a summary is offered, clearly labelled as machine-generated, and never saved without a person accepting it. | M |
| E22-S3 | As an auditor, I can tell which content originated from a suggestion. **AC:** accepted suggestions record the suggestion, who accepted it, when, and against which version. | M |
| E22-S4 | As a compliance officer, I control what may be sent to the external service. **AC:** a policy governs which fields and classifications may leave; restricted records are excluded; every outbound call is logged. | M |

---

# Phase 6 — Interface

## E23 — Interface shell
*Outcome: the look, feel and behaviour that stakeholders will judge.* Trace:
deck slide 15, stakeholder directives, R-1.

| ID | Story | Size |
|---|---|---|
| E23-S1 | As a user, the application has a consistent shell with tabbed navigation. **AC:** home, forums, policies, escalations, reports and administration; breadcrumbs; current location always clear. | M |
| E23-S2 | As a user, I switch between a light and a dark theme, and it is remembered. **AC:** switchable from the interface; applied before first paint; persists across sessions. | S |
| E23-S3 | As a user, I change the font size on any page and it is remembered. **AC:** a visible control on every page; the whole page scales coherently; persists. | S |
| E23-S4 | As a user, every table paginates, sorts, searches and lets me set the page size. **AC:** one shared component; paging and sorting happen server-side so behaviour is correct on large datasets; page size persists. | L |
| E23-S5 | As a user, the interface is usable by keyboard and with a screen reader. **AC:** full keyboard navigation, visible focus, correct roles and labels, adequate contrast in both themes. | M |

## E24 — Screens
*Outcome: the screens people actually use.* Trace: deck slide 15.

| ID | Story | Size |
|---|---|---|
| E24-S1 | As a new user, the home page tells me how to use the system. **AC:** guidance on forum types and how to choose one, templates, decision authority and escalation protocols. | M |
| E24-S2 | As a governance user, the main table shows the inventory with the specified columns. **AC:** sortable, filterable, searchable, paginated; a row opens the record. | M |
| E24-S3 | As a governance user, the forum detail page shows everything about a forum. **AC:** details, membership, linkages, documents, decisions, history; edit is available only with permission. | L |
| E24-S4 | As a requester, a guided form walks me through creating a forum. **AC:** explains the process and the review to expect, lists required fields, validates as I go, and saves a draft. | L |
| E24-S5 | As an administrator, an administration area covers users, roles and reference data. **AC:** reachable from the shell; restricted to administrators. | M |

---

# Phase 7 — Deployment

## E25 — Installation and operations
*Outcome: a deployment team with no context can install and run this, offline.*
Trace: the phase 2 success criterion.

| ID | Story | Size |
|---|---|---|
| E25-S1 | As a deployer, I install the whole system on an air-gapped server from staged artifacts. **AC:** a documented, scripted install with no network access at any point; the script verifies its own prerequisites and fails clearly when one is missing. | L |
| E25-S2 | As a deployer, I install on a managed corporate Windows workstation. **AC:** same scripted path; no compiler, no package manager, no administrator rights beyond what is documented. | M |
| E25-S3 | As a deployer, I can confirm the installation is healthy. **AC:** one command checks database, cache, workers, scheduler, assets and permissions and reports pass or fail per check with a remedy for each failure. | M |
| E25-S4 | As an operator, I can back up and restore. **AC:** documented, scripted, tested by an actual restore into an empty database, not only by taking a backup. | M |
| E25-S5 | As an operator, I can upgrade without losing data. **AC:** a documented upgrade path; migrations are reversible or explicitly flagged as not; tested from the previous release. | L |
| E25-S6 | As a deployer, the database can be either self-installed or provisioned by a database team. **AC:** both paths documented; the provisioned path does not require superuser; both are tested. | M |
| E25-S7 | As an operator, the system produces logs and metrics I can act on. **AC:** structured logs, error reporting, and a documented list of what to watch. | M |

## E26 — Quality
*Outcome: confidence that what is claimed to work, works.*

| ID | Story | Size |
|---|---|---|
| E26-S1 | As an engineer, every entity has tests covering create, read, update, permissions and validation. **AC:** coverage reported; no entity without tests. | L |
| E26-S2 | As an engineer, every workflow has tests covering the happy path, each rejection path and each permission boundary. **AC:** a test attempts each transition as a role that should not be allowed it. | L |
| E26-S3 | As an engineer, the main journeys are covered end to end in a browser. **AC:** forum creation through to approval, policy drafting through to publication, escalation raising through to closure. | L |
| E26-S4 | As an engineer, automated checks enforce the platform rules. **AC:** checks fail the build on a CDN reference, a network fetch at run time, a compiler-requiring dependency, or client-identifying content. | M |
| E26-S5 | As an engineer, the system is exercised with realistic data volumes. **AC:** seeded with a volume representative of the real inventory; list, search and dashboard response times recorded. | M |
