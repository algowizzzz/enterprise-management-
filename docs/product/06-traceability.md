# Consilium — Traceability Matrix

**Document:** 06 of 07 — Traceability
**Purpose:** every one of the 64 requirements, traced to the entities that carry it, the module that owns it, the UI surface that delivers it, and how it is satisfied.

---

> **On counts.** Where this document and `01-requirements-baseline.md` both
> state how many requirements were materially changed or clarified, the
> requirement tables in `01` are authoritative — they carry the markers, and this
> summary was written from an earlier pass over them. The two disagree by one or
> two either way. Recount from `01` before quoting a figure externally.

## 1. Keys used in this document

### 1.1 UI surfaces

| Key | Surface | Built as |
|---|---|---|
| `CS-1` | Home page with user guide | Custom (Bootstrap + jQuery, vendored) |
| `CS-2` | Forum register — the main table | Custom |
| `CS-3` | Forum detail, including the interconnectivity view | Custom |
| `CS-4` | Create-forum wizard | Custom |
| `CS-5` | Dashboards | Custom |
| `CS-6` | Governing document register | Custom |
| `CS-7` | Governing document detail | Custom |
| `CS-8` | Escalation register | Custom |
| `CS-9` | Escalation detail | Custom |
| `CS-10` | Personal task and attestation inbox | Custom |
| `CS-11` | Import batch review screen | Custom |
| `DK-1` | Desk form and list views | Native |
| `DK-2` | Role and permission administration | Native |
| `DK-3` | Taxonomy maintenance and CSV import | Native |
| `DK-4` | Workflow configuration | Native |
| `DK-5` | Report builder, query reports, export | Native |
| `DK-6` | Change-history and audit views | Native |
| `DK-7` | Notification template administration | Native |
| `DK-8` | Scheduled job configuration and logs | Native |
| `API` | REST / RPC interface, permission-evaluated | Native |
| `BG` | Background job or scheduled sweep — no UI | — |

### 1.2 Satisfaction classes

`Native` — stock framework feature, no work.
`Config` — metadata: entities, fields, workflows, permissions, notifications, reports.
`Build` — application code.

---

## 2. Module CGF — G-1 … G-19

| ID | Entities | Module | UI surface | How satisfied |
|---|---|---|---|---|
| **G-1** | `Governance Forum`; its five multi-select child tables; `File`; `DocPerm` / `User Permission` / `DocShare` | CGF | `CS-2`, `CS-3`, `DK-1` | **Config.** Entity definition plus permission rules. Attachment handling and the permission engine are native. The register is a custom screen over the permission-evaluated API. |
| **G-2** | `Governance Forum` + the five taxonomy child tables; indexes per `03-schema.md` §7.3 | CGF | `CS-2`, `DK-1`, `DK-5` | **Config + Build.** Native list and report filtering on Desk. Hand-built filter, sort, search and configurable page size on the custom register, paged in SQL. Multi-select filters are `EXISTS` subqueries. |
| **G-3** | `Governance Forum`; `Governance Forum Type`, `Primary Risk Category`, `Legal Entity`, `Operating Group`, `Line of Business`; `Forum Business Unit`, `Forum Risk Type`, `Forum Legal Entity`, `Forum Jurisdiction`, `Forum Governance Responsibility` | CGF | `CS-3`, `CS-4`, `DK-1`, `DK-3` | **Config.** Link fields for the singular attributes, child tables for the multi-valued ones. Dependent-field behaviour is field metadata. |
| **G-4** | `Forum Link`; `Forum Regulatory Requirement`; `Regulatory Requirement`; `Governance Forum.regulatory_required`, `.parent_forum` | CGF | `CS-3`, `DK-1` | **Config + Build.** Child tables and a gated dependent table. Build for the interconnectivity rendering (`O-2`). |
| **G-5** | `Committee Formation Request`; `Formation Evaluation`; `Committee Charter`; `Charter Approval Evidence`; `Governance Forum.compliance_status` | CGF | `CS-4`, `DK-1`, `DK-4` | **Config + Build.** Multi-state workflow on the request. Build for the progression gate and for the request-approved-creates-forum action. |
| **G-6** | `Workflow`, `Workflow State`, `Workflow Transition` (framework); semantic flags on `Governance Forum` and `Committee Formation Request` | CGF | `DK-4` | **Native + Config.** The workflow is a configuration record, editable by an administrator. Semantic flags keep logic decoupled from state names. |
| **G-7** | `Formation Evaluation`; `Committee Formation Request.completeness_confirmed`, `.duplicate_check_result`; `Committee Charter.rgo_challenge_status` | CGF | `CS-4`, `DK-1` | **Build.** Server-side validation on transition; duplicate detection against the forum register; charter-challenge gate; approval validation against the intake record. |
| **G-8** | `Approval Decision`; `Workflow Action` (framework); `Committee Charter` | CGF | `CS-3`, `DK-1`, `DK-4` | **Config + Build.** Role-gated transitions; build for conditional path selection by change materiality and forum type. |
| **G-9** | `Version` (framework); `Comment` (framework); `Document Version`; `Version Revert Log` | CGF | `CS-3`, `DK-6` | **Native + Build.** Field-level history and comments are native. **Revert is a build** — write a new version, never mutate history. |
| **G-10** | `Attestation Campaign`, `Attestation Task`, `Attestation Task Item`; `Forum Membership`; `Governance Forum Role.can_attest`; `Governance Forum.next_review_on`, `.last_attested_on` | CGF | `CS-10`, `CS-5`, `BG` | **Build.** The shared attestation engine, campaign type "Forum Inventory", opening in the first quarter. Participants resolved from active membership seats whose role can attest. |
| **G-11** | `Disbandment Plan`; `Disbandment Approval`; `Governance Forum.disbanded_on`, `.is_active`; `Retention Assignment` | CGF | `CS-3`, `DK-1`, `DK-4` | **Config + Build.** Terminal workflow state with its own approval set. Build for the approval-completeness gate and the retention consequence on disbandment. |
| **G-12** | All CGF entities; `Report`, `Dashboard Chart`, `Number Card` (framework) | CGF | `CS-5`, `DK-5` | **Native + Build.** Native report builder, query reports and export on Desk; custom dashboard screens for the specified layout. |
| **G-13** | `Role`, `Has Role`, `User Group`, `DocPerm`, `User Permission`, `DocShare` (framework); `Forum Membership`; `Governance Forum Role`; `Authority Delegation` | CGF | `DK-2`, `CS-3` | **Native + Config + Build.** Access roles in the permission engine; participation and accountability as membership seats; build for delegation validity windows and for nomination by chair, sponsor or secretary. |
| **G-14** | `Notification`, `Email Template`, `Email Queue` (framework); `Notification Channel`; `Notification Dispatch` | CGF | `DK-7`, `BG` | **Native + Config + Build.** Native triggers and templates; build for the pluggable channel abstraction and the dispatch evidence record. |
| **G-15** | `File` (framework); `Document Version`; `Committee Charter`; `Forum Meeting` (agenda, minutes) | CGF | `CS-3`, `DK-1`, `DK-6` | **Native + Build.** Native attachment handling and activity log; build for the version chain over charter and minute documents. |
| **G-16** | `Retention Class`, `Retention Assignment`, `Legal Hold`, `Archive Record`, `Disposition Event` | CGF | `DK-1`, `BG` | **Build.** Retention classes and schedules, hash-chained archive, legal holds, approved disposition. **Changed from the source: this is ours, not an outbound hook.** |
| **G-17** | `Committee Formation Request`; `Formation Evaluation`; `Guide Article` | CGF | `CS-4`, `DK-4` | **Config + Build.** Intake entity and workflow; custom wizard carrying the guidance the source requires at intake. Build for the completeness gate. |
| **G-18** | `Committee Formation Request` (the standardized field block); `Jurisdiction`, `Operating Group`, `Line of Business`, `Business Unit`, `Governance Forum Type` | CGF | `CS-4`, `DK-1` | **Config.** Mandatory-field and validation metadata. **Changed from the source: committee-centric field names.** |
| **G-19** | `External Reference`, `External System`, `Export Batch`, `Import Batch`; in-database links from `Governing Document.approving_forum` and `Escalation Forum Link` | CGF | `CS-11`, `DK-5`, `API` | **Config + Build.** Reuse by the Policy and Escalation modules is an in-database relationship, not an integration. Reuse by the risk appetite system and risk register is a file export. Inbound is the governed import path. |

---

## 3. Module POL — P-1 … P-26

| ID | Entities | Module | UI surface | How satisfied |
|---|---|---|---|---|
| **P-1** | `Governing Document`; `Governing Document Type`; `Document Version`; `File`; `DocPerm` / `User Permission` / `DocShare`; `confidential`, `handling_classification`, `allow_download`, `allow_print`, `allow_share` | POL | `CS-6`, `CS-7`, `DK-1` | **Config + Build.** Entity and permission rules are configuration. **The restricted-handling controls are a build** — the framework has no native per-record suppression of download, print or share. |
| **P-2** | `Governing Document` and its taxonomy child tables; trigram indexes per `03-schema.md` §7.4 | POL | `CS-6`, `DK-1`, `DK-5` | **Config + Build.** As G-2. |
| **P-3** | `Governing Document`; `Document Accountability Role`; all seventeen taxonomies; `Document Relationship` | POL | `CS-7`, `DK-1`, `DK-3` | **Config.** Every named attribute maps to a field or child table. Dependent behaviour is field metadata. |
| **P-4** | `Document Relationship`; `Governing Document.parent_document` | POL | `CS-7`, `CS-5` | **Config + Build.** Child table for lineage; build for the document-family visualisation. |
| **P-5** | `Governing Document.approving_forum` (in-database); `External Reference` for risk, process, control, training and issue references | POL | `CS-7`, `CS-11` | **Config + Build.** **Changed from the source:** in-platform links where the counterpart is a Consilium record; imported reference records where it is not. |
| **P-6** | `Document Regulatory Reference`; `Regulatory Requirement`; `Governing Document.regulatory_required`; `Import Batch` for the regulatory-change file | POL | `CS-7`, `CS-11`, `BG` | **Config + Build.** Gated dependent child table. **Changed from the source:** the regulatory-change feed is a file import; the impact fan-out to owners of documents citing a changed requirement is a build. |
| **P-7** | `Workflow` (framework); `SLA Definition`; `SLA Clock`; `Document Template.action` | POL | `DK-4`, `CS-7`, `BG` | **Native + Config + Build.** Native workflow; **build for the service-level definition, clock and breach alerting** — not a framework feature. |
| **P-8** | `Approval Decision`; `Document Relationship.owner_approval_required`; `Attestation Campaign`/`Task`; `Horizon Scan`; `Applicability Exemption`; `Notification` | POL | `CS-7`, `CS-10`, `DK-4`, `BG` | **Config + Build.** Workflow configuration; build for parent-owner approval injection, the annual document attestation campaign and horizon-scan due scheduling. |
| **P-9** | `Version` (framework); `Document Version`; `Version Revert Log` | POL | `CS-7`, `DK-6` | **Native + Build.** Native field-level history for metadata. **The document body chain and revert are a build**, because we hold the authoritative body. |
| **P-10** | `Document Review Cycle`; `Governing Document.next_review_on`, `.review_frequency_months`; `SLA Clock` | POL | `CS-7`, `CS-10`, `BG` | **Config + Build.** Review-cycle entity and scheduled due detection; build for the service-level clock on overdue reviews. |
| **P-11** | `Monitoring Activity`; `Monitoring Result`; `Policy Violation` | POL | `CS-7`, `CS-5`, `BG` | **Config + Build.** Entities plus a scheduled due sweep; build for the central monitoring dashboard. |
| **P-12** | All POL entities; `Report`, `Dashboard Chart` (framework) | POL | `CS-5`, `DK-5` | **Native + Build.** As G-12. |
| **P-13** | `Role`, `DocPerm`, `User Permission`, `DocShare` (framework); `Authority Delegation`; `Document Accountability Role`; the three rendition flags | POL | `DK-2`, `CS-7` | **Native + Config + Build.** Native permission engine including permission levels for field-level restriction; build for the rendition gate and the delegation register. All access changes are logged natively. |
| **P-14** | `Notification`, `Email Template` (framework); `Notification Channel`; `Notification Dispatch` | POL | `DK-7`, `BG` | **Native + Config + Build.** As G-14. |
| **P-15** | `Document Template`; `Template Section`; `Governing Document Type`; naming-convention validation | POL | `DK-1`, `CS-7` | **Config + Build.** Template entity and sections; build for naming-convention enforcement. **Changed from the source:** collaborative drafting, redlining and version comparison during editing belong to the external editor. |
| **P-16** | `Document Intake Request`; `Classification Rule Set`, `Classification Question`, `Classification Answer Option`, `Classification Rule`; `Classification Assessment`, `Classification Assessment Answer` | POL | `CS-7`, `DK-1` | **Build.** **Changed from the source:** an admin-configured rules engine, versioned, with a stored evaluation trace. The rules themselves are data and are not required to ship the capability. |
| **P-17** | `File` (framework); `Version`, `Comment` (framework) | POL | `CS-7`, `DK-6` | **Native.** No limit on attachment type or count; native activity log. |
| **P-18** | `Retention Class`, `Retention Assignment`, `Legal Hold`, `Archive Record`, `Disposition Event` | POL | `DK-1`, `BG` | **Build.** As G-16. **Changed from the source.** |
| **P-19** | `Document Publication`; `Publication Audience`; the three rendition flags; `Document Version.published`; `Governing Document.superseded_by` | POL | `CS-7`, `DK-1` | **Build.** Publication record with audience and permitted renditions; build for the rendition-permission gate and for retention of superseded documents with history. |
| **P-20** | `Import Batch`, `Import Row`, `Import Profile`, `Import Field Mapping`, `External System`, `External Reference`, `Export Batch`; all taxonomies; `User` | POL | `CS-11`, `DK-3`, `API` | **Build.** **Changed from the source:** the governed file import and export pipeline, carrying the mapping, validation, handling-rule and traceability obligations in full. Identity alignment is satisfied by app-native users with pluggable single sign-on. |
| **P-21** | `Document Applicability`; `Applicability Exemption`; `Business Unit`, `Legal Entity`, `Material Entity`, `Jurisdiction`; `Notification Dispatch` | POL | `CS-7`, `BG` | **Config + Build.** Applicability and exemption entities; build for resolving the applicable audience and dispatching on create, change and retire. |
| **P-22** | `Policy Violation`; `External Reference`; `Escalation Matter` (in-database) | POL | `CS-7`, `CS-5`, `DK-1` | **Config + Build.** **Changed from the source:** the external issue link is a recorded reference identifier with a provenance batch, not a live connector. |
| **P-23** | `Metadata Remediation Task`; `Governing Document.parent_document`; taxonomy `is_active`; `User.enabled` | POL | `CS-10`, `BG` | **Build.** Referential-consequence detection on retirement, deactivation and disbandment, raising a remediation task to the owner. |
| **P-24** | `Glossary Term`; `Glossary Term Link` | POL | `CS-7`, `DK-1` | **Config + Build.** Entity with scope levels and approval status; **build for the enforcement validator** that prevents use of undefined terms. Version control and audit are native. |
| **P-25** | `Approval Decision`; `Exception Authorisation`; `Classification Assessment.outcome`; `Workflow Action` (framework) | POL | `CS-7`, `DK-4` | **Config + Build.** Publish transition gated on a complete approval set; build for resolving the required set from the classification, and for the exception-authorisation record that is the only permitted bypass. |
| **P-26** | `Document Version`; `Version Revert Log`; `Approval Decision`; `Document Accountability Role`; `Notification Dispatch`; external editor | POL | `CS-7`, `BG` | **Build (partial) + external.** **Changed from the source:** inline commenting, revision suggestion and collaborative editing are the external editor's. Ours: review-stage transition, reviewer assignment, disposition record and its notification, the authoritative version chain, and retention of prior versions. |

---

## 4. Module ESC — E-1 … E-19

| ID | Entities | Module | UI surface | How satisfied |
|---|---|---|---|---|
| **E-1** | `Escalation Matter`; `Escalation Impacted Entity`; `DocPerm` / `User Permission` / `DocShare` | ESC | `CS-8`, `CS-9`, `DK-1` | **Config.** Entity definition plus permission rules. |
| **E-2** | `Escalation Matter` and its child tables; indexes per `03-schema.md` §7.3 | ESC | `CS-8`, `DK-1`, `DK-5` | **Config + Build.** As G-2. |
| **E-3** | `Escalation Matter`; `Escalation Type`, `Risk Type`, `Organizational Level`, `Legal Entity`, `Material Entity`; `Escalation Impacted Entity` | ESC | `CS-9`, `DK-1`, `DK-3` | **Config.** Every named attribute maps to a field or child table; tier-1 and tier-2 risk types come from one tiered taxonomy. |
| **E-4** | `Escalation Matrix`; `Escalation Matrix Rule`; `Escalation Matter.severity`, `.severity_source`, `.matched_matrix_rule` | ESC | `CS-9`, `DK-1` | **Config + Build.** The matrix and its rules are configuration; build for rule resolution at intake and for recording which rule fired. |
| **E-5** | `Escalation Template`; `Escalation Template Field`; `Escalation Matter` | ESC | `CS-9` | **Config + Build.** Conditional mandatory-field behaviour driven by the selected template and the severity; workflow routing to gather further detail and approvals. |
| **E-6** | `Escalation Template`, `Escalation Template Field`; `Escalation Matter`; `Action Plan`; `Risk Acceptance`; `Escalation Forum Link` | ESC | `CS-9`, `DK-1` | **Config + Build.** All three specified templates modelled. **Note: `governance_forums` and `impacted_entities` are plural**, per the source appendix, and `escalation_date` is distinct from the identification date. |
| **E-7** | `Escalation Forum Link`; `Governance Forum`; `Forum Membership`; `Governance Forum Role`; `Notification Dispatch` | ESC | `CS-9`, `BG` | **Config + Build.** In-database selection of forums as pathways; build for resolving forum participants through membership seats and dispatching to them. |
| **E-8** | `Escalation Matter.material_entity_impact`, `.risk_appetite_breach`; `Escalation Matrix`; `Action Plan`; `Risk Acceptance`; `Escalation Closure`; `Assignment Rule` (framework) | ESC | `CS-9`, `DK-4`, `BG` | **Config + Build.** Workflow configuration and assignment rules; build for matrix-driven routing and the two conditional notification paths. |
| **E-9** | `Escalation Review`; `Approval Decision`; `Risk Acceptance.next_reassessment_on`; `Authority Delegation`; `Escalation Matter.sensitive`, `.response_template_completed`; `SLA Definition`/`SLA Clock` | ESC | `CS-9`, `DK-4`, `BG` | **Config + Build.** Multi-step review and approval configuration; build for the second-line challenge clock, the reassessment scheduler, the sensitive-record restriction and the mandatory-response gate. |
| **E-10** | `Escalation Closure`; `Closure Criterion`; `File` | ESC | `CS-9` | **Config + Build.** Criteria as configurable rows; build for the closure gate that refuses closure until required criteria are met with evidence. |
| **E-11** | `Periodic Submission`; `Report` (framework); `Notification Dispatch` | ESC | `CS-5`, `DK-5`, `BG` | **Config + Build.** Submission record and scheduled reminders; build for the nil-return confirmation workflow. |
| **E-12** | `Version` (framework); `Comment` (framework); `Version Revert Log` | ESC | `CS-9`, `DK-6` | **Native + Build.** Native history; **revert is a build.** |
| **E-13** | `SLA Definition`; `SLA Clock`; `Business Calendar` | ESC | `CS-9`, `CS-5`, `BG` | **Build.** Per-state accrual, total time open, warning and breach detection on an hourly sweep. Not a framework feature. |
| **E-14** | `Escalation Matter.status`, `.workflow_state`, semantic flags; `External Reference` | ESC | `CS-9`, `DK-4` | **Config.** Workflow states including the externally-tracked terminal state, which carries the external reference. |
| **E-15** | All ESC entities; `Report`, `Dashboard Chart` (framework) | ESC | `CS-5`, `DK-5` | **Native + Build.** As G-12. |
| **E-16** | `Role`, `DocPerm`, `User Permission`, `DocShare` (framework); `Authority Delegation`; `Escalation Matter.sensitive` | ESC | `DK-2`, `CS-8` | **Native + Config + Build.** Native role and permission engine and groupings; **build for the sensitive-record restriction**, which must hold on list, form, report, search, export and the REST interface. |
| **E-17** | `Notification`, `Email Template` (framework); `Notification Channel`; `Notification Dispatch`; `User Group` | ESC | `DK-7`, `BG` | **Native + Config + Build.** As G-14. |
| **E-18** | `Retention Class`, `Retention Assignment`, `Legal Hold`, `Archive Record`, `Disposition Event` | ESC | `DK-1`, `BG` | **Build.** As G-16. **Changed from the source.** |
| **E-19** | `Import Batch`, `Import Row`, `Import Profile`, `External System`, `External Reference`, `Export Batch`; `Escalation Forum Link`; `User` | ESC | `CS-11`, `API`, `BG` | **Build.** **Changed from the source:** inbound becomes the governed file import, capable of creating pre-populated escalation matters; outbound becomes an export with a linkage register; forum selection is an in-database relationship; identity is app-native with pluggable single sign-on. |

---

## 5. Supplementary requirements brought into scope

| ID | Entities | Module | UI surface | How satisfied |
|---|---|---|---|---|
| **O-1** | `Guide Article` | CGF | `CS-1`, `CS-4` | **Build.** Managed guide content, editable without a deployment, surfaced on the home page and inside the create-forum wizard. |
| **O-2** | `Forum Link`; `Governance Forum.parent_forum`; `Governance Forum Type` | CGF | `CS-1`, `CS-3` | **Build.** Rendered on both the home page and the forum detail page, since the sources place it in both. |
| **O-3** | All CGF entities; `Forum Compliance Review` | CGF | `CS-5` | **Build + Native.** Custom dashboard over native chart and number sources. |
| **O-4** | `Notification Channel`; `Notification Dispatch` | CGF | `DK-7`, `BG` | Already delivered by G-14. |
| **O-5** | `Escalation Matter`; `Escalation Forum Link` | CGF | `CS-3`, `CS-9` | Delivered by the in-database relationship between the modules. |
| **O-6** | `AI Service Request`; `AI Suggestion Acceptance` | CORE | `CS-3`, `CS-7` | **External AI services**, surfaced as an optional assist with recorded provenance. No internal data source exists for it. |
| **O-7** | `AI Service Request`; `Import Batch` (regulatory change) | CORE | `CS-5`, `CS-11` | **External AI services** plus the manual regulatory-change import path. |

---

## 6. Reverse trace — which requirements each major entity carries

A reviewer checking "why does this entity exist" reads this table.

| Entity | Requirements |
|---|---|
| `Governance Forum` | G-1, G-2, G-3, G-4, G-9, G-10, G-11, G-12, G-19, E-7, P-5 |
| `Forum Membership` | G-10, G-13, G-14, E-7 |
| `Governance Forum Role` | G-13, G-10 |
| `Committee Formation Request` | G-5, G-6, G-7, G-8, G-17, G-18 |
| `Formation Evaluation` | G-5, G-7 |
| `Committee Charter` | G-1, G-5, G-7, G-8, G-9, G-15 |
| `Disbandment Plan` | G-11 |
| `Forum Compliance Review` | G-6, G-10 |
| `Forum Meeting` / `Forum Motion` / `Forum Vote` | G-13, G-8, E-9 |
| `Governing Document` | P-1 … P-25 |
| `Document Intake Request` | P-16, P-7, P-25 |
| `Classification Rule Set` + children | P-16, P-7, P-25 |
| `Classification Assessment` | P-16, P-25 |
| `Document Version` | P-9, P-15, P-19, P-26, G-9, G-15, E-12 |
| `Version Revert Log` | P-9, G-9, E-12 |
| `Document Publication` | P-19, P-1, P-13 |
| `Document Review Cycle` | P-10, P-8 |
| `Monitoring Activity` / `Monitoring Result` | P-11, P-12 |
| `Policy Violation` | P-22, P-11, P-12 |
| `Glossary Term` | P-24 |
| `Horizon Scan` + children | P-8 |
| `Implementation Plan` | P-8, P-12 |
| `Applicability` / `Applicability Exemption` | P-21, P-8 |
| `Metadata Remediation Task` | P-23 |
| `Escalation Matter` | E-1 … E-19 |
| `Escalation Matrix` + rules | E-4, E-8 |
| `Escalation Template` + fields | E-5, E-6, E-9 |
| `Action Plan` / `Risk Acceptance` | E-6, E-8, E-9 |
| `Escalation Closure` / `Closure Criterion` | E-10 |
| `Escalation Review` | E-9, E-13 |
| `Periodic Submission` | E-11 |
| `Attestation Campaign` / `Task` / `Task Item` | G-10, P-8 |
| `Retention Class` / `Assignment` / `Legal Hold` / `Archive Record` / `Disposition Event` | G-16, P-18, E-18, P-19, G-15 |
| `Import Batch` / `Row` / `Profile` / `Field Mapping` | G-19, P-20, P-6, P-22, E-19 |
| `External System` / `External Reference` | G-19, P-5, P-6, P-22, E-19, E-8 |
| `Export Batch` | G-19, P-20, E-19, P-12, G-12, E-15 |
| `Authority Delegation` | G-13, P-13, E-9, E-16 |
| `Approval Decision` / `Exception Authorisation` | P-25, G-8, E-9 |
| `SLA Definition` / `SLA Clock` | E-13, P-7, P-10, E-9 |
| `Notification Channel` / `Notification Dispatch` | G-14, P-14, E-17, P-21, E-7 |
| `AI Service Request` / `AI Suggestion Acceptance` | O-6, O-7 (provenance for all AI use) |
| `Watched Field Set` / `Watched Field` | G-6, G-10 |
| `Guide Article` | O-1, G-17 |
| All seventeen taxonomies | G-3, G-18, P-3, P-21, E-3, and the taxonomy-alignment clauses of G-19, P-20, E-19 |

---

## 7. Coverage assertion

| Check | Result |
|---|---|
| CGF requirements traced | 19 of 19 |
| Policy requirements traced | 26 of 26 |
| Escalation requirements traced | 19 of 19 |
| **Total** | **64 of 64** |
| Supplementary requirements traced | 7 of 7 |
| Requirements with no entity | 0 |
| Requirements with no UI surface | 0 |
| Requirements satisfied purely by a native feature, with no configuration or build | **1** — P-17 |
| Requirements requiring a build component | 55 |
| Requirements materially changed by a stakeholder decision (bold Δ) | 15 — see `01-requirements-baseline.md` §4 |
| Requirements clarified or narrowed by a stakeholder decision (plain Δ) | 26 — same section |
