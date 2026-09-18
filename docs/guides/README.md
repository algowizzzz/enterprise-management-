# Consilium: user and configuration guide

These guides explain how to use the Consilium governance, risk and policy
platform, screen by screen, and how to **configure it to work the way your
organisation works** without asking an engineer. Every picture was taken from
the running system with the demonstration data loaded. The people you see in
the pictures are demonstration personas, such as *Committee Secretary (Demo)*.

They sit alongside two shorter references:

- [`../USER-GUIDE.md`](../USER-GUIDE.md) is a short orientation to the portal.
- [`../ADMIN-GUIDE.md`](../ADMIN-GUIDE.md) is the administrator's checklist:
  first run, access, branding and health checks.

Where these guides and those two references cover the same ground, these guides
give the full, click-by-click procedure.

---

## The chapters

| # | Chapter | What it covers |
|---|---|---|
| 1 | [Getting started](01-getting-started.md) | Signing in, finding your way, the portal and the workspace, roles, text size and theme, the help assistant |
| 2 | [Forums](02-forums.md) | The forum inventory, filters, a forum's page and its tabs, membership on any date, linkages, decisions |
| 3 | [Asking for a forum: formation requests](03-forum-formation.md) | Raising a request, evaluation, questions, approval steps, exceptions and bypasses, the forum it creates |
| 4 | [Compliance reviews, watched fields and disbandment](04-compliance-and-reviews.md) | Recording a compliance review, automatic re-review, the annual review panel, disbanding a forum |
| 5 | [Meetings, minutes, motions, votes and charters](05-meetings-votes-charters.md) | Seats, sittings, minutes and their versions, putting a motion and voting on it, quorum, charters and their challenge |
| 6 | [Policies and other governing documents](06-policies.md) | The register, a document's tabs, lifecycle actions, approvals, versions and the viewer, publication, reviews, horizon scanning, requests and classification, monitoring, violations, the glossary |
| 7 | [Escalations](07-escalations.md) | Raising a matter, severity and the matrix, taking ownership from a queue, working it, action plans, risk acceptance, second-line review, closure, sensitive and systemic matters, time limits and time in each status, record history and evidence packs |
| 8 | [Your inbox and attestation](08-tasks-and-attestation.md) | The inbox, answering an attestation, counter-signing, running campaigns |
| 9 | [Reports](09-reports.md) | Management reporting, exporting figures, gaps and risk, emerging risks, regulatory updates |
| 10 | [Administration](10-administration.md) | People and roles, role profiles, record-level restrictions, impersonation, reference data, imports, branding, time zone, retention and legal holds |
| 11 | [**Configuring the platform your way**](11-configuring-workflows.md) | Adding and renaming workflow states (states and phases); new workflows; approval routes; lifecycle gates; watched fields; the escalation matrix; time limits; templates; classification rules; notifications; campaigns; home-page guidance |
| 12 | [Troubleshooting and questions](12-troubleshooting-and-faq.md) | What an error means and what to do about it |

---

## How to use these guides

- **Start with chapter 1**, whatever your role. It takes ten minutes, and the
  rest of the guides assume you know the portal, the workspace and roles.
- **Then read the chapters for your role** (see the table below). Each chapter
  stands on its own.
- **Each chapter follows the same pattern:**
  1. what the area is for;
  2. who can use it (the roles);
  3. numbered procedures with pictures;
  4. what happens next;
  5. the errors you may meet and what they mean;
  6. tips.
- **Words in bold** are the exact labels you will see on screen: buttons, tabs,
  fields and menu items.
- **Terms** are defined in the [glossary](../product/05-glossary.md). You can
  also ask the help assistant, for example "What does *watched field* mean?".

### The four rules behind everything

Four platform rules explain most of what you will see. They also explain why
configuration is safe to change.

1. **Nothing is deleted.** Seats are ended, forums are disbanded, documents are
   retired, reference values are made inactive, and versions are added rather
   than overwritten. You can always see how things stood on a past date.
2. **States are configuration, logic reads flags.** A state's name, such as
   "Review", means nothing to the platform. What the platform reads is a small
   set of *flags* recorded against each state: whether the record is editable,
   in force, awaiting review, still open, and so on. A state with no flags
   recorded is **refused**, never guessed. Chapter 11 shows how this makes
   adding or renaming a state safe.
3. **Every action is checked on the server.** The screens only offer what you
   may do, but the server checks your role and the record's stage again when
   you act. Following a link or retrying an old page cannot get round it.
4. **Every refusal is recorded.** When a control stops an action, the reason is
   written to the **Governance Refusal Log**, even though the action itself
   did not happen.

---

## Which chapters do I need?

| Your role | Read |
|---|---|
| Anyone who only looks things up (**Governance Viewer**, **Consilium Audit**) | 1, 2, 6 (the register and a document's page), 9 |
| **Committee Secretary** | 1, 2, 3, 5, 8 |
| **Forum Owner** | 1, 2, 4, 8 |
| **Risk Governance Office** | 1, 2, 3, 4, 5, 8, 9, 11 (sections on formation routes, watched fields and campaigns) |
| **Head of Risk Governance** | 1, 3 (approvals, exceptions and bypasses), 7 (risk acceptance), 8 |
| **Compliance Reviewer** | 1, 2, 4, 8 |
| **Policy Owner** | 1, 6, 8 |
| **Policy Reviewer** | 1, 6 (review, returning to drafting, violations) |
| **Enterprise Policy Office** | 1, 6, 9, 11 (lifecycle, gates, routes, rule sets, notifications) |
| **Escalation Owner** | 1, 7, 8 |
| **Escalation Reviewer** | 1, 7 (second-line review) |
| **Records Manager** | 1, 10 (retention and legal hold) |
| **Taxonomy Administrator** | 1, 10 (reference data and imports) |
| **Consilium Administrator** / platform administrator | All, especially 10, 11 and 12 |

---

## About the pictures

- **How they are made.** Every picture is produced by
  `scripts/capture_screenshots.py`, which signs in as each demonstration persona
  and photographs the screens at 1440 × 900 pixels. It signs in without a
  password: it creates an ordinary session on the server and discards it
  afterwards. Re-running the script refreshes every picture after the screens
  change. The file `images/manifest.json` records which picture was taken as
  whom, and when.
- **Pictures in chapter 11** (in `images/verification/`) were taken while the
  worked examples were set up on the demonstration site. Those examples were
  then removed.
- **The demonstration data is rebuilt from time to time**, and record numbers
  (such as `FRM-2026-00006`) change when it is. The script therefore finds each
  record by what it is (for example "the forum awaiting its first review"), not
  by its number.
- **Your screens may differ.** Your organisation's name, logo and colours
  replace the demonstration branding (chapter 10). Some buttons and tabs appear
  only for particular roles.

## Printed and Word versions

`scripts/build_guides.sh` combines these chapters into one PDF and one Word
document. Each has a title page, a table of contents and every picture.
