# SOURCE: the CGF Management requirements document

Transcribed from screenshots of the **original Word document**. Upstream of
`PRD-frappe-build.md`; where they differ, **this wins**.

Captured: front matter + **G-1 … G-19 (complete)**.

---

## ⭐ Front matter — note what is NOT here

Purpose, Scope, How to Read, and the Priority table are **identical boilerplate**
to the other two documents.

**The module intro contains no platform reference at all:**

> "The Committee & Governance Forum Management solution will establish a single,
> enterprise-wide inventory of committees and governance forums. It will
> standardize the committee lifecycle by enabling:
> - Formal intake to stand up a committee
> - Documented governance approvals
> - Creation and ongoing maintenance of approved committee charters"

**Contrast with the Policy document**, whose intro says *"The Policy Management
solution **in the incumbent GRC platform**…"*. CGF is platform-neutral; Escalation was too.

This is useful evidence: the incumbent GRC platform reference is **specific to Policy
Management**, not a programme-wide assumption. Two readings remain —
either Policy alone was slated for the incumbent GRC platform, or the sentence is a stale leftover
that only survived in that one document. Still needs confirming with the
authors, but the scope of the problem is narrower than it first looked.

---

## Requirements G-1 … G-17

**Every row is `Source: ERM`, `Priority: Mandatory`.** No Optional requirements.

Across all three modules now: **64 requirements, 100% Mandatory, zero Optional.**

Text is materially consistent with `PRD-frappe-build.md` §4.1. Deltas and
confirmations below.

### ✅ G-5 — the five RGO evaluation criteria confirmed verbatim

The source lists them as an explicit sub-list under "Committee Request
Evaluation Criteria: Ability to highlight steps in RGO review":
- Gap in risk/governance coverage
- Duplication?
- Clear escalation/reporting pathways
- Alignment with RMF, Risk Taxonomy, Policy structure
- Resource feasibility

**This validates the `RGO Evaluation` child table** in `DATA-MODEL.md` §3.3 —
all five Check fields map 1:1. The PRD's §4.3 design was faithful here.

Also confirmed: *"Exception Handling: Include process for resolving disputes or
exceptions via **Head of Risk Governance**"* — the role that owns the Exception
state in the formation workflow.

### ⚠️ G-7 vs G-17 — the intake form has two names in the source

G-7 says the system must validate approvals *"aligned with the information
provided in the **'Committee Intake Form'** and Committee Charter."*

G-17 is titled **"Governance Intake Form"**.

**The source document is internally inconsistent about the name of its own
intake artifact.** Almost certainly the same thing, but worth resolving before
it becomes two DocTypes. (The PRD used "Governance Intake Form" throughout.)

### ✅ G-11 — confirmed

Disbandment approvals: *"Delegating Authority, Sponsor, Chair, and any
**jurisdictional CRO** if applicable"* — matches the PRD. CRO = Chief Risk
Officer, a role not listed in the PRD's §3 role table. **Add it.**

### ✅ G-10 — annual attestation confirmed

*"conducted in **Q1**, requiring Committee Chairs, Secretaries, and **OGFs** to
review and confirm the accuracy of the Committee and Governance Forum
Inventory."*

"Owner of Governance Forum" is used without definition — presumably Owner of Governance Forum, but
**it is not defined anywhere in the material seen so far.** Add to the
open-questions list; it determines who the attestation tasks are assigned to.

### G-1 … G-4, G-6, G-8, G-9, G-12 … G-17

Consistent with the PRD. G-3's ten tagging fields, G-13's role list, G-17's five
example intake questions and the RGO validation gate all match.

---

## What this document changes

| # | Finding | Action |
|---|---|---|
| 1 | **CGF intro is platform-neutral — no the incumbent GRC platform** | Narrows the platform conflict to the Policy doc alone. Still confirm, but it is not programme-wide. |
| 2 | **All 64 requirements across all three modules are Mandatory** | There is no phase-2 in the SOW as written. If the programme needs staging, that is a **scope renegotiation**, not a prioritisation exercise. Raise early. |
| 3 | G-5's five RGO criteria confirmed verbatim | `RGO Evaluation` child table validated — build with confidence |
| 4 | G-7 "Committee Intake Form" vs G-17 "Governance Intake Form" | Resolve naming before it becomes two entities |
| 5 | **jurisdictional CRO** is an approval role | Missing from the PRD §3 role table — add |
| 6 | **"Owner of Governance Forum"** used undefined in G-10 | Define; it determines attestation task assignment |

---

# G-18 and G-19 — full text (completes the document)

Both `Source: ERM`, `Priority: Mandatory`.

### ⚠️ G-18 — Governance Intake Form Field

> **Description:** The system shall define and enforce a standardized set of
> intake form fields required to create, modify, or retire a **Committee or
> Governance Forum**. These fields shall ensure consistent capture of key
> identifying, ownership, and organizational information to support effective
> review, approval, reporting, and lifecycle management. Required fields shall
> be configurable, validated for completeness, and aligned to enterprise
> taxonomies to enable downstream governance, integration, and auditability.
>
> Examples include, but are not limited to:
> - Document Name
> - Document ID
> - Requester
> - Document Type
> - Jurisdiction
> - Parent Document
> - Child Document
> - Owning Organization (OG/CS)
> - Owning Organization (LOB)
> - Owning Organization (BU)
> - Document Sponsor

**🔴 This field list looks like a copy-paste from the Policy module.**

The requirement is about forming a **Committee**, and G-17's example questions
are entirely committee-centric (*"Are you submitting this request to create a
new Committee…"*, *"Who is the delegating authority for the Committee?"*). But
G-18's fields are **document-centric**: Document Name, Document ID, Document
Type, Document Sponsor, Parent/Child Document.

Compare with Policy's **P-3** metadata list, which contains the same
Document Name / Document ID / Document Type / Document Sponsor / Parent
Document / Child Document / Owning Organization (OG/CS)(LOB) fields. The overlap
is too exact to be coincidence.

For a committee intake you would expect *Committee Name*, *Committee ID*,
*Committee Type*, *Committee Sponsor* — and G-3's own tagging list uses exactly
that vocabulary (*Governance Forum ID*, *Governance Forum Name*, *Governance
Forum Type*).

**So the source document contradicts itself twice on the intake form:**
1. G-7 calls it the *"Committee Intake Form"*; G-17 calls it the *"Governance
   Intake Form"*.
2. G-17's questions describe a committee; G-18's fields describe a document.

**Action:** confirm with the authors whether G-18's field names are intentional
or inherited from the Policy template. This directly determines the field list
on the `Committee Formation Request` DocType — currently modelled from G-18 as
🟡 in `DATA-MODEL.md` §3.2. **Do not build those fields until this is settled.**

### G-19 — Integration Capabilities

> **Description:** The system shall support integration capabilities that enable
> Committee and Governance Forum data to be shared consistently across
> enterprise risk, governance, and escalation platforms. These integrations
> shall ensure that governance structures, approvals, and relationships are
> accurately reflected and reusable across dependent processes and systems.

**Core Integration Objectives**
- The system shall **publish** Committee and Governance Forum data for use in
  other modules, including Policy Management, Escalations, Risk Appetite, and
  Risk Identification, to support consistent selection and alignment (e.g.,
  approving committees, escalation pathways).
- The system shall **consume** relevant data from other enterprise platforms
  where governance context is required, ensuring alignment across end-to-end
  risk and governance workflows.

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

**Technical and Operational Capabilities**
- The system shall support inbound and outbound data exchanges in formats
  supported by target systems.
- Integration frequency (e.g., real-time, scheduled, or on-demand) shall be
  configurable based on business needs.
- The system shall support integration with **Active Directory (or equivalent)**
  to enable user selection and notification routing using authoritative user
  data.
- The system shall support integration with **enterprise records management and
  retention systems**, where applicable.

> Consistent with P-20 and E-19: all three modules require records-management /
> retention integration, and all three require AD. **Confirms these are shared
> Core services, not per-module work** — as the PRD §7/§11 argued.
>
> G-19 also confirms CGF is the **publisher**; Policy, Escalations, Risk
> Appetite and Risk Identification are consumers. This is the strongest
> argument for building CGF first.

---

## Status: all three source documents now captured

| Module | Reqs | Priority | Source column |
|---|---|---|---|
| CGF | G-1 … G-19 | **all Mandatory** | ERM |
| Policy | P-1 … P-26 | **all Mandatory** | ERM (P-20 = ERM, ONFR, LRC) |
| Escalation | E-1 … E-19 | **all Mandatory** | ERM |

**64 of 64 Mandatory. Zero Optional across the entire programme.**

> Housekeeping note: the CGF file was open as **"AutoRecovered"** with an unsaved
> recovery banner when photographed. Worth saving the real file before it is
> lost.
