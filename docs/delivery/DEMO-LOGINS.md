# Demonstration logins

Who the demonstration personas are, how to sign in as them, and where each
one's day starts.

> **Sandbox sign-in: every persona and `Administrator` share one sandbox
> password**, set by `deploy/demo_logins.py --default-password`, so every
> demonstration and sandbox site built from this repository has the same
> logins. The team shares the password itself; it is not printed in these
> documents. Use it only on
> sites that hold fictitious data and are not reachable from the internet.
> Before connecting real data or single sign-on, change the Administrator
> password and disable the demonstration personas (see
> [Before a site holds anything real](#before-a-site-holds-anything-real)).

The personas are fictitious and generic. They exist only on a demonstration or
training site loaded by `deploy/demo_data.py`, and every one of them has an
`@demo.example` address. Never load them onto a server that holds real records.

---

## The 23 personas

Source: `PERSONAS` in [`deploy/demo_data.py`](../../deploy/demo_data.py); the
roles below were checked against the demonstration site and match.

- "Menus in the header" is what `consilium_core/navigation.py` (`cns_nav`)
  shows each persona on the demonstration site. Menus are filtered by role and
  read permission, so each persona sees only what they can use.
- "Start here" is what `deploy/demo_logins.py` prints for the persona: the
  first matching line of its `START_HERE` list. The paths it gives still work;
  the menu that leads to each is in [Finding your way](#finding-your-way).

| # | Persona | Login | Roles | Menus in the header | Start here |
|---|---|---|---|---|---|
| 1 | Chair of the Board | `board.chair@demo.example` | Governance Viewer | Home, My work, Governance, Insights | Home — the forum map; read-only across forums and policies |
| 2 | Independent Director, Risk Committee Chair | `director.risk@demo.example` | Governance Viewer | Home, My work, Governance, Insights | Home — the forum map; read-only across forums and policies |
| 3 | Independent Director, Audit Committee Chair | `director.audit@demo.example` | Governance Viewer | Home, My work, Governance, Insights | Home — the forum map; read-only across forums and policies |
| 4 | Chief Executive Officer | `chief.executive@demo.example` | Governance Viewer, Forum Owner, Escalation Reviewer | Home, My work, Governance, Escalations, Insights | Inbox — escalation approvals and challenges |
| 5 | Chief Risk Officer | `chief.risk.officer@demo.example` | Head of Risk Governance, Forum Owner, Policy Owner, Escalation Owner, Escalation Reviewer, Sensitive Escalation Access, Governance Viewer | Home, My work, Governance, Policies, Escalations, Insights | Inbox, then /escalations (sensitive matters visible) and /reports |
| 6 | Chief Compliance Officer | `chief.compliance.officer@demo.example` | Compliance Reviewer, Policy Owner, Forum Owner, Escalation Owner, Escalation Reviewer, Sensitive Escalation Access | Home, My work, Governance, Policies, Escalations, Insights | Inbox — reviews waiting; /forum-review for compliance decisions |
| 7 | Chief Information Officer | `chief.information.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 8 | Chief Operating Officer | `chief.operating.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 9 | Chief Financial Officer | `chief.financial.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 10 | General Counsel | `general.counsel@demo.example` | Policy Reviewer, Escalation Reviewer, Sensitive Escalation Access, Governance Viewer | Home, My work, Governance, Policies, Escalations, Insights | Inbox — documents in review; return with comments from /policy |
| 11 | Head of Operational Risk | `head.operational.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner, Escalation Reviewer | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 12 | Head of Technology Risk | `head.technology.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 13 | Head of Model Risk | `head.model.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 14 | Treasurer | `treasurer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 15 | Head of Personal and Commercial Banking | `head.retail.banking@demo.example` | Policy Owner, Escalation Owner, Governance Viewer | Home, My work, Governance, Policies, Escalations, Insights | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 16 | Head of Internal Audit | `head.internal.audit@demo.example` | Consilium Audit, Governance Viewer | Home, My work, Governance, Policies, Escalations, Insights | /reports and a record's History tab; Export evidence pack |
| 17 | Internal Auditor | `internal.auditor@demo.example` | Consilium Audit | Home, My work, Governance, Policies, Escalations, Insights | /reports and a record's History tab; Export evidence pack |
| 18 | Risk Governance Office Lead | `risk.governance.lead@demo.example` | Risk Governance Office, Committee Secretary, Taxonomy Administrator, Consilium Administrator | All seven, including Admin | /admin — reference data, imports, attestation campaigns; the desk at /app |
| 19 | Risk Governance Analyst | `risk.governance.analyst@demo.example` | Risk Governance Office, Governance Viewer | Home, My work, Governance, Insights | /formation-requests to decide new forums; /forums compliance reviews |
| 20 | Committee Secretary | `committee.secretary@demo.example` | Committee Secretary, Governance Viewer | Home, My work, Governance, Insights | /forums — a forum's meetings, minutes, motions and votes |
| 21 | Enterprise Policy Office Lead | `policy.office.lead@demo.example` | Enterprise Policy Office, Policy Reviewer | Home, My work, Policies, Insights | /policies — approvals, gate exceptions, attestation from a policy |
| 22 | Second Line Reviewer | `second.line.reviewer@demo.example` | Policy Reviewer, Compliance Reviewer, Escalation Reviewer | Home, My work, Governance, Policies, Escalations, Insights | Inbox — reviews waiting; /forum-review for compliance decisions |
| 23 | Records Manager | `records.manager@demo.example` | Records Manager, Governance Viewer | Home, My work, Governance, Insights | /policies retention and dispositions; the desk for archive records |

### Finding your way

The header has two rows. The top row holds the brand, the **search** box ("/"
or Ctrl/Cmd+K finds any forum, policy or escalation you may see), text size,
theme and your user menu. The second row holds the menus; each opens a panel
of pages with a line on what each is for.

| Path in "Start here" | Menu → item |
|---|---|
| Inbox, `/tasks` | **My work** (the badge counts what is waiting) → All my tasks, Approvals, Reviews, Attestations, Escalations waiting for an owner |
| `/forums`, `/forum-review` | **Governance** → Forum inventory, Awaiting compliance review, Overdue reviews |
| `/formation-requests` | **Governance** → Formation requests |
| `/policies` | **Policies** → Policy library (also In review, Reviews due, Request a policy or change, Regulatory updates, Horizon scanning) |
| `/escalations` | **Escalations** → Escalation register (also Breached, Awaiting review, Raise an escalation) |
| `/reports`, Gaps and risk | **Insights** → Management reporting, Coverage matrix, Gaps and risk, Emerging risks |
| `/admin` | **Admin** → Administration, Imports, Attestation campaigns, Branding, **Integrations** |

`Administrator` is not a persona. It is the platform administrator, needed
for the desk (`/app`): workflows, state flags and settings. It gets a password
only when you pass `--administrator`.

**A tour in five sign-ins.** The generated file lists the same tour; its
wording predates the menu names.

1. **Chief Risk Officer**: **My work**, then a sensitive escalation (search for
   it), then **Insights → Gaps and risk**. Ask the **Help** assistant a
   question on the way.
2. **Committee Secretary**: **Governance → Forum inventory**, then a forum's
   Meetings and Decisions tabs; put a motion to a vote.
3. **Enterprise Policy Office Lead**: **Policies → In review**: a policy with
   its approvals in order and a gate exception; *Open in Doc AI* on a version.
4. **Risk Governance Office Lead**: **Governance → Formation requests** to
   decide a new forum; **Admin → Integrations** to see the AI, Doc AI,
   horizon-scanning, e-mail and sign-on cards.
5. **Internal Auditor**: any record's History tab and *Export evidence pack*.

---

## Setting the logins on a new sandbox

`deploy/demo_data.py` creates the personas **with no password**. After loading
the demonstration data, give them the published sandbox password:

```bash
cd .bench/sites
FRAPPE_BENCH_ROOT=<bench> ../../.venv/bin/python ../../deploy/demo_logins.py \
    --site <site> --url <url> --out <file> --default-password
```

What it does:

* It sets the shared sandbox password on every enabled `@demo.example` user
  and on `Administrator`, and writes it into the file for the team.
* It writes a Markdown file to `--out`: the site address, and each persona
  with login, roles and where to start.
* It **refuses** a site that holds non-demo users, unless you pass `--force`,
  so it cannot reset real people's passwords.
* Running it again changes nothing but the file. Nothing is emailed.

### Private passwords instead

For a demonstration that should not share the published password (a site
reachable by people outside the team, for example), leave out
`--default-password` and add `--administrator`. Each account then gets its own
random 20-character password, and the file is written readable by its owner
only. In that mode the script refuses to write the file inside this repository,
because a password committed here is public for good.

## Before a site holds anything real

The published password makes a sandbox easy to share, and makes it unsafe for
anything else. Before a site receives real records, is reachable from outside
the team, or is connected to single sign-on:

1. **Change the Administrator password**, or disable password sign-in for it
   once single sign-on works.
2. **Disable every `@demo.example` persona** (Advanced configuration → User →
   filter on the email → set Enabled off), or build the site without demo data.
3. **Never run `demo_logins.py --default-password`** on it again. It refuses a
   site with real users, but a site with only demo users and real data would
   not be caught.

A production site is never built with demonstration data at all: see
[`HANDOFF-AGENT.md`](../../HANDOFF-AGENT.md) §3.
