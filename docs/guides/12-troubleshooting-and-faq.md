# 12. Troubleshooting and questions

**Purpose.** What an error means and what to do about it; the questions people
ask most; and the known limitations of the current version.

**First, three habits that solve most problems:**

1. **Read the message.** Every refusal names the rule that refused and, usually,
   the role or step that is missing.
2. **Ask the Help panel "Why can't I …?"** on the page. It works out whether
   the reason is a role, the record's stage, or something that must be done
   first ([chapter 1](01-getting-started.md), section 1.7).
3. **Reload the page.** A page left open across an upgrade, or after someone
   else acted on the record, shows stale choices. The server always checks
   again.

---

## 12.1 Access

| Symptom | Likely cause | What to do |
|---|---|---|
| A tab in the top bar is missing | You do not hold a role for that area. | See the role table in [chapter 1](01-getting-started.md). Ask your administrator. |
| "… are not open to you" | The page exists, but not for your roles. | Ask your administrator. |
| A record "does not exist, or is not available to you" | It is restricted (a sensitive escalation, a confidential document, a record-level restriction), or the reference is wrong. The system deliberately does not say which. | Check the reference. An administrator can **impersonate** you to see what you see ([chapter 10](10-administration.md)). |
| You cannot open a sensitive escalation | You are neither named on it (raiser, identified by, accountable executive, response owner, or its assigned group) nor hold **Sensitive Escalation Access**. | Ask whoever sent the reference. |
| A figure on Reports differs from a colleague's | Figures count only what each person may read. | Expected. |
| The originator of a returned formation request cannot answer it | The answer is given on the request form, which needs the Committee Secretary or Risk Governance Office role. (The originator can open, follow and withdraw it.) | The office enters the answer, or the originator is given the Committee Secretary role. |

## 12.2 Refusals

| Message (short) | Meaning | What to do |
|---|---|---|
| "… may not take the action "…" … It belongs to: …" | Your role does not take this action. | Ask someone with the named role. |
| ""…" is not available while … is …" | Not at this stage. | Look at the record's progress bar or Lifecycle tab. |
| "*Action* of … is refused. *Gate*: *reason*" | A lifecycle gate. | Do what the reason says; see [chapter 6](06-policies.md). |
| "No semantic state flags are configured for …" | A state has no Workflow State Flag row. This is a configuration error. | An administrator adds the row ([chapter 11](11-configuring-workflows.md), section 11.3 step 3). |
| "… cannot be "…". It should be one of …" | A value is not among a list field's options. | Choose a listed value; for lifecycle states, see [chapter 11](11-configuring-workflows.md), section 11.3. |
| "Workflow State transition not allowed from … to …" | No transition allows this move for your role. | Use an offered action; an administrator can add a transition. |
| "Approval step … has nobody to decide it." (*Step Unassigned*) | Nobody active holds the step's role, or a person the step needs is missing from the record. | Assign the role to an active person, or complete the record. |
| "Rule set … is sealed. Publish a new version instead" | Classification rules are never edited after use. | See [chapter 11](11-configuring-workflows.md), section 11.12. |
| "Workflow state … names no phase. Set Phase on its Workflow State Flag row …" | A document state has no flag row, or its row names no phase. | An administrator sets the Phase ([chapter 11](11-configuring-workflows.md), section 11.3 step 3). |
| **Unknown Phase** when saving a Workflow State Flag row | The Phase is not one of the record type's phases. | Use one of the phases the message lists: Draft, Review, Approved, Published, Implemented or Retired. |
| "… is sequential and cannot be decided yet: … must be decided first." | An earlier approval step is still open. | Wait for it, or chase its approver. |
| "… is under legal hold …" / "… is retained under retention class …" | The record is locked by records management. | Nothing, until the hold is released. |
| "The name "…" does not follow the naming convention …" | The document template's naming rule. | Rename as the message shows. |

Every one of these refusals is also written to the **Governance Refusal Log**.
Administrators can read the full detail there.

## 12.3 Pages and screens

| Symptom | Likely cause | What to do |
|---|---|---|
| A page looks unstyled or out of date after an upgrade | The browser kept old files. | Reload. |
| "Your inbox could not be read" | A server-side problem. | Reload. If it persists, tell your administrator (the Error Log has the detail). |
| The Help panel opens by itself on every page | It was left open in this browser tab. | Close it with **×**; it stays closed. |

---

## 12.4 Frequently asked questions

**How do I undo something?**
Most things cannot be deleted by design. Instead:

- **documents:** revert to an earlier version (a new version is written);
- **escalations:** revert on the History tab;
- **seats:** end them;
- **forums:** disband them;
- **requests:** withdraw them;
- **reference values:** make them inactive.

A recorded compliance decision cannot be edited. Record a new review.

**Why can't I just delete a mistaken record?**
Because the platform is the audit record. What was recorded, by whom and when
must remain readable. Correct it: for example a new version, a new review, or
**Correct metadata** on a document.

**Who sees what I write?**
Anyone who can read the record. Comments on reviews and closures are written
for the owner and the auditor. Sensitive and restricted records are limited
to the people cleared for them.

**Can a colleague act for me while I am away?**
Yes. Ask your administrator for an **Authority Delegation**
([chapter 10](10-administration.md)). Their actions show "under delegation".

**Why did a document's approval "disappear"?**
A new version was uploaded while the document was in Review. Approvals are
given against a version, so the steps must be raised again
([chapter 6](06-policies.md), section 6.4).

**Why did my escalation's severity go up on its own?**
Its time limit was breached. A breach raises severity one step, even if it
was set by hand ([chapter 7](07-escalations.md), section 7.9).

**Why did my forum become "Pending" when I only changed its mandate?**
The mandate is a **watched field**. Changing it sends the forum back for a
compliance review ([chapter 4](04-compliance-and-reviews.md), section 4.3).

**Why did my attestation disappear from my inbox?**
It was either answered (perhaps by your delegate), or it passed its due date
and **expired** overnight. Ask the governance office.

**Why was no email sent?**
Notifications go to the channel their template names. If outgoing mail is not
configured, they are recorded instead. **Notification Dispatch** shows every
notification, its channel and its outcome ([chapter 11](11-configuring-workflows.md),
section 11.13).

**Can we add our own stage to the policy lifecycle?**
Yes, without an engineer. See [chapter 11](11-configuring-workflows.md),
section 11.3.

**Can we rename a stage?**
For governing documents, yes, by configuration ([chapter 11](11-configuring-workflows.md),
section 11.4). The six phases themselves are fixed. For other record types, ask an engineer: the platform writes
some of those state names itself.

---

## 12.5 Known limitations in this version

These are known. Work round them as described.

| Area | Limitation | Work-round |
|---|---|---|
| Formation requests | An originator who holds no raising role cannot answer a returned request (the answer form needs the Committee Secretary or Risk Governance Office role). | The office enters the answer, or the originator is given the Committee Secretary role. |
| Formation requests | **Changes Requested** on a step does not send the request back to the originator. | Return the request with questions instead. |
| Forums | A change of chair made through the membership seat does not trigger a compliance re-review. | Ask a Compliance Reviewer to review the forum. |
| Meetings | Minutes are not shown on the portal. | Read them in the workspace, on the meeting's record. |
| Meetings | A **Deferred** motion may stay open for ballots after its outcome is recorded. | Put a new motion when the matter returns. |
| Policies | The **Open a review cycle** shortcut is offered even when a cycle is already open. | Conclude the open cycle first. |
| Policies | Change and Retire requests stay open until withdrawn. | Withdraw them once the change is done. |
| Escalations | The systemic box cannot be changed on the portal after a matter is raised. | Change it in the workspace; saving routes the matter again. |
| Imports | A batch rejected outright cannot be validated again. | Upload the file again. |
| Classification rule sets | A duplicated rule set is sealed after its first save. | Make every change before the first save ([chapter 11](11-configuring-workflows.md), section 11.12). |

### Fixed in this version

These problems, described in earlier editions of this guide, are fixed:

- **Workflow State Flag Phase.** A phase that is not one of the record type's
  phases is refused when the row is saved (**Unknown Phase**), instead of
  surfacing later as a refusal about missing flags.
- **Formation requests.**
  - A bypass now excuses only the step it names.
  - A Head of Risk Governance cannot bypass a step that is their own to
    decide.
  - Role-based steps go to the role's queue, not to the alphabetically first
    holder.
  - The originator can open and follow the request.
- **Business calendars.** An existing calendar opens and can be edited in the
  workspace.
- **Forums.**
  - A disbanded forum's header shows its standing once.
  - Motions are put, voted and closed on the portal ([chapter 5](05-meetings-votes-charters.md)).
  - Annual reviews are recorded from the Annual review panel ([chapter 4](04-compliance-and-reviews.md)).
- **Policies.** **Record Approval** now requires a complete approval chain.
- **Attestation.** Campaign reminders follow the campaign's reminder schedule.
- **Home page.** Every published guide article is shown, including a second
  article in a category and articles in a category with no card of its own.
- **Everywhere.**
  - The top bar fits every tab.
  - The filters on Policies and Escalations are kept in the page address.
  - Signing in keeps the page's filters.
- **Escalations.**
  - People named on a sensitive matter see it.
  - Closing a matter asks for confirmation.

## 12.6 Getting more help

- **The Help panel** on every page answers questions about that page.
- **Your governance office** maintains the home-page guidance and answers
  process questions.
- **Your administrator** handles access, configuration and the logs:
  - the **Governance Refusal Log** (what was refused and why);
  - the **Error Log** (server errors);
  - **Notification Dispatch** (what was sent).
- **Technical references** for administrators: [`../ADMIN-GUIDE.md`](../ADMIN-GUIDE.md),
  [`../OPERATIONS.md`](../OPERATIONS.md), [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md).
