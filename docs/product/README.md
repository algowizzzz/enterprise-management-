# Product documentation

The authoritative description of what Consilium is and how it is built.

| Document | What it is | Who reads it |
|---|---|---|
| `01-requirements-baseline.md` | All 64 requirements, restated, with what each needs | Everyone |
| `02-data-model.md` | The logical model: entities, fields, relationships | **Reviewed by the stakeholder.** Engineers build from it |
| `03-schema.md` | The physical PostgreSQL schema | **Reviewed by the stakeholder.** Engineers and DBAs |
| `04-architecture.md` | Components, boundaries, deployment topology | **Reviewed by the stakeholder.** Engineers and operators |
| `05-glossary.md` | Domain terms and abbreviations | Everyone, first |
| `06-traceability.md` | Requirement → entity → module → screen | Reviewers and QA |
| `07-assumptions-and-gaps.md` | What is assumed, inferred or unresolved | Reviewers first |

Start with the glossary, then the data model. `07` lists what to push back on.

Delivery planning lives in `../delivery/EPICS.md`.
