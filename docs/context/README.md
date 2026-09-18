# Why the product is the way it is

`docs/product/` describes what was built. This folder records the decisions and
the source material behind it — the arguments that were had, the conflicts in
the requirements and how each was called, and what is still unresolved.

**Read `README-FIRST.md` first.** It states the settled positions in one page.

| File | What it is |
|---|---|
| `README-FIRST.md` | The settled positions, and the three questions that still change work |
| `DECISIONS.md` | The binding directives, D-1 to D-12. **These override the source documents wherever they disagree.** |
| `ANSWERS-ROUND-1.md` | Two further rounds of stakeholder answers, which moved scope materially |
| `QUESTIONS-FOR-ASH.md` | Twenty open questions grouped by what each blocks; several are now answered and marked so |
| `DATA-MODEL.md` | The working model, with its open items. Superseded by `../product/02-data-model.md`, but it carries the provenance and the argument |
| `SOURCE-*.md` | Analysis of each source document: what it says, where it contradicts the others, what was chosen |
| `PRD-frappe-build.md` | The reconstructed programme requirements. Upstream of everything, and wrong in several places the `SOURCE-*` files identify |
| `replicas/` | Clean reproductions of the six source documents, each with a fidelity marker |

## A note on sanitization

This repository is public. The client, its people, and the commercial products
it uses are referred to by role — "the client", "the programme sponsor", "the
incumbent GRC platform" — rather than by name.

That costs something and it is worth knowing what: a reproduction in `replicas/`
can no longer be matched to its original by name, and a decision attributed to
"the sponsor" does not tell you which person. Where that matters for a specific
decision, ask rather than guess.

Requirement identifiers (`G-1`, `P-16`, `E-7`) are unchanged throughout — they
are neutral and they are how everything cross-references.
