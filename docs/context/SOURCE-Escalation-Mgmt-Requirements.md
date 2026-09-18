# SOURCE: the Escalation Management requirements document

Transcribed from screenshots of the **original Word document** — one of the three
the client source docs the PRD was reconstructed from. This is upstream of
`PRD-frappe-build.md`; where they differ, **this wins**.

---

## Front matter

**ERM Technology Implementations — Escalation Management — High-Level
Requirement Document** (the client organisation)

### Purpose
This document defines the high-level functional requirements for the
implementation of Enterprise Risk Management (ERM) technology capabilities
supporting Escalation Management. The requirements are intended to establish a
common understanding of expected system capabilities and controls across
stakeholders and to inform solution design, configuration, and implementation
planning.

### Scope
The requirements outlined in this document focus on enterprise-level
capabilities and outcomes, rather than detailed technical design or
configuration decisions. They describe what the system must support to enable
effective governance, risk oversight, and escalation processes, while allowing
flexibility in how those capabilities are delivered through configuration,
integration, or process alignment.

### How to Read the Requirements
- Requirements are expressed at a functional level and are intended to be
  technology-agnostic where possible.
- Statements use directive language (e.g., "the system shall") to clearly
  indicate mandatory capabilities.
- Examples provided within requirements are illustrative and are not intended
  to be exhaustive, unless explicitly stated otherwise.
- **Requirements may be satisfied through native platform functionality,
  configuration, workflow design, or integration with existing enterprise
  systems, provided the stated outcomes and controls are achieved.**

### Priority definitions
| Priority | Definition |
|---|---|
| Mandatory | A requirement that must be implemented **as part of this SOW**. |
| Optional | A requirement that may be implemented at a later phase. |

### Module intro
The Escalation Management solution will enable consistent intake, routing,
tracking, and resolution of escalations across the enterprise. The goal is to
ensure escalations are managed in accordance with defined standards and reach
the appropriate decision-makers in a timely and auditable manner.

---

## Requirements table

Columns in the original: **Req ID | Description and Information | Source | Priority**

**Every requirement E-1 … E-19 is `Source: ERM`, `Priority: Mandatory`.
There are zero Optional requirements in this module.**

Only deltas against the PRD are reproduced in full below; where the PRD's text
matches the source, see `PRD-frappe-build.md` §6.1.

### ⭐ E-6 — Configurable Escalation Templates — FULL TEXT (PRD lost this)

> **Description:** Ability to configure templates based on Escalation Matter
> types. Ability to have standardized (required) fields across templates.
> Examples include but are not limited to:

**Escalation Template**
- Escalation ID
- Escalation Title
- Escalation Type
- Escalation Identification Date
- Tier 1 Risk Type
- Accountable Executive
- Governance Forum(s)
- Impacted Entities
- Escalation Status
- Escalation Trigger
- Escalation Date

**Action Plan Template**
- Escalation ID
- Action Plan Start Date
- Action Plan Accountable Executive
- Governance Forum(s)
- Action Plan Name
- Action Plan End Date
- Action Plan Owner
- Action Plan Status

**Risk Acceptance Template**
- Escalation ID
- Risk Acceptance Name
- Risk Acceptance Start Date
- Risk Acceptance Accountable Executive
- Risk Acceptance ID (if available)
- Risk Acceptance Status
- Risk Acceptance End Date
- Governance Forum(s)
- Risk Acceptance Rationale

> The PRD compressed E-6 to a single sentence and dropped all three field
> lists. These are **direct schema input** — see `DATA-MODEL.md` §5.

### ⭐ E-19 — Integration — FULL TEXT (resolves the PRD's truncation flag)

The PRD marked E-19 as *"truncated in the converted source file at ~2000
characters"*. The original is **not truncated** — the loss was a conversion
artifact, exactly as the PRD suspected. Complete text:

> The system shall support integration capabilities that enable Escalation
> Matters to be created, updated, and tracked consistently across enterprise
> risk, governance, and issue management platforms. Integrations shall ensure
> escalation data is accurately shared, reused, and synchronized to support
> timely decision-making, oversight, and auditability.

**Inbound Integration**
- The system shall support receiving data from external systems (e.g., issue
  management, operational risk events, risk appetite monitoring) to
  automatically create Escalation Matters with pre-populated data where
  applicable.
- Inbound integrations shall map source system fields to escalation data
  elements to ensure completeness, consistency, and traceability.
- The system shall validate inbound data and apply defined handling rules for
  missing, invalid, or incomplete information.

**Outbound Integration**
- The system shall support sending escalation data to external systems (e.g.,
  issue management platforms) to support downstream tracking, resolution, and
  reporting.
- Outbound integrations shall support field mapping to populate target system
  records accurately and maintain linkage between related records across
  systems.
- The system shall support synchronization of escalation status and key
  attributes, where applicable.

**Governance and Escalation Alignment**
- The system shall enable selection of Committees and Governance Forums as
  escalation pathways using authoritative data from the Committee & Governance
  Forum platform.
- The system shall support linkage to related risk identifiers (e.g., the risk identification system),
  where available, to maintain end-to-end traceability across the risk
  lifecycle.
- The system shall support restricted data handling for sensitive escalations
  in accordance with access control requirements.

**Technical and Operational Considerations**
- Integration methods and frequencies (e.g., real-time, scheduled, or
  on-demand) shall be configurable based on business needs.
- Data exchanges shall use formats supported by source and target systems.
- The system shall support integration with enterprise identity platforms
  (e.g., Active Directory) to enable user selection, routing, and notifications
  using authoritative user data.

**Data Alignment and Standards**
- The system shall support alignment to enterprise taxonomies maintained by
  designated systems of record to ensure taxonomies remain consistent across
  integrated platforms.
- Taxonomy values shall be sourced from, or synchronized with authoritative
  systems.
- Examples of aligned taxonomies include, but are not limited to:
  - Organizational hierarchy fields
  - Primary Risk Category
  - Material Entity
- Data exchanges shall include field mapping between source and target systems
  to ensure compatibility, completeness, and data integrity.
- The system shall define handling rules for invalid, missing, or incomplete
  data received through integrations.

**← end of E-19. Nothing further; the requirement is complete.**

---

## What this source document changes

| Finding | Impact |
|---|---|
| **A Priority column exists** (Mandatory/Optional) — the PRD dropped it entirely | The source docs already carry prioritisation. My earlier "no MVP split" gap was half-wrong: the field exists, the PRD lost it. **But for Escalation the answer is unhelpful — all 19 are Mandatory.** |
| **All 19 are Mandatory, "as part of this SOW"** | There is a **Statement of Work** governing scope. Escalation has no deferrable requirements. Someone should confirm the same for the Policy (26) and CGF (19) docs — if those also read all-Mandatory, the SOW commits to all 64. |
| **E-6's three template field lists recovered** | Direct schema input. `Action Plan` and `Risk Acceptance` move from 🟡 guessed to 🟢 specified. |
| **E-19 complete** | Resolves half of PRD §10 Q5. Confirms the truncation was a conversion artifact, not missing source. P-20 still needs the same check against the Policy .docx. |
| **"Requirements may be satisfied through native platform functionality, configuration, workflow design, or integration"** | Explicitly blesses the Frappe configure-don't-code approach. Useful when justifying the platform choice. |
| **"Source: ERM"** on every row | Single originating function; no conflicting stakeholder sources to reconcile in this module. |
