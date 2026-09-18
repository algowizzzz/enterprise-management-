# Answers — round 1 (from the sponsor, relayed)

Applies to `QUESTIONS-FOR-THE SPONSOR.md`. Numbering follows that file's chat list 1–20.

---

## Settled

| # | Question | Answer | Consequence |
|---|---|---|---|
| 3 | Who owns the document body + version chain? | **We do.** Editor is independent; documents are **manually uploaded**. | Revert (D-4) is **ours** to build. No editor API dependency in phase 2. Policy record holds the file + version chain. |
| 4 | the AI services platform access | **Yes** | Still need endpoint + auth string at deploy time; not a build blocker. |
| 7 | TLS / ports / service account | **Ignore for now** | Deferred to deployment hardening. Logged as a devops gap to close before go-live. |
| 8 | Retention/WORM + backups | **We own them** | No longer an external hook — retention is **in scope for us to build**. Bigger than previously scoped. |
| 9 | Teams alerts | **Paused**, but **Graph API** when built | Build the notification layer with a pluggable channel; Teams channel stubbed against Graph API. |
| 12 | Watched fields (re-review trigger) | **Configurable** | Admin-editable watched-field list, not a hard-coded constant. |
| 14 | Undefined terms | **CRO** = Chief Risk Officer/Office · **ONFR** = Operational & Non-Financial Risk · **LRC** = Legal & Regulatory Compliance | Role and stakeholder vocabulary resolved. **Owner of Governance Forum** still inferred — see judgement calls. |
| 15 | Attestation — one mechanism or three? | **Three** | Three distinct attestation events (CGF Q1 inventory · Policy annual · Forum owner+compliance annual), built on **one shared engine** with three campaign types. |
| 16 | Voting | **Record votes too** | Vote records are in scope: who voted, how, outcome, quorum met. |
| 17 | The seven Optional deck items | **Yes, in scope** | Including the home-page user guide, flow-chart view and dashboards. |
| 18 | The four unknown connectors | **Out of scope. Manual upload instead.** | the enterprise GRC system, Risk Appetite, the risk identification system, regulatory change all become **file/manual import**. Removes the largest unknown in the programme. |
| 19 | P-16 Major/Minor classification rules | **Admin-configured, and will change** | Build a **rules engine**, not fixed logic. Admin defines questions, answers and the resulting classification. |
| 20 | Existing the incumbent GRC platform | **Forget it — build from scratch** | No the incumbent GRC platform integration anywhere. |

## Judgement calls delegated to us

| # | Item | Our call |
|---|---|---|
| 11 | Which CGF workflow | Proceed with the two-record split: nine-state RGO flow on `Committee Formation Request`; Draft → Pending → Compliant / Non-Compliant / Not-Applicable on `Governance Forum`. |
| 13 | G-18 intake field naming | Use **committee-centric** names (Forum Name / ID / Type / Sponsor), matching G-3's vocabulary. The document-centric list is treated as inherited from the Policy template. |
| 14b | **Owner of Governance Forum** | Read as **Owner of Governance Forum** — the accountable owner of a forum, distinct from the Chair. Modelled as a membership role. Flagged for confirmation; low risk since it is a role name, not a structure. |

## Standing directive — repository sanitization

**No reference to the client, its people, its entities, or recognisable
look-alikes may appear in anything pushed to the repository.** This covers
document text, code, comments, commit messages, DocType names, fixture data,
demo data, theme colours named after a brand, and file names.

The platform is written as a **generic enterprise governance, risk and policy
platform**. Requirements keep their identifiers (G-1, P-16, E-7) but not their
provenance. All client-identifying material stays in this scratchpad and is
never committed.

---

# Answers — round 2

| # | Question | Answer | Consequence |
|---|---|---|---|
| 1–4 | Identity, taxonomies, doc ownership, the AI services platform | **Approved as proposed** | Users: app-native with SSO pluggable. Taxonomies: admin-maintained tables + CSV import. We hold the document body and version chain. the AI services platform reachable. |
| 5 | Target environment | **Air-gapped Linux server.** Windows laptop first, locally. | **No internet at install time.** Everything pre-staged: Python wheels, asset bundle, vendored front-end libraries. Phase-1 offline install capability is now load-bearing, not a nicety. |
| 6 | Postgres | **Use what we created** — self-installed, we hold superuser | `bench new-site` works unchanged. The `--no-setup-db` managed path is documented as an alternative but is not the deployment route. |
| 10 | Membership design | **Approved** | Standalone `Forum Membership` record, admin-maintained `Governance Forum Role`, by-position seats, delegation, configurable quorum. |

## Air-gapped: what it changes

The no-CDN directive and the air-gapped server are **the same requirement**, and
that is convenient. A CDN reference would simply fail on the target box, so
vendoring Bootstrap and jQuery is not a style preference — it is the only thing
that works. Every external asset must ship in the repository.

Install-time checklist this creates (all verified in phase 1):
- Python dependency wheelhouse, no compiler required
- Pre-built front-end asset bundle committed to the repo
- Vendored Bootstrap + jQuery, no network fetch at build or run time
- No `npm`/`yarn` step at any point
- Postgres and Redis installed locally from packages staged on the box

## Review scope

**the sponsor reviews three artifacts only:** the **data model**, the **schema**, and the
**architecture diagram.** Everything else in the document set is for our own
build and for the deploying team.

## Delivery sequence (agreed)

1. **BA** — full document set (data model, schema, architecture diagram, plus
   supporting documentation)
2. **the sponsor review** — the three artifacts above
3. **PM** — epics and stories for the e2e build
4. **BA** — ~40 page presentation deck
5. **Build**
