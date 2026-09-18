# Data Model & Schema — Policy / Escalation / CGF platform

> **Read `DECISIONS.md` first.** Five directives now override parts of this
> document: the AI services platform is a separate app called for all AI services (D-1); the
> document editor is a separate app (D-2); the PPTX role sets are all in scope
> (D-3); version **revert** is in scope and must be built (D-4); the `Directive`
> document type is legacy and is not modelled (D-5).


Requested by the sponsor (the client). Derived from `PRD-frappe-build.md` (64 requirements),
`DIRECTIVES-stakeholder.md`, and
`SOURCE-Escalation-Mgmt-Requirements.md` (the **original** Escalation .docx —
authoritative where it differs from the reconstructed PRD).

**Provenance is marked throughout:**
- 🟢 **From PRD** — field/entity stated explicitly in the PRD (mostly §4.3, which
  gave exact field names for the CGF formation flow).
- 🟡 **Derived** — entity/field required to satisfy a numbered requirement, but
  the PRD did not name it. Proposed here; needs sign-off.
- 🔴 **Blocked** — cannot be specified until an §8/§10 open question is answered.

Target DB is **PostgreSQL** (per the winbench port), not MariaDB.

---

## 1. How Frappe's schema actually works

Before the entity list, the three mechanics that shape everything below:

| Concept | Physical result in Postgres |
|---|---|
| **DocType** | One table, `tab<DocType Name>` (e.g. `tabGovernance Forum`) |
| **Child table** | Its own DocType/table, rows tied to the parent by `parent`, `parenttype`, `parentfield`, `idx` |
| **Link field** | A `varchar(140)` holding the target row's `name` (its primary key) — **not** an integer FK. Referential integrity is enforced by the framework, not by a DB constraint |
| **Every table** | Inherits `name` (PK, varchar 140), `owner`, `creation`, `modified`, `modified_by`, `docstatus` (0 draft / 1 submitted / 2 cancelled), `idx` |
| **Workflow state** | A plain field (conventionally `workflow_state`) on the doctype; transitions live in the `Workflow` config, not in the table |
| **Audit trail** | Framework-managed `tabVersion` rows (JSON diff per change) + `tabComment`. **Satisfies G-9 / P-9 / E-12 with no custom tables** |

**Consequence for reporting:** there are no DB-level foreign keys. Any BI tool
pointed at this schema must join on `name` strings, and must filter
`docstatus != 2`.

---

## 2. Shared / Core entities (build first — everything depends on them)

PRD §7 requires these once, reused across all three modules. Each is a simple
reference DocType with seed data.

| DocType | Purpose | Referenced by |
|---|---|---|
| 🟢 `Legal Entity` | Common Taxonomy | G-3, P-3, E-3 |
| 🟢 `Line of Business (LOB)` | Common Taxonomy — Owning Organization | G-3, P-3 |
| 🟢 `Organization (OG/CS)` | Common Taxonomy — Owning Organization | G-3, P-3, G-18 |
| 🟢 `Primary Risk Category` | Common Taxonomy | G-3, P-3, E-3 |
| 🟢 `Governance Forum Type` | Common Taxonomy | G-3 |
| 🟡 `Jurisdiction` | Required by G-18, P-3, P-21 | G-18, P-3, P-21 |
| 🟡 `Document Type` | Framework/Policy/Standard/Procedure/Supporting | P-1, P-3, G-18 |
| 🟡 `Business Unit (BU)` | Named in G-18's field list | G-18 |
| 🟡 `Risk Type Tier 1` / `Risk Type Tier 2` | E-3 names both tiers explicitly | E-3 |
| 🟡 `Material Entity` | P-3/P-21 treat as flag + taxonomy | P-3, P-21, E-8 |

**Standard shape for each:** `name` (the code/label), `description`, `is_active`
(Check), `parent_<self>` (Link, where hierarchical — LOB and Organization are).

> 🔴 **Seed data is an open question.** The PRD says these taxonomies are
> "maintained by designated systems of record" and "synchronized with
> authoritative systems" (G-19, P-20, E-19) — but §8 marks every one of those
> source systems **Unknown**. Decide now whether v1 ships with manually seeded
> taxonomy (and a later sync), because it blocks every other entity.

---

## 3. Module: Committee & Governance Forum

### 3.1 `Governance Forum` — the master record 🟢

Fields exactly as PRD §4.3 specifies:

| Field | Type | Notes |
|---|---|---|
| `forum_id` | Data (autoname) | 🟢 naming series |
| `forum_name` | Data | 🟢 |
| `forum_type` | Link → `Governance Forum Type` | 🟢 |
| `description` | Text | 🟢 |
| `cadence` | Data/Select | 🟢 |
| `committee_chair` | Link → `User` | 🟢 |
| `primary_risk_category` | Link → `Primary Risk Category` | 🟢 |
| `legal_entity` | Link → `Legal Entity` | 🟢 |
| `owning_org_og_cs` | Link → `Organization (OG/CS)` | 🟢 |
| `owning_org_lob` | Link → `Line of Business` | 🟢 |
| `status` | Select | 🟢 In Formation / Approval in Progress / Active / Disbanded (G-5 names the last two) |
| `formation_request` | Link → `Committee Formation Request` | 🟢 back-link to intake |
| `workflow_state` | Data | 🟡 for the G-11 disbandment workflow |
| `regulatory_required` | Check | 🟡 G-4 |
| `regulatory_requirements` | Table → `Forum Regulatory Requirement` | 🟡 G-4 |
| `upstream_forums` / `downstream_forums` | Table → `Forum Link` | 🟡 G-4 self-referencing mapping |
| `secretary` / `sponsor` | Link → `User` | 🟡 named as roles in G-13 |
| `next_review_date` / `last_attestation_date` | Date | 🟡 G-10 |
| `members` | Table → `Forum Membership` | 🆕 **PPTX slide 12** — voting/non-voting per G-13. **Was missing entirely.** |
| `governance_responsibilities` | Table/Select (Oversight, Decision Making) | 🆕 PPTX |
| `regulatory_compliance_status` | Select (Compliant / Non-Compliant / Pending / Not Applicable) | 🆕 PPTX |
| `escalation_protocol` / `escalation_threshold` | Text / Data | 🆕 PPTX — **what makes E-7's "forum as escalation pathway" work** |
| `approval_status` | Select | 🆕 PPTX — for *changes* to the forum, distinct from formation status |
| `jurisdiction` | Link/Table | 🆕 PPTX (multi-select) |

> 🔴 **Cardinality conflict — resolve before building.** PPTX slide 12 says
> **Business Units, Risk Types, Legal Entities and Jurisdiction are
> multi-select**. The .docx G-3 and the PRD §4.3 spike treat them as single
> values, which is how they are modelled above. A Link field and a child table
> are **not interchangeable once data exists**. The .docx is newer, but it is
> also the document that lost E-6's template lists and copy-pasted G-18 from
> Policy — so newer does not automatically mean righter. **Ask the authors.**

### 3.1b `Forum Membership` (child table) 🆕

From PPTX slide 12 (`Membership`) + G-13 (*"voting vs. non-voting"*):
`member` (Link → User), `role` (Select: Chair / Secretary / Sponsor / Member),
`voting` (Check), `start_date`, `end_date`, `is_delegate` (Check),
`delegated_by` (Link → User).

**This entity was absent from the data model entirely.** A committee without
members is not a committee — it blocks G-13, G-14 (notify members), E-7 (pull
forum user details) and the G-10 attestation.

### 3.1c `Forum Risk Link` (child table) 🆕

From PPTX slide 14 item 1 (*"link governance forum to identified risks (risk Id
or categories) and their assessments"*): `risk_id` (Data or Link → an external
risk register — **source system Unknown**), `risk_category` (Link → Risk
Category taxonomy), `assessment_ref` (Data/URL), `linked_on` (Date).

Overlaps the multi-select **Risk Types** field from the PPTX CGF field list —
decide whether risk tagging is one child table carrying both category and
specific risk IDs, or two separate structures. One table is cheaper and does not
lose anything.

### 3.2 `Committee Formation Request` — the intake (G-17) 🟢

| Field | Type |
|---|---|
| `requester` | Link → `User`, read-only 🟢 |
| `is_new_committee` | Check 🟢 |
| `rationale` | Text 🟢 |
| `purpose_scope` | Text 🟢 |
| `proposed_responsibilities` | Text 🟢 |
| `delegating_authority` | Link → `User` 🟢 |
| `delegating_authority_approved` | Check (optional per G-17 wording) 🟢 |
| `proposed_timeline` | Date 🟢 |
| `first_meeting_date` | Date 🟢 |
| `workflow_state` | Data 🟢 |
| `rgo_evaluation` | Table → `RGO Evaluation` 🟢 |

Plus the G-18 standardized intake fields — ⚠️ **DO NOT BUILD YET**:
`document_name`, `document_id`, `requester`, `document_type`, `jurisdiction`,
`parent_document`, `child_document`, `owning_org_og_cs`, `owning_org_lob`,
`owning_org_bu`, `document_sponsor`.

> 🔴 G-18's field list is **document-centric on a committee intake form**, and
> matches Policy's P-3 metadata almost exactly — it looks copy-pasted from the
> Policy template. G-17's questions and G-3's tagging fields both use committee
> vocabulary (`Governance Forum ID/Name/Type`). The source also can't decide
> whether the artifact is the "Committee Intake Form" (G-7) or the "Governance
> Intake Form" (G-17).
>
> Confirm with the authors before building these fields. If they were meant to
> be `committee_name`, `committee_id`, `committee_type`, `committee_sponsor`,
> the whole intake DocType changes shape.

### 3.3 `RGO Evaluation` — child table (G-7) 🟢

`gap_in_coverage`, `duplication_check`, `escalation_pathway_clear`,
`aligned_to_rmf_taxonomy_policy`, `resource_feasibility` (all **Check**),
`completeness_confirmed` (**Check — gates workflow progression**),
`reviewer_comments` (Text), `reviewed_by` (Link → User), `reviewed_on` (Datetime).

### 3.4 `Committee Charter` 🟢

`formation_request` (Link), `charter_document` (Attach),
`rgo_challenge_status` (Select: Not Reviewed / Changes Requested / Cleared),
`rgo_challenge_comments` (Text), `approval_evidence` (Attach Multiple — G-5's
"email, meeting minutes, signed document").

### 3.5 Supporting 🟡

| DocType | For |
|---|---|
| `Disbandment Plan` | G-11 — attachment + trigger scenario + approvals |
| `Attestation Campaign` / `Attestation Task` | G-10 — PRD §4.2 explicitly calls for "one task per Chair/Secretary/Owner of Governance Forum per year" |
| `Forum Link` (child) | G-4 upstream/downstream mapping |

---

## 4. Module: Policy Management

### 4.1 `Policy` — master record 🟡

The PRD gives no field list for Policy (unlike §4.3 for CGF), so this is derived
from P-3's metadata list, which is explicit about content:

| Group | Fields |
|---|---|
| Identity | `document_name`, `document_id` (autoname), `document_type` (Link), `lifecycle_phase` (Select), `version` |
| Ownership | `document_owner`, `document_approver`, `document_liaison`, `document_delegate` (optional), `document_sponsor`, `key_contact` — all Link → `User` |
| Org alignment | `owning_org_og_cs`, `owning_org_lob`, `legal_entity`, `jurisdiction`, `line_of_defense` |
| Risk | `primary_risk_category`, `material_entity` (Check per P-3's "Y/N") |
| Relationships | `parent_document` (Link → Policy), `children` (Table → `Policy Relationship`), `direct_document_link` (Data/URL) |
| Regulatory | `regulatory_required` (Check), `regulatory_details` (Table, dependent on the Check — P-6) |
| Control | `confidential` (Check — **drives the P-1/P-13 restricted permission rule**), `training_required` (Check) |
| Workflow | `workflow_state`, `effective_date`, `next_review_date`, `implementation_confirmed_by`/`_on` (🟢 PPTX step 10) |

### 4.1b Policy workflow states 🟢 — from the source PPTX (slide 5)

**`DRAFT → Review → Approved → Published → Implemented`**

The PRD assumed `Draft → Review → Approved → Published → Retired`. That is
wrong on the last state: **Implemented** is a distinct act (Front Line confirms
implementation *after* publication), and retirement is a separate lifecycle
concern, not the terminal workflow state.

| Transition | Actor | Sets |
|---|---|---|
| (initiate request) | First Line / Business Unit | — |
| → DRAFT | First Line (assigned **Drafter**) | `Status = DRAFT` |
| review rounds | **Reviewers**, then **Second Line** (regulatory alignment, risk mitigation, oversight) | — |
| → Review | **Policy Office** (consistency + terminology) | `Status = Review` |
| → Approved | First Line **and** Second Line approvals | `Status = Approved` |
| → Published | **Policy Office** (publication + notifications) | `Status = Published` |
| → Implemented | **Front Line** confirmation | `Status = Implemented` |
| (ongoing) | **Risk and Compliance** monitor; **Audit** assesses | — |
| re-entry | any reassessment / feedback / regulatory change / operational need | back to DRAFT |

Roles to add to the role table: **Drafter, Second Line, Policy Office (= EPO?),
Front Line, Risk and Compliance, Audit**.

### 4.2 Supporting Policy entities

| DocType | Requirement | Provenance |
|---|---|---|
| `Policy Intake Request` | P-16 — carries the dynamic Q&A + the major/minor classification result | 🟡 |
| `Policy Relationship` (child) | P-4 — parent/child/addendum lineage | 🟡 |
| `Policy Applicability` (child) | P-21 — business units, jurisdictions, roles, exemptions | 🟡 |
| `EPO Monitoring Activity` | P-11 — **named in PRD §5.2** | 🟢 |
| `Policy Violation` | P-22 — **named in PRD §5.2**; links to the enterprise GRC system | 🟢 |
| `Glossary Term` | P-24 — **named in PRD §5.2**; enforced-term validation | 🟢 |
| `Horizon Scan Finding` | §5.3 — the correlation engine's record; links finding → impacted policies | 🟡 |
| `Implementation Plan` | 🆕 **PPTX TOM slide 9** — "store implementation plans in the centralized system of record, tagging impacted risks, processes, and control structures". Tracks impact sizing, working groups, training needs, and the policy owner's post-implementation verification | 🟢 |
| `Attestation Campaign` / `Attestation Task` | **P-8 (source doc) requires annual attestation for Policy too, not just CGF G-10** — reuse one shared pattern across both modules | 🟢 |

> ⚠️ **P-16 is the one genuine business-logic build.** The PRD calls it a
> "genuine business-rule build, needs precise rules from business, not a native
> feature." The *schema* is easy (a question set + a classification field); the
> **decision rules are not specified anywhere** and must come from the business
> before this can be built.

---

### 4.3 `Horizon Scan` 🟢 — **now fully specified** (PPTX Horizon Scanning slide)

The PPTX annex settles what Horizon Scanning is: **a periodic obligation on the
Policy Owner**, not a data feed. Every "typical activity" listed is a human
action (review consultations, monitor industry reports, track tech developments,
analyze geopolitical change, run scenario planning, engage SMEs), and the deck's
example policy statement makes it an owner duty whose **findings feed policy
reviews**.

| Field | Type |
|---|---|
| `policy` | Link → Policy |
| `scanned_by` | Link → User (the Policy Owner) |
| `scan_date` | Date |
| `period_covered` | Data |
| `coverage_areas` | Table MultiSelect → Horizon Scanning Coverage Area |
| `sources_reviewed` | child table (source type, reference, date) |
| `findings` | Text Editor |
| `impact_assessment` | Select: No change / Review triggered / Immediate update required |
| `linked_policy_review` | Link → the Policy review record it feeds |

`Horizon Scan Finding` (already listed in §4.2 as 🟡) becomes the child of this
record rather than a free-standing correlation-engine output.

**Build-order consequence:** §8 put Horizon Scanning last as "genuinely net-new,
depends on an unnamed external source." As specified in the deck it is an
attestation-shaped record on Policy with a scheduled reminder — **cheaper than
the Escalation module**, and it shares the `Attestation Campaign` / `Attestation
Task` pattern already needed for G-10 and P-8. The automated feed (slide 13
Optional item 7, "real-time regulatory updates") is an enhancement layered on
this record later, not a prerequisite. Moved up in §8 below.

---

## 5. Module: Escalation Management

### 5.1 `Escalation Matter` 🟡 (fields from E-3, which is explicit)

`escalation_title`, `escalation_id` (autoname), `escalation_type` (Link),
`escalation_identification_date` (Date), `escalation_matter_description` (Text),
`tier_1_risk_type` (Link), `tier_2_risk_type` (Link, optional),
`impacted_entity` (Link), `escalation_matter_identifier` (Link → User — note
E-3 says "person"), `organizational_level_identifier` (Link),
`accountable_executive` (Link → User).

Plus: `severity` (Select High/Medium/Low — E-4), `status` (Select: Open / Under
Review / **Closed – Tracked in the enterprise GRC system** — E-14 names these verbatim),
`sensitive` (Check — E-16 restricted visibility), `me_impact` (Check — E-8),
`risk_appetite_breach` (Check — E-8), `escalation_pathway` (Link →
`Governance Forum` — E-7), `workflow_state`, SLA fields (E-13).

### 5.2 Supporting

| DocType | Requirement | Provenance |
|---|---|---|
| `Escalation Matrix` | E-4 — **named in PRD §6.2**; drives severity-based routing | 🟢 |
| `Escalation Response Template` | E-9 — "completion mandatory for all escalations" | 🟡 |
| `Action Plan` | E-6, E-8 — **fields specified in source, see below** | 🟢 |
| `Risk Acceptance` | E-6, E-8, E-9 — **fields specified in source, see below** | 🟢 |
| `Escalation Closure` (child or fields) | E-10 — closure criteria + auditable evidence | 🟡 |

### 5.3 Template field lists — from the ORIGINAL source doc 🟢

E-6 in the Escalation Management requirements document specifies three
templates by field. **The reconstructed PRD compressed E-6 to one sentence and
lost these**, so they were guessed at above until the source surfaced. These are
authoritative:

**Escalation Template** → confirms/extends `Escalation Matter`:
`escalation_id`, `escalation_title`, `escalation_type`,
`escalation_identification_date`, `tier_1_risk_type`, `accountable_executive`,
`governance_forums` (**plural — Table, not a single Link**), `impacted_entities`
(**plural — Table**), `escalation_status`, `escalation_trigger`,
`escalation_date` (**distinct from identification date**).

> Two corrections to §5.1 above: `governance_forums` and `impacted_entities` are
> **many**, not one. E-7's single "escalation pathway" wording misled the
> earlier derivation. And `escalation_date` vs `escalation_identification_date`
> are separate fields — confirm the business distinction.

**`Action Plan`** (new DocType, child of or linked to Escalation Matter):
`escalation_id` (Link → Escalation Matter), `action_plan_name`,
`action_plan_start_date`, `action_plan_end_date`,
`action_plan_accountable_executive` (Link → User), `action_plan_owner`
(Link → User), `action_plan_status` (Select), `governance_forums` (Table).

**`Risk Acceptance`** (new DocType):
`escalation_id` (Link → Escalation Matter), `risk_acceptance_name`,
`risk_acceptance_id` (Data, "if available" — i.e. an **external** identifier,
optional), `risk_acceptance_start_date`, `risk_acceptance_end_date`,
`risk_acceptance_accountable_executive` (Link → User), `risk_acceptance_status`
(Select), `governance_forums` (Table), `risk_acceptance_rationale` (Text).

> `risk_acceptance_id (if available)` implies Risk Acceptances may originate in
> another system. Add to the §8 discovery list — which system, and is it
> authoritative?
>
> E-9 additionally requires Risk Acceptance to "support periodic reassessment",
> which is not in E-6's field list — add `next_reassessment_date` (🟡) and a
> scheduled job.

---

## 6. Cross-module relationship map

```
Governance Forum ──published via G-19 API──┐
        ▲                                   ├──> Escalation Matter.escalation_pathway  (E-7)
        │                                   └──> Policy.approving_committee            (P-5)
        │
Committee Formation Request ──1:1──> Committee Charter
        └──child──> RGO Evaluation

Policy ──self-ref──> Policy (parent/child/addendum, P-4)
   ├──> Policy Violation ──> the enterprise GRC system (external, 🔴 undiscovered)
   ├──> Glossary Term (enforced vocabulary, P-24)
   ├──> EPO Monitoring Activity (P-11)
   └──< Horizon Scan Finding (§5.3 correlation engine)

Escalation Matter ──> Escalation Matrix (routing, E-4)
   ├──> Action Plan / Risk Acceptance (E-8)
   └──> Risk Appetite system + CGF  (E-8: BOTH, confirmed per direction)

ALL ──> Version + Comment (native audit, G-9/P-9/E-12)
ALL ──> File (attachments) ──webhook──> Retention/WORM (external, hook only)
```

---

## 7. What the schema cannot yet specify 🔴

Directly blocked by PRD §10 open questions:

1. **Taxonomy sync** — every Common Taxonomy DocType is meant to sync from an
   authoritative source. None of those sources is identified (§8). Blocks the
   foundation layer.
2. **the enterprise GRC system linkage fields** on `Policy Violation` and `Escalation Matter` — no
   API contract, so the foreign identifier's format/name is unknown.
3. **the risk identification system linkage** — P-5/E-19 require it; §10 Q2 says it is not even
   confirmed which system that is.
3b. **Records management / retention integration** — required by **all three**
   modules (P-20, E-19, G-19), broader than the fire-and-forget WORM hook the
   PRD scoped. One shared Core service; same undiscovered system.
4. **AD/OIDC** — user identity is the anchor of every `Link → User` field above.
   §10 Q6 says the protocol is unconfirmed. **Needed day one.**
5. **P-16 classification rules** — see §4.2. Confirmed still open: the source
   doc gives only the two example questions, no decision table.
6. ~~**P-20 / E-19 truncated text**~~ — **RESOLVED.** Both are complete in the
   original .docx files; the truncation was a conversion artifact. See the two
   `SOURCE-*.md` transcriptions.
7. **Platform conflict** — the Policy source doc opens "The Policy Management
   solution **in the incumbent GRC platform**…". The CGF and Escalation source docs are
   platform-neutral, so this is **specific to Policy**, not programme-wide.
   Still needs confirming before Policy build.
8. **P-26 scope** — the source treats the Policy Editor as a full Mandatory
   requirement; only verbal direction says it already exists. If that is wrong,
   P-26 is among the largest items in the programme (Google-Docs-class
   collaborative editing, which Frappe has no native answer for).
9. **G-18 intake field naming** — see §3.2; blocks the `Committee Formation
   Request` field list.
10. ✅ **RESOLVED (D-4) — version revert IS in scope.** **Version revert** — PPTX business requirement #10 wants "see **and revert
   to** previous versions". Frappe's Version log is a diff trail; restore-to-
   version is **not native**. Confirm whether revert is still required.
11. **"Playbook"** (PPTX slide 6) — guidance shown at policy creation. Undefined:
   static help text, a template, or its own content entity?
12. **Roles `Monitor` and `Partner`** appear in the PPTX RBAC list but in no
   later document. Dropped or lost?
13. **Forum field cardinality** — single vs multi-select; see §3.1a. Blocks the
   first entity anyone would build.
14. **Voting** — PPTX TOM says forums *vote* on governing documents ("eliminate
   positive confirmation"). Not a workflow transition; implies a motion/vote
   entity with per-member positions. Scope unconfirmed.
15. **Three conflicting role vocabularies** (PPTX Policy / PPTX CGF Risk
   Oversight / .docx G-13). Reconcile into one model before building RBAC.
16. ✅ **RESOLVED (D-5) — `Directive` is legacy; do NOT model it.** ~~`Directive` as a governing document type (PPTX) — absent from .docx P-1.~~ Likewise "lexicon" vs P-24 "glossary".
17. **Undefined roles/terms** — `jurisdictional CRO` (G-11 approval role, missing
   from the PRD role table) and `Owner of Governance Forum` (G-10 attestation participant, never
   defined). Both affect who records link to.

18. **Which CGF workflow is real?** 🔴 The corpus now contains two. PPTX
   slide 13: Draft → Pending → Compliant / Non-Compliant / Not-Applicable,
   driven by the **Compliance team**, with send-back-to-creator, re-review on
   edits to watched fields, and **annual review by owner + compliance**. PRD
   §4.3: a nine-state RGO formation workflow. They cannot both be the
   `Governance Forum` workflow. Slide 13's states are identical to the PPTX
   *Regulatory Compliance Status* field values, which suggests that field **is**
   the workflow state rather than a separate attribute. Blocks: the Workflow
   DocType, the state field on §3.1, and §3.2's relationship to it.
19. **Recurring attestation is unmodelled.** Slide 13 step 7 requires an annual
   review signed by **both** the forum owner and compliance. Nothing in §3.1
   carries `last_attestation_date` / `next_review_due`, and no scheduled job
   exists. Same gap as G-10, now with a named cadence and a dual signer.
20. **Field-change-triggers-review (slide 13 step 6)** needs an explicit
   watched-field list. "Certain fields" is not specifiable. Implementation is a
   `on_update` hook resetting state to Pending — cheap to build, impossible to
   build correctly without the list.
21. **the enterprise GRC system may be a named commercial GRC platform.** 🟡 PPTX slide 14 names **a named commercial GRC platform, the incumbent GRC platform and
   a named enterprise HR platform** as the GRC platforms in scope for API integration. That is the
   first hint at the identity of the enterprise GRC system connector listed as Unknown above and
   in §5. Recorded as a **candidate, not a confirmation** — do not build against
   a named commercial GRC platform's API until confirmed. Note the same slide lists the incumbent GRC platform as an
   *integration target* while the stakeholder directive is to *replace*
   the incumbent GRC platform; coexist-then-replace needs to be stated explicitly in scope.
22. **Escalation → Risk Appetite is NOT settled.** 🔴 PRD §8 records "Escalation
   feeds both CGF and Risk Appetite" as a *confirmed design decision*. PPTX
   slide 14 still carries it as an open question: *"Do we want escalations to
   feed into the tool or do we want escalations to feed into other areas like
   risk appetite?"* Either the PRD captured a later decision, or it asserted a
   resolution that was never made. This decides whether `Escalation Matter`
   needs an outbound Risk Appetite connector at all.
23. **Priority is not uniform after all.** PPTX slide 13 carries seven
   **Optional** business requirements — the first Optional content anywhere in
   the corpus. Every requirement in all three .docx sources is Mandatory. So the
   authors do use the Optional category and chose not to apply it in the .docx
   set. Two of the Optional items (automated notifications, escalation tracking)
   are Mandatory in the .docx. Earlier note that the all-Mandatory .docx set was
   template laziness is **withdrawn** — it looks deliberate, which means the
   .docx set may be over-committed on purpose. Confirm with the author.
24. **Optional slide-13 items 6–7 are not buildable from the corpus** —
   real-time governance-gap detection, policy-change impact assessment,
   predictive analytics for emerging risks, live regulatory updates. All require
   an external data source named nowhere. They align with the stakeholder
   directives for the AI services platform summarization and Copilot; treat as a separate
   AI workstream, not schema.
25. **Governance flow-chart view (slide 13 Optional item 2)** consumes the
   parent/sub-parent linkage from §3.1 and the *councils and oversight bodies*
   forum kinds. It is a view, not new schema — but it only works if forum
   linkage is a real field and not free text.

26. **UI: native Desk vs. hand-built Bootstrap.** 🔴 PPTX slide 15 specifies a
   screen-by-screen UI (home page, main table, forum detail, Report tab, Admin
   tab, Create Forum tab). In Frappe **all of it is native** — List/Report/Form
   views, a Workspace for the tabs, the Role Permissions Manager for Admin. The
   stakeholder directives instead require vendored Bootstrap + jQuery screens
   with custom pagination/sort/search, no DataTables, a font-size dropdown and a
   the client's public website/dark-blue theme switcher. These are two different products. Decide
   before any front-end work: native Desk (weeks, themed) or custom UI (months,
   exactly as drawn). The table behaviour the directives demand is the one thing
   both sources agree on.
27. **The flow-chart view has two homes.** Slide 13 Optional item 2 puts
   governance interconnectivity on the **home page**; slide 15 item 9 puts it on
   the **forum detail page**. Both are cheap once forum linkage is a real Link
   field (§3.1) rather than free text. Confirm which, or build both.
28. **"Regulatory change system" is a fourth unknown connector.** The Policy
   business-case slide names integration with "escalation, **regulatory
   change**, and risk systems". Add alongside the enterprise GRC system, Risk Appetite and the
   enterprise risk platform in the connector inventory — all Unknown. This is
   plausibly the source behind the Optional "real-time regulatory updates", and
   would feed §4.3 `Horizon Scan` if it exists.
29. **Three separately funded systems, not one platform.** 🔴 Each business-case
   slide carries its own ERPM TIP funding line and its own dates: Governance and
   Escalation implement **March 2026**, Policy **June 2026**, all with funding
   available by **Nov 1 2025** and development starting then. The requirements
   corpus treats them as three modules of one product. Which framing the build
   is judged against changes what "done" means, and whether shared entities
   (User, taxonomies, Attestation, audit) can be built once.
30. **All published dates have lapsed.** Every implementation milestone on the
   deck is in the past as of today. Either the programme slipped or the deck
   predates a re-plan. **Do not schedule off this deck** — get current dates.
31. ✅ **RESOLVED (D-1) — all AI is an outbound call to the AI services platform (MCP), not built here.** 14 AI use cases have no requirements behind them. Across the three
   business-case slides: policy drafting from regulatory text, change-flagging,
   duplicate/conflict detection, violation-trend analysis, policy
   recommendation; charter-update suggestions, overlapping-mandate detection,
   stale-forum detection, cross-forum structural analysis, activity monitoring;
   escalation-inconsistency detection, bottleneck flagging, under/over-escalation
   patterns, threshold suggestions. None appear in any .docx requirement set and
   none have acceptance criteria. They line up with the AI services platform and Copilot
   directives. Treat as a **fourth workstream / roadmap**, not v1 schema, unless
   told otherwise.
32. **Dissolution is confirmed in scope.** The Governance business-case slide
   lists "workflow automation for forum creation, updates, and **dissolution**",
   matching G-18 and PPTX CGF item 13. The forum workflow needs a terminal
   disbanded state with its own approval path and retention rules — neither
   workflow candidate in item 18 includes one.
33. **New taxonomy: Horizon Scanning Coverage Area** 🟢 — eight named values from
   the deck: regulatory changes, cybersecurity threats, AI governance, privacy
   requirements, operational resilience, third-party risk, ESG expectations,
   geopolitical developments. Add to §2.
34. **Is the incumbent GRC platform actually deployed here?** All three current-state blocks
   describe **manual process** being replaced (Word, PDF, email, spreadsheets,
   PPT decks, intranet) — no incumbent product. Yet slide 14 lists the incumbent GRC platform as
   an integration target and the stakeholder directive is to "kill the incumbent GRC platform."
   Clarify whether the incumbent GRC platform exists in this footprint at all; it changes
   whether any migration or coexistence work is needed.

---

## 8. Recommended build order

1. **Core taxonomy DocTypes** + AD/OIDC auth (everything hangs off `User` and
   the taxonomies).
2. **CGF module** — it is the most fully specified (§4.3 gives real field names
   and a validated workflow), and G-19 publishes the data the other two consume.
3. **Policy module** — largest (26 reqs), but P-16 and P-26 are gated on
   business rules / the existing editor's interface.
4. **Escalation module** — depends on CGF (E-7) and on two undiscovered
   connectors (the enterprise GRC system, Risk Appetite).
5. ~~**Horizon Scanning** — depends on an unnamed external source; genuinely
   net-new build.~~ **Revised** (PPTX Horizon Scanning slide, §4.3): it is a
   periodic Policy-Owner record sharing the Attestation pattern, with **no
   external dependency**. Build it **with the Policy module** (step 3), not
   last. Automated regulatory feeds remain a later enhancement.

Native Frappe features that require **no schema work** and should not be
rebuilt: audit/version history (G-9/P-9/E-12), RBAC (G-13/P-13/E-16),
notifications (G-14/P-14/E-17), SLA tracking (E-13, P-7), attachments
(G-15/P-17), reporting (G-12/P-12/E-15), REST API (G-19/P-20/E-19 outbound).
