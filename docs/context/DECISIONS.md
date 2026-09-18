# Decisions log — directives that close open questions

Newest first. Each entry names what it resolves in `DATA-MODEL.md` §7 and in the
source documents. These override earlier analysis.

---

## D-12 — Multi-select wins. Single is a subset.
Closes §7 item 8 / the PPTX cardinality conflict. **Business Units, Risk Types,
Legal Entities and Jurisdiction are multi-select** on `Governance Forum`.

Rationale (confirmed correct): in Frappe, multi→single is a UI restriction;
single→multi is a **data migration** (Link column → child table, plus every
report, filter and integration that reads it). Start where reversal is cheap.

Implementation: `Table MultiSelect` child tables, one per taxonomy.
**Two carve-outs** where the requirement itself says singular:
- **Primary Risk Category** (G-3) — "Primary" means one. Model as a single Link
  *plus* the multi-select `risk_types` table; primary is one of them.
- **Owning Organization (OG/CS)** and **(LOB)** (G-3, G-18) — org ownership is
  a single accountable line; keep as Links.

Cost of multi-select to be aware of, not to avoid: list-view filters on child
tables need `Table MultiSelect` filter syntax, and any outbound integration
(G-19 publishes to Policy/Escalation/Risk Appetite/the risk identification system) now sends arrays —
confirm consumers accept them.

## D-11 — One umbrella, not three systems.
Closes §7 item 29. The three TIP-funded systems are being **combined into a
single platform**: Policy + Escalation + CGF, plus AI services via the AI services platform
(API/MCP) and redirect-out to the document AI editor when editing is needed.

Consequences: shared entities (User, taxonomies, audit, attestation, RBAC) are
built **once**, in Core. Cross-module links become native Link fields rather
than integrations — G-19's "publish to Policy, Escalations, Risk Appetite" is
an in-database join for the first two. Only Risk Appetite and the risk identification system stay as
external connectors. The separate implementation dates on the business-case
slides no longer apply.

## D-10a — "vended/vendered sql" meant **vendored JavaScript and CSS**.
Confirmed by the author. It restates the no-CDN directive for Bootstrap and
jQuery assets. **There was never a database directive from the sponsor** — so nothing
competes with D-10 below.

## D-10 — Postgres confirmed.
Closes the database question. Frappe + PostgreSQL, as already built and tested
in the Windows port. No SQL Server consideration needed.

## D-9 — The document AI editor is already built.
Reinforces D-2: it exists, from the prior the AI services platform project. Not a build item and
not a risk. This platform **redirects to it** when a policy needs editing, and
consumes what comes back. The only open item is the hand-off contract (entry to
Review Stage, reviewer assignment, disposition and version events returning) —
and **who stores the authoritative document body and its version chain**, which
also decides whether D-4's revert applies to Policy here or lives in that app.

## D-8 — **We won the contract. the incumbent GRC platform did not.**
Closes §7's the incumbent GRC platform question and the Policy-doc platform reference.

The requirement documents were **written for the incumbent GRC platform and then handed to us**.
The "in the incumbent GRC platform" sentence in the Policy module intro is therefore a stale
platform reference, not a live commitment — but the **scope it describes is
ours in full**. Standing rule:

> **Anything the incumbent GRC platform would have built, we build.**

This also settles the slide-14 tension: the incumbent GRC platform is not a coexistence partner
here. It stays on the connector list only if an *existing, separate* the incumbent GRC platform
deployment is confirmed elsewhere in the footprint (§7 item 34, still open —
low priority now).

---

## D-5 — `Directive` document type is **legacy. Ignore.**
Closes §7 item 16 (in part). The PPTX governing-document taxonomy listed
`Directive` as a type absent from the .docx P-1 taxonomy. It is legacy and is not
to be modelled. **Do not add a `Directive` value to the policy-type taxonomy.**
*(The related "lexicon vs glossary" naming question in the same item is
unaffected — P-24 "glossary" stands.)*

## D-4 — **Version revert is in scope.**
Closes §7 item 10. Deck business requirement #10: *"Ability to see and revert to
previous versions."* The .docx (P-9, G-9) require only that history be tracked
and prior versions retained and accessible; **revert** appears in the deck.
Direction is to include it.

**Build consequence:** Frappe's Version log is a forward diff trail — it records
changes, it does not restore. Revert must be built: read the Version chain,
reconstruct the target snapshot, write it back as a **new version** (never by
mutating history), with the revert itself recorded as an auditable action
(who, when, from which version, why). Applies to `Policy`, `Governance Forum`,
and `Committee Charter`.

## D-3 — **Roles: use the PPTX role sets.**
Direction: *"Roles include if in ppt."* Where the deck names a role vocabulary,
it is in scope. That means all three named sets are modelled, not reconciled
away:
- **Policy (deck slide 3–4 #4):** Owner, Approver, Monitor, Partner, Reviewer,
  Delegate
- **CGF Risk Oversight (deck slide 12):** Owner, Approver, Escalator, Risk Owner
- **CGF access roles (.docx G-13):** Committee Secretary, Forum Owners, Reviewer,
  Approver, Viewer, Administrator

Partly closes §7's three-role-vocabularies problem: the answer is **include them
all** rather than collapse them. They are different axes — *access* roles
(G-13, RBAC) versus *accountability* roles on a record (deck). Model access roles
as Frappe Roles and accountability roles as fields/child rows on the record.

## D-2 — **The document editor is a separate application.**
Closes the P-26 question. The Policy Editor is **not built here** — this platform
integrates with it. P-26's inline commenting, revision suggestions, real-time
feedback disposition and collaborative editing are that app's responsibility.

**What remains ours:** the hand-off contract — how a policy enters Review Stage,
how reviewer assignments are passed, how dispositions and version/audit events
come back, and where the authoritative document body lives. **Still needed:** the
editor's API surface and whether it or we own the document versions.

## D-1 — **the AI services platform is a separate application. Call it for AI services.**
Closes §7 item 31 and the AI questions raised by the business-case slides.
All AI capability — summarization, drafting, classification suggestions, gap
detection, impact analysis — is **an outbound call to the AI services platform**, not a model we
host or train.

Per `replicas/06-AI-Services-Deck.md`, the AI services platform exposes an **MCP server** (JSON-RPC
2.0, on-prem and AWS, RBAC + OAuth + audit logging). So the integration is an
MCP client, not bespoke REST work — which is the point that deck makes.

**Build consequence:** one adapter, one credential path, one audit hook. The 14
AI use cases on the business-case slides become **feature requests against
the AI services platform**, not schema or model work here. Ours is: where in each workflow an AI
call is offered, what context we send, and how a suggestion is recorded (who
accepted it, against which version) so the audit trail stays intact.

**Still needed:** endpoint and auth for the ERPM AI MCP server from this
platform's network zone; whether text-only still holds; data-boundary rules for
sending policy or escalation content to it.

---
---

# Open recommendations — awaiting your call

## R-2 — CGF workflow: build both, because they are two different DocTypes

**The conflict may not be a conflict.** The two state machines describe two
different things, and Frappe already wants them on separate records:

| Record | Workflow | Evidence |
|---|---|---|
| `Committee Formation Request` (G-17 intake) | the **nine-state RGO formation flow** — submission, RGO evaluation against the five criteria (G-5), Head of Risk Governance exception path, approval chain | G-5, G-7, G-17 are all written about a *request* |
| `Governance Forum` (the master record) | slide 13's **Draft → Pending → Compliant / Non-Compliant / Not-Applicable**, compliance-driven, send-back-to-creator, annual review, re-review on watched-field edits | slide 13 step 1 is "create new forum"; slide 15 item 10.II warns users about compliance review at intake |

A formation request is approved → it **creates** a Governance Forum in Draft.
The forum then carries a compliance status for the rest of its life. Both
documents are satisfied and nothing is thrown away.

**Why this is safe to build without an answer.** In Frappe a Workflow is a
**DocType record** — states and transitions are rows in a table, editable by an
administrator in the UI. Changing the state machine later is configuration, not
a rebuild — **provided business logic never keys off literal state strings**.
So the standing rule for this build:

> Never write `if status == "Pending Compliance Review"`. Key logic off a small
> set of semantic flags on the record (`is_editable`, `is_active`,
> `requires_review`) that the workflow sets. Then a state rename, an added
> approval step, or a wholesale swap to the other state machine costs an
> afternoon of configuration.

Proceed on this basis; fold in the real answer whenever it arrives.

**One item still genuinely blocked:** slide 13 step 6, "changes to certain
fields trigger a Compliance team review." The list of fields is not specifiable
from any document. Build the mechanism (an `on_update` hook comparing a
configurable watched-field list, resetting state), ship it with a **best-guess
default list** — forum type, mandate, chair, risk categories, parent forum,
regulatory-required flag — and let Compliance edit the list in the UI. Costs
nothing to change later.

## R-1 — UI: the gap between A, B and C, and why the choice doesn't block you

**The honest answer: the gap is real between A and B, small between A and C —
and none of it blocks the next several weeks of work.**

| | A — native Desk, themed | C — hybrid | B — full custom Bootstrap |
|---|---|---|---|
| Time to a demo-able system | ~3–4 weeks | ~7–9 weeks | ~4–5 months |
| Matches slide 15 layout | roughly | **yes, on the screens that matter** | exactly |
| Matches the sponsor's Bootstrap/jQuery/theming directives | partially | yes, on those screens | yes, everywhere |
| Table pagination/sort/search | free | free on Desk screens, hand-built on custom ones | hand-built everywhere |
| Re-implementation risk | none | contained | **high** — permissions UI, workflow buttons, attachments, version display, report builder, export all rebuilt |

What B actually costs is not CSS. It is re-implementing the things Frappe
already got right: permission-aware rendering, workflow action buttons, file
attachments, comment threads, version history display, the report builder and
its exports. Server-side permissions still hold — Frappe enforces them in the
API regardless of the front end — so B is not *unsafe*, it is *slow*, and every
one of those rebuilt pieces is a place to get an audit finding.

**Recommendation: C.** Custom Bootstrap on the five to eight screens anyone
demos or uses daily — home page with the user guide, the main forum table, forum
detail, the create-forum wizard, dashboards. Native Desk for admin, role
management, taxonomy maintenance, workflow configuration, report builder, audit.
Users never notice the seam; the parts that win the room look exactly like
slide 15; the parts nobody demos cost nothing.

**Why you can defer the decision:** the data model, workflows, permissions,
integrations and revert logic are **identical in all three options**. That is
the next several weeks of work. Build the backend, demo it on A, then skin the
demo screens into C. Nothing done in that period is wasted under any of the
three, and you will be choosing with a working system in front of you instead
of a slide.
