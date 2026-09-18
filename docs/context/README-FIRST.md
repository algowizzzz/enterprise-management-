# Internal context — keep this out of the public repository

Everything here is derived from the client's own documents. It is the material
the public repository deliberately does **not** contain, because that repository
is public and this is not.

**Where to put it:** anywhere outside the repository working tree, or inside it
only if you add the folder to `.gitignore` first. Do not commit it.

## What a new session should read, in this order

| File | What it is |
|---|---|
| `DECISIONS.md` | **Read first.** Every binding directive, D-1 to D-12 plus two open recommendations. These override the source documents wherever they disagree. |
| `ANSWERS-ROUND-1.md` | Two further rounds of stakeholder answers. These override the source documents too, and change scope substantially — retention came in-house, connectors went out, the deck's Optional items came in. |
| `QUESTIONS-FOR-THE SPONSOR.md` | The twenty open questions, grouped by what each one blocks. Several are now answered; the file marks which. |
| `replicas/00-README.md` | Index to clean reproductions of the six source documents, with a fidelity marker on each — 🟢 transcribed verbatim, 🟡 reconstructed. |
| `DATA-MODEL.md` | The working data model, with a §7 list of open items. Superseded by the repository's `docs/product/02-data-model.md`, but it carries the provenance and the argument. |
| `SOURCE-*.md` | Analysis of each source document: what it says, where it contradicts the others, and what was chosen. |
| `PRD-frappe-build.md` | The reconstructed programme PRD. Upstream of everything, and wrong in several places the `SOURCE-*` files identify. |

## The short version of what is settled

- We won the contract. The requirement documents were written for a different
  platform and handed to us; anything that platform would have built, we build.
- The document editor and the AI services are separate applications. We call
  them. **But we hold the authoritative document body and its version chain**,
  so versioning and revert are ours.
- Integrations are out of scope. File import and export replace them.
- Retention and WORM are ours to build, not an external hook.
- All 64 requirements are Mandatory. There is no phase two in the statement of
  work as written; staging delivery is a scope renegotiation, not a
  prioritisation exercise.
- Multi-select for business units, risk types, legal entities and jurisdiction;
  single for primary risk category and owning organisation.
- Nothing may identify the client in anything pushed to the repository.

## The three questions that still change work rather than detail

1. **Which single sign-on protocol.** LDAP and OIDC are configuration. SAML is
   not implemented in the framework at all — that is a separate build and needs
   separate estimation. "We use SSO" is not a sufficient answer.
2. **The major/minor policy classification rules.** The rules engine is built
   and the rules are data; the actual decision rules have to come from the
   business and cannot be inferred.
3. **Whether the inferred parts of the model hold.** `docs/product/07-assumptions-and-gaps.md`
   in the repository lists them and names the most consequential one. It exists
   to be argued with.
