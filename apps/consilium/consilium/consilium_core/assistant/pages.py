"""What each portal page is for, and how to do things on it.

This is the assistant's first source of answers. The guides explain the
platform area by area; people ask about the screen in front of them. So every
portal page has an entry here: what it is for, the record it shows (if any),
the questions worth suggesting there, and the tasks someone does on it — each
task with the steps, where to go, and **what it requires**, so that "how do I…"
can be answered with "you can, like this" or "you can't, because…" for the
person actually asking.

A task's ``requires`` is evaluated on the server against the asker's real
roles and permissions (``context.check_requirement``). It is never shown as a
promise: the page or endpoint the task leads to checks again on the way in.

Pages that other parts of the platform are still adding (``/tasks``,
``/imports``, ``/policy-intake``, ``/raise-escalation``, ``/document-view``,
``/attestation-campaigns``) are described here too. An entry for a page that is
not installed does no harm — nobody can be on it — and ``installed_routes``
lets the suggestions leave it out of "where do I find" answers until it is.

Nothing here names a workflow state as logic. State names appear only in prose.
"""

from __future__ import annotations

import os

import frappe

#: Roles that administer the platform. Admin documentation is shown only to
#: holders of one of these.
ADMIN_ROLES = ("System Manager", "Consilium Administrator")

GOVERNANCE_OFFICE_ROLES = ("Risk Governance Office", "Head of Risk Governance", "System Manager")

#: Record types the assistant can describe, the portal page that shows one, and
#: the query parameter that names it. The page is also where an answer links.
RECORD_ROUTES = {
	"Governance Forum": ("/forum", "name"),
	"Governing Document": ("/policy", "name"),
	"Escalation Matter": ("/escalation", "name"),
	"Committee Formation Request": ("/formation-request", "name"),
	"Document Version": ("/document-view", "version"),
	"Document Intake Request": ("/policy-intake", "name"),
}


#: A record's page is useless without a record, so an answer that sends someone
#: to "an escalation matter's page" links to the list they open one from.
LIST_FOR_RECORD_PAGE = {
	"/forum": "/forums",
	"/forum-review": "/forums",
	"/formation-request": "/formation-requests",
	"/policy": "/policies",
	"/document-view": "/policies",
	"/escalation": "/escalations",
}


def _task(id, label, keywords, steps, href=None, requires=None, why=None):
	return {
		"id": id,
		"label": label,
		"keywords": keywords,
		"steps": steps,
		"href": href,
		"requires": requires or {},
		"why": why,
	}


PAGES: dict[str, dict] = {
	"/": {
		"title": "Home",
		"purpose": (
			"The starting point. It shows where the forum inventory stands (active forums, reviews "
			"awaiting or overdue, open formation requests), counts by category and compliance "
			"standing, recent changes, and the governance office's guidance on using the system."
		),
		"module": "Core",
		"starters": [
			"What can I do here?",
			"How do I request a new forum?",
			"Where do I find a policy?",
			"What does compliance status mean?",
		],
		"tasks": [
			_task(
				"home-figures", "Open the list behind a figure",
				"figure count tile number inventory stands click filtered list overdue awaiting",
				["Each figure under 'Where the inventory stands' is a link.",
				 "Choose it to open the matching list, already filtered."],
			),
			_task(
				"home-request-forum", "Request a new forum",
				"request new forum committee create formation start ask",
				["Search the forum inventory first: a forum may already cover the ground.",
				 "Choose 'Request a new forum' on Home or Forums.",
				 "Fill in the four sections, save a draft if you need to, then submit it for evaluation."],
				href="/create-forum",
				requires={"doctype": "Committee Formation Request", "ptype": "create"},
			),
		],
	},
	"/forums": {
		"title": "Forum inventory",
		"purpose": (
			"Every governance forum on the inventory — boards, committees, councils and working "
			"groups. Filter by type, compliance status, cadence, risk category, owning group and "
			"standing, or search names, references and mandates. The filters stay in the address, "
			"so a filtered list can be bookmarked or shared."
		),
		"module": "Governance",
		"doctype": "Governance Forum",
		"starters": [
			"What can I do here?",
			"How do I filter to forums awaiting review?",
			"How do I request a new forum?",
			"What does quorum mean?",
		],
		"tasks": [
			_task(
				"forums-filter", "Filter or search the inventory",
				"filter search narrow find standing awaiting review overdue disbanded type cadence",
				["Use 'Narrow the list' to filter by type, compliance status, cadence, risk category, "
				 "owning group or Standing (active, disbanded, awaiting review, regulatory-required, review overdue).",
				 "Or type in the table's search box to search names, references and mandates.",
				 "Copy the page address to share the same filtered list."],
				href="/forums",
				requires={"doctype": "Governance Forum", "ptype": "read"},
			),
			_task(
				"forums-open", "Open a forum",
				"open view forum details page row click",
				["Choose a row in the table to open that forum's page."],
				href="/forums",
				requires={"doctype": "Governance Forum", "ptype": "read"},
			),
			_task(
				"forums-request", "Request a new forum, or a change to one",
				"request new forum create committee formation change modify retire",
				["A forum is never created directly: you raise a formation request.",
				 "Choose 'Request a new forum', fill in the four sections, and submit for evaluation.",
				 "The governance office evaluates it; an approved request creates the forum."],
				href="/create-forum",
				requires={"doctype": "Committee Formation Request", "ptype": "create"},
			),
		],
	},
	"/forum": {
		"title": "Forum",
		"purpose": (
			"One forum: its type, compliance standing, officers and next review date, with tabs "
			"for Details, Membership (as at any past date), Linkages, Documents, Decisions and History."
		),
		"module": "Governance",
		"doctype": "Governance Forum",
		"record_param": "name",
		"starters": [
			"What can I do here?",
			"How do I see who sat on this forum last year?",
			"How do I record a compliance review?",
			"Why can't I edit this forum?",
		],
		"tasks": [
			_task(
				"forum-edit", "Edit this forum",
				"edit change update modify forum record mandate details",
				["Choose 'Edit this forum' at the top of the page. It opens the record in the workspace.",
				 "A change to a watched field, such as the mandate, sends the forum back for a compliance review."],
				requires={"doctype": "Governance Forum", "ptype": "write", "record": True, "desk": True},
				why="Editing needs write access to this forum (Risk Governance Office, Committee Secretary, "
				    "Forum Owner or Compliance Reviewer) and workspace access.",
			),
			_task(
				"forum-membership-history", "See membership on a past date",
				"membership members seat who sat past date history as at",
				["Open the Membership tab.",
				 "Change 'Membership as at' to the date you want. Seats are ended, never deleted, so the history is exact."],
				requires={"doctype": "Governance Forum", "ptype": "read"},
			),
			_task(
				"forum-review", "Record a compliance review",
				"compliance review record decision compliant non-compliant reviewer assess",
				["Choose 'Record a compliance review' on the forum's page.",
				 "Pick the decision: Compliant, Non-Compliant (give your reasons), Not Applicable, or Returned to creator.",
				 "A review is its own record and cannot be edited afterwards."],
				requires={"doctype": "Forum Compliance Review", "ptype": "create"},
				why="Only the Compliance Reviewer role records compliance reviews.",
			),
			_task(
				"forum-decisions", "See decisions and meetings",
				"decisions motions votes meetings sittings outcome quorate",
				["Open the Decisions tab: motions and their outcomes, and the meetings held.",
				 "A decision counts only if the meeting was quorate and the outcome was recorded."],
				requires={"doctype": "Governance Forum", "ptype": "read"},
			),
			_task(
				"forum-change", "Ask for a change to this forum",
				"change modify retire disband forum request",
				["Raise a formation request of type modify or retire, naming this forum.",
				 "Choose 'Request a new forum' and pick the request type."],
				href="/create-forum",
				requires={"doctype": "Committee Formation Request", "ptype": "create"},
			),
		],
	},
	"/forum-review": {
		"title": "Compliance review",
		"purpose": (
			"Record a compliance decision on one forum, and see the decisions already recorded. "
			"Each decision says where it leaves the forum."
		),
		"module": "Governance",
		"doctype": "Governance Forum",
		"record_param": "forum",
		"starters": [
			"What can I do here?",
			"What does Non-Compliant require?",
			"Can I change a review after saving it?",
		],
		"tasks": [
			_task(
				"review-record", "Record a compliance decision",
				"record compliance decision review compliant non-compliant not applicable return",
				["Under 'Record a compliance decision', choose the decision.",
				 "Non-Compliant needs your reasons; returning to the creator needs your questions.",
				 "Save. The review is its own record and cannot be edited afterwards."],
				requires={"doctype": "Forum Compliance Review", "ptype": "create"},
				why="Only the Compliance Reviewer role records compliance reviews.",
			),
		],
	},
	"/create-forum": {
		"title": "Request a new forum",
		"purpose": (
			"The guided formation request: what you are asking for and why, the forum, "
			"accountability, and timing. Nothing is created until the request has been evaluated "
			"and approved. If the office returns it with questions, you answer them here."
		),
		"module": "Governance",
		"doctype": "Committee Formation Request",
		"record_param": "request",
		"starters": [
			"What can I do here?",
			"What happens after I submit?",
			"How do I answer the office's questions?",
		],
		"tasks": [
			_task(
				"create-fill", "Fill in and submit a request",
				"fill submit request form draft save evaluation sections required",
				["Fill in the four sections. Fields marked * are required; the three explanations need a few sentences each.",
				 "'Save draft' keeps your work; the address then carries the request's reference so you can bookmark it.",
				 "'Submit for evaluation' hands it to the governance office and locks it."],
				href="/create-forum",
				requires={"doctype": "Committee Formation Request", "ptype": "create"},
				why="Raising formation requests needs the Committee Secretary or Risk Governance Office role.",
			),
			_task(
				"create-respond", "Answer questions from the governance office",
				"answer respond questions returned office reply",
				["Open your request (the link in the notice, or from its page).",
				 "The questions are shown with a box for your answer. Answering sends it back into evaluation."],
			),
		],
	},
	"/formation-requests": {
		"title": "Formation requests",
		"purpose": (
			"The governance office's queue of formation requests, filterable by whose move it is "
			"(the office, the originator or an approver), and the forums awaiting a compliance review."
		),
		"module": "Governance",
		"doctype": "Committee Formation Request",
		"starters": [
			"What can I do here?",
			"How do I find requests waiting on me?",
			"What are the five criteria?",
		],
		"tasks": [
			_task(
				"queue-mine", "See the requests waiting on you",
				"waiting whose move queue filter mine originator approver",
				["Use the 'Whose move it is' filter: the office, the originator, or an approver."],
				href="/formation-requests",
				requires={"doctype": "Committee Formation Request", "ptype": "read"},
			),
			_task(
				"queue-open", "Work a request",
				"open request evaluate work start",
				["Choose a request in the queue. Its page shows only the actions valid at its current stage."],
				href="/formation-requests",
				requires={"roles": GOVERNANCE_OFFICE_ROLES},
				why="Working requests belongs to the Risk Governance Office and the Head of Risk Governance.",
			),
		],
	},
	"/formation-request": {
		"title": "Formation request",
		"purpose": (
			"One formation request as the governance office works it: the case, the forum asked "
			"for, the overlap check, the five criteria, questions to the originator, what blocks "
			"approval, the approval steps and any exception. Only the actions valid now are offered."
		),
		"module": "Governance",
		"doctype": "Committee Formation Request",
		"record_param": "name",
		"starters": [
			"What can I do here?",
			"Why can't I approve this request?",
			"What does raising an exception do?",
		],
		"tasks": [
			_task(
				"request-evaluate", "Evaluate the request",
				"start evaluation criteria findings assess record findings five",
				["Choose 'Start evaluation'.",
				 "Record a finding and a note against each of the five criteria: the gap, duplication, "
				 "the escalation pathway, fit with the framework, and resourcing."],
				requires={"roles": ("Risk Governance Office", "System Manager")},
				why="Evaluation belongs to the Risk Governance Office.",
			),
			_task(
				"request-return", "Return it to the originator with questions",
				"return originator questions send back ask",
				["Choose 'Return to originator' and write your questions."],
				requires={"roles": ("Risk Governance Office", "System Manager")},
				why="Returning a request belongs to the Risk Governance Office.",
			),
			_task(
				"request-approve", "Approve the request",
				"approve approval blocked blockers outstanding",
				["'Approve' is disabled until nothing blocks it; the page lists what is outstanding "
				 "(an unassessed criterion, an undecided step, or a rejected step).",
				 "An approved request creates the forum, in draft."],
				requires={"roles": GOVERNANCE_OFFICE_ROLES},
				why="Approval belongs to the Risk Governance Office or the Head of Risk Governance.",
			),
			_task(
				"request-steps", "Raise or decide approval steps",
				"approval steps raise decide step decision route approver",
				["'Raise approval steps' creates the steps from the configured formation approval route.",
				 "Whoever a step is assigned to (or their delegate) records its decision on this page."],
			),
			_task(
				"request-exception", "Raise or resolve an exception",
				"exception bypass skip step cannot complete resolve authorise",
				["'Raise an exception' when a step cannot be completed normally.",
				 "Only the Head of Risk Governance can resolve it, or authorise a bypass."],
				requires={"roles": GOVERNANCE_OFFICE_ROLES},
				why="Exceptions are raised by the office and resolved by the Head of Risk Governance.",
			),
			_task(
				"request-close", "Reject or withdraw the request",
				"reject withdraw close cancel reason",
				["Choose 'Reject' or 'Withdraw' and give a reason. The originator may withdraw their own request."],
			),
		],
	},
	"/policies": {
		"title": "Policy inventory",
		"purpose": (
			"Every governing document — frameworks, policies, standards, procedures. Filter by type, "
			"lifecycle phase, owning group, risk category and handling classification; Standing "
			"offers in force, awaiting review, review overdue, due within 90 days and no review date."
		),
		"module": "Policy",
		"doctype": "Governing Document",
		"starters": [
			"What can I do here?",
			"How do I find policies due for review?",
			"How do I create a new document?",
			"What is a standard?",
		],
		"tasks": [
			_task(
				"policies-filter", "Find documents due or overdue for review",
				"filter review due overdue standing in force search find",
				["Use 'Narrow the list' and choose a Standing: in force, awaiting review, review overdue, "
				 "review due within 90 days, or no review date."],
				href="/policies",
				requires={"doctype": "Governing Document", "ptype": "read"},
			),
			_task(
				"policies-create", "Create a new governing document",
				"create new document policy draft write add",
				["Choose 'New document'. It opens a new record in the workspace, in Draft.",
				 "To ask for a document rather than draft one, use a policy intake request."],
				requires={"doctype": "Governing Document", "ptype": "create", "desk": True},
				why="Drafting documents needs the Policy Owner or Enterprise Policy Office role, and workspace access.",
			),
			_task(
				"policies-intake", "Ask for a new document or a change",
				"intake request ask new change document policy",
				["Raise a policy intake request describing what is needed and why."],
				href="/policy-intake",
				requires={"doctype": "Document Intake Request", "ptype": "create"},
			),
		],
	},
	"/policy": {
		"title": "Governing document",
		"purpose": (
			"One governing document, with tabs for Details, Lifecycle (where it is, the actions "
			"available next and anything that would block them), Versions, Lineage and Horizon scanning."
		),
		"module": "Policy",
		"doctype": "Governing Document",
		"record_param": "name",
		"starters": [
			"What can I do here?",
			"Why can't I publish this document?",
			"What happens after approval?",
		],
		"tasks": [
			_task(
				"policy-move", "Move the document through its lifecycle",
				"submit review approve publish implement retire reinstate reopen lifecycle action move phase",
				["Open the Lifecycle tab to see the actions available next and what would block each.",
				 "Take the action from the Actions menu on the document in the workspace.",
				 "A lifecycle gate may refuse a move, for example publishing without a complete approval chain."],
			),
			_task(
				"policy-edit", "Edit this document",
				"edit change update document record owner",
				["Choose 'Edit' at the top of the page to open it in the workspace.",
				 "A document is editable only while its phase allows it (in Draft, for example)."],
				requires={"doctype": "Governing Document", "ptype": "write", "record": True, "desk": True},
				why="Editing needs write access to this document and workspace access.",
			),
			_task(
				"policy-versions", "See earlier versions",
				"version versions history earlier previous changed compare",
				["Open the Versions tab: every version, what changed and whether it was published."],
			),
		],
	},
	"/policy-intake": {
		"title": "Document requests",
		"purpose": (
			"Ask for a new governing document, a change to one, or its retirement. With no request "
			"named, the page lists the requests you may read and, if you may raise one, the form. "
			"A request's own page shows its classification questions, the outcome and the rule that "
			"produced it, and lets the requester challenge it; the Enterprise Policy Office may "
			"override the outcome and create the document."
		),
		"module": "Policy",
		"doctype": "Document Intake Request",
		"record_param": "name",
		"starters": [
			"What can I do here?",
			"How do I ask for a new policy?",
			"What does major change mean?",
			"How do I challenge the classification?",
		],
		"tasks": [
			_task(
				"intake-submit", "Raise a document request",
				"raise submit intake request new change retire document policy ask",
				["Choose the request type (new, change or retirement) and, for a change or retirement, the document.",
				 "Give the business justification and the proposed effective date, then raise it.",
				 "Answer the classification questions; the rules in force decide whether it is a major or minor change."],
				href="/policy-intake",
				requires={"doctype": "Document Intake Request", "ptype": "create"},
				why="Raising document requests needs the Policy Owner or Enterprise Policy Office role.",
			),
			_task(
				"intake-challenge", "Challenge the classification",
				"challenge classification outcome disagree major minor",
				["Open the request and use 'Challenge the classification' with your statement.",
				 "The Enterprise Policy Office may then override the outcome, with a justification."],
			),
			_task(
				"intake-create", "Create the document from a request",
				"create document from request override office",
				["Once classified, the Enterprise Policy Office uses 'Create the document' on a request for a new document."],
				requires={"roles": ("Enterprise Policy Office", "System Manager")},
				why="Creating the document and overriding a classification belong to the Enterprise Policy Office.",
			),
		],
	},
	"/document-view": {
		"title": "Document viewer",
		"purpose": (
			"One version of a governing document: its text or file, its details, the other versions "
			"in the chain, and the glossary definitions that apply. Whether you may download or print "
			"it, and whether a watermark is shown, follows the document's handling classification."
		),
		"module": "Policy",
		"doctype": "Document Version",
		"record_param": "version",
		"starters": ["What can I do here?", "Why can't I download this document?", "How do I see other versions?"],
		"tasks": [
			_task(
				"docview-other", "See other versions of this document",
				"other versions previous history chain earlier",
				["The other versions in the chain are listed beside the text; choose one to open it."],
			),
			_task(
				"docview-download", "Download or print the document",
				"download print save copy file watermark",
				["Download and print are offered only when the document's handling classification allows "
				 "them for you. A confidential or restricted document may be view-only, and may show a watermark."],
			),
		],
	},
	"/escalations": {
		"title": "Escalation register",
		"purpose": (
			"The register of matters raised. Filter by open or closed, severity, status, type, "
			"organisational level and age, and find matters past their time limit."
		),
		"module": "Escalation",
		"doctype": "Escalation Matter",
		"starters": [
			"What can I do here?",
			"How do I raise an escalation?",
			"How do I find overdue matters?",
			"What is a risk acceptance?",
		],
		"tasks": [
			_task(
				"esc-raise", "Raise an escalation",
				"raise new escalation matter create report issue open",
				["Choose 'Raise an escalation'.",
				 "You need a title and description, the type, the date identified, the tier 1 risk type, "
				 "at least one impacted entity, who identified it, the organisational level, the "
				 "accountable executive, the trigger and the severity."],
				href="/raise-escalation",
				requires={"doctype": "Escalation Matter", "ptype": "create"},
				why="Raising escalations needs the Escalation Owner role.",
			),
			_task(
				"esc-overdue", "Find matters past their time limit",
				"overdue breached late time limit sla filter past",
				["Use 'Narrow the list' and the time-limit filters to show matters past their limit."],
				href="/escalations",
				requires={"doctype": "Escalation Matter", "ptype": "read"},
			),
		],
	},
	"/escalation": {
		"title": "Escalation matter",
		"purpose": (
			"One escalation matter: what happened, severity and routing, time limits, impacted "
			"entities and forums, action plans, risk acceptances, reviews, closure and history."
		),
		"module": "Escalation",
		"doctype": "Escalation Matter",
		"record_param": "name",
		"starters": [
			"What can I do here?",
			"How do I close this matter?",
			"How do I add an action plan?",
			"What is a risk acceptance?",
		],
		"tasks": [
			_task(
				"esc-close", "Close the matter",
				"close closure resolve finish complete matter",
				["Record an Escalation Closure: the closure type and a summary.",
				 "Tick 'Response template completed' on the matter and set its status to Closed.",
				 "The system refuses to close a matter until both are done."],
				requires={"doctype": "Escalation Matter", "ptype": "write", "record": True, "desk": True},
				why="Closing needs write access to this matter (Escalation Owner) and workspace access.",
			),
			_task(
				"esc-action-plan", "Add an action plan",
				"action plan add owner dates remediate",
				["Open the matter in the workspace and add an action plan with an owner and dates."],
				requires={"doctype": "Action Plan", "ptype": "create", "desk": True},
				why="Action plans are created by the Escalation Owner role.",
			),
			_task(
				"esc-accept", "Record a risk acceptance",
				"accept risk acceptance rationale expire",
				["Record a risk acceptance with a rationale, an accountable executive, start and end "
				 "dates and an approval. It expires and is reassessed periodically."],
				requires={"doctype": "Risk Acceptance", "ptype": "create", "desk": True},
				why="Risk acceptances are recorded by the Escalation Owner role.",
			),
			_task(
				"esc-edit", "Edit this matter",
				"edit change update matter severity status",
				["Choose 'Edit' at the top of the page to open it in the workspace."],
				requires={"doctype": "Escalation Matter", "ptype": "write", "record": True, "desk": True},
				why="Editing needs write access to this matter and workspace access.",
			),
		],
	},
	"/raise-escalation": {
		"title": "Raise an escalation",
		"purpose": (
			"The guided form for raising a new escalation matter. The escalation matrix proposes the "
			"severity and the forums; the template for the escalation type says what else is needed."
		),
		"module": "Escalation",
		"doctype": "Escalation Matter",
		"starters": ["What can I do here?", "What does severity source mean?", "Which fields are required?"],
		"tasks": [
			_task(
				"raise-fill", "Fill in and raise the escalation",
				"fill submit raise required fields severity source matrix manual escalation",
				["Give a title and description, the escalation type, the date identified, the tier 1 "
				 "risk type, at least one impacted entity, who identified it, the organisational level, "
				 "the accountable executive, the trigger and the severity.",
				 "Severity source: Matrix lets the escalation matrix set severity; Manual override keeps yours.",
				 "The template for the type and severity may ask for more before the matter can be raised."],
				href="/raise-escalation",
				requires={"doctype": "Escalation Matter", "ptype": "create"},
				why="Raising escalations needs the Escalation Owner role.",
			),
		],
	},
	"/reports": {
		"title": "Management reporting",
		"purpose": (
			"The management view across forums, documents and escalations: headline figures, "
			"breakdowns, records missing required information, time-limit clocks, and an escalation "
			"analysis you can group by period and download. Counts include only records you may see."
		),
		"module": "Core",
		"starters": ["What can I do here?", "How do I download the escalation analysis?", "Why do my counts differ from a colleague's?"],
		"tasks": [
			_task(
				"reports-csv", "Download the escalation analysis",
				"download csv export escalation analysis group month quarter year",
				["In the Escalations section, group the analysis by month, quarter or year.",
				 "Choose 'Download CSV'."],
				href="/reports",
			),
			_task(
				"reports-drill", "Open the list behind a figure",
				"figure drill list filtered open count",
				["Every figure with a matching list links to it, already filtered."],
				href="/reports",
			),
		],
	},
	"/tasks": {
		"title": "Inbox",
		"purpose": (
			"Everything waiting on you, across forums, policies and escalations: approval steps to "
			"decide, requests returned to you, reviews falling due and more. Attestations are answered "
			"here; everything else opens on its own screen."
		),
		"module": "Core",
		"starters": ["What can I do here?", "How do I complete an attestation?", "Why is something in my inbox?"],
		"tasks": [
			_task(
				"tasks-open", "Act on an item in your inbox",
				"inbox task act open complete decide item waiting me",
				["Choose an item to open the record it concerns, where the action waiting on you is offered."],
				href="/tasks",
			),
			_task(
				"tasks-attest", "Complete an attestation",
				"attest attestation confirm answer campaign complete",
				["Attestations are answered in the inbox itself: confirm each statement, or say what is "
				 "wrong, and submit before the due date."],
				href="/tasks",
			),
		],
	},
	"/imports": {
		"title": "Imports",
		"purpose": (
			"Files brought in through the governed import pipeline. Upload a file against an import "
			"profile, review every row — what the file gave, what the profile made of it, and why any "
			"row was refused — then commit or discard the batch. Nothing is written until you commit."
		),
		"module": "Core",
		"doctype": "Import Batch",
		"starters": ["What can I do here?", "How do I import reference data?", "Why was a row refused?"],
		"tasks": [
			_task(
				"imports-run", "Import a file",
				"import upload csv file map columns profile commit load bulk batch",
				["Upload the file against the import profile that describes it.",
				 "Open the batch and review its rows and any refusals.",
				 "Commit the batch to write it, or discard it."],
				href="/imports",
				requires={"doctype": "Import Batch", "ptype": "create"},
				why="Uploading imports needs create access to import batches (administrators).",
			),
			_task(
				"imports-refused", "Find out why a row was refused",
				"row refused rejected error validation failed why",
				["Open the batch: each refused row shows the reason next to the values the file gave."],
				href="/imports",
				requires={"doctype": "Import Batch", "ptype": "read"},
			),
		],
	},
	"/attestation-campaigns": {
		"title": "Attestation campaigns",
		"purpose": (
			"Open the annual forum attestations, generate each campaign's tasks, and chase the records "
			"a campaign could not ask about. Administrators of campaigns see every campaign; the "
			"governance office sees the forum campaigns."
		),
		"module": "Core",
		"doctype": "Attestation Campaign",
		"starters": ["What can I do here?", "How do I start a campaign?", "What is an attestation?"],
		"tasks": [
			_task(
				"campaigns-start", "Open a campaign and generate its tasks",
				"start open create new campaign attestation annual population generate tasks",
				["Open the campaign for the period.",
				 "Generate its tasks: each person in its population gets one in their inbox."],
				href="/attestation-campaigns",
				requires={"roles": ("Risk Governance Office", "Head of Risk Governance", "Consilium Administrator", "System Manager")},
				why="Running campaigns belongs to the governance office (forum campaigns) and campaign administrators.",
			),
			_task(
				"campaigns-chase", "Chase what a campaign could not ask about",
				"chase outstanding overdue unassigned records progress who attested",
				["Open the campaign to see who has attested, who is outstanding, and the records it could not ask about."],
				href="/attestation-campaigns",
			),
		],
	},
	"/admin": {
		"title": "Administration",
		"purpose": (
			"For administrators: users, roles and record-level restrictions, every reference list "
			"with its counts, the home-page guide articles, and links to configuration and operations."
		),
		"module": "Core",
		"admin_only": True,
		"starters": ["What can I do here?", "How do I give someone a role?", "How do I edit the home-page guide?", "How do I turn on AI answers?"],
		"tasks": [
			_task(
				"admin-roles", "Give someone a role",
				"role assign give user access permission grant add person",
				["Open Users, then the person, then the Roles tab, and tick the roles.",
				 "For people who share a job, a Role Profile gives the set in one step."],
				href="/app/user",
				requires={"roles": ADMIN_ROLES},
				why="Managing users and roles is for administrators.",
			),
			_task(
				"admin-restrict", "Limit someone to part of the organisation",
				"restrict limit user permission organisation unit legal entity record-level",
				["Open Record-level restrictions (User Permissions) and restrict the user to a unit or legal entity."],
				href="/app/user-permission",
				requires={"roles": ADMIN_ROLES},
				why="Record-level restrictions are managed by administrators.",
			),
			_task(
				"admin-reference", "Add or retire a reference value",
				"reference data list value add inactive retire taxonomy dropdown empty",
				["Find the list under 'Reference data' and choose 'Add a value'.",
				 "Never delete a value records use: untick Active instead."],
				href="/admin",
				requires={"roles": ADMIN_ROLES + ("Taxonomy Administrator",)},
				why="Reference data is maintained by administrators and the Taxonomy Administrator role.",
			),
			_task(
				"admin-guide", "Edit the home-page guidance",
				"guide article home page guidance write edit",
				["Under 'The home-page guide', add or edit a Guide Article and tick Published."],
				href="/app/guide-article",
				requires={"doctype": "Guide Article", "ptype": "write"},
				why="Guide articles are edited by administrators.",
			),
			_task(
				"admin-assistant", "Configure the help assistant",
				"assistant ai answers answer endpoint model settings help configure turn on enable",
				["Open Assistant Settings in the workspace.",
				 "The assistant works with nothing configured. To add AI-assisted answers, set the "
				 "request format, endpoint, model and key, then tick 'Use an AI Endpoint'."],
				href="/app/assistant-settings",
				requires={"doctype": "Assistant Settings", "ptype": "write"},
				why="Assistant Settings are for administrators.",
			),
		],
	},
	"/ui-kit": {
		"title": "Interface reference",
		"purpose": "A reference sheet of the portal's interface components, for people building or checking screens.",
		"module": "Core",
		"starters": ["What can I do here?"],
		"tasks": [],
	},
}

#: Tasks that make sense everywhere, whatever the page.
GLOBAL_TASKS = [
	_task(
		"global-theme", "Change the text size or switch to the dark theme",
		"text size font bigger smaller dark light theme contrast",
		["Use A− / A+ in the top bar to change the text size (↺ resets it).",
		 "Use the moon button to switch between light and dark. Both are remembered on this browser."],
	),
	_task(
		"global-signout", "Sign out or see your profile",
		"sign out log out logout profile account",
		["Choose your name at the top right, then Profile or Sign out."],
	),
	_task(
		"global-roles", "Get access to something you cannot see",
		"access role permission cannot see missing hidden grant",
		["Ask your administrator to check your roles.",
		 "Record-level restrictions can also limit you to particular units or legal entities."],
	),
]


#: The pages that are an area someone works in, rather than a single record or
#: a form. "What access do I have" lists these.
AREA_ROUTES = ("/tasks", "/forums", "/formation-requests", "/policies", "/policy-intake", "/escalations",
               "/reports", "/imports", "/attestation-campaigns", "/admin")


def normalise_route(path: str | None) -> str:
	"""The page-map key for a path: no query, no trailing slash, no ``.html``."""
	path = (path or "/").split("?", 1)[0].split("#", 1)[0].strip() or "/"
	if not path.startswith("/"):
		path = "/" + path
	if path != "/":
		path = path.rstrip("/")
	if path.endswith(".html"):
		path = path[: -len(".html")]
	if path in ("/index", "/home"):
		path = "/"
	return path


def installed_routes() -> set[str]:
	"""The page-map routes whose page is actually installed on this site.

	Other parts of the platform are adding pages; until one lands, the assistant
	should not send anyone to it. The home page is always there.
	"""
	www = frappe.get_app_path("consilium", "www")
	found = {"/"}
	for route in PAGES:
		stem = route.strip("/")
		if stem and (os.path.exists(os.path.join(www, stem + ".html"))
		             or os.path.exists(os.path.join(www, stem, "index.html"))):
			found.add(route)
	return found


def page_for(route: str) -> dict | None:
	return PAGES.get(normalise_route(route))
