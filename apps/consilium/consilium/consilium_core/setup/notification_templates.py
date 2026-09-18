"""The notification events the application raises, and their default wording.

Each event is a stable code (``policy.review.overdue``). The wording lives in
``Notification Template`` rows so an administrator can change it without a
release; this module supplies the first version of each row and the built-in
fallback used when a template is missing, inactive or fails to render. The
fallback exists because a reminder that an obligation is overdue must not be
lost because somebody mistyped a Jinja tag.

Seeding is additive. A template an administrator has edited is never
overwritten: only the two descriptive fields the application maintains
(``event_description`` and ``context_help``) are refreshed, so they stay true
when an event gains context.

Every event's context also carries the common names ``notification.notify``
adds: ``recipient``, ``recipient_name``, ``subject_doctype``, ``subject_name``,
``link``, ``today``, ``event_code`` and ``doc`` (the subject record as a
dictionary, empty when there is none).

Events marked *caller* below are raised today by modules that still send
through ``notification.dispatch`` with hard-coded text. Their templates are
seeded now so that moving those callers to ``notification.notify`` is a change
of call, not of configuration. Their context names are the ones the caller is
expected to pass.
"""

from __future__ import annotations

import frappe

#: The channel seeded templates use. Email, falling back to the record channel
#: when the site has no outgoing mail — see ``seed_email_channel``.
DEFAULT_TEMPLATE_CHANNEL = "EMAIL"
RECORD_CHANNEL = "RECORD"

_COMMON = "recipient, recipient_name, subject_doctype, subject_name, link, today, doc"

# (event_code, description, context names, subject, body)
EVENTS: list[tuple[str, str, str, str, str]] = [
    # ------------------------------------------------------------ P-10 reviews
    (
        "policy.review.due_soon",
        "Daily. A document in force has its periodic review falling due within the notice period and no "
        "review cycle open. To the document owner.",
        "due_on, days_until",
        "Review due {{ due_on }}: {{ doc.document_name }}",
        "The periodic review of {{ doc.document_name }} ({{ subject_name }}) is due on {{ due_on }}, "
        "in {{ days_until }} day(s).\n\nOpen a review cycle so the review is scheduled and tracked.\n\n{{ link }}",
    ),
    (
        "policy.review.overdue",
        "Daily, repeated weekly. A document in force is past its review date with no review cycle open. "
        "To the document owner.",
        "due_on, days_overdue",
        "Review overdue: {{ doc.document_name }}",
        "The periodic review of {{ doc.document_name }} ({{ subject_name }}) fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue.\n\nOpen a review cycle, or record why the review is deferred.\n\n{{ link }}",
    ),
    (
        "policy.review.escalated",
        "Daily, repeated weekly. A document's review has been overdue beyond the escalation period. "
        "To the document approver.",
        "due_on, days_overdue, document_owner",
        "Escalated: review of {{ doc.document_name }} is {{ days_overdue }} days overdue",
        "The periodic review of {{ doc.document_name }} ({{ subject_name }}), owned by {{ document_owner }}, "
        "fell due on {{ due_on }} and is {{ days_overdue }} day(s) overdue. You are receiving this as the "
        "document's approver.\n\n{{ link }}",
    ),
    (
        "policy.review_cycle.starting",
        "Daily. An open review cycle is scheduled to start within the notice period. To the reviewer and "
        "the document owner.",
        "document_name, scheduled_start, due_on",
        "Review starting {{ scheduled_start }}: {{ document_name }}",
        "The {{ doc.cycle_year }} review of {{ document_name }} is scheduled to start on {{ scheduled_start }}"
        "{% if due_on %} and is due on {{ due_on }}{% endif %}.\n\n{{ link }}",
    ),
    (
        "policy.review_cycle.due_soon",
        "Daily. An open review cycle is due within the notice period. To the reviewer and the document owner.",
        "document_name, due_on, days_until",
        "Review due {{ due_on }}: {{ document_name }}",
        "The {{ doc.cycle_year }} review of {{ document_name }} is due on {{ due_on }}, in {{ days_until }} "
        "day(s). Record the outcome when it concludes.\n\n{{ link }}",
    ),
    (
        "policy.review_cycle.overdue",
        "Daily, repeated weekly. An open review cycle is past its due date. To the reviewer and the "
        "document owner.",
        "document_name, due_on, days_overdue",
        "Review overdue: {{ document_name }}",
        "The {{ doc.cycle_year }} review of {{ document_name }} fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    (
        "policy.review_cycle.escalated",
        "Daily, repeated weekly. An open review cycle has been overdue beyond the escalation period. "
        "To the document approver.",
        "document_name, due_on, days_overdue",
        "Escalated: review of {{ document_name }} is {{ days_overdue }} days overdue",
        "The {{ doc.cycle_year }} review of {{ document_name }} fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue. You are receiving this as the document's approver.\n\n{{ link }}",
    ),
    # --------------------------------------------------------- P-11 monitoring
    (
        "policy.monitoring.due_soon",
        "Daily. An active monitoring activity is due within the notice period. To the person responsible.",
        "document_name, due_on, days_until",
        "Monitoring due {{ due_on }}: {{ doc.activity_title }}",
        "The monitoring activity {{ doc.activity_title }} for {{ document_name }} is due on {{ due_on }}, "
        "in {{ days_until }} day(s). Log the result when it is performed.\n\n{{ link }}",
    ),
    (
        "policy.monitoring.overdue",
        "Daily, repeated weekly. An active monitoring activity is past its due date. To the person responsible.",
        "document_name, due_on, days_overdue",
        "Monitoring overdue: {{ doc.activity_title }}",
        "The monitoring activity {{ doc.activity_title }} for {{ document_name }} fell due on {{ due_on }} and "
        "is {{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    (
        "policy.monitoring.escalated",
        "Daily, repeated weekly. A monitoring activity has been overdue beyond the escalation period. "
        "To the owner of the document it monitors.",
        "document_name, due_on, days_overdue, responsible",
        "Escalated: monitoring of {{ document_name }} is {{ days_overdue }} days overdue",
        "The monitoring activity {{ doc.activity_title }}, the responsibility of {{ responsible }}, fell due "
        "on {{ due_on }} and is {{ days_overdue }} day(s) overdue. You are receiving this as the owner of "
        "{{ document_name }}.\n\n{{ link }}",
    ),
    # ------------------------------------------------- E-9 risk acceptance
    (
        "escalation.risk_acceptance.reassessment_due",
        "Daily. An approved risk acceptance is due for reassessment within the notice period. To the "
        "accountable executive.",
        "due_on, days_until",
        "Reassessment due {{ due_on }}: {{ doc.risk_acceptance_name }}",
        "The risk acceptance {{ doc.risk_acceptance_name }} ({{ subject_name }}) is due for reassessment on "
        "{{ due_on }}, in {{ days_until }} day(s).\n\n{{ link }}",
    ),
    (
        "escalation.risk_acceptance.reassessment_overdue",
        "Daily, repeated weekly. An approved risk acceptance is past its reassessment date. To the "
        "accountable executive.",
        "due_on, days_overdue",
        "Reassessment overdue: {{ doc.risk_acceptance_name }}",
        "The risk acceptance {{ doc.risk_acceptance_name }} ({{ subject_name }}) was due for reassessment on "
        "{{ due_on }} and is {{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    (
        "escalation.risk_acceptance.expiring",
        "Daily. An approved risk acceptance reaches its end date within the notice period. To the "
        "accountable executive.",
        "end_date, days_until",
        "Risk acceptance ends {{ end_date }}: {{ doc.risk_acceptance_name }}",
        "The risk acceptance {{ doc.risk_acceptance_name }} ({{ subject_name }}) ends on {{ end_date }}, in "
        "{{ days_until }} day(s). Renew it, or plan for the risk to be remediated.\n\n{{ link }}",
    ),
    (
        "escalation.risk_acceptance.expired",
        "Daily, repeated weekly. A risk acceptance is past its end date but is still recorded as in force. "
        "To the accountable executive.",
        "end_date, days_overdue",
        "Risk acceptance past its end date: {{ doc.risk_acceptance_name }}",
        "The risk acceptance {{ doc.risk_acceptance_name }} ({{ subject_name }}) ended on {{ end_date }}, "
        "{{ days_overdue }} day(s) ago, and is still recorded as in force.\n\n{{ link }}",
    ),
    # ----------------------------------------------- E-11 periodic returns
    (
        "escalation.periodic_return.opened",
        "Daily, once per return. A quarter opened and its periodic return was created. To the return's owner.",
        "period_label, period_start, period_end, due_on",
        "Periodic return {{ period_label }} opened",
        "The periodic escalation return for {{ period_label }} ({{ period_start }} to {{ period_end }}) has "
        "been created. It is due by {{ due_on }}. If no matters fall in the period, confirm a nil return."
        "\n\n{{ link }}",
    ),
    (
        "escalation.periodic_return.due_soon",
        "Daily. An open periodic return is due within the notice period. To the return's owner.",
        "period_label, due_on, days_until",
        "Periodic return {{ period_label }} due {{ due_on }}",
        "The periodic escalation return for {{ period_label }} is due on {{ due_on }}, in {{ days_until }} "
        "day(s). If no matters fall in the period, confirm a nil return.\n\n{{ link }}",
    ),
    (
        "escalation.periodic_return.overdue",
        "Daily, repeated weekly. An open periodic return is past its due date. To the return's owner.",
        "period_label, due_on, days_overdue",
        "Periodic return {{ period_label }} overdue",
        "The periodic escalation return for {{ period_label }} fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    # ---------------------------------------------------- forum reviews
    (
        "governance.forum_review.overdue",
        "Daily, repeated weekly. A live forum is past its annual review date. To the forum owner.",
        "forum_name, due_on, days_overdue",
        "Annual review overdue: {{ forum_name }}",
        "The annual review of {{ forum_name }} ({{ subject_name }}) fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    (
        "governance.forum_attestation.open",
        "Daily, repeated weekly. A forum attestation task is past its due date and unanswered. To the "
        "person assigned and the forum owner.",
        "forum_name, task, due_on, days_overdue",
        "Attestation overdue: {{ forum_name }}",
        "The attestation task {{ task }} for {{ forum_name }} fell due on {{ due_on }} and has not been "
        "answered.\n\n{{ link }}",
    ),
    (
        "governance.forum_attestation.second_signature_missing",
        "Daily, repeated weekly. A dual-signed forum review has the owner's response but not the "
        "compliance counter-signature. To the second signatory and the forum owner.",
        "forum_name, task, due_on, days_overdue",
        "Counter-signature missing: {{ forum_name }}",
        "The owner has responded to review task {{ task }} for {{ forum_name }}, due {{ due_on }}, but the "
        "compliance counter-signature is missing. The review is not complete until both have signed."
        "\n\n{{ link }}",
    ),
    # ---------------------------------------------- attestation campaigns
    (
        "attestation.task.reminder",
        "Daily, on the days the campaign's reminder schedule names (so many days before the due date). "
        "An attestation task is still unanswered, or answered and still awaiting its counter-signature. "
        "To the person the task asks, or to the second signatory.",
        "campaign_title, task, due_on, days_until, awaiting, note",
        "Reminder: {{ campaign_title }} is due {{ due_on }}",
        "Your {{ awaiting }} for {{ campaign_title }} (task {{ task }}) is due on {{ due_on }}, in "
        "{{ days_until }} day(s).{% if note %}\n\n{{ note }}{% endif %}\n\n{{ link }}",
    ),
    # ------------------------------------------------------ action plans
    (
        "escalation.action_plan.due_soon",
        "Daily. An open action plan reaches its end date within the notice period. To the plan owner.",
        "end_date, days_until",
        "Action plan due {{ end_date }}: {{ doc.action_plan_name }}",
        "The action plan {{ doc.action_plan_name }} ({{ subject_name }}) is due to complete on {{ end_date }}, "
        "in {{ days_until }} day(s).\n\n{{ link }}",
    ),
    (
        "escalation.action_plan.overdue",
        "Daily, repeated weekly. An open action plan is past its end date. To the plan owner and the "
        "accountable executive.",
        "end_date, days_overdue",
        "Action plan overdue: {{ doc.action_plan_name }}",
        "The action plan {{ doc.action_plan_name }} ({{ subject_name }}) was due to complete on {{ end_date }} "
        "and is {{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    # ----------------------------------------------------- service levels
    (
        "sla.warning",
        "Hourly. A running service-level clock has passed its definition's warning threshold. To the "
        "people accountable for the measured record.",
        "definition, definition_title, measure, threshold_pct, started_on, target_on, clock",
        "Approaching its time limit: {{ subject_doctype }} {{ subject_name }}",
        "{{ subject_doctype }} {{ subject_name }} has used {{ threshold_pct }}% of its service level "
        "\"{{ definition_title }}\" ({{ measure }}). The clock started {{ started_on }} and the target is "
        "{{ target_on }}.\n\n{{ link }}",
    ),
    (
        "sla.breached",
        "Hourly. A running service-level clock has passed its target. To the people accountable for the "
        "measured record. Escalation matters are told by the escalation module instead.",
        "definition, definition_title, measure, started_on, target_on, clock",
        "Time limit breached: {{ subject_doctype }} {{ subject_name }}",
        "{{ subject_doctype }} {{ subject_name }} has breached its service level \"{{ definition_title }}\" "
        "({{ measure }}). The target was {{ target_on }}.\n\n{{ link }}",
    ),
    # ------------------------------------------------- P-6 regulatory change
    (
        "regulatory.requirement.changed",
        "On save of a regulatory requirement whose substance changed. To the owner of every governing "
        "document and forum that cites it.",
        "requirement (code, name, citation, regulator, summary), changes (list of label, old, new), "
        "changed_fields, citing_label",
        "Regulatory change: {{ requirement.name }} cited by {{ citing_label }}",
        "The regulatory requirement {{ requirement.name }} ({{ requirement.code }}"
        "{% if requirement.citation %}, {{ requirement.citation }}{% endif %}) has changed, and "
        "{{ citing_label }} cites it.\n\nWhat changed:\n{% for c in changes %}- {{ c.label }}: "
        "{{ c.old or '(empty)' }} -> {{ c.new or '(empty)' }}\n{% endfor %}\nCheck whether the reference "
        "is still current.\n\n{{ link }}",
    ),
    # --------------------------------- E11-S5, P-26 document dispositions
    (
        "policy.document.changed",
        "On a governing document coming back into force with a new version. To everyone its applicability "
        "reaches (E11-S5).",
        "version_label, change_summary, effective_on",
        "Changed: {{ doc.document_name }} ({{ subject_name }}) — version {{ version_label or 'new' }} in force",
        "A new version of {{ doc.document_name }} is now in force{% if version_label %} (version "
        "{{ version_label }}){% endif %}{% if effective_on %}, effective {{ effective_on }}{% endif %}."
        "{% if change_summary %}\n\nWhat changed: {{ change_summary }}{% endif %}\n\nYou are receiving this "
        "because the document's recorded applicability reaches you.\n\n{{ link }}",
    ),
    (
        "policy.document.retired",
        "On a governing document leaving force for good. To everyone its applicability reaches, and its owner "
        "(E11-S5).",
        "reason, retired_on, retention_outcome",
        "Retired: {{ doc.document_name }} ({{ subject_name }})",
        "{{ doc.document_name }} was retired on {{ retired_on }} and no longer applies."
        "{% if reason %}\n\nReason: {{ reason }}{% endif %}\n\nThe record and its versions are kept: "
        "{{ retention_outcome }}\n\n{{ link }}",
    ),
    (
        "policy.review.disposition",
        "On a review round ending — returned to drafting or accepted. To the document's originator, its owner "
        "(P-26).",
        "disposition, decided_by, comments, version_label",
        "{{ disposition }}: {{ doc.document_name }}",
        "The review of {{ doc.document_name }} ({{ subject_name }}){% if version_label %}, version "
        "{{ version_label }},{% endif %} ended: {{ disposition }} by {{ decided_by }}."
        "{% if comments %}\n\nComments:\n{{ comments }}{% endif %}\n\n{{ link }}",
    ),
    (
        "policy.gate_exception.approved",
        "On the policy office approving a request to excuse a lifecycle gate. To the person who asked.",
        "exception_authorisation, approved_by, justification",
        "Exception approved: {{ doc.document_name }}",
        "Your request {{ exception_authorisation }} to excuse a lifecycle gate on {{ doc.document_name }} "
        "({{ subject_name }}) was approved by {{ approved_by }}.\n\nJustification: {{ justification }}\n\n{{ link }}",
    ),
    (
        "policy.attestation.opened",
        "On an attestation campaign being opened for a governing document. To each person asked to attest.",
        "campaign, campaign_title, due_on",
        "Attestation requested: {{ doc.document_name }}",
        "You are asked to attest that you have read and will comply with {{ doc.document_name }} "
        "({{ subject_name }}), by {{ due_on }}. Campaign: {{ campaign_title }}.\n\n{{ link }}",
    ),
    # ---------------------------------------------------- caller events
    (
        "core.watched_field.changed",
        "Caller: watched_fields, Notify Only. A watched field changed. To the person who changed it.",
        "summary",
        "Watched field changed on {{ subject_doctype }} {{ subject_name }}",
        "Changed: {{ summary }}.\n\n{{ link }}",
    ),
    (
        "governance.formation.returned",
        "Caller: governance formation. A formation request was returned with questions. To the requester.",
        "questions",
        "Formation request returned with questions",
        "Request {{ subject_name }} was returned to you: {{ questions }}\n\n{{ link }}",
    ),
    (
        "governance.formation.approval_requested",
        "Caller: governance formation. A formation request awaits an approver's decision. To the approver.",
        "step_title",
        "Formation approval requested",
        "Request {{ subject_name }} awaits your decision at step {{ step_title }}.\n\n{{ link }}",
    ),
    (
        "governance.formation.exception_raised",
        "Caller: governance formation. A formation request was routed as an exception. To the authority.",
        "rationale",
        "Formation exception raised",
        "Request {{ subject_name }} was routed to you as an exception: {{ rationale }}\n\n{{ link }}",
    ),
    (
        "governance.formation.approved",
        "Caller: governance formation. A formation request was approved. To the requester.",
        "",
        "Formation request approved",
        "Request {{ subject_name }} was approved.\n\n{{ link }}",
    ),
    (
        "governance.formation.rejected",
        "Caller: governance formation. A formation request was rejected. To the requester.",
        "reason",
        "Formation request rejected",
        "Request {{ subject_name }} was rejected: {{ reason }}\n\n{{ link }}",
    ),
    (
        "governance.forum.review_recorded",
        "Caller: governance lifecycle. A compliance review decision was recorded. To compliance reviewers.",
        "reviewer, decision",
        "Compliance review recorded",
        "{{ reviewer }} recorded {{ decision }} on forum {{ subject_name }}.\n\n{{ link }}",
    ),
    (
        "governance.forum.returned_for_review",
        "Caller: governance lifecycle. A watched field changed and the forum needs compliance re-review. "
        "To compliance reviewers.",
        "summary",
        "Forum returned for compliance review",
        "Watched field(s) changed on forum {{ subject_name }}: {{ summary }}.\n\n{{ link }}",
    ),
    # ----------------------------- P-14 approval steps, G-11 disbandment
    (
        "policy.approval.requested",
        "An approval step on a governing document was raised. To the step's approver (P-14).",
        "approval_step, version_label",
        "Approval requested: {{ doc.document_name }}",
        "You are asked to decide the step \"{{ approval_step }}\" on {{ doc.document_name }} "
        "({{ subject_name }}){% if version_label %}, version {{ version_label }}{% endif %}.\n\n{{ link }}",
    ),
    (
        "policy.approval.decided",
        "An approval step on a governing document was decided. To the document owner (P-14).",
        "approval_step, decision, decided_by, comments",
        "Approval step decided: {{ doc.document_name }}",
        "{{ decided_by }} recorded \"{{ decision }}\" on the step \"{{ approval_step }}\" of "
        "{{ subject_name }}.{% if comments %}\n\nReason: {{ comments }}{% endif %}\n\n{{ link }}",
    ),
    (
        "policy.approval.bypassed",
        "An approval step on a governing document was bypassed under an exception authorisation. To the step's "
        "approver and the document owner (P-14).",
        "approval_step, authorisation, justification",
        "Approval step bypassed: {{ doc.document_name }}",
        "The step \"{{ approval_step }}\" on {{ subject_name }} was bypassed under exception authorisation "
        "{{ authorisation }}: {{ justification }}\n\n{{ link }}",
    ),
    (
        "governance.disbandment.approval_requested",
        "A forum disbandment plan was raised. To each approver it names (G-11).",
        "forum",
        "Forum disbandment awaits your approval",
        "Disbandment plan {{ subject_name }} for forum {{ forum }} needs your decision.\n\n{{ link }}",
    ),
    (
        "governance.forum.disbanded",
        "Caller: governance lifecycle. A forum was disbanded. To compliance reviewers.",
        "effective_on",
        "Forum disbanded",
        "Forum {{ subject_name }} was disbanded with effect from {{ effective_on }}. The record remains, "
        "inactive.\n\n{{ link }}",
    ),
    (
        "escalation.matter.breached",
        "Caller: escalation resolution. A matter breached its time threshold and was raised. To the "
        "matter's accountable people and the matrix rule's groups.",
        "",
        "Escalation {{ doc.escalation_id or subject_name }} has breached its time threshold",
        "{{ doc.escalation_title }} has passed its configured threshold and has been raised to severity "
        "{{ doc.severity }}. Breach {{ doc.breach_count }} recorded on {{ doc.last_breach_on }}.\n\n{{ link }}",
    ),
    (
        "escalation.matter.material_entity_impact",
        "Caller: escalation resolution. A matter was flagged as affecting a material entity. To the "
        "matter's accountable people and the matrix rule's groups.",
        "",
        "Escalation {{ doc.escalation_id or subject_name }} reports material entity impact",
        "{{ doc.escalation_title }}\n\n{{ link }}",
    ),
    (
        "escalation.matter.queued",
        "Caller: escalation assignment. The matrix routed a matter to a role or group queue and it is waiting "
        "for an owner. To every member of the queue who may read the matter.",
        "queue, rule_code",
        "Escalation {{ doc.escalation_id or subject_name }} is waiting for an owner",
        "{{ doc.escalation_title }} (severity {{ doc.severity }}) has been routed to {{ queue }} by matrix rule "
        "{{ rule_code }}. One member of the queue takes ownership and becomes its response owner; open your "
        "inbox or the matter to take it.\n\n{{ link }}",
    ),
    (
        "policy.document.audience",
        "Caller: policy applicability. A document was published, changed or retired. To everyone its "
        "applicability reaches.",
        "event, detail",
        "{{ doc.document_name }} ({{ subject_name }}) — {{ event }}",
        "{% if detail %}{{ detail }}{% else %}{{ doc.document_name }} has been {{ event | lower }}. You are "
        "receiving this because the document's recorded applicability reaches you.{% endif %}\n\n{{ link }}",
    ),
    (
        "policy.horizon_scan.due",
        "Caller: policy horizon scanning. A horizon scan is due; escalated to the sponsor when late. To the "
        "document owner, and the sponsor when escalated.",
        "due_on, days_overdue, escalated",
        "Horizon scan due for {{ doc.document_name }}",
        "A horizon scan for {{ doc.document_name }} ({{ subject_name }}) fell due on {{ due_on }}, "
        "{{ days_overdue }} day(s) ago. Record what you reviewed, the period covered, the sources and your "
        "impact assessment.{% if escalated %} This reminder has been escalated to the document sponsor."
        "{% endif %}\n\n{{ link }}",
    ),
]

EVENT_INDEX: dict[str, tuple[str, str, str, str, str]] = {row[0]: row for row in EVENTS}


def context_help(event_code: str) -> str:
    row = EVENT_INDEX.get(event_code)
    specific = row[2] if row else ""
    return f"{specific}; plus {_COMMON}" if specific else f"Common only: {_COMMON}"


def seed_email_channel() -> None:
    """The email channel, falling back to the record channel.

    Email goes through the framework's own mail queue and the site's configured
    outgoing Email Account; nothing here names a mail server. A site with no
    outgoing account still records every notification, on the record channel,
    because the email adapter reports itself unavailable rather than failing.
    """
    if frappe.db.exists("Notification Channel", DEFAULT_TEMPLATE_CHANNEL):
        return
    if not frappe.db.exists("Notification Channel", RECORD_CHANNEL):
        return
    frappe.get_doc(
        {
            "doctype": "Notification Channel",
            "channel_code": DEFAULT_TEMPLATE_CHANNEL,
            "title": "Email",
            "channel_type": "Email",
            "adapter": "email",
            "fallback_channel": RECORD_CHANNEL,
            "is_active": 1,
        }
    ).insert(ignore_permissions=True)


def seed_templates() -> list[str]:
    """One template per event on the email channel. Never rewrites wording."""
    if not frappe.db.table_exists("Notification Template"):
        return []
    channel = DEFAULT_TEMPLATE_CHANNEL
    if not frappe.db.exists("Notification Channel", channel):
        channel = RECORD_CHANNEL
    created = []
    for event_code, description, _context, subject, body in EVENTS:
        help_text = context_help(event_code)
        existing = frappe.db.get_value(
            "Notification Template", {"event_code": event_code, "channel": channel}, "name"
        )
        if existing:
            frappe.db.set_value(
                "Notification Template",
                existing,
                {"event_description": description, "context_help": help_text},
                update_modified=False,
            )
            continue
        # An administrator who moved an event to another channel has made a
        # choice; seeding it back onto email would send it twice.
        if frappe.db.exists("Notification Template", {"event_code": event_code}):
            continue
        doc = frappe.get_doc(
            {
                "doctype": "Notification Template",
                "event_code": event_code,
                "channel": channel,
                "is_active": 1,
                "subject": subject,
                "body": body,
                "event_description": description,
                "context_help": help_text,
            }
        ).insert(ignore_permissions=True)
        created.append(doc.name)
    return created


def seed_all() -> None:
    seed_email_channel()
    seed_templates()


# ------------------------------------------------------------------------------
# G-14 / O-4: meeting schedules and charter reviews; P-8: approval steps left
# pending. Appended as their own block so this module's list above stays as it
# was; ``EVENTS`` and ``EVENT_INDEX`` are what every reader uses.
# ------------------------------------------------------------------------------

GOVERNANCE_MEETING_AND_CHARTER_EVENTS: list[tuple[str, str, str, str, str]] = [
    (
        "governance.meeting.scheduled",
        "Caller: governance meetings. A forum meeting was scheduled. To the forum's current members, the "
        "meeting's chair and its secretary (G-14).",
        "forum_name, meeting_reference, scheduled_on, location",
        "Meeting scheduled: {{ forum_name }}, {{ scheduled_on }}",
        "{{ forum_name }} meets on {{ scheduled_on }}{% if location %} at {{ location }}{% endif %} "
        "({{ meeting_reference }}).\n\n{{ link }}",
    ),
    (
        "governance.meeting.rescheduled",
        "Caller: governance meetings. A scheduled forum meeting moved to another time or place. To the "
        "forum's current members, the meeting's chair and its secretary (G-14).",
        "forum_name, meeting_reference, scheduled_on, location, previous_scheduled_on, previous_location",
        "Meeting moved: {{ forum_name }}, now {{ scheduled_on }}",
        "The {{ forum_name }} meeting {{ meeting_reference }} has moved from {{ previous_scheduled_on }}"
        "{% if previous_location %} ({{ previous_location }}){% endif %} to {{ scheduled_on }}"
        "{% if location %} at {{ location }}{% endif %}.\n\n{{ link }}",
    ),
    (
        "governance.meeting.cancelled",
        "Caller: governance meetings. A forum meeting that had not yet taken place was cancelled. To the "
        "forum's current members, the meeting's chair and its secretary (G-14).",
        "forum_name, meeting_reference, scheduled_on",
        "Meeting cancelled: {{ forum_name }}, {{ scheduled_on }}",
        "The {{ forum_name }} meeting {{ meeting_reference }} on {{ scheduled_on }} has been cancelled."
        "\n\n{{ link }}",
    ),
    (
        "governance.charter.review_due",
        "Daily. A charter in force has its review falling due within the notice period. To the forum owner "
        "and the committee secretary (G-10, G-14).",
        "charter_title, forum_name, due_on, days_until",
        "Charter review due {{ due_on }}: {{ charter_title }}",
        "The charter {{ charter_title }} of {{ forum_name }} is due for review on {{ due_on }}, in "
        "{{ days_until }} day(s). Review it and publish a new version, or record that it stands.\n\n{{ link }}",
    ),
    (
        "governance.charter.review_overdue",
        "Daily, repeated weekly. A charter in force is past its review date. To the forum owner and the "
        "committee secretary (G-10, G-14).",
        "charter_title, forum_name, due_on, days_overdue",
        "Charter review overdue: {{ charter_title }}",
        "The review of the charter {{ charter_title }} of {{ forum_name }} fell due on {{ due_on }} and is "
        "{{ days_overdue }} day(s) overdue.\n\n{{ link }}",
    ),
    (
        "governance.charter.challenge_recorded",
        "Caller: governance charters. The risk governance office recorded its challenge on a charter — changes "
        "requested, or cleared. To the forum owner, the committee secretary and the risk governance office "
        "(G-7, G-14).",
        "charter_title, forum_name, outcome, comments, reviewed_by, outstanding",
        "Charter {% if outstanding %}challenged{% else %}challenge {{ outcome | lower }}{% endif %}: "
        "{{ charter_title }}",
        "{{ reviewed_by }} recorded \"{{ outcome }}\" on the risk governance office's challenge of "
        "{{ charter_title }}{% if forum_name %} ({{ forum_name }}){% endif %}."
        "{% if comments %}\n\n{{ comments }}{% endif %}"
        "{% if outstanding %}\n\nThe challenge is outstanding: the charter is not cleared for approval until "
        "it is answered.{% endif %}\n\n{{ link }}",
    ),
    (
        "policy.approval.step_due_soon",
        "Daily. An approval step on a governing document is due within the notice period. To the step's "
        "assignee, or everyone in its queue (P-8).",
        "approval_step, due_on, days_until, queue, document, document_name",
        "Approval due {{ due_on }}: {{ document_name }}",
        "The step \"{{ approval_step }}\" on {{ document_name }} ({{ document }}) is waiting for "
        "{% if queue %}a decision from the {{ queue }} queue{% else %}your decision{% endif %}, due on "
        "{{ due_on }} ({{ days_until }} day(s)).\n\n{{ link }}",
    ),
    (
        "policy.approval.step_overdue",
        "Daily, repeated every few days. An approval step on a governing document is past its due date. To the "
        "step's assignee, or everyone in its queue (P-8).",
        "approval_step, due_on, days_overdue, queue, document, document_name",
        "Approval overdue: {{ document_name }}",
        "The step \"{{ approval_step }}\" on {{ document_name }} ({{ document }}) was due on "
        "{{ due_on }} and is {{ days_overdue }} day(s) overdue.{% if queue %} It is waiting in the {{ queue }} "
        "queue: any member may decide it.{% endif %}\n\n{{ link }}",
    ),
    (
        "policy.approval.step_escalated",
        "Daily, repeated every few days. An approval step has been overdue beyond the escalation lag. To the "
        "document approver, or the document sponsor when the approver holds the step (P-8).",
        "approval_step, assigned_to, due_on, days_overdue, document, document_name",
        "Escalated: approval of {{ document_name }} is {{ days_overdue }} days overdue",
        "The step \"{{ approval_step }}\" on {{ document_name }} ({{ document }}), assigned to "
        "{{ assigned_to }}, was due on {{ due_on }} and is {{ days_overdue }} day(s) overdue. You are receiving "
        "this so that it can be chased, delegated or, with a recorded exception, bypassed.\n\n{{ link }}",
    ),
]

EVENTS.extend(GOVERNANCE_MEETING_AND_CHARTER_EVENTS)
EVENT_INDEX.update({row[0]: row for row in GOVERNANCE_MEETING_AND_CHARTER_EVENTS})


# G-13: a forum's chair, sponsor or secretary nominates their own delegate from
# /forum (governance/delegates.py), and may end the delegation early.
DELEGATE_NOMINATION_EVENTS: list[tuple[str, str, str, str, str]] = [
    (
        "governance.delegate.nominated",
        "Caller: governance delegates. A forum's chair, sponsor or secretary nominated someone to act for "
        "them on the forum's administrative tasks. To the delegate.",
        "forum_name, delegator, delegator_name, valid_from, valid_to, actions",
        "You are {{ delegator_name }}'s delegate for {{ forum_name }}",
        "{{ delegator_name }} has nominated you to act for them on {{ forum_name }} from {{ valid_from }} to "
        "{{ valid_to }}, for: {{ actions }}.\n\nWhat you do under the delegation is recorded as done on their "
        "behalf.\n\n{{ link }}",
    ),
    (
        "governance.delegate.ended",
        "Caller: governance delegates. The person who delegated ended the delegation before its end date. "
        "To the delegate.",
        "forum_name, delegator, delegator_name, valid_from, valid_to, actions",
        "Your delegation for {{ forum_name }} has ended",
        "{{ delegator_name }} has ended your delegation for {{ forum_name }}. From today you no longer act for "
        "them on it.\n\n{{ link }}",
    ),
]

EVENTS.extend(DELEGATE_NOMINATION_EVENTS)
EVENT_INDEX.update({row[0]: row for row in DELEGATE_NOMINATION_EVENTS})
