# SOURCE: the business requirements deck

Label on slides: **DRAFT 2.25.25** · 19 slides · Enterprise Risk Management ·
INTERNAL. Captured: slides 3–7.

**This is the "source PPTX" the PRD refers to in §10 Q1.** It is the *business*
requirements deck that predates the three `.docx` technical requirement
documents (`20260306`) by roughly a year. Chronology:

```
PPTX  (DRAFT 2.25.25 / filename 20250407)   ← business requirements, this doc
  ↓
3 × .docx (20260306)                        ← technical requirements, 64 reqs
  ↓
PRD-frappe-build.md                         ← reconstructed Frappe mapping
```

Read it as **earlier and less binding** than the .docx set, but it contains
material the later documents never carried forward.

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

### 🔴 This corrects the data model

The PRD's §5.2 assumed the lifecycle was
`Draft → Review → Approved → Published → **Retired**`.

The business requirements say
`DRAFT → Review → Approved → Published → **Implemented**`.

**"Implemented" is a real state, not a synonym for Published** — step 10 is a
distinct confirmation act by the Front Line *after* publication. Retirement is a
separate concern (lifecycle stage ⑥ on slide 7), not the terminal workflow
state.

Named actors, which map to workflow transition roles:
**First Line / Business Unit · Drafter · Reviewers · Second Line · Policy
Office · Front Line · Risk and Compliance · Audit**

> Note "Policy Office" here vs **"EPO"** in the .docx (P-11, P-23, P-24).
> Almost certainly the same body — confirm, and pick one name.

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

### What this settles

- **PRD §10 Q1 — "what is the existing horizon-scanning tool?"** — stage ① says
  *"leverages **existing** horizon scanning mechanisms"*. It confirms the
  mechanism exists but **still does not name it.** The question stands; this is
  just corroboration that it is real.
- **③ explicitly routes approval "via appropriate governance forums"** —
  a direct Policy → CGF dependency, reinforcing build-CGF-first.
- **⑤ establishes escalation for non-conformance** — a direct Policy →
  Escalation dependency. The three modules are more coupled than the .docx
  documents suggest.
- **④ integrates policies into PRC** — one of the "Unknown" systems in the PRD
  §8 connector inventory, here given a concrete role.

---

## Slide 3–4 — Business Requirements 1–29

Earlier, looser precursors to the 26 P-requirements. Most map cleanly. Items
worth noting because they **do not** appear in the later .docx:

| # | Requirement | Note |
|---|---|---|
| 4 | RBAC roles: **Owner, Approver, Monitor, Partner, Reviewer, Delegate** | 🔴 **"Monitor" and "Partner" are roles that appear nowhere in the .docx or the PRD.** Either dropped deliberately or lost. Confirm. |
| 10 | "Ability to see and **revert** to previous versions" | Revert is stronger than the .docx's "archive and see previous versions" (P-9). Frappe's Version log is a diff trail — **restore-to-version is not native**. Flag if still required. |
| 12 | **Real-time collaborative editing** | Reinforces the P-26 concern |
| 13 | **Automated Consistency Checks**: detects discrepancies in terminology | Not in the .docx. Would be a natural the AI services platform use case |
| 24 | **Regulatory Watchlist Integration**: real-time legal/compliance/risk updates | Relates to the unnamed horizon-scanning source |
| 25 | **AI-Powered Impact Analysis**: assesses how new regulations affect existing policies | 🟢 **AI was in scope from the very first business requirements** — not a late addition from the WhatsApp thread. Strengthens the AI services platform case. |
| 29 | **Compliance Monitoring Dashboard**: tracks adherence across departments | Broader than P-11's EPO monitoring |

The rest (1–3, 5–9, 11, 14–23, 26–28) are recognisable ancestors of P-1…P-26.

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

### Why this matters

Every one of these five is **something Frappe's Desk already provides natively**:
a workspace dashboard, list views with filters, the form sidebar showing
version history/comments/attachments, Role Permissions Manager, and the
Notification DocType.

That is a meaningful argument that the Bootstrap/jQuery directive should apply
to **portal/Web Form pages**, not to replacing the Desk — the UI the business
asked for is close to what the Desk does out of the box.

🆕 **"Playbook"** is a new concept — guidance content shown at policy creation
time. Not in the .docx or PRD. Needs definition: static help text, a template,
or a separate content entity?

---

## Summary — what this deck changes

| # | Finding | Impact |
|---|---|---|
| 1 | **Policy workflow states are `DRAFT → Review → Approved → Published → Implemented`** | Corrects the PRD's assumed "…→ Retired". **Implemented is a distinct state.** Update the data model. |
| 2 | 13-step workflow with named actors (First/Second Line, Policy Office, Front Line, Risk & Compliance, Audit) | Gives real transition roles for the Policy workflow — previously entirely 🟡 |
| 3 | 6-stage Policy Lifecycle with outcomes | Higher-level model; confirm which governs |
| 4 | Horizon scanning confirmed to **exist** but still unnamed | PRD §10 Q1 corroborated, not answered |
| 5 | Policy ③ approves "via governance forums"; ⑤ escalates non-conformance | The three modules are **tightly coupled**; CGF-first confirmed |
| 6 | **AI-Powered Impact Analysis was requirement #25 from the start** | the AI services platform is not scope creep |
| 7 | Roles **Monitor** and **Partner** exist here, absent from all later docs | Confirm whether dropped or lost |
| 8 | Business req #10 wants **revert to previous version** | Frappe's Version log does not natively restore. Flag. |
| 9 | UI requirements closely match Frappe Desk's native capabilities | Argues Bootstrap directive = portal pages, not a Desk replacement |
| 10 | **"Playbook"** concept | Undefined; needs a decision |
| 11 | "Policy Office" (PPTX) vs "EPO" (.docx) | Same body? Pick one name |

---

# BATCH 2 — slides 8–12

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

## Slide 10 — "Governance Management System" (section divider, no content)

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

### Why this matters

1. **Cardinality conflict.** The PPTX says Business Units, Risk Types, Legal
   Entities and Jurisdiction are **multi-select**. The .docx G-3 lists them as
   singular tagging fields, and the PRD §4.3 spike modelled them as single
   Links. **Single vs. multi is a schema decision that is expensive to reverse
   once data exists** — a Link field and a child table are not interchangeable.
   The .docx is newer and nominally authoritative, but it is also the document
   that lost E-6's template lists and copy-pasted G-18 from Policy. **Ask.**
2. **`Membership` is missing from the entire data model.** A committee has
   members, with voting/non-voting status (G-13). That is a child table at
   minimum, and it is needed before any committee can be considered modelled.
3. **Escalation Protocol / Escalation Threshold on the forum** are what make
   E-7's "select a forum as escalation pathway" meaningful — the forum carries
   the rules.
4. **Three different role vocabularies now exist**: PPTX Policy (Owner,
   Approver, Monitor, Partner, Reviewer, Delegate), PPTX CGF Risk Oversight
   (Owner, Approver, Escalator, Risk Owner), .docx G-13 (Committee Secretary,
   Forum Owners, Reviewer, Approver, Viewer, Administrator). These need
   reconciling into one role model before RBAC is built.

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

### 🔴 This is a SECOND, different CGF state machine

| | PPTX slide 13 | PRD §4.3 (reconstructed) |
|---|---|---|
| States | Draft → Pending → Compliant / Non-Compliant / Not-Applicable | 9-state RGO formation workflow |
| Driver | **Compliance team** | multi-role approval chain |
| Rework | send back to creator with comments | rejection path |
| Recurrence | **annual review by owner AND compliance** | not modelled |
| Re-trigger | **edits to certain fields re-open review** | not modelled |

These are not the same workflow and cannot both be the CGF Workflow DocType.
Slide 13's is simpler, compliance-centric, and maps 1:1 onto the *Regulatory
Compliance Status* field also introduced on the PPTX CGF field list
(Compliant / Non-Compliant / Pending / Not Applicable) — which suggests the
status field **is** the workflow state, not a separate attribute.
**Needs reconciliation before the Workflow DocType is built.**

Two mechanics here exist nowhere else in the corpus and have no data-model
support yet:
- **field-change-triggers-review** — needs a watched-field list plus a
  `on_update` hook that resets state to Pending
- **annual review** — needs `last_attestation_date` / `next_review_due` and a
  scheduled job; dual sign-off (owner *and* compliance)

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

### ⚠️ This is the FIRST "Optional" content in the entire corpus

Every requirement in all three .docx sources is marked Mandatory. Slide 13
proves the authors **do** use the Optional category and chose not to apply it
in the .docx set. That changes my earlier reading: the all-Mandatory .docx is
**not** template laziness — it is a deliberate escalation of scope between the
deck and the requirements documents. Worth confirming with the author, because
if it was not deliberate the .docx set is over-committed by design.

Note items 4 and 5 are marked Optional here while the .docx marks the
equivalents Mandatory (notifications: G-9/P-x/E-x; escalation tracking: the
entire Escalation module). Same-named requirement, opposite priority,
depending on which document you read.

Items 6 and 7 are AI/ML-class asks (real-time gap detection, predictive
analytics, automated risk assessment, live regulatory feeds). They require an
external data source that is not named anywhere in the corpus. Not buildable
from the requirements as written — and they line up with the stakeholder
WhatsApp directives for **the AI services platform summarization** and **Copilot**.

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

### 🔴 Two conflicts

1. **This question is recorded as ALREADY RESOLVED in the PRD.** PRD §8 states
   it as a *confirmed design decision*: "Escalation feeds both CGF and Risk
   Appetite." The deck still has it open. Either the PRD captured a later
   decision the deck predates, or the PRD asserted a resolution that was never
   made. **Ask which.**
2. **"a named commercial GRC platform" is the first hint at the enterprise GRC system's identity.** §8 of the data model
   lists 7 unnamed/Unknown connector targets, the enterprise GRC system among them. Slide 14 names
   a named commercial GRC platform, the incumbent GRC platform and a named enterprise HR platform as the GRC platforms in scope. Recording
   a named commercial GRC platform as a *candidate* for the enterprise GRC system — **a hint, not a confirmation**.

Note also: **the incumbent GRC platform appears here as an integration target**, while the
stakeholder WhatsApp directive says the objective is to *"kill the incumbent GRC platform."*
Those are compatible only if the plan is coexist-then-replace. Worth stating
explicitly in scope, because "integrate with the incumbent GRC platform" and "replace
the incumbent GRC platform" imply very different connector work.

Item 1 (link forum → risk ID / risk category + assessments) is the concrete,
buildable one: it is a Link plus a child table on Governance Forum, and it
overlaps the multi-select *Risk Types* field from the PPTX CGF field list.

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

### Notes

- **This is the first explicit UI specification in the corpus** — and it is a
  screen-by-screen layout, not a capability list: home page, main table, forum
  detail, Report tab, Admin tab, Create Forum tab.
- Items 3 and 4 (search bar + sortable/filterable main table) are **exactly**
  the stakeholder WhatsApp directive: *every table needs pagination, sort and
  search with configurable page size, no DataTables, vendored Bootstrap +
  jQuery*. The two sources agree — this is the one place they do.
- Item 1 here is **identical text** to slide 13's Optional item 1. Same
  requirement appears once as **Optional** (slide 13) and once in the
  **mandatory UI list** (slide 15). Another priority collision — see §7 item 23
  of the data model.
- Item 9's "ability to see governance interconnectivity" is the flow-chart view,
  here on the **forum detail page**; slide 13's Optional item 2 put it on the
  **home page**. Both, or pick one — ask.
- Item 10.II confirms the slide-13 workflow: **compliance review is mandatory
  and users are warned about it before they start**, which reinforces that
  slide 13's state machine (not the PRD §4.3 nine-state one) is the real CGF
  workflow. See §7 item 18.
- Frappe mapping: items 2–5 and 10 are native Desk (List View, Report View,
  Form View, workspace/dashboard cards). Items 6–8 as *tabs* are a Workspace
  layout. Item 7 (Admin tab) is the native Role Permissions Manager. **None of
  this needs custom UI in Frappe** — but it does conflict with the stakeholder
  directive to build Bootstrap + jQuery screens. That is a real fork in the
  road and should be decided before any front-end work starts.

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

### ⚠️ What this slide actually settles

**Horizon Scanning is a human process, not a data feed.** Every listed activity
is something a Policy Owner *does* (reads consultations, attends forums, talks
to SMEs). The example policy statement makes it an **obligation on the Policy
Owner**, performed **periodically**, whose **findings feed policy reviews**.

That collapses the §7 "undiscovered external source" problem for this module:
Horizon Scanning does **not** need a regulatory data feed to ship v1. It needs:

- a `Horizon Scan` record: `policy` (Link), `scanned_by` (Link → User, the
  Policy Owner), `scan_date`, `period_covered`, `coverage_areas` (multi-select
  from the 8 named: regulatory change, cybersecurity, AI governance, privacy,
  operational resilience, third-party risk, ESG, geopolitical), `sources_
  reviewed` (child table), `findings` (Text), `impact_assessment` (Select:
  no change / review triggered / immediate update required), `linked_policy_
  review` (Link).
- a scheduled reminder driven by the policy's review cadence.
- the outcome linking back into the Policy review workflow.

**This changes the build order.** §8 listed Horizon Scanning last as "genuinely
net-new, depends on an unnamed external source." As specified here it is a
simple attestation-style record on Policy, and is **cheaper than the Escalation
module**. Automated feeds (slide 13 Optional item 7, "real-time regulatory
updates") are a later enhancement on top of the same record, not a prerequisite.

Also note: the 8 coverage areas are a **named taxonomy** — add to §2.

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

## Cross-cutting read on the three business-case slides

1. **They are three separately funded systems, not one product.** Each has its
   own TIP funding line, its own development window and its own implementation
   date. The requirements corpus treats them as three modules of one platform —
   the funding treats them as three systems. Which one the client build is being
   judged against matters for scope and for what "done" means.
2. **The timelines have already lapsed.** All three implementation dates
   (March 2026 ×2, June 2026) are in the past as of today. Either the programme
   slipped, or this deck predates a re-plan. **Ask for the current plan dates**
   before anyone commits to a schedule off this deck.
3. **Governance and Escalation share a March 2026 date** — consistent with the
   dependency (E-7 needs CGF forums) only if they ship together. Policy lands
   three months later despite being the largest module (26 reqs).
4. **Every slide carries an AI Use Cases block.** 14 AI use cases across the
   three. None are in the .docx requirement sets, none have acceptance criteria,
   and they align with the stakeholder directives (the AI services platform, Copilot). They are a
   fourth workstream that the requirements documents do not cover at all — treat
   as roadmap, not v1 scope, unless told otherwise.
5. **"Integration with escalation, regulatory change, and risk systems"**
   (Policy slide) names **regulatory change** as a distinct system. That is a
   fourth external connector alongside the enterprise GRC system, Risk Appetite and the enterprise
   risk platform — and it is plausibly the source behind Horizon Scanning's
   "real-time regulatory updates" Optional item. Add to the §8 connector
   inventory as Unknown.
6. **"Dissolution"** (Governance slide) confirms the disbanding half of G-18 /
   PPTX CGF item 13 is in scope and needs its own workflow terminal state.
7. **Current-state framing is consistent across all three**: Word/PDF/email,
   spreadsheets, PPT decks, intranet. The system being replaced is **manual
   process**, not an incumbent product — which sits oddly beside the
   "kill the incumbent GRC platform" directive and the incumbent GRC platform-as-integration-target on
   slide 14. Worth clarifying whether the incumbent GRC platform is deployed anywhere in this
   footprint today.
