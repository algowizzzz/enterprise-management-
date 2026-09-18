# Requirements Replicas — index

> Standing directives that override these documents are in `../DECISIONS.md`.

Clean reproductions of each source document, one file per original, with
analysis stripped out. Use these when you need *what the document says*. Use the
`SOURCE-*.md` and `DATA-MODEL.md` files one directory up when you need *what it
means and where it conflicts*.

**Classification: the client INTERNAL. Nothing in this directory goes into the public
repository.**

| File | Replica of | Fidelity |
|---|---|---|
| `01-ERM-Policy-Management-HLR.md` | the Policy Management requirements document | table 🟡 faithful, appendices 🟢 verbatim |
| `02-ERM-Escalation-Management-HLR.md` | the Escalation Management requirements document | table 🟡 faithful, appendices 🟢 verbatim |
| `03-ERM-CGF-Management-HLR.md` | the CGF Management requirements document | table 🟡 faithful, appendices 🟢 verbatim |
| `04-Business-Requirements-Deck-20250407.md` | the business requirements deck | 🟢 verbatim (slides 1–2 not captured) |
| `05-Stakeholder-UI-Directives.md` | WhatsApp thread with the sponsor | 🟢 verbatim |
| `06-AI-Services-Deck.md` | the AI services platform deck (ERPM AI) | 🟢 verbatim |

## Fidelity legend

- 🟢 **verbatim** — transcribed directly from a photograph of the original.
- 🟡 **faithful** — reproduced from the reconstructed PRD, which was derived from
  the original. Meaning is right; exact wording may differ. Where a 🟢 appendix
  covers the same requirement, **the appendix wins**.

## Corpus totals

| Module | Reqs | Priority |
|---|---|---|
| Policy (P-1…P-26) | 26 | all Mandatory |
| CGF (G-1…G-19) | 19 | all Mandatory |
| Escalation (E-1…E-19) | 19 | all Mandatory |
| **Total** | **64** | **64 Mandatory, 0 Optional** |

The only Optional requirements anywhere in the corpus are the **7 on deck slide
13**, which are not in any .docx.
