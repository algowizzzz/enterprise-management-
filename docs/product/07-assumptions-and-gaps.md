# Consilium — Assumptions and Gaps

**Document:** 07 of 07 — Assumptions and Gaps
**Purpose:** everything still assumed, inferred or unresolved, with the impact if the assumption is wrong and what would settle it.

---

## 1. How to use this document

Each item has four parts: what is assumed, why it was assumed, **what breaks if
it is wrong**, and **what would settle it**. Items are grouped by what they
block and ordered within each group by impact.

Nothing here is a blocker to starting. Several are blockers to finishing.

| Severity | Meaning |
|---|---|
| **H** | Wrong answer means rework of a model, a schema or a delivery mechanism. |
| **M** | Wrong answer means rework of a feature or a screen. |
| **L** | Wrong answer means an adjustment. |

---

## 2. Blocks go-live, not the build

### A-1 — Write-once storage for archive payloads is not decided  ·  **H**

**Assumed:** that the deployment can provide storage for `private/files` on
which the archive payloads cannot be altered or deleted for their retention
period.

**Why:** the retention requirements (G-16, P-18, E-18) call for a write-once,
read-many form. The platform delivers three of the four mechanisms — no
application path that mutates, database privileges revoked from the application
role, and a verified hash chain. **The fourth, immutable media, is an
infrastructure property this platform cannot create.**

**If wrong:** the platform provides strong tamper *evidence* and good tamper
*resistance*, but not write-once media. A regulator or auditor who tests the
control by attempting a direct file modification will succeed, and the hash
chain will record that they did. Whether that satisfies the obligation is a
judgement the risk function has to make, not one this document can make for it.

**Settles it:** a decision on the filesystem, mount options and backup product
for the air-gapped server, and a named owner for it. Until then, state the
control as "tamper-evident with restricted write access", not "WORM".

---

### A-2 — Backup ownership and retention are unassigned  ·  **H**

**Assumed:** that someone backs up the database and the file tree **together**,
and that restore is tested.

**Why:** neither is decided. `04-architecture.md` §9.4 explains why a database
restored without its files, or files restored without the database, is useless.

**If wrong:** recovery fails when it is needed, and the hash verification that
would have detected an inconsistent restore is never run because nobody owns it.

**Settles it:** a named owner for backups, a stated retention period for them,
and one tested restore before go-live.

---

### A-3 — Transport security, ports and the service account are deferred  ·  **M**

**Assumed:** deferred to deployment hardening, per an explicit stakeholder
instruction.

**If wrong:** nothing in the model or schema changes. This is a
deployment-readiness gap, not a design gap. It is recorded here so that
"deferred" does not quietly become "forgotten".

**Settles it:** certificate issuance, the inbound port list and the service
account the application runs under.

---

### A-4 — The framework's PostgreSQL support carries known limitations, and may carry unknown ones  ·  **H**

**Assumed:** that the two divergences found by reading the PostgreSQL and
MariaDB schema builders side by side — missing child-table and `modified`
indexes, and schema-wide index-name collisions — are the significant ones.

**Why:** the framework prints a notice on site creation that PostgreSQL support
is limited in this major version and that fixes target the next one. Two
concrete divergences were found by direct source comparison. **A third was
found in the search path.** There is no reason to believe the list is complete.

**If wrong:** further divergences appear under load or during a schema
migration, at the worst possible time.

**Settles it:** two things, in order. (1) A decision on whether to target the
next major version of the framework, which is an architecture call already
flagged in the platform toolchain's handover. (2) A migration-and-load rehearsal
against a representative dataset on the target server — not a smoke test.

---

### A-5 — Website global search cannot be indexed as the framework writes the query  ·  **M**

**Assumed:** that the custom register screens, which query indexed columns
directly, carry the search requirements (G-2, P-2, E-2) and that website global
search is a secondary surface.

**Why:** the framework's PostgreSQL global-search query computes
`TO_TSVECTOR("content")` at query time with the one-argument form, which is not
immutable and therefore cannot be indexed. The two-argument form can be indexed
but will not be matched by the query as written. See `03-schema.md` §7.4.

**If wrong** — that is, if global search is expected to be the primary search
surface — it is a sequential scan of the whole search index on every query, and
it will be unacceptably slow.

**Settles it:** either a decision that the register screens are the search
surface, or a framework patch changing the query to the two-argument form. The
patch is small and is a no-op on the other database engine.

---

## 3. Blocks a feature, not the platform

### B-1 — The major/minor classification rules do not exist  ·  **M**

**Assumed:** that shipping a configurable rules engine, seeded with the two
example questions the source gives, is an acceptable delivery of P-16.

**Why:** an explicit stakeholder decision — the rules are admin-configured and
will change.

**If wrong:** nothing structural. The engine is built either way. What is at
risk is that the platform ships with a rule set nobody has agreed, and the first
real classification is wrong.

**Settles it:** one working session with the policy office to author the first
rule set. It is configuration, so it does not need engineering time and it does
not need to happen before the build.

---

### B-2 — Watched fields ship with a guessed default list  ·  **M**

**Assumed:** forum type, mandate, chair, primary risk category, risk types,
parent forum, regulatory-required flag and owning organisation.

**Why:** the source says "certain fields" and names none. The list is
admin-editable by design.

**If wrong:** compliance review fires too often, which is noise, or too rarely,
which is a control gap. Either is a configuration change.

**Settles it:** confirmation from the compliance function. Low urgency because
the cost of being wrong is one screen edit.

---

### B-3 — Concurrent editing of a document body is unguarded  ·  **M**

**Assumed:** that a soft checkout flag on the governing document is sufficient
to prevent two people downloading, editing externally and both uploading.

**Why:** the document editor is external and the round trip is manual. Between
download and upload, this platform does not know what is happening.

**If wrong:** the second upload silently supersedes the first, and the first
editor's work is lost with no signal. The version chain records both versions,
so nothing is destroyed — but the loss is not surfaced.

**Settles it:** confirmation that a soft, administrator-releasable checkout is
acceptable, rather than a hard lock or an editor integration. **This is a
recommendation, not a decision that has been taken.**

---

### B-4 — Closure criteria for escalations are not specified  ·  **M**

**Assumed:** that criteria are configurable rows per closure type, as
`Closure Criterion`.

**Why:** E-10 requires criteria to be *enforced* and names none.

**If wrong:** the criteria set is wrong, which is a configuration change.

**Settles it:** the escalation function listing the criteria for each closure
type.

---

### B-5 — The regulatory-change import format is unknown  ·  **M**

**Assumed:** a delimited file that can be mapped to `Regulatory Requirement`
rows and matched against existing citations.

**Why:** the regulatory-change source was to be a connector; it is now a file,
and nobody has said what is in the file.

**If wrong:** the import profile needs rewriting. The pipeline does not.

**Settles it:** one sample file from whoever owns the regulatory-change process.

---

### B-6 — SAML is not available in the framework  ·  **M**

**Assumed:** that single sign-on, when enabled, will use LDAP or OIDC.

**Why:** verified — there is no SAML implementation in the framework source.
LDAP has first-class configuration including group mapping; OIDC is configured
as a social-login provider.

**If wrong** — that is, if SAML is mandated — it is an **additional component or
build**, not a configuration. Estimate it separately.

**Settles it:** the identity team naming the protocol. This is already on the
open-questions list and is not blocking, because identity is app-native in phase
one.

---

### B-7 — Directory group-to-role mapping is a governance choice, not a technical one  ·  **L**

**Assumed:** that group mapping, if used at all, maps to a small set of coarse
access roles, and that record-level accountability roles stay under local
control.

**Why:** mapping makes provisioning automatic and simultaneously makes role
assignment invisible to this platform's audit trail — which several requirements
depend on.

**If wrong:** either provisioning is manual, or the access-change log has a hole
in it.

**Settles it:** a decision from the risk function on whether external group
membership may confer access without a local audit record.

---

## 4. Inferred model elements awaiting confirmation

All eighteen are listed in `02-data-model.md` §11 with their consequences. The
five that carry real risk are repeated here; the remainder are low-cost either
way.

### C-1 — `Regulatory Requirement` as a shared library  ·  **H**

**Inferred.** Neither G-4 nor P-6 says regulatory references are shared; both
read as free-text capture on the record.

**If rejected:** P-6's "notify impacted policy owners when a regulatory change
occurs" becomes a text search across free-text fields and is effectively
unimplementable as written. G-4 degrades to free-text rows.

**Settles it:** confirmation that regulatory citations are drawn from a
controlled list rather than typed. This is the single most consequential
inference in the model.

---

### C-2 — `OGF` read as "Owner of Governance Forum"  ·  **M**

**Inferred**, and flagged as such at the time it was proposed. The source uses
the abbreviation without definition, as a participant in the annual inventory
attestation alongside chairs and secretaries.

**If wrong:** a seat role is misnamed and the attestation population is wrong.
It is a role name, not a structure, so the correction is a taxonomy edit and a
re-run of the campaign population.

**Settles it:** one sentence from the risk governance function.

---

### C-3 — Restricted handling of download, print and share  ·  **H**

**Inferred as a build.** P-1 and P-13 name view, download, print and share as
separately controllable for confidential documents. The framework has no native
per-record suppression of these.

**If the requirement is softer than written** — for example, if "restricted"
means only that unauthorised users cannot open the record at all — the build
disappears and native permissions suffice.

**If the requirement is as written**, it is a real build, and it must hold on
every path: the form, the list, the report builder, the export, the search index
and the REST interface. **Partial implementation is worse than none, because it
creates the appearance of a control.**

**Settles it:** a conversation with whoever owns the confidential-document
control about what it must actually prevent.

---

### C-4 — Denormalised chair, secretary and owner on the forum  ·  **M**

**Inferred as a performance decision.** The membership record is authoritative;
the forum's officer fields are derived and read-only.

**If wrong** — that is, if the derived fields drift from the membership rows —
the register shows one chair and the membership screen another, and the
attestation population is built from the wrong one.

**Settles it:** not a stakeholder question. It is an engineering obligation: the
derivation must be a single code path, invoked on every membership change, with
a reconciliation sweep that reports drift. **Recorded here because a
denormalisation without a reconciliation check is a defect waiting to happen.**

---

### C-5 — `Closure Criterion`, `Delegable Action`, `Exception Authorisation`, `Business Calendar`  ·  **L**

Four small inferred entities, each making a stated requirement expressible. Each
is cheap to add and cheap to remove. Listed so that a reviewer who does not want
them can say so.

---

## 5. Where two sources still conflict, and what was chosen

These were resolved in order to produce a buildable model. Each is recorded with
the reasoning, so a reviewer can overturn it knowingly.

| # | Conflict | Chosen | Reasoning |
|---|---|---|---|
| **D-1** | The intake artefact is called the "Committee Intake Form" in one requirement and the "Governance Intake Form" in another, in the same document. | **One artefact**, modelled as `Committee Formation Request`, covering create, modify and retire. | Both requirements describe the same object with the same content. Two entities would duplicate every field and split the workflow. |
| **D-2** | One requirement's field list is **document-centric** (Document Name, Document ID, Document Type, Document Sponsor) on a **committee** intake form, and matches the policy metadata list almost exactly. | **Committee-centric names.** | A stakeholder decision settled it. The list reads as inherited from the policy template rather than intended. |
| **D-3** | Two incompatible state machines for the governance forum: a nine-state formation and approval flow, and a five-state compliance flow. | **Two records, two workflows.** Formation flow on the request; compliance flow on the forum. An approved request creates a forum in Draft. | Neither source is discarded. The two flows describe different objects with different lifespans. A stakeholder decision confirmed the split. |
| **D-4** | One requirement reads as a **single** escalation pathway; the template appendix says **governance forum(s)** and **impacted entities**, plural. | **Plural.** Both are child tables. | The appendix is verbatim from the source; the requirement table text is a faithful reconstruction. Verbatim wins. |
| **D-5** | The forum field list in the deck makes business units, risk types, legal entities and jurisdiction **multi-select**; the requirement document reads them as single. | **Multi**, with two carve-outs where the requirement itself is singular: **primary** risk category, and owning organisation. | A stakeholder decision settled it, on the reasoning that multi-to-single is a presentation change and single-to-multi is a data migration. |
| **D-6** | The deck lists a governing-document type absent from the requirement document's taxonomy. | **Not modelled.** It is legacy. | A stakeholder decision settled it. |
| **D-7** | The deck places the governance interconnectivity view on the **home page**; the user-interface slide places it on the **forum detail page**. | **Both.** | It is a view over data that already exists as real relationships. Building it twice costs one component and one placement. |
| **D-8** | One source records "escalation feeds both the governance forums and the risk appetite system" as a **confirmed decision**; another still carries it as an **open question**. | **Both links are modelled**, the forum link in-database and the risk appetite link as an `External Reference`. | With connectors out of scope, the risk appetite link is a recorded identifier either way. The cost of modelling it is one nullable column; the cost of omitting it is a migration. |
| **D-9** | Three overlapping role vocabularies across three documents. | **All three modelled**, on two axes: access roles in the permission engine, accountability roles on the record. | A stakeholder decision directed that all named role sets are in scope. The two-axis split is what makes them coexist without contradiction. |
| **D-10** | Every requirement in the three requirement documents is Mandatory; the only Optional items anywhere are seven on the deck. | **All 64 Mandatory; the seven supplementary items brought into scope as `O-1..O-7`.** | A stakeholder decision brought them in. They are numbered separately so the 64 stays a clean set. |
| **D-11** | One source describes the lifecycle as ending at **Retired**; the deck is explicit that **Implemented** is a distinct act performed after publication, with retirement a separate concern. | **The deck's model.** Draft → Review → Approved → Published → Implemented, with Retired as a separate terminal concern. | The deck is the only source that carries the state machine at all. |
| **D-12** | One source's module introduction names a specific third-party platform as the delivery platform. | **Ignored as a stale platform reference.** The scope it describes is in full. | A stakeholder decision settled it: anything that platform would have delivered, this platform delivers. |

---

## 6. Deliberate exclusions — recorded so they are not mistaken for oversights

| Excluded | Why |
|---|---|
| Foreign key constraints | The framework deletes and renames rows in an order that does not respect them; migration fails in ways that are hard to diagnose. Referential integrity is application-enforced throughout. Stated plainly in `03-schema.md` §9.3. |
| Table partitioning | No table in the sizing estimate justifies it. Recorded so nobody builds it speculatively. |
| A separate reporting database | No requirement asks for one, and the read volume does not justify one. Reporting consumers get a read-only database role. |
| Clustering or high availability | No requirement specifies availability, and the single-scheduler constraint means scaling out needs a deliberate design rather than a copy of the node. |
| An inbound interface for the AI platform | Would be a second authentication surface and a second permission model, with no requirement behind it. |
| Real-time collaborative editing | The external document editor's responsibility. |
| Live connectors to the four external systems | Out of scope by stakeholder decision, replaced by the governed import pipeline. The pipeline is forward-compatible: a connector would populate the same rows. |
| Directive as a governing document type | Legacy, by stakeholder decision. |
| External taxonomy synchronisation | Out of scope this phase. The `external_code` column on every taxonomy is the seam where it would attach. |
| Model training or hosting of any kind | The AI platform is external. |

---

## 7. What a reviewer should push back on

Offered in the spirit of making review productive rather than exhaustive. If a
reviewer has limited time, these are the five places where being wrong is
expensive.

1. **The shared `Regulatory Requirement` library (C-1).** If citations are typed
   rather than selected, one whole requirement becomes unimplementable as
   written, and that should be known now rather than discovered in build.
2. **What "restricted handling" must actually prevent (C-3).** The difference
   between "cannot open" and "cannot download, print or share" is the difference
   between configuration and a build that has to hold on six separate paths.
3. **Whether tamper-evidence is sufficient where the requirement says write-once
   (A-1).** This is a risk judgement, not an engineering one, and this document
   deliberately does not make it.
4. **Retention as a build rather than an outbound hook.** It is the largest
   single scope increase against the source requirement set, and it followed
   from one stakeholder answer. If that answer is revisited, a substantial part
   of Core disappears.
5. **The multi-select decision (D-5).** It is correct and it is not free — every
   filter on those four attributes becomes a subquery rather than a column
   comparison, on the most-used screen in the platform. Worth confirming that
   the reviewer knows the cost they are buying.

---

## 8. Items settled, recorded so they are not reopened

For completeness. Each of these was an open question and has been answered.

| Question | Answer |
|---|---|
| Who owns the document body and version chain? | **This platform.** The editor is independent; documents are uploaded manually. Revert is ours to build. |
| Retention and write-once — external hook or ours? | **Ours to build.** |
| Are the connectors in scope? | **No.** Manual and file-based import instead, for all four. |
| One attestation mechanism or three? | **Three events, one engine.** |
| Are votes recorded, or only decisions? | **Votes are recorded** — entitlement, who voted, how, the outcome, and quorum. |
| Are the major/minor classification rules fixed? | **No** — an admin-configured rules engine. |
| Is the watched-field list fixed? | **No** — admin-editable. |
| Membership design | **Approved:** standalone dated record, admin-maintained seat-role taxonomy with flags, by-position seats, delegation on the seat, configurable quorum per forum. |
| Which forum workflow? | **Both** — formation on the request, compliance on the forum. |
| Identity | **App-native records, single sign-on pluggable later.** |
| Taxonomies | **Admin-maintained tables with CSV import.** No external synchronisation this phase. |
| Database | **PostgreSQL, self-installed, superuser held.** |
| Target environment | **Air-gapped Linux server**, with a Windows laptop for local development. No internet at install time. |
| Are the seven supplementary deck items in scope? | **Yes.** |
| Field-name convention on the committee intake form | **Committee-centric.** |
| Undefined abbreviations | Expanded in `05-glossary.md` §B. One — the forum-owner abbreviation — remains inferred. |

---

## Known inconsistencies in this document set

Found by building a presentation from these documents and checking every figure
against its source. None changes a design decision; all of them would embarrass
whoever quoted the wrong one in a room.

1. **Entity totals were stated three different ways.** §2.2 of the data model
   computes 78 standalone + 36 child = 114. Two other passages restated a
   different total from an earlier draft. The restatements have been removed
   rather than corrected, so §2.2 is now the only place the number is stated.
   **§2.2 is authoritative.**

2. **The count of materially changed requirements disagrees between documents.**
   The traceability summary and the requirement tables differ by one or two in
   each direction. The **requirement tables carry the markers and are
   authoritative**; the summary was written from an earlier pass. Recount before
   quoting a figure.

3. **"Requirements with no user-interface surface: 0"** in the traceability
   summary sits alongside rows whose only surface is a background job, which is
   explicitly not a user interface. The rows are right; the summary line is
   loose.

4. **Some delivery trace tags reference decisions that do not exist here.** The
   epic list cites decision identifiers from a separate log. They are real
   decisions, but they cannot be resolved from this document set alone.

The general lesson, recorded because it will recur: a figure restated in more
than one place will eventually disagree with itself. State it once and reference
it.
