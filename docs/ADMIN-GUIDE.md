# Administrator guide

For the people who set the platform up and keep it running: platform
administrators, the governance office's lead, and whoever maintains the
reference data. Installing the system is covered in [`RUNBOOK.md`](RUNBOOK.md)
and day-to-day running in [`OPERATIONS.md`](OPERATIONS.md). This guide covers
what comes after installation: making the system usable, making it yours, and
keeping it correct.

> **Step-by-step, illustrated guides.** For click-by-click procedures with
> screenshots, see [`guides/README.md`](guides/README.md), especially
> [chapter 10, Administration](guides/10-administration.md) and
> [chapter 11, Configuring the platform your way](guides/11-configuring-workflows.md).
> Chapter 11 has a verified procedure for every configuration record named in
> §6 below.

Read [`USER-GUIDE.md`](USER-GUIDE.md) first. Everything below assumes you know
what the portal's pages are for.

---

## 1. How it fits together

| Piece | What it is | Where to change it |
|---|---|---|
| **Portal** | The screens most people use: `/`, `/forums`, `/policies`, `/escalations`, `/reports`, `/admin`, the guided forms. | Page templates in `apps/consilium/consilium/www/`. Look and feel from **Portal Branding**. |
| **Workspace** | The full record screens at `/app`, with four workspaces: Governance, Policy, Escalation, Consilium Administration. | Records, roles and settings, through the interface. |
| **Record types** | About 140 entities across Core, Governance, Policy and Escalation. | Generated from `apps/consilium/specs/`; see `DEVELOPING.md`. |
| **Reference data** | The lists every form chooses from. | `/admin`, or CSV import. The starting set is in `deploy/reference/`. |
| **Rules as data** | Workflow state flags, watched fields, approval routes, lifecycle gates, escalation matrix, service levels. | Records in the workspace. None of these need a release. |

Three design rules explain most of how the system behaves. Knowing them saves
support calls.

1. **Nothing is deleted.** Seats are ended, forums are disbanded, documents are
   retired, and reference values are made inactive. History can always be read
   back as it stood on any date.
2. **States are configuration, flags are logic.** A state's name (for example
   "Under Review") means nothing to the code. The code reads semantic flags
   (`is_editable`, `is_active`, `requires_review`, `is_open`, `is_committable`,
   `requires_statement`, `is_affirmative`), and a state's flags come from its
   **Workflow State Flag** row. Renaming a state, or adding one, is
   configuration.
3. **Every refusal is recorded.** When a control stops an action, the reason
   is written to the **Governance Refusal Log**, even if the action is rolled
   back.

---

## 2. First-run checklist

After installation, in this order. A system without these steps works, but
people will hit empty dropdowns and unassigned steps.

1. **Reference data.** `deploy/seed.py` loads a generic starting set:
   - forum types and roles;
   - risk categories and a two-tier risk type taxonomy;
   - organisation units and organisational levels;
   - legal entity, jurisdictions, document types, escalation types, lines of
     defence.

   Replace it with your own taxonomy (§4). It is only there so the system
   works out of the box.
2. **Time zone.** In **System Settings**, set the zone your organisation works
   in. Dates the server stamps, such as "decided on", use it. The installer
   leaves it at UTC.
3. **Branding.** Set the portal's name, logo, colours and home page (§5).
4. **People and roles** (§3). At least one active person must hold each of:
   - **Risk Governance Office.** Raising approval steps on a formation request
     fails with *Step Unassigned* without one.
   - **Head of Risk Governance.** Approval exceptions and bypasses need one.
   - **Compliance Reviewer.** Forums cannot leave draft without one.
   - **Enterprise Policy Office**, **Policy Owner** and **Policy Reviewer**, for
     the document lifecycle.
   - **Escalation Owner** and **Escalation Reviewer.**
5. **Formation approval route.** A standard route is created automatically.
   Review its steps under *Governance → Formation Approval Route* and adjust
   them to your delegations.
6. **Escalation configuration.** Create at least one **Escalation Matrix**, the
   **SLA Definitions** for the time limits you hold yourselves to, and a
   **Business Calendar** if limits count working hours only. Without these,
   severity is always manual and no clock runs.
7. **Home page guidance.** Write **Guide Articles** (Admin → *The home-page
   guide*). Each article replaces one section of the built-in wording on the
   home page.
8. **Notification channels.** Point **Notification Channels** at your mail
   system. To show your logo in outgoing mail, set **Brand Logo** on the
   outgoing **Email Account**.
9. **Retention.** Define **Retention Classes** and assign them, before records
   accumulate.
10. **Check it.** Run the health check (§8). It should report every check
    passed.

---

## 3. People and access

**Add a person.** *Admin → Users*, or `/app/user/new`. Use the **System User**
type for anyone who works in the portal or the workspace. Assign roles on the
user's **Roles** tab. For people who share a job, a **Role Profile** (*Admin →
Role profiles*) gives the right set in one step.

**Limit someone to part of the organisation.** *Admin → Record-level
restrictions* (User Permissions). For example, restrict a user to one
organisation unit or legal entity. The restriction applies everywhere:
lists, counts, reports, search and the API.

**Sensitive escalations.** A matter marked *sensitive* is invisible to anyone
without the **Sensitive Escalation Access** role, on every read path. Grant
that role sparingly, and review who holds it as part of your access reviews.

**See what a user sees.** Open the user in the workspace and use
**Impersonate** (System Manager only). (In this framework version the button is shown only when you are signed in as
the **Administrator** account; see [guides/10-administration.md §10.3](guides/10-administration.md).) The session is logged. This is the
right way to reproduce "I can't see X", and it involves no password.

**Remove access.** Disable the user; do not delete them. Their name stays on
everything they did.

The role table in the user guide (§8) says what each role can do. The exact
permissions are on each record type (*Admin → Permission rules*). Change them
there if your operating model differs, and record why.

---

## 4. Reference data

`/admin` lists every reference list with its purpose, its module and how many
values it holds. **Add a value** opens a new entry. **Refresh counts** re-reads
the numbers.

- **Never delete a value that records use.** Untick **Active** instead. The
  value stays on historical records and is no longer offered for new ones.
- **Codes are permanent.** Integrations and imports match on the code. Rename
  the display name freely, but do not reuse a retired code.
- **Bulk changes:** every list accepts CSV import (*workspace → the list →
  Menu → Import*). **Import Profiles** save a mapping you use regularly.
- **Risk types have two tiers.** A tier 1 type has no parent; a tier 2 type
  must have one.
- **Organisation units are one tree:** operating groups, corporate support,
  lines of business and business units.

---

## 5. Making it look like your organisation

*Consilium Administration → Portal Branding* (`/app/portal-branding`). One
record controls:

| Section | Fields | Where it shows |
|---|---|---|
| Identity | Portal name, organisation name, logo, browser-tab icon | Portal header and footer, the browser tab, the sign-in page, the workspace header and loading screen. |
| Colours | Primary colour, accent colour, header style (primary colour or white) | Every portal page. Shades are derived from the primary colour, and the dark theme is adjusted to keep contrast. |
| Typeface | Font family name, regular and bold font files | Every portal page. |
| Home page banner | Heading, text, image, two buttons and their links | The top of the home page. |
| Footer | A line of text | Every portal page. |

Save, then reload the portal. There is no deployment step.

**Brand assets are uploaded, not committed.** Logos, photographs and font files
are stored as site files and served from your own server, so the code
repository never holds anyone's brand. Upload only assets your organisation is
licensed to use in this way, particularly fonts. Many commercial fonts are
licensed per domain or per server.

**Practical advice:**

- **Logo:** use SVG where you can, wide rather than square. If your logo is
  drawn for a white background, set **Header style** to *White*.
- **Banner image:** at least 1600 pixels wide, with the subject on the right.
  The heading sits on the left over a gradient.
- **Colours:** the system picks white or dark text for readability
  automatically. Check the home page in both themes after a change.

Saving the record also updates the framework's own settings: the website and
system application name, logo, favicon, splash image and footer. It also hides
the framework's help and app-switcher entries. The same step re-runs on every
migration, so an upgrade does not bring them back.

---

## 6. Configuring behaviour

All of these are records. Change them in the workspace; none needs a release.

| To change | Edit | Notes |
|---|---|---|
| The steps a formation request goes through | **Formation Approval Route** (and its steps) | Steps are role-based, in sequence or in parallel. The most specific active route wins. A role-based step goes to the first enabled holder of the role, alphabetically. |
| The criteria a request is evaluated on | Seeded on each new request as rows | The five standard criteria are always present. |
| Document approval routing | **Approval Route** | Conditional routing for governing documents. |
| What must be true before a document changes phase | **Document Lifecycle Gate** | For example, no publication without a complete approval chain. |
| The document lifecycle itself | *Workflow → Governing Document Lifecycle* | Add a state here **and** its **Workflow State Flag** row (below). |
| What a state means | **Workflow State Flag** | One row per state, per record type. A state with no row is refused rather than guessed. |
| Changes that send a record back for review | **Watched Field Set** | For example, changing a forum's mandate sends it back for a compliance review. |
| Escalation severity and routing | **Escalation Matrix** (rules, routes, notifications) | Used when a matter's severity source is *Matrix*. |
| Required fields per escalation type and severity | **Escalation Template** | Separate templates for the escalation, its action plans and its risk acceptances. |
| Time limits | **SLA Definition**, **Business Calendar** | Clocks start and stop automatically; breaches are recorded and notified. |
| Periodic attestations | **Attestation Campaign** | Generates a task for each person in the population. |

**Adding a workflow state (worked example).** To add "Legal Review" between
Review and Approved:

1. Add the state and its transitions to the workflow.
2. Add a **Workflow State Flag** row: target type *Governing Document*, state
   field `lifecycle_phase`, state *Legal Review*, and the flags it should carry
   (editable? active? requires review? open?).
3. Test by moving a document through it.

Without step 2 the system refuses to enter the state rather than leaving stale
flags. That is deliberate: a missing row shows up at once, instead of quietly
removing a permission weeks later.

> **The full procedure has more steps than this summary.** Governing Document's
> *Lifecycle Phase* is a list field, so the new state must also be added to its
> options. Customize Form refuses to do this; a Property Setter is needed. You
> also need a Workflow State and a Workflow Action Master for the new names,
> and optionally a lifecycle gate. All of this was verified on the
> demonstration site: see
> [guides/11-configuring-workflows.md §11.3](guides/11-configuring-workflows.md)
> for the procedure, and §11.4 for renaming a state safely.

---

## 7. The workspace

The four Consilium workspaces are part of the application and sit first in the
sidebar. The framework's own workspaces (Users, Website, Tools, Integrations,
Build) come after them. Administrators can add shortcuts or cards to a
workspace with **Edit**. Users can hide workspaces they do not need from their
own sidebar.

---

## 8. Keeping it healthy

| Check | Command (from `<bench>/sites`, with `FRAPPE_BENCH_ROOT=<bench>`) | Expect |
|---|---|---|
| Health check | `python <repo>/deploy/healthcheck.py --site <site>` | Every check passed, including *libraries loaded on demand*. |
| Full verification | `<repo>/scripts/verify.sh --bench <bench> --site <site>` | Platform rules, toolchain tests, migration, application tests, health. |
| Interface sweep | `python <repo>/scripts/ui_regression.py --site <site> --url <address>` | Every portal page renders, signed in and out; no dead links or missing assets; no framework branding visible. |

Run the health check after every change to the installation, and the full
verification after every upgrade.

**Where to look when something fails:**

- **Error Log** (Admin → *Error log*): server errors, with their traceback.
- **Governance Refusal Log**: every action a control refused, and why.
- **Scheduled jobs** (Admin → *Scheduled jobs*): background work and when it
  last ran. Run **exactly one** scheduler process across the deployment, or
  every scheduled job fires twice.

**Upgrading:** follow [`OPERATIONS.md`](OPERATIONS.md). In short: back up,
update the code, re-import the asset bundle with
`winbench assets --import <bundle> --copy`, migrate, then run the health
check. Browsers pick up new stylesheets and scripts automatically, because
asset addresses carry a fingerprint of the files.

---

## 9. Demonstration data

`deploy/demo_data.py` loads a realistic demonstration organisation:

- about twenty role-based personas (all `@demo.example`);
- a forum hierarchy with membership, meetings, motions and votes;
- governing documents in every lifecycle phase;
- escalations in every state, with action plans, risk acceptances and
  closures;
- configuration: escalation matrix, time limits, approval route, attestation
  campaign, guide articles.

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> python <repo>/deploy/demo_data.py --site <site>
```

It is safe to run twice. **Do not load it into production.** The script's
header describes how to remove it. The demonstration users have no passwords;
use **Impersonate** to see the system as one of them.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| A dropdown on a form is empty | The reference list has no active values | Add values at `/admin`, or re-run `seed.py`. |
| "Step Unassigned" when raising approval steps | Nobody active holds the step's role | Give the role to an active person (§2, step 4). |
| A JSON or code field shows no editor | The runtime libraries are missing from the asset bundle | Re-import the bundle; the health check names what is missing. |
| The workspace opens on a blank setup wizard | First-run setup not marked complete | Run `seed.py`; it completes setup and resets the landing page. |
| The portal looks unstyled or out of date | Assets not linked after an upgrade | `winbench assets --import <bundle> --copy`, then reload. |
| A user sees less than expected | A role or record-level restriction | Impersonate them (§3) and check *Record-level restrictions*. |
| A refusal message on save | A control or gate refused it | The message names the rule; the Governance Refusal Log has the detail. |
| Scheduled notices arrive twice | Two scheduler processes | Stop one. |

---

## 11. Help assistant

The **Help** button on every portal page answers questions about that page.
It needs no configuration and no network: out of the box it answers from the
user guide, this guide (administrators only), the glossary, published **Guide
Articles**, published enterprise-scope **Glossary Terms**, and a built-in
description of every portal page. Answers take the asker's roles and
permissions into account, and it never describes a record the asker cannot
read.

**Where the guides come from.** In a development checkout the assistant finds
the repository's `docs/` folder itself. An installation from the bundle
carries the application but not `docs/`; copy the folder onto the server and
set its path in the site configuration:

```bash
cd <bench>/sites
FRAPPE_BENCH_ROOT=<bench> python -m frappe.utils.bench_helper frappe \
    --site <site> set-config assistant_docs_path /path/to/docs
```

Without it the assistant still answers from the page descriptions, the
glossary records and the guide articles. Edited guides are picked up on the
next question; there is nothing to rebuild.

**Settings.** *Consilium Administration → Assistant Settings*
(`/app/assistant-settings`):

| Setting | What it does |
|---|---|
| Questions Per Person Per Hour | The limit on each person (default 30). It protects a paid AI service and the server alike. |
| Use an AI Endpoint | Off by default. When on, an AI service phrases the answer; when off, or when the service fails or is slow, the built-in answer is shown. |
| Request Format | *Anthropic Messages API*, or *OpenAI-compatible (internal gateway)* for a gateway your organisation runs in front of a model. |
| Endpoint Base URL | The service's base address, reachable **from the server**. Browsers never contact it. |
| Model | The model identifier the endpoint expects. |
| API Key | Stored encrypted. Leave blank for a gateway that authenticates the server another way. |
| Timeout, Maximum Answer Length | After the timeout the built-in answer is shown. |
| What Leaves the Platform | See below. |

**What leaves the platform** when an AI endpoint is on:

- *Guidance only* (the default): the question, the guide sections that match
  it, the kind of page and its address (never a record's title or reference),
  the asker's role names, and what the built-in answer worked out about their
  access. No record contents, and not the asker's name or email.
- *Include visible record summary*: also a few fields of the record on screen
  that the asker may read, and the actions open to them on it. Never for a
  sensitive escalation, or a confidential or restricted document (or a request
  about one).

Every request to the endpoint is recorded as an **AI Service Request** with
exactly what was sent (less the key) and what came back, including failures
and timeouts.

**The log.** Every question is an **Assistant Interaction**: who asked, on
which page, the answer, whether an AI answer was shown and, if not, why, and
how long it took. Administrators and Consilium Audit can read it; nobody can
edit it. A restricted record is never named in it.
