# Delivery documents

**TL;DR.** Consilium **1.0.0** is finished and measured:

- **Tests:** 1453 tests, OK, on a clean site. The interface sweep passes
  302/302 and the browser journeys 11/11.
- **Requirements:** 49 of 64 mandatory requirements are fully reachable, 9
  partly, and 6 miss a single clause.
- **Backlog:** 151 of 191 stories are done, and none is in progress.
- **Last round:** a new header with global search and role-filtered menus.
  Admin → Integrations connects AI (tested against an OpenAI-compatible
  provider), the document editor ("Open in Doc AI"), horizon scanning, and
  e-mail over SMTP or Microsoft Graph.
- **Deployment:** the install is rehearsed air-gapped on Rocky Linux 9, with
  `verify.sh` 14/14.
- **What is left:** mainly target-environment work: a real Windows run,
  certificates, the identity provider, the mail route (SMTP or a Graph app
  registration), load, and a bundle rebuilt from the final commit.

Start with the session summary, then the document for your question.

## In this folder

| Document | Read it for | In one line |
|---|---|---|
| [`SESSION-SUMMARY.md`](SESSION-SUMMARY.md) | The whole picture in five minutes | What exists, the decisions behind it, what is not done, and what still needs a person |
| [`REQUIREMENTS-COVERAGE.md`](REQUIREMENTS-COVERAGE.md) | "Does it meet requirement X?" | Every requirement (G, P, E, O), measured on the final build. For each: what satisfies it, how a user reaches it (class a–d), the demonstration record and the passing tests. Also the remaining gaps and the screen map |
| [`EPICS.md`](EPICS.md) | "Is story X done?" | 36 epics, 191 stories: 151 done, 39 partial, 1 not started, each with its evidence. Obsolete acceptance criteria are struck through with the reason |
| [`DEPLOYMENT-READINESS.md`](DEPLOYMENT-READINESS.md) | "Can the deploying team install and run it?" | What the operator does, **what the organisation provides** (certificate, SMTP or Microsoft Graph app registration, identity provider, AI endpoint, tool addresses), and the air-gapped rehearsal evidence: install, verify, migration, upgrade, services, load, sign-on, Windows. Also what only the real server can confirm |
| [`DEMO-LOGINS.md`](DEMO-LOGINS.md) | Signing in as a persona | The 23 demonstration personas with roles and where each starts, and which menus each sees. How to generate passwords, and why none is ever in git. **Holds no passwords** |
| [`evidence/linux-rehearsal/`](evidence/linux-rehearsal/) | Proof behind the readiness claims | Air-gap proof; install, upgrade, migration, restore and load logs; `verify.sh` reports; rendered systemd and nginx configurations |

## Elsewhere in the repository

| Document | For |
|---|---|
| [`../../HANDOFF-AGENT.md`](../../HANDOFF-AGENT.md) | The AI coding agent taking the platform in-house: run it locally, then deploy it. §4 lists the organisation's decisions, including Admin → Integrations |
| [`../../HANDOVER.md`](../../HANDOVER.md) | Engineers picking the project up cold. Section 4 is the status |
| [`../RUNBOOK.md`](../RUNBOOK.md) | The step-by-step install and acceptance procedure, including the Windows acceptance script |
| [`../OPERATIONS.md`](../OPERATIONS.md) | Day-to-day running; certificates, ports and service accounts; and the technical configuration material that used to be in the guides |
| [`../guides/`](../guides/README.md) | The onboarding guide for business users and administrators: chapters 00–10 and a glossary (11), every screen shown with numbered callouts. Chapter 8 is "your first day" by role; chapter 9 is administration without code |
| [`../USER-GUIDE.md`](../USER-GUIDE.md), [`../ADMIN-GUIDE.md`](../ADMIN-GUIDE.md) | Quick starts: for users, and for administrators (the first-week checklist) |
| [`../product/`](../product/README.md) | Requirements baseline, data model, schema, architecture, glossary, traceability, assumptions |

## Deliverables kept outside the repository

These are generated files, not versioned. By default they are written to
`~/Desktop/Consilium-deliverables/`.

| File | What it is | How it is produced |
|---|---|---|
| `Consilium-Requirements-Coverage.xlsx` | The coverage matrix and the backlog (all 191 stories) as a workbook, in 13 tabs: requirements map, summary, all requirements, one tab per module, gaps, screens, deployment readiness, epics, test cases, parse log | `.venv/bin/python scripts/coverage_to_xlsx.py`, generated from `REQUIREMENTS-COVERAGE.md` and `EPICS.md`. Edit the Markdown, not the workbook |
| `Consilium-Leadership-Briefing.pptx` | 49-slide leadership briefing: what was built (including the redesigned portal and the Integrations screen), the evidence, AI connected and tested, what is not done, the road to production and the decisions asked for. Screenshots come from the final onboarding guide | A deck generator (pptxgenjs) fed by a facts file with the figures above and screenshots from `docs/guides/images/` |
| `Consilium-Onboarding-Guide.pdf`, `.docx` | The onboarding guide in `docs/guides/` as one illustrated book: 217 pages, 185 screenshots with numbered callouts. It replaces the older `Consilium-User-and-Configuration-Guide` files, which are superseded | `scripts/build_guides.sh` |
| `DEMO-LOGINS.md` (with passwords) | Per-run random passwords for the personas (and Administrator with `--administrator`); readable by its owner only | `deploy/demo_logins.py --site <site> --url <url> --out <file outside the repo> --administrator`. It refuses a path inside the repository. **Never commit it and never copy it into the repository** |
