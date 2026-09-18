# SOURCE: the Policy Management requirements document

Transcribed from screenshots of the **original Word document**. Upstream of
`PRD-frappe-build.md`; where they differ, **this wins**.

---

## 🔴 THE HEADLINE FINDING — read this first

The module intro paragraph, which **the reconstructed PRD dropped entirely**,
reads:

> **"The Policy Management solution in the incumbent GRC platform will serve as a centralized
> repository for enterprise policies and automate key stages of the policy
> lifecycle, including drafting, review, approval, publication, periodic review,
> and retirement. These capabilities support consistent policy governance and
> alignment with regulatory expectations."**

**The source requirements were authored assuming the incumbent GRC platform is the platform.**

The PRD's §1 lists the incumbent GRC platform only as *out of scope* — "the risk identification system — a separate,
already-in-flight the incumbent GRC platform project… Not part of this build." It never
mentions that the Policy requirements themselves name the incumbent GRC platform as the
delivery platform.

Two readings, and they have very different consequences:

1. **Benign:** these requirements were written while the incumbent GRC platform was the assumed
   platform; the Frappe decision came later and supersedes it. The sentence is
   stale. → Just needs the doc updated so nobody is misled.
2. **Serious:** the business/ERM stakeholders still believe Policy Management is
   being delivered **in the incumbent GRC platform**, while the build team is building on
   Frappe. → A live misalignment on the single most expensive assumption in the
   programme.

**This needs a direct question to the requirement authors before any Policy
build starts.** Note the "kill the incumbent GRC platform" framing in the WhatsApp thread
suggests reading 1 — but that is an inference, not confirmation.

Note also: the front matter says requirements are *"technology-agnostic where
possible"* and *"may be satisfied through native platform functionality,
configuration, workflow design, or integration"* — which argues the incumbent GRC platform
reference is incidental rather than binding. Still needs confirming.

---

## Front matter

**ERM Technology Implementations — Policy Management — High-Level Requirement
Document** (the client organisation)

Purpose, Scope, How to Read the Requirements, and the Priority table are
**identical in wording** to the Escalation document — see
`SOURCE-Escalation-Mgmt-Requirements.md`.

> Minor observation: the Scope paragraph in the *Policy* doc still says
> "…governance, risk oversight, and **escalation** processes", i.e. the boilerplate
> was copied across the three documents without retargeting. Harmless, but it
> confirms these are template-generated and the intros deserve scrutiny rather
> than trust.

---

## Priority and Source columns

| Observation | Detail |
|---|---|
| **All P-1 … P-20 are `Mandatory`** (P-21…P-26 not captured in this batch) | Same as Escalation — no Optional requirements so far |
| **P-20's Source is `ERM, ONFR, LRC`** | **Different from every other row.** Everything else is `ERM` alone. ONFR and LRC are new acronyms not defined anywhere in the material seen so far — likely *Operational & Non-Financial Risk* and *Legal & Regulatory Compliance*, **but that is a guess.** P-20 (Integration) therefore has three stakeholder groups to satisfy, not one. |

---

## Requirements — deltas against the PRD

Where the PRD's text matches the source, see `PRD-frappe-build.md` §5.1. Only
material differences are reproduced here.

### ⭐ P-8 — Configurable Review and Approval Workflow (PRD lost the attestation clause)

Full bullet list in source:
- Ability to ensure parent policy owners approve changes to child documents, if
  necessary.
- Automated routing, reminders, and escalations.
- Approval tracking in real time, including timestamps, comments, and signoffs.
- Forms and workflows for Exception Requests and Exemptions.
- Ability to route approvals and notifications to user groups.
- Role-based assignment of approval steps.
- Conditional logic to determine approval paths based on policy type, change
  type, or risk level.
- Audit trail capturing all approval actions and timestamps.
- **Ability to route notifications for annual attestation and deadline
  reminders.**  ← *not in the PRD's P-8*
- Ability to route notifications for horizon scanning:
  - Notify policy owners when horizon scans are due.
  - Track completion of manual horizon scans.
  - Trigger downstream workflows after scans.

> **Policy has an annual attestation process too.** The PRD only surfaced
> attestation for CGF (G-10). This adds an `Attestation` requirement on the
> Policy side that the data model did not account for — the shared
> `Attestation Campaign`/`Attestation Task` pattern should cover **both**
> modules.

### ⭐ P-16 — Policy Intake Templates (PRD lost the "Workflow Integration" block)

Source adds, after the Major/Minor classification rules:

**Workflow Integration:**
- Classification drives routing, approval steps, and SLAs tracking.
- Ability to classify different types of changes
- Updating fields or metadata
  - Templates or intake include required fields.
  - Templates or intake standardized naming conventions for policy documents.
  - Maintain version history and rationale for change classification & Full
    audit trail of intake submissions, classification logic, and workflow
    actions.

The two example questions are confirmed verbatim: *"Does this impact compliance
obligations?"*, *"Does this alter core policy principles?"* — still only
examples. **The actual decision rules remain unspecified**, so P-16 stays the
one genuine business-logic build.

### ⭐ P-20 — Integration Capabilities — FULL TEXT (resolves the PRD's truncation flag)

The PRD marked P-20 truncated at ~2000 chars. The original is **not truncated** —
same conversion artifact as E-19. The PRD was missing the final section:

**Data Quality and Control**
- The system shall support validation of inbound and outbound data to ensure
  completeness and integrity.
- Defined handling rules shall be applied for missing, invalid, or incomplete
  data.

Also present in source but absent from the PRD's version:
- *"The system shall support integration with enterprise **records management
  and retention systems**, where applicable."* (under Technical and Operational
  Capabilities)
- Identity integration wording is richer: AD enables *"user selection,
  **organizational alignment**, and notification routing"* — org alignment is an
  extra obligation.

Otherwise P-20's Core Integration Objectives / Data Alignment and Standards /
Technical and Operational Capabilities match the PRD.

### P-13 — RBAC (emphasis in source)

The word **shall** is underlined in the original on the confidential-documents
sentence:

> "The system **shall** include enhanced controls for confidential or restricted
> policy documents to ensure that visibility, access, and permitted actions
> (e.g., view, download, print, share) are limited to authorized users only."

Typographic emphasis in a requirements doc usually signals a control the authors
expect to be tested. Reinforces my earlier flag: **view/download are
enforceable; print/share are advisory in a web app.** Needs an explicit
conversation about what "limited" means as a control.

### P-1 … P-7, P-9 … P-12, P-14, P-15, P-17 … P-19

Materially consistent with the PRD. P-3's metadata list is confirmed verbatim
(22 example fields), which validates the `Policy` DocType derivation in
`DATA-MODEL.md` §4.1.

---

## Summary of what this document changes

| # | Finding | Action |
|---|---|---|
| 1 | **Source requirements name the incumbent GRC platform as the Policy platform** | **Confirm with requirement authors before Policy build.** Highest priority. |
| 2 | P-20 Source = `ERM, ONFR, LRC` — three stakeholder groups | Identify ONFR and LRC; they must sign off Integration scope |
| 3 | P-20 complete — "Data Quality and Control" recovered | **PRD §10 Q5 now fully closed** (E-19 + P-20 both intact in source) |
| 4 | P-8 requires **annual attestation** for Policy | Extend the attestation pattern beyond CGF in the data model |
| 5 | P-20 requires integration with **records management and retention systems** | Retention was "hook only"; this is a second, broader obligation |
| 6 | P-16 "Workflow Integration" block recovered | Classification drives SLA tracking, not just routing |
| 7 | P-13's underlined **shall** on confidential controls | Treat print/share restriction as a testable control — resolve feasibility |
| 8 | Boilerplate copied across all three docs (Policy scope mentions "escalation") | Don't over-read the intros; verify module-specific claims |

---

# APPENDIX — P-21 … P-26 (second batch)

All `Source: ERM`, `Priority: Mandatory`. **No Optional requirements exist in
the Policy module either.**

### P-20 — final line recovered
The requirement closes with two bullets the earlier capture cut off:
- *"…invalid, or inconsistent data received through integrations."*
- **"Integration activity and data exchanges shall be traceable to support audit
  and compliance requirements."**

### P-21 Applicability Management
Ability to maintain applicability for each policy. The system shall send
automated notifications to applicable parties when a policy is created, changes,
or is retired. Applicability includes but not limited to: Business units,
subsidiaries, material entities; Jurisdictions (provincial, federal,
international); Roles or functions responsible for compliance; Formal exemptions
and deviations with approvals.

### P-22 Violation and Issue Management
As per the PRD, and confirms the parenthetical *(Policy Violation Location is to
be confirmed)* is in the **original** — an open item the business already knows
about.

### P-23 Missing Field Maintenance
As per the PRD.

### P-24 Glossary Management
Adds three explicit bullets the PRD folded into prose:
- **Maintain a centralized glossary of policy terms managed by EPO.** ← *EPO
  ownership is stated; the PRD omitted who owns it*
- Link glossary terms to documents for contextual help.
- Enable version control and audit trail for glossary changes.

### P-25 Approval Management
As per the PRD — mandatory approval before publication, configurable
multi-step/role, full audit trail, no bypass without documented exception
authorization.

### ⭐ P-26 Policy Editor — **the source does NOT say it is already built**

Source text (Mandatory, ERM) describes a **full build requirement**:

**Review Stage Management**
- The system shall allow a policy document to be transitioned into a designated
  Review Stage.
- Reviewer assignments shall be configurable based on roles, groups, or policy
  characteristics.
- The system shall support sequential or parallel review configurations, as
  required.

**Feedback and Disposition**
- Reviewers shall be able to provide inline comments and revision suggestions
  directly within the policy document.
- The Policy Owner shall be able to view, assess, and disposition all feedback in
  real time (e.g., accept, reject, request clarification) without exiting the
  workflow.
- Upon disposition of feedback or revisions, the system shall automatically
  notify the originator of the feedback of the Policy Owner's decision.

**Version Control and Auditability**
- The system shall maintain version control throughout the editing and review
  process, ensuring visibility of all changes.
- All reviewer comments, owner dispositions, edits, and notifications shall be
  captured in a complete audit trail with timestamps and user attribution.
- Prior versions of the document shall be retained and accessible in accordance
  with document retention requirements.

**Collaboration and Transparency**
- The system shall provide real-time visibility into review progress and
  outstanding feedback.
- The system shall support collaborative editing features that enable efficient
  review while preserving governance controls.

> 🔴 **Delta against the PRD.** The PRD states: *"Note per direction: P-26's
> Policy Editor is **confirmed already built** — this is an integration task,
> not new development."* That claim comes from **verbal direction**, not from
> the requirements. The source treats P-26 as a Mandatory requirement like any
> other.
>
> This matters because of what P-26 actually asks for: **inline commenting,
> revision suggestions, redlining, real-time feedback disposition, and
> collaborative editing with version comparison** — Google-Docs-class
> functionality. Frappe has none of this natively; its text editor is a
> rich-text field with document-level comments, not in-line track-changes.
>
> **If the "already built" claim is wrong, or the existing editor is thinner
> than P-26 requires, this is one of the largest items in the whole programme.**
> PRD §10 Q4 asks what interface it exposes; the prior question is whether it
> covers these bullets at all. Get a demo, not an assurance.
