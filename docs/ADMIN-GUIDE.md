# Consilium administrator quick start

For business administrators: the people who set the platform up for their
organisation and keep it that way. Everything here is done on screen, with no
release. The full chapter, with pictures of every screen, is
[Administration without code](guides/09-administration.md). Installation,
servers and anything that needs a command are for your platform team (see
[`OPERATIONS.md`](OPERATIONS.md), *Appendix: platform-team reference*).

Read the [quick start](USER-GUIDE.md) first.

---

## Your first week: a checklist

1. **Reference lists.** On **Admin → Administration**, check each list
   (risk categories, organisation units, legal entities, jurisdictions,
   document and escalation types). Add your own values with **Add a value**;
   untick **Active** on any you don't use.
2. **People and roles.** Add people under **Users** and give them roles, or a
   **Role profile** for their job. Make sure at least one active person holds
   each of: Risk Governance Office, Head of Risk Governance, Compliance
   Reviewer, Enterprise Policy Office, Policy Owner, Policy Reviewer,
   Escalation Owner and Escalation Reviewer. Approvals need someone to go to.
3. **Branding.** **Admin → Branding**: your name, logo, colours and home-page
   banner.
4. **Approval routes.** Check who approves new forums and policies (**Formation
   Approval Route**, **Approval Route**) against your delegations.
5. **Escalations.** Check the escalation matrix, the time limits and your
   business calendar (working hours and holidays).
6. **Home-page guidance.** **Write an article** for each part of **How it
   works**.
7. **Integrations.** **Admin → Integrations**: email, AI, Doc AI and horizon
   scanning, each with a test button.

## People and access

- **Add someone:** **Users** → **+ Add User** → roles on the **Roles** tab.
- **Limit someone to part of the organisation:** **User Permission** (for
  example one organisation unit). It applies everywhere.
- **Sensitive escalations:** only people named on a sensitive matter and holders
  of **Sensitive Escalation Access** see it. Grant that role sparingly.
- **Seeing what a user sees:** the system administrator opens the person's
  record and clicks **Impersonate**, giving a reason. No password is involved,
  the person is told, and the session is recorded. This is the right way to
  check "I can't see X".
- **Remove access:** untick **Enabled**. Never delete a person.
- **Delegation:** an **Authority Delegation** lets a colleague act for someone
  who is away, between two dates.

## Making changes safely

- **Nothing is deleted.** Values, people, routes and templates are made
  inactive.
- **Change one thing at a time**, then test it with a test record.
- **Every refusal is recorded** in the **Governance Refusal Log**. Check it
  after a change.

## What you can change yourself

| To change | Where | Guide |
|---|---|---|
| Lists the drop-downs offer | Administration → reference data | [9.3](guides/09-administration.md) |
| Bring in records from a spreadsheet | Admin → Imports | [9.4](guides/09-administration.md) |
| Name, logo, colours, banner | Admin → Branding | [9.5](guides/09-administration.md) |
| Notification wording | Notification Template | [9.6](guides/09-administration.md) |
| Time limits, working hours, holidays | SLA Definition, Business Calendar | [9.7](guides/09-administration.md) |
| Escalation severity and routing | Escalation Matrix | [9.8](guides/09-administration.md) |
| Who approves new forums and policies | Formation Approval Route, Approval Route | [9.9](guides/09-administration.md) |
| Changes that send a forum back for review | Watched Field Set | [9.10](guides/09-administration.md) |
| A new step in the policy lifecycle | Workflow, Workflow State Flag | [9.11](guides/09-administration.md) |
| Attestation campaigns and reminders | Attestation Campaign | [9.12](guides/09-administration.md) |
| The home page's "How it works" | Guide Article | [9.13](guides/09-administration.md) |
| AI, Doc AI, horizon scanning, email, single sign-on | Admin → Integrations | [9.14](guides/09-administration.md) |

## When to call your platform team

Ask them to:

- switch on **custom lifecycle steps** (once), before you add a step to the
  policy lifecycle;
- write a **new routing condition** for the escalation matrix, or a new kind
  of attestation campaign or import profile;
- switch **single sign-on** on or off;
- set up the **outgoing mail account**;
- give out **demonstration logins** on a training site;
- install, upgrade, back up or restore the platform.

## The Help assistant

**Help** answers from this guide, the onboarding guide, the glossary, your
published guide articles and a description of every screen. It takes each
person's roles into account and never describes a record they can't read.
If your organisation connects an AI service (**Admin → Integrations**), it
phrases the answers. Choose **what leaves the platform** on that card. Every
question and every AI request is recorded.
