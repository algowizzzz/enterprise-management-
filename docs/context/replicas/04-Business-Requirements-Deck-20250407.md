# Business Requirements — Governance, Policy & Governance Infrastructure
## the client organisation — Enterprise Risk Management | INTERNAL

**Replica of:** the business requirements deck
**Deck stamp:** DRAFT 2.25.25
**Fidelity:** 🟢 slide content below is transcribed verbatim from the deck.
Slides 1–2 and any slides after the business-case set were not captured.
Analysis and conflicts are kept out of this file — see
`../SOURCE-PPTX-Business-Requirements.md` and `../DATA-MODEL.md`.

---

## Slides 3–4 — Business Requirements 1–29

29 numbered business requirements, the precursor set to the later P-1…P-26.
Items captured verbatim:

| # | Requirement |
|---|---|
| 4 | RBAC roles: **Owner, Approver, Monitor, Partner, Reviewer, Delegate** |
| 10 | Ability to see and **revert** to previous versions |
| 12 | Real-time collaborative editing |
| 13 | **Automated Consistency Checks** — detects discrepancies in terminology |
| 24 | **Regulatory Watchlist Integration** — real-time legal/compliance/risk updates |
| 25 | **AI-Powered Impact Analysis** — assesses how new regulations affect existing policies |
| 29 | **Compliance Monitoring Dashboard** — tracks adherence across departments |

Items 1–3, 5–9, 11, 14–23 and 26–28 are earlier forms of requirements that
appear in the Policy HLR as P-1…P-26.

---

## ⭐ Slide 5 — DRAFT Workflow: the actual Policy state machine

The single most useful thing in this deck. Neither the .docx nor the PRD
contains it.

1. **First Line/Business Unit initiates policy request** with relevant details
   (required fields), who is required to be engaged based on policy type, and
   proposed implementation date
2. **First Line (assigned Drafter)** drafts policies using standardized
   templates and sends notification to reviewers — **`Status = DRAFT`**
3. **Reviewers** review and provide feedback and request revisions
4. **Second Line** reviews for regulatory alignment, risk mitigation, and
   oversight. Provides feedback and requests revisions
5. Feedback, revisions, and/or escalation
6. **Policy Office review for consistency and terminology** — **`Status = Review`**
   *(highlighted in yellow in the source — someone flagged this step)*
7. **First Line and Second Line approvals** — **`Status = Approved`**
8. **Publication and Notifications by Policy Office** — **`Status = Published`**
9. Policy is accessible to relevant users
10. **Front Line Implementation and confirmation** — **`Status = Implemented`**
11. **Risk and Compliance** monitors policy compliance
12. **Audit** assesses the policy process to assess effectiveness and adherence
13. Updates can be triggered as part of a required reassessment or feedback,
    regulatory changes, operational needs, etc. — which moves the policy back
    through the **DRAFT → Review → Approved → Published → Implemented** process

---

## ⭐ Slide 7 — Policy Lifecycle (6 stages) — "Risk Governance: Deeper Dive"

A different and higher-level model than the 13-step workflow. Both appear in the
same deck; they are complementary (stages vs. states), but somebody should
confirm which one governs.

| # | Stage | What it does | Outcome |
|---|---|---|---|
| ① | **Horizon Scanning & Needs Assessment** | *"**Leverages existing horizon scanning mechanisms** to identify regulatory, risk, and operational changes. Ensures insights reach policy owners, triggering timely reviews. Integrates findings into a centralized process, linking policies to risks (the risk identification system), business units, legal entities, and jurisdictions."* | Policies align with external and internal risk changes; governance stays proactive and responsive |
| ② | **Development** | Determines the appropriate governing document type. Ensures documents follow a standardized structure aligned with the **RMF**. Stores and classifies policies centrally with tagging to risk, legal entity, etc. | Governing documents consistently structured, properly classified, accessible |
| ③ | **Review & Approval** | Designated **delegates** provide input through a structured comment process managed by policy owners with **central policy office oversight**. Uses a workflow for tracking, ensures **structured comment rounds**, facilitates approval **via appropriate governance forums** | Efficiently reviewed with expert input, transparent, fully auditable, approved at the right level |
| ④ | **Impact Assessment & Implementation** | Assesses **people, process, technology, and data** impacts. Uses structured impact-sizing, aligns stakeholders, integrates policies into **Process/Risk/Control (PRC)**, verifies implementation through a feedback loop with process/control owners | Policies fully operationalized with clear impact understanding |
| ⑤ | **Monitoring & Enforcement** | Operationalizes conformance tracking. Links policy adherence to enforcement information, establishes **escalation processes for non-conformance**, maintains accountability | Conformance continuously monitored with proactive enforcement |
| ⑥ | **Continuous Improvement & Retirement** | Assesses effectiveness using issues, enforcement outcomes, stakeholder feedback. Ensures outdated/redundant/ineffective policies are **formally retired**. Works with horizon scanning but focuses on existing policies | Policies refined, retired when no longer relevant, structured review process |

---

## ⭐ Slide 6 — User Interface requirements

**Directly relevant to the open Bootstrap/jQuery vs Frappe Desk question.**

1. **Centralized dashboard hub** for users to manage tasks and monitor statuses
   - Displays pending tasks, notifications, policy statuses, due dates for
     reassessments
   - **Displays SLAs showing time remaining or past due**
2. **Tab or button at the top to initiate a new Policy**, leading to a screen
   with required information plus **"information (Playbook) that should be
   considered when creating a policy"**
3. **Policy Repository**: searchable list or grid with filters (business unit,
   risk type, status…). Clicking into a policy shows Owner, Reviewers, Business
   Unit, Risk Type, Status, **current version, version history, audit trails,
   and attachments**. Includes a button to initiate an update to the policy.
4. **Admin tab** to manage user roles, permission settings, and a searchable
   user directory
5. **Admin tab** to create and edit **notification templates** for the policy
   lifecycle

> Slide 6 item 5 ends with a copy-pasted fragment from slide 5 ("First Line
> (assigned Drafter) drafts policies…") — an editing artifact, not a
> requirement.

---

## Slides 8–9 — Policy Management: **TOM Details** (Target Operating Model)

Key Actions per lifecycle stage. Material additions over the .docx:

### Horizon Scanning & Needs Assessment
> *"Ensure that **existing** horizon scanning mechanisms are used effectively in
> policy development."*
- Identify and **map existing horizon scanning functions** to ensure outputs
  reach the right policy owners
- **Assign accountability** for horizon scanning insights so reviews are
  triggered as needed
- Incorporate findings into scheduled policy reviews
- Leverage the **centralized system of record** to tag policies impacted by
  horizon scanning insights, linking to risk, jurisdiction, business unit, legal
  entity

> Third confirmation that horizon scanning **exists and is not to be rebuilt** —
> and "identify and map existing functions" implies **more than one** such
> function. Still unnamed (PRD §10 Q1).

### Development
> *"Determine the type of governing document needed and draft accordingly."*
- Classify whether a **policy, standard, procedure, directive, framework, or
  other governing document** is required
- Maintain consistent language and structure, aligning with the **RMF and
  lexicon**
- Store drafts centrally, tagging relevant risks, units, jurisdictions

> 🆕 **"Directive"** is a governing document type. The .docx P-1 lists only
> *Frameworks, Policies, Standards, Procedures, Supporting Documents*. Add
> `Directive` to the `Document Type` taxonomy, or confirm it was dropped.
> "Lexicon" also appears here and may be the same thing as P-24's Glossary.

### Review & Approval
- Designate representatives from **each OG/CS and risk group** for expertise
  without overloading the process
- The comment process is **managed by the policy owner with support from the
  central policy office**, through a workflow system with an audit trail
- Conduct **structured rounds of comments**, ensuring **feedback is provided
  when comments are not incorporated** *(= P-26's disposition notification)*
- The central policy office ensures adherence to the structured process
- 🆕 **"Eliminate positive confirmation and ensure governance forums VOTE on the
  governing document at the appropriate level, avoiding unnecessary escalation
  to the highest board or management committee."**

> **Voting is a first-class concept** and appears nowhere in the .docx or PRD.
> It connects to G-13's *"voting vs. non-voting"* user grouping. Approval is not
> merely a sign-off — a forum may need a recorded vote. That is a distinct
> entity (a motion/vote with per-member positions), not a Frappe workflow
> transition. **Confirm scope.**

### Impact Assessment & Implementation
- Assess impact across **people, process, technology, and data**
- Establish a formal **impact sizing** process identifying system updates,
  procedural adjustments, **workforce training needs**
- Use **cross-functional working groups** to align business units, control
  functions, technology teams
- Tie implementation into the bank's **process, risk, and control (PRC)** system
- Maintain a **feedback loop** between policy owners and process/control owners
- 🆕 **"Store implementation plans in the centralized system of record, tagging
  the impacted risks, processes, and control structures."**

> 🆕 **`Implementation Plan` is a new entity** — not in the .docx or the data
> model. It is stored, tagged, and tracked to completion.

### Monitoring & Enforcement
- Automate compliance tracking (**attestations**, dashboards, periodic reviews)
- Link **real-world enforcement data (audit findings, risk events)** to policy
  assessments
- **Address policy breaches through defined escalation procedures** ← Policy →
  Escalation dependency, stated twice

### Continuous Improvement & Retirement
- Reviews and retirements driven by regulatory updates, emerging risks,
  organizational needs
- Policies **retired when redundant, outdated, or integrated into other
  governing documents**
- Tie **regulatory change management** directly to policy reviews
- 🆕 **"Ensure the policy owner verifies that implementation was successful by
  assessing whether the necessary processes, controls, and governance structures
  were put in place."** ← a distinct verification act after Implemented
- Structured feedback loop between **horizon scanning teams** and policy owners
- Monitor effectiveness by linking compliance trends, risk incidents, audit
  findings to scheduled updates

---

---

## Slide 10 — "Governance Management System" (section divider, no content)

---

---

## ⭐ Slides 11–12 — Governance Infrastructure Tool: DRAFT Requirements

*Slide 11 labelled **DRAFT 3.10.25**; slide 12 labelled **DRAFT 2.25.25** — the
deck carries mixed revision dates.*

This is the CGF module's business-requirements precursor. **Slide 12 item 15
gives an explicit field list for the Governance Forum entity**, and it conflicts
with what the data model currently has.

### Business Requirements 1–14
1. Searchable, centralized data repository for all governance forum details,
   data, and documents
2. Metadata tagging for easy filtering and retrieval
3. Categorize forums by business unit, risk type, legal entity, jurisdiction
4. 🆕 **Map governance responsibilities to each forum (e.g., Oversight, Decision
   Making) to ensure accountability**
5. 🆕 **Tag forum to regulatory requirements by jurisdiction, risk categories,
   risk appetite statements**
6. See governance interconnectivity/linkages between **committees, councils, and
   oversight bodies** using a field to identify **parent/sub-parent**
7. Audit trail and version control
8. 🆕 **Ability to submit comments as part of workflow**
9. Create and generate reports summarizing data
10. Search and filter functionality
11. Ability to attach documents
12. RBAC **by ability (Admin, Edit, View-Only)** and what they can see *(TBD)*
13. Workflow capabilities for establishing [and disbanding] governance forums
14. 🆕 **Workflow capabilities for escalation and resolution**

> #14 means the **CGF module itself needs escalation workflow**, not just
> Escalation Management. And #6 introduces **councils and oversight bodies** as
> forum kinds alongside committees.

### 🔴 Item 15 — Fields (*"Use drop downs/tables wherever possible"*)

| Field | Note |
|---|---|
| Forum Name | matches |
| Forum Type | matches |
| **Business Units (multi-select)** | 🔴 data model has single Link |
| **Risk Types (multi-select)** | 🔴 data model has single Link (`primary_risk_category`) |
| **Legal Entities (multi-select)** | 🔴 data model has single Link |
| **Jurisdiction (multi-select)** | 🔴 not on the Governance Forum at all in the data model |
| **Governance Responsibilities** (Oversight, Decision Making) | 🆕 absent from .docx and data model |
| **Membership** | 🆕 **absent entirely — committee membership is its own entity** |
| Meeting Frequency | ≈ `cadence` |
| **Regulatory Compliance Status** (Compliant / Non-Compliant / Pending / Not Applicable) | 🆕 absent |
| Last Updated | native `modified` |
| Version Control/Change Log | native Version log |
| Linkages to other forums (Parent, Sub-Forum) | ≈ G-4 upstream/downstream |
| **Approval Status (For Changes to Forum)** | 🆕 separate from formation status |
| **Risk Oversight Roles** (Owner, Approver, Escalator, Risk Owner) | 🆕 different role set again |
| **Escalation Protocol** | 🆕 absent |
| **Escalation Threshold** | 🆕 absent |

---

## Slide 13 — Governance Infrastructure Tool

### DRAFT Workflow (7 steps, verbatim)

1. Select create new forum
2. Fill out required fields
3. Submit to "Pending Status"
4. Compliance team reviews the forum's setup, roles, and activities. Ability to
   send forum back to creator with comments/questions
5. Compliance changes the status to **Compliant, Non-Compliant,
   Not-Applicable**
6. Changes to certain fields trigger a Compliance team review
7. Annual review required by owner and compliance

---

## Slide 13 — "Optional Business Requirements" (7 items, verbatim)

1. Home page with User Guide on how to set up a governance forum, clear
   definitions for each type and how to determine which one you need, templates
   (charters, meeting materials, reporting requirements), decision-making
   authority, and escalation protocols
2. Ability to see governance interconnectivity or linkages between committees,
   councils, and oversight bodies on home page with flow chart
3. Visual Dashboard that can be customized to summarize forum activity,
   compliance status, and gaps in governance coverage
4. Automated notifications
5. Escalation Tracking and Resolution *(TBD)*
6. Real-time detection of governance gaps and impact assessment for policy
   changes
7. Real-time regulatory updates, predictive analytics for emerging risks, and
   automated governance risk assessments

---

## Slide 14 — "Risk Program Integration Ideas" (verbatim)

1. Ability to link governance forum to identified risks (risk Id or categories)
   and their assessments
2. Ability to feed forum data into risk monitoring dashboards and reporting
   tools
3. Ability to support API integration with existing tool (e.g. **GRC platforms
   like a named commercial GRC platform, the incumbent GRC platform, a named enterprise HR platform**) with or without real time updates

### Open question left in the deck (verbatim)

> "Do we want escalations to feed into the tool or do we want escalations to
> feed into other areas like risk appetite?"

---

## Slide 15 — Governance Infrastructure Tool, DRAFT Requirements → **User Interface**

Deck header stamp on this slide: **DRAFT 2.25.25**.
File: the business requirements deck,
footer *Enterprise Risk Management | INTERNAL*.

Verbatim:

1. Home page with User Guide on how to set up a governance forum, clear
   definitions for each type and how to determine which one you need, templates
   (charters, meeting materials, reporting requirements), decision-making
   authority, and escalation protocols.
2. Dashboard with forum counts by category, recent updates, etc. *(TBD)*
3. Search bar at top allowing filtering by business unit, risk type, etc.
4. Main table sortable and filterable with specified columns
5. Ability to click on forum to see additional details
6. Separate **Report tab** at the top of page to be able to export forum data
7. Separate **Admin tab** at the top of page to be able to manage users, roles,
   etc.
8. Separate **Create Forum tab** at the top of the page
9. Once in forum details, ability to click edit if you have permission to edit.
   Ability to see governance interconnectivity or linkages between committees,
   councils, and oversight bodies
10. Once in the Create Forum tab
    - I. Information about reviewing User Guide to understand how and when to
      create a forum
    - II. Have information about needing to go through compliance review process
    - III. Have list of required fields

---

## Slide (Policy annex) — **Horizon Scanning for Policy Documents**

A dense reference slide, mostly definitional. Verbatim:

### Functions of Horizon Scanning for Policy Documents

1. **Early Identification of Emerging Risks**
   1. Detects potential regulatory, operational, economic, environmental, or
      geopolitical risks before they become significant issues.
   2. Helps organizations proactively update policies.
2. **Monitoring Regulatory Changes**
   1. Tracks upcoming legislation, regulatory guidance, industry standards, and
      government initiatives.
   2. Ensures policies remain compliant with evolving legal requirements.
3. **Identifying Opportunities**
   1. Highlights new technologies, business practices, or market developments
      that may improve operations or create strategic advantages.
   2. Supports innovation within policy frameworks.
4. **Supporting Strategic Planning**
   1. Provides future-focused intelligence to help policymakers and leadership
      make informed decisions.
   2. Aligns policy development with long-term organizational objectives.
5. **Assessing Policy Effectiveness**
   1. Tests whether existing policies will remain relevant under future
      scenarios.
   2. Identifies areas requiring revision or enhancement.
6. **Enhancing Resilience and Preparedness**
   1. Enables organizations to prepare contingency plans for emerging threats
      and uncertainties.
   2. Strengthens risk management and business continuity planning.
7. **Informing Stakeholder Engagement**
   1. Identifies changing stakeholder expectations, societal trends, and
      industry practices.
   2. Supports more responsive and inclusive policy development.

### Typical Horizon Scanning Activities

- Reviewing regulatory publications and consultations.
- Monitoring industry reports and market trends.
- Tracking technological developments (e.g., AI, cybersecurity).
- Analyzing geopolitical, economic, and environmental changes.
- Conducting scenario planning and trend analysis.
- Engaging with industry forums, professional associations, and subject matter
  experts.

### Example Policy Statement (verbatim)

> "The Policy Owner shall conduct periodic horizon scanning to identify emerging
> regulatory requirements, industry developments, technological changes, and
> evolving risks that may impact this policy. Findings shall be assessed and
> incorporated into policy reviews as appropriate."
>
> For a financial institution, horizon scanning commonly covers **regulatory
> changes, cybersecurity threats, AI governance, privacy requirements,
> operational resilience, third-party risk, ESG expectations, and geopolitical
> developments** that may require policy updates.

---

## Slide — **Enterprise Policy Management System** (business case / TIP slide)

### What it is
> Comprehensive technology capabilities to develop, manage, and maintain
> policies through the policy management lifecycle using a dynamic inventory and
> a structured workflow, moving away from the current heavily manual processes.

### Current State
- Policies are drafted and reviewed manually using Word, .pdf forms, and email
- Inventory is tracked via spreadsheets, with no automation or controls
- Policies are stored on the intranet without appropriate search abilities or
  taxonomy alignments

### Key Capabilities
- Centralized, searchable policy repository, integrated with risk taxonomy
- Automated workflow for policy development, maintenance, and archival
- Document retention, version control, and audit trail functionality
- Role-based access and reporting features
- Integration with escalation, regulatory change, and risk systems

### Benefits & Risks of Not Implementing
- **Benefits:** Reduces manual drafting and feedback loops; centralizes access,
  improving clarity and reducing duplication; automates lifecycle tracking to
  ensure timely, compliant policies; saves staff time with integrated workflows
  and audit trails; aligns policies with enterprise systems for better
  governance
- **Risks:** FTE waste time tracking versions and chasing approvals; fragmented
  processes increase risk of outdated policies; no audit trail limits
  accountability and readiness for reviews; missed updates due to lack of system
  alerts or integration; manual processes drive inconsistency and compliance
  risk

### AI Use Cases
- Draft or update policies using regulatory text and internal templates
- Flag policies that may need updates due to rule or internal changes
- Identify duplicate or conflicting policy requirements across groups
- Analyze violation trends and suggest specific policy clarifications
- Recommend related policies to users based on keywords, taxonomy, or usage
  patterns

### Timeline
| # | Milestone | Date |
|---|---|---|
| 1 | System Design (Preliminary) | March 2025 |
| 2 | ERPM Tech Investment Portfolio (TIP) Planning | April 2025 |
| 3 | ERPM TIP Submissions and Reviews | May 2025 – August 2025 |
| 4 | ERPM TIP Funding Available | By November 1, 2025 |
| 5 | System Development | November 2025 – **May 2026** |
| ★ | System Implementation | **June 2026** |

---

## Slide — **Enterprise Governance Management System** (business case / TIP slide)

### What it is
> There is no centralized inventory or oversight of governance activities across
> the client, and the current governance infrastructure is managed through manual and
> fragmented processes. These Governance Infrastructure technology capabilities
> would provide a centralized platform to manage all committees and governance
> forums that are relevant to the **Risk Management Framework** across the client,
> ensuring appropriate coverage and traceability by **legal entity, risk type,
> and operating group**, among other key data dimensions in the risk taxonomy.
> It would also include built-in workflows for forum activities and decisions.

### Current State
- No unified governance inventory; fragmented across teams and spreadsheets
- Some teams maintain no inventory at all
- Forum structures are rebuilt ad hoc for audits or regulatory requests
- No view of full coverage or interconnectivity

### Key Capabilities
- Centralized governance forum inventory with searchable attributes
- Workflow automation for forum creation, updates, and **dissolution**
- Document repository with retention, versioning, and audit trail
- Role-based access, reporting, and analytics
- Integration with escalation, policy, and enterprise risk platform

### Benefits & Risks of Not Implementing
- **Benefits:** Eliminates duplication by centralizing forum data; automates
  updates, saving time during reorganizations; improves coordination across
  forums and decision-makers; strengthens audit readiness with built-in version
  control; enables integration with broader risk capabilities
- **Risks:** FTE spend time recreating forum lists for reviews; overlap or gaps
  persist without centralized visibility; no system to track changes creates
  compliance exposure; governance blind spots delay decisions and escalate risk;
  fragmentation raises conformance risk

### AI Use Cases
- Recommend charter updates to improve alignment and clarity
- Flag governance forums with duplicate or overlapping mandates
- Identify outdated forums or inactive governance bodies
- Suggest structural improvements based on cross-forum analysis
- Monitor governance activity levels and flag potential coordination gaps

### Timeline
| # | Milestone | Date |
|---|---|---|
| 1 | System Design (Preliminary) | March 2025 |
| 2 | ERPM TIP Planning | April 2025 |
| 3 | ERPM TIP Submissions and Reviews | May 2025 – August 2025 |
| 4 | ERPM TIP Funding Available | By November 1, 2025 |
| 5 | System Development | November 2025 – **March 2026** |
| ★ | System Implementation | **March 2026** |

---

## Slide — **Enterprise Escalation Management System** (business case / TIP slide)

### What it is
> These technology capabilities would document, track, and resolve escalation
> events, addressing the current lack of traceability within the governance
> ecosystem. They would support consistency across risk types and ensure
> escalations are directed to the correct committee and authority level through
> **predefined pathways**.

### Current State
- No central view of escalation triggers, destinations, or outcomes
- Paths are tracked inconsistently across email and PPT decks
- Escalation ladders are reconstructed manually for audits or reviews

### Key Capabilities
- Centralized repository for escalation paths, forums, and decision outcomes
- Automated workflows for maintaining and updating escalation protocols
- Documented triggers and actions with full audit trail
- Analytics and tracking for escalation patterns and effectiveness
- Integration with other risk capabilities

### Benefits & Risks of Not Implementing
- **Benefits:** Clarifies escalation paths, reducing confusion and delay;
  automates updates, avoiding manual errors and rework; saves time by routing
  matters to the right forum faster; enhances auditability with documented
  decision trails; connects escalation with governance and risk systems
- **Risks:** Time lost rebuilding paths from emails and slides; inconsistent
  escalation leads to missed or late action; no clear triggers or tracking
  undermines accountability; disjointed protocols weaken enterprise response

### AI Use Cases
- Detect inconsistencies in how similar matters were escalated
- Flag delays or bottlenecks in current escalation flows
- Surface potential under-or-over-escalation patterns
- Suggest updates to thresholds, triggers, or destination forums

### Timeline
| # | Milestone | Date |
|---|---|---|
| 1 | System Design (Preliminary) | March 2025 |
| 2 | ERPM TIP Planning | April 2025 |
| 3 | ERPM TIP Submissions and Reviews | May 2025 – August 2025 |
| 4 | ERPM TIP Funding Available | By November 1, 2025 |
| 5 | System Development | November 2025 – **March 2026** |
| ★ | System Implementation | **March 2026** |

---
