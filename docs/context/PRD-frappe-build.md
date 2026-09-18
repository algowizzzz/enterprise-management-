# PRD-frappe-build.md — TRANSCRIPTION (batch 1 of N)

> Transcribed from screenshots. Source file on the client machine:
> `C:\Users\sahme29\Desktop\usecases\policy_roymond\docs\techdocs\PRD-frappe-build.md`
> Lines 1–132 captured. Ellipses `[…]` mark text cut off by the screen edge.
> INTERNAL the client MATERIAL — do not commit to the public repo.

---

# Product Requirements Document — Policy, Escalation & Committee/Governance Forum Management

**Status:** Final for handoff — Build Platform: **Frappe Framework**
**Audience:** New build team (assume no prior context on this project)
**Source of truth:** Every requirement below is reproduced verbatim from the
three original the client requirement documents converted in `docs/converted/`:
`ERM_Tech_Policy_Mgmt_Requirements_20260306`,
`ERM_Tech_Escalation_Mgmt_Requirements_20260306`,
`ERM_Tech_CGF_Mgmt_Requirements_20260306`. **64 requirements total**
(P-1..26, E-1..19, G-1..19). If anything here looks abbreviated, cross-check the
source file — two requirements (P-20, E-19) have a truncated final sentence in
this document only (noted inline); everything else is complete.

---

## 1. Purpose & Scope

Build an internal Governance, Risk and Policy platform covering three modules —
**Policy Management**, **Escalation Management**, and **Committee & Governance
Forum (CGF) Management** — on the **Frappe Framework** (MIT licensed core; the
`bench` CLI tool used to manage it is GPL-3.0 — a dev/ops tool, not code we
distribute, so this is a low-risk license note, not a blocker; confirm with Legal
regardless).

### Explicitly out of scope

- **the risk identification system** — a separate, already-in-flight the incumbent GRC platform project per the
  originating email thread ("we simply need to finish the play and get this piece
  of the incumbent GRC platform into production"). Not part of this build. If integration is ever
  needed, treat the "Risk Identification (the risk identification system) system" referenced in
  P-5/E-19/G-19 as a **hypothesis, not a confirmed fact**, that it's the same
  the incumbent GRC platform the risk identification system project — confirm before assuming.
- **the enterprise GRC system, Regulatory Database, Risk Appetite system, Process/Risk/Control (PRC)
  system, Training system** — real systems referenced throughout the
  requirements, but **none are named/documented anywhere in the source
  material**. Each needs its own discovery conversation with its owning team
  before integration work can be scoped or estimated. See §8 (Data Connector
  Inventory).
- **Retention/WORM system** — being built as a **separate workstream**. This
  platform only needs to call it (a webhook/API hook), not implement it.
- **an alternate internal platform** — an alternate internal platform mentioned in the originating email as
  a possible foundation. Per direction, **not used** — the AI services platform is the confirmed
  AI capability provider instead (see §7).

---

## 2. Platform Decision: Frappe Framework

Frappe was selected because its native capabilities map directly onto the
hardest requirements across all three modules:

| Capability we need | Frappe's native mechanism |
|---|---|
| Generic, metadata-defined record types (per module) | **DocType** |
| A workflow engine whose *business logic* is authored by non-developers, not hardcoded | **Workflow DocType** — states, transitions, guard c[onditions], approvals, all edited through a UI |
| Role/record/field-level access control, incl. confidential-document handling | Role Permissions Manager + field-level permission rules |
| Audit trail / version history on every record | Native Version log + Comments |
| Templated, event/condition-driven notifications | Notification DocType |
| Reporting & dashboards | Report Builder + Dashboard Charts |
| REST API per record type | Auto-generated, no code needed |
| Document attachments + retention hook | File DocType + custom webhook on finalize |

**Environment note for the build team:** Frappe requires a Linux environment
(`bench` is not supported on native Windows). Use Docker (`frappe_docker`, the
officially supported path) or a properly provisioned Linux dev server/VM. **Do
not assume WSL2 will work out of the box** — a prior attempt on a locked-down
corporate laptop hit a hard blocker: outbound internet access from WSL2 was
blocked by corporate network policy, and the standard fix (WSL2 "mirrored"
networking) was itself unavailable because IPv6 was disabled at the OS level.
This was an environment/policy issue, not a Frappe defect — confirm your dev
environment has normal outbound network access (or a working internal package
mirror, see §9) before assuming the install will "just work."

> ⚠️ **TRANSCRIBER'S NOTE — this paragraph is now out of date.** Native Windows
> + PostgreSQL was proven working on the client laptop (Phases 0–2 of the winbench
> runbook, 8/8 smoke checks, Desk UI and workflow/audit trail verified). Docker
> and WSL2 are no longer required. Flag for revision.

---

## 3. Roles (consolidated across all three modules)

| Role | Used in |
|---|---|
| Policy Owner | Policy |
| Reviewer / Approver | Policy, CGF |
| Compliance / Legal | Policy |
| Accountable Executive | Escalation |
| Escalator | Escalation |
| Response Owner | Escalation |
| Second Line of Defence (2LOD) | Escalation |
| Risk Governance Office (RGO) Reviewer | CGF |
| Committee Chair / Secretary / Sponsor | CGF |
| Head of Risk Governance | CGF (exception resolution) |
| Head of Enterprise Risk | Escalation (systemic exception resolution) |
| Delegate (any role) | All three — delegation is a named requirement in each module |
| Administrator | All three |

RBAC must support: role-based permissions, delegation with accountability
retained, and a **confidential/restricted** flag on records (Policy, and
sensitive Escalations) that limits view/download/print/share to authorized roles
only.

---

## 4. Module: Committee & Governance Forum Management (G-1..G-19)

### 4.1 Requirements (full text)

| Req | Title | Description |
|---|---|---|
| G-1 | Committee and Governance Forum Repository | The system shall provide a centralized, searchable Committee & Governance Forum repository that stor[es …] details, charter documents, and associated metadata. Access, visibility, and permitted actions shall be governed by role-based access controls (RBAC). |
| G-2 | Search and Retrieval | Provide advanced search and filter capabilities allowing users to search and filter Committee and Governance Forums by me[tadata …] |
| G-3 | Committee and Governance Forum Tagging | Ability to click into Committee and Governance Forum and tag the forums with metadata (with field depend[ency …]) common taxonomy with other systems. Ability to control selections using dropdowns. Examples include, but are not limited to: Governance Forum ID, Governa[nce Forum] Name, Governance Forum Type, Description, Cadence, Committee Chair, Primary Risk Category (Common Taxonomy), Legal Entity (Common Taxonomy), Owning Organ[ization (OG/]CS) (Common Taxonomy), Owning Organization (LOB) (Common Taxonomy). |
| G-4 | Forum Mapping | Ability to map forums to related forums (Upstream/Downstream Committee and Governance Forum). Ability to tag Committee and Govern[ance Forum as] regulatory required (Y/N) with field dependency. Ability to add regulatory requirements. |
| G-5 | Committee Formation | The system shall support the Committee formation process by enabling structured intake, evaluation, approval evidence captu[re, …] handling, and status tracking in alignment with Risk Governance Office (RGO) standards. **Committee Request Evaluation Criteria:** Ability to highlight s[…] review: Gap in risk/governance coverage; Duplication?; Clear escalation/reporting pathways; Alignment with RMF, Risk Taxonomy, Policy structure; Resource[…]. **Charter Review:** RGO must be able to flag draft Charter for completeness and appropriateness before approvals. **Approval Evidence:** Ability to allow[…] acceptable forms of approval (email, meeting minutes, signed document). **Exception Handling:** Include process for resolving disputes or exceptions via[…] Governance. **Status Tracking:** Requirement to track Committee formation status (e.g., "Approval in Progress" → "Active"). |
| G-6 | Configurable Automated Workflow | Supports Committee Formation process: Automated workflow for establishing, maintaining, and disbanding forums w[ith …] including approvals and escalations. Workflow configurations shall be administratively configurable without custom development. |
| G-7 | Support for Risk Governance Office Controls | The system shall prevent progression of Committee requests when required information, approvals, or [evidence] are incomplete or inconsistent. Ability to validate if Committee formation request form is complete and if any additional information is required. RGO val[idates] Committee and Governance Forum creation request against existing Committee and Governance Forum Inventory to prevent overlaps or conflicts. Ability to rev[iew/]challenge the draft Committee Charter for completeness and appropriateness before Requester sends it for final approvals to appropriate Sponsor or Committ[ee] authorities. Ability to validate approvals provided by Requester for Committee formation to see if these are aligned with the information provided in the [Governance] Intake Form' and Committee Charter. Ability to validate approvals before updating Committee and Governance Forum Inventory. |
| G-8 | Configurable Review and Approval Workflow | Ability to establish a multi-step approval process based on different stakeholders and roles, with sup[port for] sequential or parallel approvals. This includes documenting or capturing the Committee Charter approval. Workflows and approvals may differ based on mater[iality of] change or request and/or committee type. |
| G-9 | Version Control, Audit History, and Accountability Tracking | Ability to track all changes to forums, maintain complete history, and log actions ([…]) taken by users with timestamps. Ability to archive and see previous versions, where applicable. |
| G-10 | Forum Maintenance | Ability to set and track periodic review schedules including self-assessments, charter reviews, and monitoring activities. **[Annual] Attestation Process:** The system shall enforce an annual attestation process, conducted in Q1, requiring Committee Chairs, Secretaries, and OGFs to review [and] confirm the accuracy of the Committee and Governance Forum Inventory. |
| G-11 | Committee Disbanding | **Disbandment Workflow:** Configurable workflow for Committee disbanding, including: Trigger scenarios (annual inventory re[view,] self-assessment, Charter review, completion of mandate); Validation of approvals and closure (Delegating Authority, Sponsor, Chair, and any jurisdictional [approvals if] applicable); **Disbandment Plan Capture:** Ability to upload and track a formal Disbandment Plan. |
| G-12 | Reporting and Dashboards | The system shall provide reporting and dashboard capabilities to support effective oversight, monitoring, and governance [of] Committees and Governance Forums across the enterprise. Reports and dashboards shall enable stakeholders to view committee status, coverage, compliance, an[d] performance metrics in a timely and actionable manner. Reporting capabilities shall support filtering, aggregation, and drill-down based on key governance attributes, including committee type, status, legal entity, risk coverage, ownership, and review or attestation status. Dashboards shall be configurable to present current and historical views of governance activity, including forums in formation, active committees, upcoming reviews, overdue actions, and SLA performance. The system shall support export of reports and artifacts to meet management, audit, and regulatory reporting needs. |
| G-13 | Role-Based Access Control | Ability to provide role-based access for individuals and delegates (e.g., Committee Secretary, Forum Owners, Reviewer, Approver, Viewer, Administrator). Ability to group users based on role (e.g., LOB, 1LOD/2LOD, Legal, Compliance, voting vs. non-voting, etc.). Ability to allow Committee Chair/Sponsor/Secretary to nominate delegates for administrative tasks. |
| G-14 | Notifications | Ability to send configurable templated automated notifications for approvals, reviews, escalations, meeting schedules, annual attestation, and charter reviews, etc. |
| G-15 | Document Management | Ability to attach documents including but not limited to, templates, charters/mandates, agendas, meeting minutes, and related documents with version control. Ability to see audit log of all activity. **Archival Requirements:** System must retain all documents and history. |
| G-16 | Data and Document Retention | Ability to retain data and documents based on Retention Management Policy and applicable retention requirements. Ability to send documents and data in WORM-compliant format to retention systems. |
| G-17 | Governance Intake Form | Ability to submit a request for creating, modifying, or retiring a committee with configurable details. Ability to have the intake form be submitted with configurable workflows. Example questions include but not limited to: Are you submitting this request to create a new Committee, as defined in the Enterprise Committee and Governance Standard? What is the rationale for creating this new Committee? What is the purpose and/or scope of this proposed Committee? What are the proposed responsibilities of this Committee? Who is the delegating authority for the Committee? Do you have the delegating authority approval (not required at this time)? What is the proposed timeline of this Committee? When is the expected first meeting of the proposed Committee? **Validation by Risk Governance Office:** Requirement for RGO to check completeness and appropriateness of intake form before proceeding. |
| G-18 | Governance Intake Form Field | The system shall define and enforce a standardized set of intake form fields required to create, modify, or retire a Committee or Governance Forum. These fields shall ensure consistent capture of key identifying, ownership, and organizational information to support effective review, approval, reporting, and lifecycle management. Required fields shall be configurable, validated for completeness, and aligned to enterprise taxonomies to enable downstream governance, integration, and auditability. Examples include, but are not limited to: Document Name, Document ID, Requester, Document Type, Jurisdiction, Parent Document, Child Document, Owning Organization (OG/CS), Owning Organization (LOB), Owning Organization (BU), Document Sponsor. |
| G-19 | Integration Capabilities | The system shall support integration capabilities that enable Committee and Governance Forum data to be shared consistently across enterprise risk, governance, and escalation platforms. These integrations shall ensure that governance structures, approvals, and relationships are accurately reflected and reusable across dependent processes and systems. **Core Integration Objectives:** The system shall publish Committee and Governance Forum data for use in other modules, including Policy Management, Escalations, Risk Appetite, and Risk Identification, to support consistent selection and alignment (e.g., approving committees, escalation pathways). The system shall consume relevant data from other enterprise platforms where governance context is required. **Data Alignment and Standards:** alignment to enterprise taxonomies maintained by designated systems of record; taxonomy values synchronized with authoritative systems (e.g., Organizational hierarchy fields, Primary Risk Category, Material Entity); field mapping between source and target systems; handling rules for invalid/missing/incomplete data. **Technical and Operational Capabilities:** inbound/outbound data exchanges in formats supported by target systems; configurable integration frequency (real-time, scheduled, on-demand); integration with Active Directory (or equivalent) to enable user selection and notification routing using authoritative user data. |

### 4.2 Frappe technical mapping

| Req | Frappe implementation |
|---|---|
| G-1, G-2, G-3 | `Governance Forum` DocType with Link fields to shared taxonomy DocTypes (Legal Entity, LOB, Primary Risk Category, Governance Forum Type); native list view search/filter |
| G-4 | Self-referencing Link fields (upstream/downstream); Check field for regulatory-required flag |
| G-5, G-6, G-7, G-8 | **Committee Formation Workflow** — see §4.3 for the full state/transition design (already validated in an earlier spike) |


| G-9 | Native Version DocType + Comments, no custom work |
| G-10 | Scheduled Job (Frappe's background scheduler) + an Attestation Campaign pattern (custom DocType tracking one task per Chair/Secretary/Owner of Governance Forum per year) |
| G-11 | A second Workflow definition on the `Governance Forum` DocType (Active → Disbanded), same engine as G-6 |
| G-12 | Report Builder + Dashboard Chart, native |
| G-13 | Role Permissions Manager; delegate nomination is a custom field + validation rule |
| G-14 | Notification DocType, condition-based |
| G-15 | Native File attachments + Version log |
| G-16 | Custom webhook fired on document finalization, calling the separately-built retention system (no retention logic built here) |
| G-17, G-18 | `Committee Formation Request` DocType (the intake) + a Web Form or Desk form with required-field validation |
| G-19 | Frappe's auto-generated REST API per DocType for the outbound side; AD/OIDC integration per §6 for the Active Directory requirement |

### 4.3 Committee Formation Workflow (G-5, G-6, G-7, G-8) — detailed design

This flow was already designed and validated in an earlier architecture spike
(originally `spike-cgf-formation-design.md`). Reproduced in full here so
nothing is lost:

**DocTypes:**

- `Governance Forum` — the master record, created once formation is approved.
  Fields: `forum_id` (autoname), `forum_name`, `forum_type` (Link),
  `description`, `cadence`, `committee_chair` (Link → User),
  `primary_risk_category` (Link), `legal_entity` (Link), `owning_org_og_cs`
  (Link), `owning_org_lob` (Link), `status`, `formation_request` (Link back to
  the intake).
- `Committee Formation Request` — the intake (G-17), workflow-driven. Fields:
  `requester` (Link → User, read-only), `is_new_committee` (Check), `rationale`,
  `purpose_scope`, `proposed_responsibilities`, `delegating_authority`
  (Link → User), `delegating_authority_approved` (Check, optional per G-17's
  wording), `proposed_timeline` (Date), `first_meeting_date` (Date),
  `workflow_state`.
- `RGO Evaluation` (child table on the Formation Request, G-7):
  `gap_in_coverage`, `duplication_check`, `escalation_pathway_clear`,
  `aligned_to_rmf_taxonomy_policy`, `resource_feasibility` (all Check),
  `completeness_confirmed` (Check — gates progression), `reviewer_comments`,
  `reviewed_by`, `reviewed_on`.
- `Committee Charter`: `formation_request` (Link), `charter_document` (Attach),
  `rgo_challenge_status` (Select: Not Reviewed / Changes Requested / Cleared),
  `rgo_challenge_comments`, `approval_evidence` (Attach Multiple — G-5's
  "email, meeting minutes, signed document").

**Workflow states:** Draft → Submitted → RGO Review → (Returned for Revision |
Duplicate/Conflict) → Charter Drafting → Charter Review → Pending Final
Approval → (Approved | Exception) → Active (or Rejected).

**Transitions & guards:**

| Transition | Guard | Approval role |
|---|---|---|
| Draft → Submitted | Required fields complete | none |
| Submitted → RGO Review | automatic | none |
| RGO Review → Returned for Revision | `completeness_confirmed == 0` | RGO Reviewer |
| RGO Review → Duplicate/Conflict | `duplication_check == 0` | RGO Reviewer |
| RGO Review → Charter Drafting | all 5 RGO checklist fields `== 1` | RGO Reviewer |
| Charter Review → Charter Drafting | `rgo_challenge_status == "Changes Requested"` | RGO Reviewer |
| Charter Review → Pending Final Approval | `rgo_challenge_status == "Cleared"` | RGO Reviewer |
| Pending Final Approval → Approved | approval evidence attached | Sponsor / Committee Authority |
| Pending Final Approval → Exception | manual | Head of Risk Governance |
| Exception → RGO Review / Rejected | manual decision | Head of Risk Governance |
| Approved → Active | automatic (creates/activates the Governance Forum record) | none |

> Transcriber's note: the Approval-role column on the last four rows was hard to
> read in the photo. The reading above is the one consistent with the RBAC line
> immediately below (Sponsor/Committee Authority acts only at Pending Final
> Approval; Head of Risk Governance only at Exception). Verify against source.

**RBAC for this flow:** Requester (own records only) · RGO Reviewer (RGO
Review/Charter Review states) · Sponsor/Committee Authority (Pending Final
Approval only) · Head of Risk Governance (Exception state only) · Committee
Secretary (read Active forums) · Administrator (full + workflow authoring).

**Disbandment (G-11)** follows the same engine pattern, a second workflow on
`Governance Forum`: Active → Disbanded, gated on validated approvals from
Delegating Authority, Sponsor, Chair, and jurisdictional CRO where applicable,
with a `Disbandment Plan` attachment required.

---

## 5. Module: Policy Management (P-1..P-26)

### 5.1 Requirements (full text)

| Req | Title | Description |
|---|---|---|
| P-1 | Policy Repository | The system shall provide a centralized, searchable policy repository that stores all policy documents and associated metadata. Access, visibility, and permitted actions shall be governed by role-based access controls (RBAC). This includes all policy document types including but not limited to: Frameworks, Policies, Standards, Procedures, and Supporting Documents. The system shall include controls to identify and apply special handling for confidential or restricted documents, ensuring that access, visibility, and actions (e.g., download, print, share) are limited to authorized roles. |
| P-2 | Search and Retrieval | Advanced search capabilities allow users to search and filter policy documents by metadata. |
| P-3 | Policy Tagging | The system shall support metadata-driven policy tagging using controlled fields, field dependencies, and standardized taxonomies aligned with enterprise systems. Metadata shall include, at a minimum: Document identifiers (name, ID, type); Ownership and accountability roles; Organizational alignment; Risk classification and applicability; Lifecycle status and relationships. Examples include, but are not limited to: Document Name, Document ID, Key Contact, Document type, Jurisdiction, Parent Document, Child document(s), Primary Risk Category (Common Taxonomy), Legal Entity (Common Taxonomy), Owning Organization (OG/CS) (Common Taxonomy), Owning Organization (LOB) (Common Taxonomy), Direct Document Link, Training Required, Attachments, Document Approver, Document Liaison, Document Owner, Document Delegate (Optional), Document Sponsor, Line of Defense, Material Entity (Y/N), Legal Entity, Lifecycle Phase. |
| P-4 | Policy Mapping & Parent-Child Lineage | Ability to map policy documents to related policy documents, & view 'policy families' in a dashboard. Examples include but are not limited to: Parent Document, Child Document(s), Addendum. |
| P-5 | Policy Mapping | Ability to map/link policy documents to other risk programs. Examples include but are not limited to: Risk assessments, Process, Risks, and Controls, Training, Regulatory Requirements Indicator (future Regulatory Library link), Related Issues. |
| P-6 | Regulatory Linkage | The system shall allow policies to be designated as regulatory-required (Yes/No). When marked "Yes," the system shall require capture of relevant regulatory details through dependent fields. Ability to maintain linkage of policy documents to applicable law, rule, regs, or standards. Ability to integrate with regulatory databases, if available, to synchronize references and effective dates. Ability to integrate with program to track regulatory changes and notify impacted policy owners. |
| P-7 | Configurable Automated Workflow | Ability to configure automated workflows for every stage of the policy lifecycle based on policy document type and type of change. The workflow configuration must support conditional logic to route tasks appropriately, tracking and reporting of SLAs for all lifecycle steps, and alerts for approaching or breached SLA thresholds. Workflow configurations shall be administratively configurable without custom development. |
| P-8 | Configurable Review and Approval Workflow | Ability to establish a multi-step approval process based on different stakeholders and roles, with support for sequential or parallel approvals. Capabilities include but are not limited to: parent policy owners approving changes to child documents where necessary; automated routing, reminders, and escalations; real-time approval tracking incl. timestamps/comments/signoffs; forms and workflows for Exception Requests and Exemptions; routing approvals/notifications to user groups; role-based assignment of approval steps; conditional logic for approval paths based on policy type/change type/risk level; full audit trail. **Horizon scanning notifications:** notify policy owners when horizon scans are due; track completion of manual horizon scans; trigger downstream workflows after scans. |
| P-9 | Version Control, Audit History, and Accountability Tracking | Ability to track all changes to policy documents, maintain complete history, and log all actions and changes taken by users with timestamps. Ability to archive and see previous versions, where applicable. |
| P-10 | Policy Maintenance | The system shall support periodic policy reviews by enabling scheduling, notifications, SLA tracking, and documentation of review outcomes. Notification when periodic reviews are scheduled to begin and when due; SLA tracking for overdue periodic reviews; logging of periodic review results. |
| P-11 | Policy Monitoring and Control Activities | Ability to set and track EPO monitoring activities for policy documents: define/track/report monitoring activities per policy; schedule and send notifications when due; log results of monitoring activities; configure a dashboard for EPO with monitoring results; maintain auditable records. |
| P-12 | Reporting and Dashboards | The system shall provide reporting and dashboard capabilities to support oversight, monitoring, and management of policy governance across the enterprise, enabling stakeholders to view policy status, lifecycle progression, compliance, coverage, and performance metrics. Reporting shall support filtering, aggregation, and drill-down by policy type, lifecycle status, ownership, risk category, legal entity, applicability, review status, and SLA performance. Dashboards configurable for current/historical views incl. policy families, parent-child relationships, upcoming/overdue reviews, monitoring outcomes, exceptions, violations. Export of reports/dashboards/artifacts for management/audit/regulatory needs. |
| P-13 | Role-Based Access Control | The system shall provide RBAC to ensure access to policy documents/data/actions is restricted based on defined roles, responsibilities, and delegated authority, enforcing segregation of duties. Access controls govern creation, editing, review, approval, monitoring, reporting, upload, publication activities. Roles configurable for Policy Owner, Reviewer, Approver, Viewer, Administrator, and organizational groupings (LOB, Legal, Compliance). Support for delegation with accountability/auditability. Enhanced controls for confidential/restricted documents (view/download/print/share limited to authorized users). All access assignments/changes/actions logged. |
| P-14 | Notifications | Ability to send configurable, templated, automated notifications across all stages of the policy lifecycle (drafting comments/revisions, review, approval, publication, maintenance activities incl. monitoring/annual assessments/periodic reviews). Templates configurable with dynamic fields (policy name, due dates, responsible parties), multiple delivery channels (email, in-app). Conditional triggers based on events/deadlines/SLA breaches. |
| P-15 | Policy Document Templates | Ability to create and configure templates for drafting different document types (Frameworks, Policies, Standards, Procedures, Supporting Documents) and action combinations (New/Edit/Retire/Review): templates align with corporate format incl. cover page with required metadata; predefined sections/formatting; configurable creation of new document types/templates without custom development; collaboration tools for real-time feedback/revisions/redlining during drafting/review; version comparison during drafting/review; standardized naming conventions enforced; hyperlinks for related documents/regulatory references; required fields. |
| P-16 | Policy Intake Templates | The system shall provide the ability to create/configure an intake form for requests to create, change, or retire a policy document. For changes to an existing document, the system must present a dynamic set of questions that automatically determine whether the change is classified as major or minor, which drives approval requirements, review steps, and escalation paths. Must enforce required fields, standardized naming conventions, and maintain version history + rationale for change classification. **Dynamic Questioning:** targeted questions (e.g. "Does this impact compliance obligations?", "Does this alter core policy principles?"); responses determine classification — Major Change (significant revisions/new sections/compliance impact → full re-approval workflow) vs Minor Change (cosmetic/metadata updates → streamlined workflow). Classification drives routing/approval steps/SLA tracking. Full audit trail of intake submissions, classification logic, workflow actions. |
| P-17 | Document Management | Ability to attach documents with no limitations on document type or number of documents. Ability to see an audit log of all activity. |
| P-18 | Data and Document Retention | Ability to retain data and documents based on Retention Management Policy and applicable retention requirements. Ability to send documents and data in WORM-compliant format to retention systems. |
| P-19 | Publication | Ability to publish policy documents with controlled access including but not limited to general employees, restricted access, or targeted groups. Must support secure publishing options (view-only, print-enabled, downloadable PDF) based on role-based permissions. Ability to retain retired/superseded policy documents with version history. |
| P-20 | Integration Capabilities | The system shall support integration capabilities that enable policy data to be exchanged consistently across enterprise risk, governance, and related platforms, keeping policy information/metadata/relationships aligned with authoritative enterprise sources. **Core Integration Objectives:** inbound/outbound data exchanges with internal/external systems (issue management, process/risk/control systems, regulatory change, governance and escalation platforms); reuse of policy data/metadata by dependent systems; configuration and field mapping for source/target compatibility. **Data Alignment and Standards:** alignment to enterprise taxonomies from designated systems of record (Organizational hierarchy, Primary Risk Category, Material Entity); field mapping; handling rules for invalid/missing/incomplete data. **Technical and Operational Capabilities:** configurable integration methods/frequencies (real-time/scheduled/on-demand); data exchange formats supported by source/target systems *(remainder of this requirement is truncated in the converted source file at ~2000 characters — confirm complete text against the original the Policy Management requirements document before finalizing build scope for this item)*. |
| P-21 | Applicability Management | Ability to maintain applicability for each policy. Automated notifications to applicable parties when a policy is created, changes, or is retired. Applicability includes but not limited to: Business units/subsidiaries/material entities; Jurisdictions (provincial/federal/international); Roles or functions responsible for compliance; Formal exemptions and deviations with approvals. |
| P-22 | Violation and Issue Management | Capture details such as the policy reference, violation type, date, responsible party, and corrective actions. Must support linking logged incidents to external issue management systems (e.g., the enterprise GRC system) through configurable integrations or APIs, if necessary. All logged violations maintain an audit trail and are reportable for compliance monitoring/governance. (Policy Violation Location is to be confirmed.) |
| P-23 | Missing Field Maintenance | Ability for policy owners and EPO to identify changes to required fields. Example: If a Parent Document (required) is retired, then a child document must be notified and take action to realign to a new Parent Document. |
| P-24 | Glossary Management | Ability to maintain glossary of policy terms both at the Enterprise level and other levels (e.g., document or document family level). The system must enforce the use of official definitions by preventing users from creating/applying terms not defined in the approved glossary. Glossary terms linkable to documents for contextual help. Version control and complete audit trail for all glossary changes. |
| P-25 | Approval Management | The system shall enforce a mandatory approval process as a control measure prior to publication of any policy document. No policy document may be published without completing all required approvals based on its classification (new/major revision/minor revision). Approval workflow configurable for multiple steps/roles (Policy Owner, Compliance, Legal, Accountable Executive), sequential or parallel. Full audit trail of approvals incl. timestamps/approver identity/decisions; prevent bypassing/overriding without documented exception authorization. |
| P-26 | Policy Editor | The system shall provide a structured policy editing and review capability supporting collaborative drafting, formal review, controlled disposition of feedback, and full auditability. **Review Stage Management:** transition to a designated Review Stage; configurable reviewer assignments by role/group/policy characteristics; sequential or parallel review. **Feedback and Disposition:** inline comments/revision suggestions within the document; Policy Owner views/assesses/dispositions feedback in real time (accept/reject/request clarification) without exiting the workflow; automatic notification to feedback originator of the disposition decision. **Version Control and Auditability:** version control throughout editing/review with visibility of all changes; all comments/dispositions/edits/notifications captured in a complete audit trail with timestamps/attribution; prior versions retained per document retention requirements. **Collaboration and Transparency:** real-time visibility into review progress/outstanding feedback; collaborative editing features preserving governance controls. |

**Note per direction: P-26's Policy Editor is confirmed already built** — this
is an *integration* task (wire it into the review workflow above), not new
development. Confirm what interface it exposes (API, embed, or shared DB)
before scoping the integration work precisely.

### 5.2 Frappe technical mapping

| Req | Frappe implementation |
|---|---|
| P-1, P-2, P-3 | `Policy` DocType with confidential-document permission rule; Link fields to shared taxonomy |
| P-4 | Self-referencing Link (parent/child/addendum) + a Tree View or custom dashboard for "policy families" |
| P-5 | Link fields to other modules — targets (Risk Assessments, PRC, Training, Issues) are external systems not yet confirmed (see §8) |
| P-6 | Link/Select fields for regulatory Yes/No + dependent fields; DB sync itself is a deferred connector (§8) |
| P-7, P-8, P-25 | Workflow DocType — full lifecycle (Draft→Review→Approved→Published→Retired) with SLA tracking via Frappe's Assignment Rule/SLA feature |
| P-9 | Native Version log |
| P-10 | Scheduled Job + Notification |
| P-11 | Custom `EPO Monitoring Activity` DocType + Dashboard |
| P-12 | Report Builder + Dashboard Chart |
| P-13 | Role Permissions Manager, field/record-level rules for confidential docs |
| P-14 | Notification DocType |
| P-15 | Print Format templates (configurable without code) |
| P-16 | Custom server/client script implementing the major/minor decision logic — **genuine business-rule build, needs precise rules from business, not a native feature** |
| P-17 | Native File attachments |
| P-18 | Webhook to the separate retention system |
| P-19 | Role-based Print Format access |
| P-20 | REST API/Webhooks; external targets unconfirmed (§8) |
| P-21 | Multi-select Table field + Notification |
| P-22 | Custom `Policy Violation` DocType + link to the enterprise GRC system (§8) |
| P-23 | Server-side validation triggered on parent-document retirement |
| P-24 | Custom `Glossary Term` DocType with enforced-term validation + native Version log |
| P-26 | **Integration**, not build — wire the existing editor into the P-8 review workflow; AI-assisted drafting features call the AI services platform adapter (§7) |

### 5.3 Horizon Scanning (P-8's sub-requirement) — its own module

Per direction, Horizon Scanning is scoped as its own capability, not folded
into the general Policy workflow:

- **External regulatory/web-data scanning already exists** (some tool/process
  today, per direction) — **not rebuilt**, only connected to. The specific
  tool/team is not yet named anywhere in the source material — this is an open
  item, not an assumption (see §10, Open Questions).
- **What's net-new: the internal mapping/correlation engine** — matching each
  external finding against our own policies, risk categories, business units,
  and jurisdictions. This does not exist today and is the real build effort
  here.
- **the AI services platform-assisted triage** — classify/summarize incoming findings, suggest
  likely impacted policies/risk categories (see §7 for the AI services platform adapter).
- On completion, if a finding requires a policy update, **auto-trigger the
  P-16 change-classification workflow**, pre-linked to the scan record.

*(batch 2 ends at line 263 — continues in next batch)*
## 6. Module: Escalation Management (E-1..E-19)

### 6.1 Requirements (full text)

| Req | Title | Description |
|---|---|---|
| E-1 | Escalation Matters Repository | The system shall provide a centralized, searchable Escalation repository that stores Escalation details and associated metadata. Access, visibility, and permitted actions shall be governed by RBAC. |
| E-2 | Search and Retrieval | Advanced search capabilities allow users to search and filter Escalation Matters by metadata. |
| E-3 | Escalation Event Tagging | Ability to click into Escalation Matters using metadata (with field dependencies) and common taxonomy with other systems, controlled via dropdowns. Examples include but not limited to: Escalation Title, Escalation ID, Escalation Type, Escalation Identification Date, Escalation Matter Description, Tier 1 Risk Type, Tier 2 Risk Type (if applicable), Impacted Entity, Escalation Matter Identifier (person), Organizational Level Identifier for Escalation, Accountable Executive. |
| E-4 | Escalation Triggers | The system shall support predefined escalation triggers, including adverse events and risk appetite breaches, as defined in approved Escalation Matrices. Trigger severity ratings (High/Medium/Low) shall determine routing and escalation pathways. |
| E-5 | Escalation Event Logging and Submission | The system shall enforce required data fields for escalation intake while allowing optional fields based on escalation type and severity. Includes logging initial intake which can be routed to additional individuals using configurable workflows to populate additional details and receive approvals. |
| E-6 | Configurable Escalation Templates | Ability to configure templates based on Escalation Matter types, with standardized (required) fields across templates. |
| E-7 | Escalation Event Mapping | Ability to select Committee and Governance Forums as Escalation Pathway pulling from the Committee and Governance Forum module. Ability to pull in Committee and Governance Forum user details (e.g., Committee Secretary and others) and send notifications. |
| E-8 | Configurable Automated Workflow (e.g., Action Plan, Risk Acceptances) | Automated workflow for logging, reviewing, actioning, and resolving Escalation Matters. Includes configuring users using roles and groups; attaching and approving closure documents; configurable workflows/pathways/roles based on Escalation Matter type and severity. System stores/references Escalation Matrices for automated routing. When a Material Entity (ME) impact flag is selected, automated notification to relevant Committee and Governance Forum. Where an Escalation Matter is triggered by a Risk Appetite breach, ability to flag the breach and follow the breach workflow. Workflow configurations administratively configurable without custom development. |
| E-9 | Configurable Review and Approval Workflow | The system shall support a structured, role-based escalation review and approval process for appropriate challenge, accountability, and timely decision-making. **Review and Challenge:** multi-step review workflows based on defined roles and escalation severity; workflow steps support Second Line of Defense (2LOD) effective challenge, including configurable SLAs prior to escalation to Accountable Executives or Governance Forums; review actions/comments/outcomes captured and retained in the audit trail. **Approval and Accountability:** configurable approval workflows (sequential/parallel) aligned to escalation type/severity/organizational hierarchy; Risk Acceptance workflows include documented approvals and periodic reassessment; accountability tracked by role (approvers, reviewers, response owners) with timestamps/decision records. **Escalation Pathways and Exceptions:** configurable escalation pathways aligned to Committee/Governance Forum structures and organizational hierarchy; delegation of escalation routing responsibilities where permitted; exception handling, restricted access for sensitive escalations, escalation to Head of Enterprise Risk for systemic issues. Completion of the Escalation Response Template mandatory for all escalations, including those in external systems (e.g., the enterprise GRC system). |
| E-10 | Escalation Closure Criteria | System to enforce closure criteria and maintain auditable evidence. |
| E-11 | Quarterly Submission & Tracking | Capability to generate reports directly from system to replace manual submissions, enabling automated quarterly tracking and reporting. Automated reminders and "no activity" confirmation workflow. |
| E-12 | Version Control, Audit History, and Accountability Tracking | Ability to track changes to Escalation Matters and maintain a complete history and log of actions taken by users with timestamp, and maintain history of version. |
| E-13 | Service Level Agreement (SLA) Tracking | The system shall track SLAs for workflow steps, status durations, and total time-open metrics to support performance monitoring and escalation oversight. |
| E-14 | Escalation Status Management | The system shall manage escalation lifecycle statuses, including but not limited to: "Open", "Under Review", "Closed – Tracked in the enterprise GRC system". |
| E-15 | Reporting and Dashboards | The system shall provide reporting and dashboard capabilities to support oversight, monitoring, and analysis of Escalation Matters across the enterprise, enabling stakeholders to view status, trends, and performance metrics. Filtering/aggregation by status, severity, risk type, governance forum, accountable executive. Dashboards configurable for real-time/historical views incl. SLA progress, upcoming actions, recurring/systemic themes. Export of reports/artifacts for management/audit/regulatory needs. |
| E-16 | Role-Based Access Control | Ability to provide role-based access for individuals and delegates. Group users based on role (e.g., Escalator, Accountable Executive or Committee and Governance Forum, Response Owner, Second Line of Defence, RGO). Associate responsibilities for each role. Flag and restrict access to escalations deemed 'sensitive'. |
| E-17 | Notifications | Ability to send configurable templated automated notifications to users and email groups across the Escalation lifecycle. |
| E-18 | Data and Document Retention | Ability to retain data and documents based on Retention Management Policy and applicable retention requirements. Ability to send documents and data in WORM-compliant format to retention systems. |
| E-19 | Integration | The system shall support integration capabilities that enable Escalation Matters to be created, updated, and tracked consistently across enterprise risk, governance, and issue management platforms. **Inbound Integration:** receiving data from external systems (issue management, operational risk events, risk appetite monitoring) to automatically create Escalation Matters with pre-populated data; field mapping for completeness/consistency/traceability; validation and handling rules for missing/invalid/incomplete information. **Outbound Integration:** sending escalation data to external systems (issue management platforms) for downstream tracking/resolution/reporting; field mapping to populate target records accurately with linkage maintained; synchronization of status and key attributes where applicable. **Governance and Escalation Alignment:** selection of Committees/Governance Forums as escalation pathways using authoritative data from the CGF platform; linkage to related risk identifiers (e.g., the risk identification system) for end-to-end traceability; restricted data handling for sensitive escalations per access control requirements. **Technical and Operational Considerations:** integration methods/frequencies (real-time/scheduled/on-demand) configurable *(remainder of this requirement is truncated in the converted source file at ~2000 characters — confirm complete text against the original the Escalation Management requirements document before finalizing build scope for this item)*. |

### 6.2 Frappe technical mapping

| Req | Frappe implementation |
|---|---|
| E-1, E-2, E-3 | `Escalation Matter` DocType, Link fields to shared taxonomy |
| E-4 | Custom `Escalation Matrix` DocType feeding severity-based routing into the workflow |
| E-5, E-6 | DocType field config per escalation type + Workflow intake |
| E-7 | Link field to `Governance Forum` (consumes the G-19 publish API) |
| E-8 | Workflow + custom routing rules for action plans/risk acceptance/ME-impact flag; **confirmed per direction: writes to both the CGF module and the Risk Appetite system**, not either/or |
| E-9 | Workflow with multi-step 2LOD challenge, exception states, role-based restricted access — genuine custom business logic, same effort regardless of platform |
| E-10 | Workflow guard condition + mandatory fields on closure |
| E-11 | Scheduled Job + Report, reminder logic |
| E-12 | Native Version log |
| E-13 | Frappe's native SLA/Assignment Rule feature |
| E-14 | Workflow states |
| E-15 | Report Builder + Dashboard Chart |
| E-16 | Role Permissions + a `sensitive` flag restricting record visibility |
| E-17 | Notification DocType |
| E-18 | Webhook to the separate retention system |
| E-19 | REST API/Webhooks; the enterprise GRC system and Risk Appetite are real connectors needing discovery (§8); CGF consumption reuses G-19's publish API |

---

## 7. Shared/Core Platform Requirements

These aren't separate requirement IDs but cross-cutting capabilities every
module depends on — build once, reuse everywhere:

| Capability | Frappe mechanism | Used by |
|---|---|---|
| Shared taxonomy (Legal Entity, LOB, Primary Risk Category, Governance Forum Type, Organization) | Reference DocTypes with seed data | All three modules (repeatedly required as "Common Taxonomy" across G-3, P-3, E-3) |
| RBAC incl. confidential/restricted document handling | Role Permissions Manager + field-level rules | G-1/G-13, P-1/P-13, E-1/E-16 |
| Audit trail / version history | Native Version log | G-9, P-9, E-12 |
| Notification framework | Notification DocType | G-14, P-14, E-17 |
| **the AI services platform integration adapter** | REST client against the client's AI gateway converse endpoint — **already built and tested** in this project's `llm/llm_client.py` (same endpoint the "Digital Worker"/the AI services platform on-prem app uses: `POST /apis/services/unified`, resource `/api/llm/converse`, at an internal gateway host). **Confirmed limitation: text-only** — the same client's image/multimodal path was live-tested and returns HTTP 500, so treat the AI services platform here as text-in/text-out only until proven otherwise. Used by the Policy Editor (P-26, smart drafting) and Horizon Scanning (§5.3, triage/summarization) — **not** a general-purpose replacement for the platform itself. | P-26, Horizon Scanning |
| AD/OIDC authentication | Frappe's native LDAP or OAuth/OIDC integration app | All three (each requirement doc references AD/equivalent for user/role sync) |
| Document retention hook | Custom webhook fired on document finalization, calling the **separately-built** retention/WORM system (not built here) | G-16, P-18, E-18 |

---

## 8. Data Connector Inventory

Every external system referenced anywhere in the three requirement docs.
Marked honestly: **Known** (confirmed from this project's own files or explicit
direction), **Assumed** (a reasonable default for *our* side of the integration
only), or **Unknown** (genuinely undiscovered — not guessed at).

| System | Direction | Reqs | What's actually known | Status |
|---|---|---|---|---|
| Active Directory / OIDC | Inbound (auth) | G-19, P-20, E-19 | **Unknown** which the client uses (LDAP vs Azure AD/OIDC) — needs IT confirmation | Needed from day one |
| CGF → Policy/Escalation | Internal | G-19 | **Known** — our own platform, Frappe's native REST API | Build early (blocks E-7, P-5 cross-links) |
| the AI services platform | Bidirectional | P-26, Horizon Scanning | **Known concretely** — see §7 | Build early |
| External horizon-scanning data source | Inbound | P-8 | **Unknown** — confirmed to exist and partially done per direction, but not named anywhere in source material | Needs discovery |
| the enterprise GRC system | Bidirectional | P-22, E-14, E-19 | **Unknown** — no API contract, auth model, or protocol confirmed anywhere | Needs discovery before it can be sized |
| Risk Appetite system | Bidirectional | E-4, E-19, G-19 | **Unknown** specific system/vendor — referenced only conceptually | Needs discovery; **confirmed design decision: Escalation feeds both CGF and Risk Appetite** |
| Risk Identification (the risk identification system) system | Outbound | P-5, E-19 | **Unknown — flagging a hypothesis, not a fact**: may be the same "the risk identification system" the incumbent GRC platform project referenced in the originating email. Needs a direct question, not an inference | Needs discovery |
| Process/Risk/Control (PRC) system | Outbound | P-5, P-20 | **Unknown** — not even the target system's identity is confirmed | Needs discovery |
| Training system | Outbound | P-5 | **Unknown** — no system named | Needs discovery |
| Retention/WORM system | Outbound | G-16, P-18, E-18 | **Known** — built separately by another workstream; this platform only calls it | Hook only, not built here |

**For every "Unknown" row: run a discovery conversation with that system's
owning team before writing any integration code.** Do not assume a REST API,
auth model, or data format — none of that is confirmed anywhere in the source
requirements.

---

## 9. Deployment & Cloud Migration

- **Environment:** Linux required for `bench` (Docker via `frappe_docker`
  recommended, or a properly provisioned Linux dev server/VM). See §2's
  environment note — do not assume WSL2 works without verifying outbound
  network access first.
- **Database:** MariaDB (Frappe is MariaDB-first; PostgreSQL support is
  second-class — don't default to Postgres based on generic best practice).
- **File storage:** configure S3-compatible object storage **from day one** —
  Frappe defaults to local-disk attachments, and migrating those to cloud
  storage later is a real project, not a config change.
- **Migration mechanic:** `bench backup` (DB dump + files) → `bench restore` on
  the target environment — this is Frappe's own native tooling, already the
  right path, just needs to be rehearsed before it's relied on.
- **Package installation:** if the build environment has the same corporate
  network restrictions encountered previously, check whether an internal
  Artifactory/package-mirror is available and point `apt`/`pip`/`npm` at it
  instead of the public internet — this was identified as a likely fix for the
  earlier WSL2 blocker but was not verified end-to-end.

> ⚠️ **TRANSCRIBER'S NOTE — §9 conflicts with what has since been proven.**
> Both the Environment and Database bullets are now out of date:
> - Native Windows + PostgreSQL 16 runs, with no Docker, WSL2 or Linux VM
>   (winbench Phases 0–2 passed on the client laptop: Desk UI, workflow engine,
>   audit trail, 8/8 smoke checks).
> - The whole port is **PostgreSQL**, not MariaDB. The "don't default to
>   Postgres" advice is the opposite of the delivered stack.
> - `bench backup`/`bench restore` → `winbench backup` (pg_dump-based),
>   already verified including a tar-binary-free restore.
> - The internal package-mirror point is correct and was the resolution path:
>   150 PyPI packages verified obtainable, npm eliminated entirely via a
>   prebuilt asset bundle.
>
> §9 needs a rewrite before the build team provisions anything.

---

## 10. Open Questions (need direct answers, not assumptions)

1. **What is the existing external horizon-scanning tool/process** referenced
   in the source PPTX and confirmed partially built per direction? Needed to
   scope and build the connector in §5.3.
2. **Is the "Risk Identification (the risk identification system) system"** referenced in P-5/E-19/
   G-19 the same system as the "the risk identification system" the incumbent GRC platform project mentioned in the
   originating email? Confirm before treating them as either the same or
   different systems.
3. **the enterprise GRC system, Regulatory Database, Risk Appetite, PRC, and Training system**
   owners/APIs — none are named in the source material; each needs its own
   discovery conversation before integration work can start.
4. **What interface does the already-built Policy Editor (P-26) expose** —
   API, iframe embed, or shared database? Determines the actual integration
   approach in §5.2.
5. **P-20 and E-19's final sentences are truncated** in the converted source
   document used to write this PRD — confirm against the original `.docx`
   files before finalizing scope for those two requirements specifically.
6. **AD/OIDC specifics** — which protocol and endpoint the client's Active Directory
   (or equivalent) actually exposes, needed for the auth integration in §7.

---

## 11. Traceability Summary

All 64 requirements are covered: G-1..G-19 (§4), P-1..P-26 (§5), E-1..E-19
(§6). Cross-cutting requirements referenced by more than one module
(version/audit — G-9/P-9/E-12; RBAC — G-13/P-13/E-16; notifications —
G-14/P-14/E-17) are built **once** as shared Core services (§7) and reused,
not duplicated per module — this is a deliberate design decision, not a gap.

*(end of document — line 413)*

---

## Side-panel notes captured alongside (provenance)
- P-20 and E-19 have truncated final sentences in the source conversion — noted
  in the document itself rather than inventing the missing text.
- This is a **new document, not a recovered one**. The earlier Frappe-mapped
  delivery plan was overwritten in place during the FastAPI conversion, and that
  workspace isn't under git, so it wasn't recoverable. This PRD is a
  from-scratch reconstruction done against the original source requirements.
