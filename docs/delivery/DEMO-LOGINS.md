# Demonstration logins

Who the demonstration personas are, how to sign in as them, and where each
one's day starts. **This file holds no passwords, and never will.** The
passwords are generated per run by `deploy/demo_logins.py` and written to a file
outside the repository (see [Getting passwords](#getting-passwords)).

The personas are fictitious and generic. They exist only on a demonstration or
training site loaded by `deploy/demo_data.py`, and every one of them has an
`@demo.example` address. Never load them onto a server that holds real records.

---

## The 23 personas

Source: `PERSONAS` in [`deploy/demo_data.py`](../../deploy/demo_data.py); the
roles below were checked against the demonstration site and match. "Start
here" is what `deploy/demo_logins.py` prints for the persona: the first
matching line of its `START_HERE` list, so the two never disagree.

| # | Persona | Login | Roles | Start here |
|---|---|---|---|---|
| 1 | Chair of the Board | `board.chair@demo.example` | Governance Viewer | Home — the forum map; read-only across forums and policies |
| 2 | Independent Director, Risk Committee Chair | `director.risk@demo.example` | Governance Viewer | Home — the forum map; read-only across forums and policies |
| 3 | Independent Director, Audit Committee Chair | `director.audit@demo.example` | Governance Viewer | Home — the forum map; read-only across forums and policies |
| 4 | Chief Executive Officer | `chief.executive@demo.example` | Governance Viewer, Forum Owner, Escalation Reviewer | Inbox — escalation approvals and challenges |
| 5 | Chief Risk Officer | `chief.risk.officer@demo.example` | Head of Risk Governance, Forum Owner, Policy Owner, Escalation Owner, Escalation Reviewer, Sensitive Escalation Access, Governance Viewer | Inbox, then /escalations (sensitive matters visible) and /reports |
| 6 | Chief Compliance Officer | `chief.compliance.officer@demo.example` | Compliance Reviewer, Policy Owner, Forum Owner, Escalation Owner, Escalation Reviewer, Sensitive Escalation Access | Inbox — reviews waiting; /forum-review for compliance decisions |
| 7 | Chief Information Officer | `chief.information.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 8 | Chief Operating Officer | `chief.operating.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 9 | Chief Financial Officer | `chief.financial.officer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 10 | General Counsel | `general.counsel@demo.example` | Policy Reviewer, Escalation Reviewer, Sensitive Escalation Access, Governance Viewer | Inbox — documents in review; return with comments from /policy |
| 11 | Head of Operational Risk | `head.operational.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner, Escalation Reviewer | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 12 | Head of Technology Risk | `head.technology.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 13 | Head of Model Risk | `head.model.risk@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 14 | Treasurer | `treasurer@demo.example` | Policy Owner, Forum Owner, Escalation Owner | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 15 | Head of Personal and Commercial Banking | `head.retail.banking@demo.example` | Policy Owner, Escalation Owner, Governance Viewer | /escalations — matters you own; take ownership from a group queue in the Inbox |
| 16 | Head of Internal Audit | `head.internal.audit@demo.example` | Consilium Audit, Governance Viewer | /reports and a record's History tab; Export evidence pack |
| 17 | Internal Auditor | `internal.auditor@demo.example` | Consilium Audit | /reports and a record's History tab; Export evidence pack |
| 18 | Risk Governance Office Lead | `risk.governance.lead@demo.example` | Risk Governance Office, Committee Secretary, Taxonomy Administrator, Consilium Administrator | /admin — reference data, imports, attestation campaigns; the desk at /app |
| 19 | Risk Governance Analyst | `risk.governance.analyst@demo.example` | Risk Governance Office, Governance Viewer | /formation-requests to decide new forums; /forums compliance reviews |
| 20 | Committee Secretary | `committee.secretary@demo.example` | Committee Secretary, Governance Viewer | /forums — a forum's meetings, minutes, motions and votes |
| 21 | Enterprise Policy Office Lead | `policy.office.lead@demo.example` | Enterprise Policy Office, Policy Reviewer | /policies — approvals, gate exceptions, attestation from a policy |
| 22 | Second Line Reviewer | `second.line.reviewer@demo.example` | Policy Reviewer, Compliance Reviewer, Escalation Reviewer | Inbox — reviews waiting; /forum-review for compliance decisions |
| 23 | Records Manager | `records.manager@demo.example` | Records Manager, Governance Viewer | /policies retention and dispositions; the desk for archive records |

`Administrator` is not a persona. It is the platform administrator, needed
for the desk (`/app`): workflows, state flags and settings. It gets a password
only when you pass `--administrator`.

**A tour in five sign-ins** (the generated file repeats this):

1. **Chief Risk Officer**: the Inbox, then a sensitive escalation, then
   Reports → Gaps and risk.
2. **Committee Secretary**: a forum's Meetings and Decisions tabs; put a motion
   to a vote.
3. **Enterprise Policy Office Lead**: a policy in review, with approvals in
   order and a gate exception.
4. **Risk Governance Office Lead**: Requests, to decide a new forum; Admin, for
   reference data.
5. **Internal Auditor**: any record's History tab and *Export evidence pack*.

---

## Getting passwords

`deploy/demo_data.py` creates the personas **with no password**, so none of
them can sign in until someone decides they should. Run this on the
demonstration site to make that decision:

```bash
cd .bench/sites
FRAPPE_BENCH_ROOT=<bench> ../../.venv/bin/python ../../deploy/demo_logins.py \
    --site <site> --url <url> --out <file outside the repo> --administrator
```

For example: `--site <site> --url http://<site>:8000 --out ~/demo-logins.md`.

What it does:

* It gives every enabled `@demo.example` user a new random 20-character
  password. With `--administrator` it gives `Administrator` one too.
* It writes a Markdown file to `--out`: the site address, and each persona
  with login, password, roles and where to start. The file is readable by its
  owner only (mode `0600`).
* It **refuses** an `--out` path inside this git work tree.
* It **refuses** a site that holds non-demo users, unless you pass `--force`.
* Running it again issues new passwords and overwrites the file. Nothing else
  changes, and nothing is emailed.

To stop the personas signing in, disable them on the desk, or run the script
again and throw the file away.

## Why the passwords never live in git

* **A committed password is public for good.** This repository is shared.
  Reverting the commit does not remove the password from history or from any
  clone already taken.
* **A known shared password is worse.** Whoever receives the platform runs the
  demo loader, possibly on a server. A password printed in the repository would
  open every demonstration site built from it.
* **So passwords are random, issued per run, and kept per site.** They exist
  only in the site's database and in the one file the operator chose to write
  outside the repository. Anyone who needs to sign in asks whoever ran the
  script, or runs it themselves on their own site.

The platform-rules check (`scripts/check_platform_rules.py`) and the rule in
[`CLAUDE.md`](../../CLAUDE.md) keep client-identifying content out of the
repository. This file and `deploy/demo_logins.py` apply the same discipline to
credentials.
