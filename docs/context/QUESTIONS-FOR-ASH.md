# Open questions for the sponsor

Grouped by what they block. Each is answerable in a sentence or two.
Items already closed by earlier direction are not repeated here.

---

## A. Blocks the build starting (need these first)

**A1 — Identity. ⚠️ Now narrower and more urgent.** Which protocol, specifically:
**LDAP, OIDC, or SAML?**

We checked the framework source rather than assuming. **LDAP is first class**
(including group-to-role mapping) and **OIDC works** (as a social-login
provider). **SAML is not implemented at all** — there is no SAML code anywhere
in the framework.

So: if the answer is LDAP or OIDC, single sign-on is configuration and can be
enabled whenever they are ready. **If the answer is SAML, it is an extra build
and has to be estimated separately.** "We use SSO" is not a sufficient answer —
the protocol is the answer, and one of the three costs real work.

Also: who provisions users, and do we read group membership for roles?

**A2 — Taxonomies: source and delivery.** Primary Risk Category, Legal Entity,
Material Entity, Organizational hierarchy (OG/CS, LOB, BU), Jurisdiction. For
each: which system is the system of record, and how do we get the values —
API, scheduled file drop, or manual seed for v1? *If v1 is manually seeded,
say so and we move on; we just need the decision.*

**A3 — Document editor hand-off.** The doc AI editor is already built. We need
its API surface, and one architectural answer: **does the editor or this
platform hold the authoritative policy document body and its version chain?**
That decides where "revert to previous version" is implemented.

**A4 — the AI services platform access.** Endpoint and auth method for the ERPM AI MCP server as
reachable from this platform's network zone. Plus the data-boundary rule: are
we permitted to send policy text, escalation detail and forum content to it?

---

## B. Blocks deployment (Phase 2 success = no devops gaps)

**B1 — Target environment.** the client Windows laptop → on-prem Linux server → AWS.
For the on-prem and AWS stages: OS and version, who owns the box, and is
outbound internet available at install time or must everything be pre-staged?

**B2 — Database provisioning.** Postgres is confirmed. Is it a **managed /
vendor-provisioned** instance or one we install? This matters concretely:
Frappe's `bench new-site` needs a **superuser** to `CREATE DATABASE` and
`CREATE ROLE`. On a managed instance we won't have that, so the DBA
pre-provisions the database and owner role and we install with
`--no-setup-db`. Either path works — we just need to know which, and whether
`CREATE EXTENSION` is permitted.

**B3 — TLS, ports, service accounts.** Who issues the certificate, which ports
are open inbound, and what service account does the app run under?

**B4 — Backup and retention.** Retention/WORM is a separate workstream. What is
its interface (API, webhook, file drop), and who owns it? Also: who owns
database backups — us or the platform team?

**B5 — Teams notifications.** the sponsor's directive adds Teams alerts. Which
mechanism is approved — Graph API with an app registration, or incoming
webhooks? Who registers the app?

---

## C. Needed for the sponsor's review of the BA documents

**C1 — Committee membership.** No source document defines it, so we are
designing it. Three questions decide the shape:
- Are seats held **by person** or **by position/title** (e.g. "the CRO or
  delegate"), so the seat survives a person leaving?
- Do we need **delegates** as first-class records (who delegated, to whom, for
  what period)?
- Is **quorum** tracked, and if so what is the rule (count or % of voting
  members)?

**C2 — CGF workflow.** We believe the two workflows in the corpus are not in
conflict — they sit on different records: the **nine-state RGO flow** on the
*Committee Formation Request*, and slide 13's **Draft → Pending → Compliant /
Non-Compliant / Not-Applicable** on the *Governance Forum* itself. Request
approved → creates the forum in Draft. Does that match intent?

**C3 — Watched fields.** Slide 13: "changes to certain fields trigger a
Compliance review." Which fields? We will ship an editable default list
(forum type, mandate, chair, risk categories, parent forum, regulatory-required
flag) unless told otherwise.

**C4 — G-18 intake fields.** G-18 lists *Document* Name / ID / Type / Sponsor /
Parent / Child on what is a **committee** intake form, and the list matches
Policy's P-3 almost exactly. Intentional, or inherited from the Policy
template? Also: G-7 calls it the "Committee Intake Form", G-17 the "Governance
Intake Form" — one artifact or two?

**C5 — Undefined terms.** **Owner of Governance Forum** (G-10 attestation participant), **jurisdictional
CRO** (G-11 approver), **ONFR** and **LRC** (P-20's additional sources), and
**"Playbook"** (deck slide 6). Each affects who records link to or what gets
built.

**C6 — Attestation.** G-10 sets an annual Q1 attestation by Chairs, Secretaries
and OGFs. P-8 separately requires annual attestation for **Policy**. Same
mechanism for both? And does the slide-13 "annual review by owner and
compliance" mean a third one, or is it the same as G-10?

**C7 — Voting.** The deck's TOM says forums *vote* on governing documents. Do
we record votes (who voted, how, outcome, quorum met), or only the decision?

---

## D. Scope confirmations (can proceed without, but cheap to answer)

**D1 — Optional items.** Deck slide 13 carries seven **Optional** requirements
— the only Optional content anywhere. Everything in the three HLR .docx is
Mandatory. Are the seven in scope for this phase?

**D2 — The four unknown connectors.** **the enterprise GRC system** (slide 14 hints it may be
**a named commercial GRC platform** — confirm?), **Risk Appetite**, **the risk identification system**, and the **regulatory
change system** named on the Policy business-case slide. For each: real system,
owner, and in scope now or stubbed for later?

**D3 — Escalation → Risk Appetite.** The deck leaves this open as a question;
the PRD records it as a confirmed decision ("escalation feeds both CGF and Risk
Appetite"). Which is current?

**D4 — P-16 classification rules.** Major vs Minor policy change. The source
gives two example questions but no decision rules. This is the one genuine
business-logic build in the programme and it cannot be inferred — we need the
actual rules from the business.

**D5 — Current plan dates.** Every implementation milestone on the business-case
slides (March 2026, June 2026) has lapsed. What are the live dates?

**D6 — the incumbent GRC platform footprint.** We won the contract, so the incumbent GRC platform is not the
platform. But is there an *existing* the incumbent GRC platform deployment elsewhere in this
footprint that we still need to integrate with (slide 14 lists it as an
integration target), or is it entirely out of the picture?
